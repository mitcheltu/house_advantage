"""
ffmpeg-based media assembly utilities.

- Muxes narration audio + generated video.
- Writes/updates media asset metadata in media_assets table.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import ffmpeg
from sqlalchemy import text

from backend.db.connection import get_engine


def _probe_duration(path: Path) -> float | None:
    try:
        info = ffmpeg.probe(str(path))
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
    video = ffmpeg.input(video_path)
    audio = ffmpeg.input(audio_path)

    out = ffmpeg.output(
        video.video,
        audio.audio,
        output_path,
        shortest=None,
        vcodec="copy",
        acodec="aac",
        audio_bitrate="192k",
    )

    if overwrite:
        out = out.overwrite_output()

    out.run(capture_stdout=True, capture_stderr=True)

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
