"""
ffmpeg-based media assembly utilities.

- Muxes narration audio + generated video.
- Writes/updates media asset metadata in media_assets table.
"""

from __future__ import annotations

import os
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
