"""
ffmpeg-based media assembly utilities.

- Muxes narration audio + generated video.
- Overlays citation card images onto video as picture-in-picture.
- Writes/updates media asset metadata in media_assets table.
"""

from __future__ import annotations

import os
import subprocess
import shutil
from pathlib import Path
from typing import Any

import ffmpeg
from sqlalchemy import text

from backend.db.connection import get_engine


def _resolve_ffmpeg_bin() -> str:
    return (
        os.getenv("FFMPEG_BIN", "").strip()
        or shutil.which("ffmpeg")
        or ("/opt/homebrew/bin/ffmpeg" if Path("/opt/homebrew/bin/ffmpeg").exists() else "")
        or ("/usr/local/bin/ffmpeg" if Path("/usr/local/bin/ffmpeg").exists() else "")
        or "ffmpeg"
    )


def _resolve_ffprobe_bin() -> str:
    custom = os.getenv("FFPROBE_BIN", "").strip()
    if custom:
        return custom

    ffmpeg_bin = _resolve_ffmpeg_bin()
    ffmpeg_path = Path(ffmpeg_bin)
    if ffmpeg_path.is_absolute():
        sibling = ffmpeg_path.with_name("ffprobe")
        if sibling.exists():
            return str(sibling)

    return shutil.which("ffprobe") or "ffprobe"


def _probe_duration(path: Path) -> float | None:
    try:
        info = ffmpeg.probe(str(path), cmd=_resolve_ffprobe_bin())
        fmt = info.get("format", {})
        return float(fmt.get("duration")) if fmt.get("duration") else None
    except Exception:
        return None


def assemble_video_with_audio(
    video_path: str,
    audio_path: str,
    output_path: str,
    overwrite: bool = True,
) -> dict[str, Any]:
    ffmpeg_bin = _resolve_ffmpeg_bin()
    video_duration = _probe_duration(Path(video_path))
    audio_duration = _probe_duration(Path(audio_path))

    # Keep final runtime aligned to narration whenever available.
    target_duration = audio_duration or video_duration

    # If generated video is shorter than narration (common with capped model durations),
    # loop the video stream so the narration is not cut off.
    if video_duration and audio_duration and audio_duration > video_duration:
        video = ffmpeg.input(video_path, stream_loop=-1)
    else:
        video = ffmpeg.input(video_path)

    audio = ffmpeg.input(audio_path)

    output_kwargs: dict[str, Any] = {
        "vcodec": "libx264",
        "pix_fmt": "yuv420p",
        "acodec": "aac",
        "audio_bitrate": "192k",
        "movflags": "+faststart",
    }
    if target_duration:
        output_kwargs["t"] = float(target_duration)

    out = ffmpeg.output(video.video, audio.audio, output_path, **output_kwargs)

    if overwrite:
        out = out.overwrite_output()

    out.run(capture_stdout=True, capture_stderr=True, cmd=ffmpeg_bin)

    out_file = Path(output_path)
    return {
        "output_path": str(out_file),
        "file_size_bytes": out_file.stat().st_size if out_file.exists() else None,
        "duration_seconds": _probe_duration(out_file),
    }


def write_media_asset(
    trade_id: int,
    asset_type: str,
    storage_url: str,
    audit_report_id: int | None = None,
    file_size_bytes: int | None = None,
    duration_seconds: float | None = None,
    resolution: str | None = None,
    generation_status: str = "ready",
    error_message: str | None = None,
    model_used: str | None = None,
) -> int:
    engine = get_engine()
    sql = text(
        """
        INSERT INTO media_assets (
          trade_id, audit_report_id, asset_type, storage_url,
          file_size_bytes, duration_seconds, resolution,
          generation_status, error_message, model_used
        ) VALUES (
          :trade_id, :audit_report_id, :asset_type, :storage_url,
          :file_size_bytes, :duration_seconds, :resolution,
          :generation_status, :error_message, :model_used
        )
        """
    )

    with engine.begin() as conn:
        result = conn.execute(
            sql,
            {
                "trade_id": trade_id,
                "audit_report_id": audit_report_id,
                "asset_type": asset_type,
                "storage_url": storage_url,
                "file_size_bytes": file_size_bytes,
                "duration_seconds": duration_seconds,
                "resolution": resolution,
                "generation_status": generation_status,
                "error_message": error_message,
                "model_used": model_used,
            },
        )
        return int(result.lastrowid)


def update_media_asset_storage_url(asset_id: int, storage_url: str) -> None:
    engine = get_engine()
    sql = text(
        """
        UPDATE media_assets
        SET storage_url = :storage_url
        WHERE id = :asset_id
        """
    )
    with engine.begin() as conn:
        conn.execute(sql, {"storage_url": storage_url, "asset_id": asset_id})


def assemble_and_register_trade_video(
    trade_id: int,
    video_path: str,
    audio_path: str,
    output_path: str,
    audit_report_id: int | None = None,
    model_used: str | None = "ffmpeg-mux",
) -> dict[str, Any]:
    assembly = assemble_video_with_audio(video_path, audio_path, output_path)
    asset_id = write_media_asset(
        trade_id=trade_id,
        audit_report_id=audit_report_id,
        asset_type="video",
        storage_url=assembly["output_path"],
        file_size_bytes=assembly.get("file_size_bytes"),
        duration_seconds=assembly.get("duration_seconds"),
        generation_status="ready",
        model_used=model_used,
    )

    return {
        "asset_id": asset_id,
        **assembly,
    }


def overlay_citation_images(
    video_path: str,
    citation_image_paths: list[str],
    output_path: str,
    image_width: int = 300,
    overwrite: bool = True,
) -> dict[str, Any]:
    """Overlay citation card images as picture-in-picture at timed intervals.

    Each citation image is scaled to *image_width* pixels wide and shown in the
    upper-right corner of the video for a segment of the video duration.  This is
    the FFmpeg fallback for when Veo reference images are unavailable.
    """
    ffmpeg_bin = _resolve_ffmpeg_bin()
    video_duration = _probe_duration(Path(video_path)) or 30.0

    if not citation_image_paths:
        shutil.copy2(video_path, output_path)
        out_path = Path(output_path)
        return {
            "output_path": str(out_path),
            "file_size_bytes": out_path.stat().st_size if out_path.exists() else None,
            "duration_seconds": video_duration,
        }

    n_images = min(len(citation_image_paths), 3)
    segment_duration = video_duration / (n_images + 1)

    # Build ffmpeg command with filter_complex
    cmd_parts: list[str] = [ffmpeg_bin]
    if overwrite:
        cmd_parts.append("-y")
    cmd_parts.extend(["-i", video_path])
    for img_path in citation_image_paths[:n_images]:
        cmd_parts.extend(["-i", img_path])

    # Build overlay filter graph
    filter_parts: list[str] = []
    prev_label = "0:v"
    for i in range(n_images):
        start_time = segment_duration * (i + 0.5)
        end_time = start_time + segment_duration
        scale_label = f"ovl{i}"
        out_label = f"tmp{i}" if i < n_images - 1 else "vout"

        filter_parts.append(f"[{i + 1}:v]scale={image_width}:-1[{scale_label}]")
        filter_parts.append(
            f"[{prev_label}][{scale_label}]overlay=W-w-30:30:"
            f"enable='between(t,{start_time:.1f},{end_time:.1f})'[{out_label}]"
        )
        prev_label = out_label

    filter_complex = ";".join(filter_parts)
    cmd_parts.extend([
        "-filter_complex", filter_complex,
        "-map", "[vout]",
        "-map", "0:a?",
        "-codec:v", "libx264",
        "-pix_fmt", "yuv420p",
        "-codec:a", "copy",
        "-movflags", "+faststart",
        output_path,
    ])

    subprocess.run(cmd_parts, check=True, capture_stdout=True, capture_stderr=True)

    out_path = Path(output_path)
    return {
        "output_path": str(out_path),
        "file_size_bytes": out_path.stat().st_size if out_path.exists() else None,
        "duration_seconds": _probe_duration(out_path),
    }
