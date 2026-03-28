"""Automated media generation utilities for TTS + video synthesis.

Features:
- Speech synthesis using Google Cloud Text-to-Speech when configured.
- Veo-compatible HTTP video generation via configurable endpoints.
- Optional Google GenAI Veo contract mode (operation-based polling).
- Automatic placeholder fallback media so pipelines can run end-to-end locally.
"""

from __future__ import annotations

import base64
import json
import os
import shutil
import time
import wave
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

import ffmpeg
import requests

try:
    from google.cloud import texttospeech  # type: ignore
except Exception:  # pragma: no cover
    texttospeech = None


def _veo_debug_enabled() -> bool:
    return os.getenv("VEO_DEBUG", "false").strip().lower() in {"1", "true", "yes", "on"}


def _veo_debug(event: str, payload: dict[str, Any] | None = None) -> None:
    if not _veo_debug_enabled():
        return
    if payload is None:
        print(f"[veo-debug] {event}")
        return

    if os.getenv("VEO_DEBUG_VERBOSE_PAYLOAD", "false").strip().lower() in {"1", "true", "yes", "on"}:
        raw = json.dumps(payload, ensure_ascii=False)
        if len(raw) > 1200:
            raw = raw[:1200] + "...<truncated>"
        print(f"[veo-debug] {event}: {raw}")
        return

    top_level = list(payload.keys()) if isinstance(payload, dict) else []
    print(f"[veo-debug] {event}: keys={top_level}")


def _json_response(resp: requests.Response) -> dict[str, Any]:
    ctype = resp.headers.get("content-type", "").lower()
    return resp.json() if "application/json" in ctype else {}


def _read_nested(payload: dict[str, Any], path: str) -> Any:
    current: Any = payload
    for token in path.split("."):
        if isinstance(current, list):
            try:
                idx = int(token)
            except ValueError:
                return None
            if idx < 0 or idx >= len(current):
                return None
            current = current[idx]
            continue

        if not isinstance(current, dict):
            return None
        current = current.get(token)
        if current is None:
            return None
    return current


def _extract_first(payload: dict[str, Any], paths: list[str]) -> Any:
    for p in paths:
        value = _read_nested(payload, p)
        if value is not None and value != "":
            return value
    return None


def _env_csv(name: str, default: str) -> list[str]:
    raw = os.getenv(name, default)
    return [part.strip() for part in raw.split(",") if part.strip()]


def _build_auth(api_key: str) -> tuple[dict[str, str], dict[str, str]]:
    mode = os.getenv("VEO_AUTH_MODE", "bearer").strip().lower()
    header_name = os.getenv("VEO_AUTH_HEADER", "Authorization").strip() or "Authorization"
    query_name = os.getenv("VEO_AUTH_QUERY_PARAM", "key").strip() or "key"

    headers: dict[str, str] = {"Content-Type": "application/json"}
    params: dict[str, str] = {}

    if not api_key:
        return headers, params

    if mode == "query":
        params[query_name] = api_key
        return headers, params

    if mode == "header":
        headers[header_name] = api_key
        return headers, params

    if mode == "x-api-key":
        headers["x-api-key"] = api_key
        return headers, params

    # default bearer
    headers[header_name] = f"Bearer {api_key}"
    return headers, params


def _google_download_params(url: str, api_key: str) -> dict[str, str] | None:
    if not api_key:
        return None

    parsed = urlparse(url)
    if parsed.netloc != "generativelanguage.googleapis.com":
        return None

    qs = parse_qs(parsed.query)
    if "key" in qs:
        return None

    return {"key": api_key}


def _get_google_supported_methods(base: str, model: str, api_key: str) -> list[str]:
    if not api_key:
        return []

    model_url = f"{base}/models/{model}"
    try:
        resp = requests.get(model_url, params={"key": api_key}, timeout=60)
        resp.raise_for_status()
        payload = _json_response(resp)
        methods = payload.get("supportedGenerationMethods") or []
        if isinstance(methods, list):
            return [str(m) for m in methods if m]
    except Exception:
        return []

    return []


def _estimate_duration_seconds(script_text: str) -> float:
    words = max(1, len((script_text or "").split()))
    # ~2.4 words/s spoken rate with bounds for short/long scripts
    return float(max(8, min(120, round(words / 2.4))))


def _resolve_ffprobe_bin() -> str:
    custom = os.getenv("FFPROBE_BIN", "").strip()
    if custom:
        return custom
    ffmpeg_bin = os.getenv("FFMPEG_BIN", "").strip()
    if ffmpeg_bin:
        sibling = Path(ffmpeg_bin).with_name("ffprobe")
        if sibling.exists():
            return str(sibling)
        sibling_exe = Path(ffmpeg_bin).with_name("ffprobe.exe")
        if sibling_exe.exists():
            return str(sibling_exe)
    return shutil.which("ffprobe") or "ffprobe"


def _probe_duration(path: Path) -> float | None:
    try:
        info = ffmpeg.probe(str(path), cmd=_resolve_ffprobe_bin())
        fmt = info.get("format", {})
        return float(fmt.get("duration")) if fmt.get("duration") else None
    except Exception:
        return None


def _probe_resolution(path: Path) -> str | None:
    try:
        info = ffmpeg.probe(str(path), cmd=_resolve_ffprobe_bin())
        for stream in info.get("streams", []):
            if stream.get("codec_type") == "video":
                width = stream.get("width")
                height = stream.get("height")
                if width and height:
                    return f"{width}x{height}"
    except Exception:
        return None
    return None


def _generate_silent_wav(output_path: Path, duration_seconds: float) -> dict[str, Any]:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    sample_rate = 24000
    channels = 1
    sample_width = 2
    frame_count = int(sample_rate * duration_seconds)
    silence_frame = (0).to_bytes(2, byteorder="little", signed=True)

    with wave.open(str(output_path), "wb") as wf:
        wf.setnchannels(channels)
        wf.setsampwidth(sample_width)
        wf.setframerate(sample_rate)
        wf.writeframes(silence_frame * frame_count)

    return {
        "path": str(output_path),
        "duration_seconds": _probe_duration(output_path),
        "file_size_bytes": output_path.stat().st_size if output_path.exists() else None,
        "provider": "silent-fallback",
    }


def _create_tts_client() -> tuple[Any | None, str | None]:
    if texttospeech is None:
        return None, "google-cloud-texttospeech package unavailable"

    tts_cred_path = os.getenv("TTS_CREDENTIALS_PATH", "").strip() or os.getenv("GOOGLE_APPLICATION_CREDENTIALS", "").strip()
    allow_adc_fallback = os.getenv("TTS_ALLOW_ADC_FALLBACK", "true").strip().lower() in {"1", "true", "yes", "on"}

    # If an explicit credentials path is configured but missing, optionally try ADC fallback.
    if tts_cred_path and not Path(tts_cred_path).exists():
        missing_msg = f"credentials file not found: {tts_cred_path}"
        if not allow_adc_fallback:
            return None, missing_msg

        original = os.getenv("GOOGLE_APPLICATION_CREDENTIALS")
        try:
            os.environ.pop("GOOGLE_APPLICATION_CREDENTIALS", None)
            client = texttospeech.TextToSpeechClient()
            return client, f"{missing_msg}; using ADC fallback"
        except Exception as exc:
            return None, f"{missing_msg}; ADC fallback failed: {exc}"
        finally:
            if original is not None:
                os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = original

    original = os.getenv("GOOGLE_APPLICATION_CREDENTIALS")
    try:
        if tts_cred_path:
            os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = tts_cred_path
        client = texttospeech.TextToSpeechClient()
        return client, None
    except Exception as exc:
        return None, str(exc)
    finally:
        # restore previous process env to avoid side effects
        if original is None:
            os.environ.pop("GOOGLE_APPLICATION_CREDENTIALS", None)
        else:
            os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = original


def _synthesize_with_gemini_tts(script_text: str, output: Path) -> tuple[dict[str, Any] | None, str | None]:
    api_key = os.getenv("GEMINI_API_KEY", "").strip()
    if not api_key:
        return None, "GEMINI_API_KEY not set"

    base = os.getenv("GEMINI_API_BASE", "https://generativelanguage.googleapis.com/v1beta").rstrip("/")
    model = os.getenv("TTS_GEMINI_MODEL", "gemini-2.5-pro-preview-tts")
    voice_name = os.getenv("TTS_GEMINI_VOICE", "Kore")

    endpoint = f"{base}/models/{model}:generateContent"

    payload_variants = [
        {
            "contents": [{"parts": [{"text": script_text}]}],
            "generationConfig": {
                "responseModalities": ["AUDIO"],
                "speechConfig": {
                    "voiceConfig": {
                        "prebuiltVoiceConfig": {
                            "voiceName": voice_name,
                        }
                    }
                },
            },
        },
        # NOTE: Avoid audioConfig; Gemini rejects unknown fields in generationConfig.
        # NOTE: Do not set responseMimeType for AUDIO; Gemini rejects it.
    ]

    last_error = None
    for payload in payload_variants:
        try:
            resp = requests.post(
                endpoint,
                params={"key": api_key},
                headers={"Content-Type": "application/json"},
                json=payload,
                timeout=180,
            )
            if resp.status_code >= 400:
                try:
                    error_payload = resp.json()
                except Exception:
                    error_payload = resp.text
                last_error = f"{resp.status_code} {resp.reason}: {error_payload}"
                continue
            resp.raise_for_status()
            data = _json_response(resp)

            part = _extract_first(
                data,
                _env_csv(
                    "TTS_GEMINI_AUDIO_PART_PATHS",
                    "candidates.0.content.parts.0,audio",
                ),
            )

            part_dict = part if isinstance(part, dict) else {}
            inline_data = part_dict.get("inlineData") if isinstance(part_dict.get("inlineData"), dict) else part_dict.get("inline_data")
            inline_data = inline_data if isinstance(inline_data, dict) else {}
            mime_type = str(inline_data.get("mimeType") or inline_data.get("mime_type") or "").strip().lower()

            audio_b64 = _extract_first(
                data,
                _env_csv(
                    "TTS_GEMINI_AUDIO_BASE64_PATHS",
                    "candidates.0.content.parts.0.inlineData.data,candidates.0.content.parts.0.inline_data.data,audio.data",
                ),
            )

            if not audio_b64:
                candidates = data.get("candidates") if isinstance(data.get("candidates"), list) else []
                for candidate in candidates:
                    parts = candidate.get("content", {}).get("parts", []) if isinstance(candidate, dict) else []
                    if not isinstance(parts, list):
                        continue
                    for part_entry in parts:
                        if not isinstance(part_entry, dict):
                            continue
                        inline = part_entry.get("inlineData") or part_entry.get("inline_data")
                        if not isinstance(inline, dict):
                            continue
                        candidate_b64 = inline.get("data")
                        if candidate_b64:
                            audio_b64 = candidate_b64
                            if not mime_type:
                                mime_type = str(inline.get("mimeType") or inline.get("mime_type") or "").strip().lower()
                            break
                    if audio_b64:
                        break
            if not audio_b64:
                if os.getenv("TTS_DEBUG_VERBOSE_PAYLOAD", "false").strip().lower() in {"1", "true", "yes", "on"}:
                    raw = json.dumps(data, ensure_ascii=False)
                    if len(raw) > 1200:
                        raw = raw[:1200] + "...<truncated>"
                    print(f"[tts-debug] Gemini TTS payload: {raw}")
                candidates = data.get("candidates") if isinstance(data.get("candidates"), list) else []
                parts_count = sum(
                    len(c.get("content", {}).get("parts", []))
                    for c in candidates
                    if isinstance(c, dict)
                )
                last_error = (
                    "Gemini TTS response did not contain audio data "
                    f"keys={list(data.keys())} candidates={len(candidates)} parts={parts_count}"
                )
                continue

            audio_bytes = base64.b64decode(str(audio_b64))
            output.parent.mkdir(parents=True, exist_ok=True)

            # Gemini TTS commonly returns raw PCM in audio/L16 format.
            if "audio/l16" in mime_type or "audio/pcm" in mime_type:
                sample_rate = 24000
                channels = int(os.getenv("TTS_GEMINI_PCM_CHANNELS", "1"))

                # Parse simple mime params like: audio/L16;codec=pcm;rate=24000
                for token in mime_type.split(";"):
                    token = token.strip()
                    if token.startswith("rate="):
                        try:
                            sample_rate = int(token.split("=", 1)[1])
                        except Exception:
                            pass
                    if token.startswith("channels="):
                        try:
                            channels = max(1, int(token.split("=", 1)[1]))
                        except Exception:
                            pass

                with wave.open(str(output), "wb") as wf:
                    wf.setnchannels(channels)
                    wf.setsampwidth(2)
                    wf.setframerate(sample_rate)
                    wf.writeframes(audio_bytes)
            else:
                output.write_bytes(audio_bytes)

            return {
                "path": str(output),
                "duration_seconds": _probe_duration(output),
                "file_size_bytes": output.stat().st_size if output.exists() else None,
                "provider": f"gemini-tts:{model}",
            }, None
        except Exception as exc:
            last_error = str(exc)

    return None, last_error


def synthesize_narration_audio(script_text: str, output_path: str) -> dict[str, Any]:
    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)

    language_code = os.getenv("TTS_LANGUAGE_CODE", "en-US")
    voice_name = os.getenv("TTS_VOICE_NAME", "en-US-Neural2-F")
    speaking_rate = float(os.getenv("TTS_SPEAKING_RATE", "1.0"))

    provider_mode = os.getenv("TTS_PROVIDER", "auto").strip().lower()

    # Gemini TTS path (requested by user)
    if provider_mode in {"gemini", "auto"}:
        gemini_result, gemini_error = _synthesize_with_gemini_tts(script_text=script_text, output=output)
        if gemini_result is not None:
            return gemini_result
        if gemini_error:
            print(f"[tts-debug] Gemini TTS failed: {gemini_error}")
        if provider_mode == "gemini" and gemini_error:
            fallback = _generate_silent_wav(output, _estimate_duration_seconds(script_text))
            fallback["error"] = gemini_error
            return fallback

    tts_client_error: str | None = None
    client, tts_client_error = _create_tts_client()
    if client is not None and texttospeech is not None:
        try:
            synthesis_input = texttospeech.SynthesisInput(text=script_text)
            voice = texttospeech.VoiceSelectionParams(
                language_code=language_code,
                name=voice_name,
            )
            audio_config = texttospeech.AudioConfig(
                audio_encoding=texttospeech.AudioEncoding.LINEAR16,
                speaking_rate=speaking_rate,
            )
            response = client.synthesize_speech(
                request={
                    "input": synthesis_input,
                    "voice": voice,
                    "audio_config": audio_config,
                }
            )
            output.write_bytes(response.audio_content)
            return {
                "path": str(output),
                "duration_seconds": _probe_duration(output),
                "file_size_bytes": output.stat().st_size if output.exists() else None,
                "provider": "google-cloud-texttospeech",
            }
        except Exception as exc:
            tts_client_error = str(exc)

    fallback = _generate_silent_wav(output, _estimate_duration_seconds(script_text))
    if tts_client_error:
        fallback["error"] = tts_client_error
    return fallback


def _generate_placeholder_image(output_path: Path) -> dict[str, Any]:
    """Generate a minimal dark placeholder PNG."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    # Minimal 1x1 dark PNG
    output_path.write_bytes(base64.b64decode(
        "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg=="
    ))
    return {
        "path": str(output_path),
        "file_size_bytes": output_path.stat().st_size if output_path.exists() else None,
        "provider": "placeholder-image",
    }


def generate_citation_image(
    prompt: str,
    output_path: str,
    aspect_ratio: str = "16:9",
) -> dict[str, Any]:
    """Generate a bill citation card image using Nano Banana 2 (Gemini image generation).

    Retries up to 3 times on empty responses (intermittent API issue).
    Falls back to placeholder when provider is disabled or API key is missing.
    """
    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)

    provider = os.getenv("IMAGE_GEN_PROVIDER", "nano-banana").strip().lower()
    if provider == "disabled":
        return _generate_placeholder_image(output)

    api_key = os.getenv("GEMINI_API_KEY", "").strip()
    if not api_key:
        return _generate_placeholder_image(output)

    base = os.getenv("GEMINI_API_BASE", "https://generativelanguage.googleapis.com/v1beta").rstrip("/")
    model = os.getenv("IMAGE_GEN_MODEL", "gemini-3.1-flash-image-preview")
    endpoint = f"{base}/models/{model}:generateContent"

    max_retries = 3
    last_error: str | None = None

    for attempt in range(max_retries):
        # Sanitize prompt to remove real people's names — the image model
        # rejects prompts with real names/likenesses just like Veo does.
        sanitized_prompt = _sanitize_prompt_for_veo(prompt)

        payload = {
            "contents": [{"parts": [{"text": sanitized_prompt}]}],
            "generationConfig": {
                "responseModalities": ["IMAGE"],
            },
        }

        try:
            resp = requests.post(
                endpoint,
                params={"key": api_key},
                headers={"Content-Type": "application/json"},
                json=payload,
                timeout=120,
            )
            resp.raise_for_status()
            data = _json_response(resp)

            candidates = data.get("candidates", [])
            for candidate in candidates:
                parts = candidate.get("content", {}).get("parts", [])
                for part in parts:
                    inline_data = part.get("inlineData") or part.get("inline_data") or {}
                    b64 = inline_data.get("data", "")
                    if b64:
                        image_bytes = base64.b64decode(b64)
                        # Always trust magic bytes over API-reported mimeType
                        if image_bytes[:2] == b'\xff\xd8':
                            output = output.with_suffix(".jpg")
                        elif image_bytes[:4] == b'\x89PNG':
                            output = output.with_suffix(".png")
                        else:
                            # Unknown format — keep original extension
                            pass
                        # Remove stale file if extension changed (e.g. .png -> .jpg)
                        requested = Path(output_path)
                        if requested != output and requested.exists():
                            requested.unlink(missing_ok=True)
                        output.write_bytes(image_bytes)
                        return {
                            "path": str(output),
                            "file_size_bytes": output.stat().st_size,
                            "provider": f"nano-banana:{model}",
                        }

            # No image data — log details for diagnosis
            finish_reasons = [
                c.get("finishReason", "unknown") for c in candidates
            ]
            last_error = f"No image data in API response (attempt {attempt+1}/{max_retries}, finishReasons={finish_reasons})"

        except Exception as exc:
            last_error = f"API error attempt {attempt+1}/{max_retries}: {exc}"

        # Wait before retry (increasing backoff)
        if attempt < max_retries - 1:
            time.sleep(3 * (attempt + 1))

    result = _generate_placeholder_image(output)
    result["error"] = last_error
    return result


def _download_to_file(
    url: str,
    output_path: Path,
    headers: dict[str, str] | None = None,
    params: dict[str, str] | None = None,
) -> None:
    with requests.get(url, headers=headers, params=params, timeout=300, stream=True) as resp:
        resp.raise_for_status()
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with output_path.open("wb") as f:
            for chunk in resp.iter_content(chunk_size=8192):
                if chunk:
                    f.write(chunk)


def _generate_placeholder_video(output_path: Path, duration_seconds: float, resolution: str = "1920x1080") -> dict[str, Any]:
    ffmpeg_bin = (
        os.getenv("FFMPEG_BIN", "").strip()
        or shutil.which("ffmpeg")
        or ("/opt/homebrew/bin/ffmpeg" if Path("/opt/homebrew/bin/ffmpeg").exists() else "")
        or ("/usr/local/bin/ffmpeg" if Path("/usr/local/bin/ffmpeg").exists() else "")
    )

    if not ffmpeg_bin:
        raise RuntimeError(
            "No Veo endpoint configured and ffmpeg is not installed for local placeholder video generation."
        )

    output_path.parent.mkdir(parents=True, exist_ok=True)
    (
        ffmpeg
        .input(f"color=c=0x0f1826:s={resolution}:r=24", f="lavfi", t=duration_seconds)
        .output(
            str(output_path),
            vcodec="libx264",
            pix_fmt="yuv420p",
            movflags="+faststart",
            r=24,
        )
        .overwrite_output()
        .run(capture_stdout=True, capture_stderr=True, cmd=ffmpeg_bin)
    )
    return {
        "path": str(output_path),
        "duration_seconds": _probe_duration(output_path),
        "file_size_bytes": output_path.stat().st_size if output_path.exists() else None,
        "resolution": _probe_resolution(output_path),
        "provider": "placeholder-video",
    }


def _poll_operation_video_url(
    operation_id: str,
    headers: dict[str, str],
    timeout_seconds: int,
    params: dict[str, str] | None = None,
) -> str | None:
    status_endpoint = os.getenv("VEO_STATUS_ENDPOINT", "").strip()
    if not status_endpoint:
        return None

    poll_every = int(os.getenv("VEO_POLL_INTERVAL_SECONDS", "5"))
    start = time.time()

    while time.time() - start < timeout_seconds:
        request_params = {"operation_id": operation_id}
        if params:
            request_params.update(params)

        resp = requests.get(status_endpoint, headers=headers, params=request_params, timeout=60)
        resp.raise_for_status()
        payload = _json_response(resp)

        status = str(payload.get("status", "")).lower()
        if status in {"succeeded", "done", "completed"}:
            return payload.get("video_url") or payload.get("result", {}).get("video_url")
        if status in {"failed", "error", "cancelled"}:
            return None

        time.sleep(max(1, poll_every))

    return None


def _poll_google_operation_video_url(
    operation_name_or_id: str,
    api_key: str,
    timeout_seconds: int,
) -> str | None:
    base = os.getenv("VEO_GOOGLE_BASE_URL", "https://generativelanguage.googleapis.com/v1beta").rstrip("/")
    op_name = operation_name_or_id.strip()
    if op_name.startswith("http://") or op_name.startswith("https://"):
        operation_url = op_name
    elif op_name.startswith("operations/"):
        operation_url = f"{base}/{op_name.lstrip('/')}"
    elif op_name.startswith("models/") and "/operations/" in op_name:
        operation_url = f"{base}/{op_name.lstrip('/')}"
    else:
        operation_url = f"{base}/operations/{op_name.lstrip('/')}"
    poll_every = int(os.getenv("VEO_POLL_INTERVAL_SECONDS", "5"))
    start = time.time()

    result_video_paths = _env_csv(
        "VEO_GOOGLE_RESULT_VIDEO_URL_PATHS",
        "response.generateVideoResponse.generatedSamples.0.video.uri,response.generatedVideos.0.video.uri,response.videos.0.uri,response.video.uri,response.video_url",
    )
    direct_video_paths = _env_csv(
        "VEO_GOOGLE_DIRECT_VIDEO_URL_PATHS",
        "generateVideoResponse.generatedSamples.0.video.uri,generatedVideos.0.video.uri,videos.0.uri,video.uri,video_url",
    )

    while time.time() - start < timeout_seconds:
        resp = requests.get(operation_url, params={"key": api_key}, timeout=90)
        resp.raise_for_status()
        payload = _json_response(resp)
        _veo_debug("google-poll-response", payload)

        # Some responses may include ready result without explicit done=true.
        eager_url = _extract_first(payload, direct_video_paths) or _extract_first(payload, result_video_paths)
        if eager_url:
            return str(eager_url)

        done = bool(payload.get("done", False))
        if done:
            url = _extract_first(payload, result_video_paths)
            if url:
                return str(url)
            # Operation done but no video — likely content filtered or failed
            _veo_debug("google-poll-done-no-video", payload)
            error_info = payload.get("error") or payload.get("response", {}).get("error")
            if error_info:
                print(f"[veo] Operation done with error: {error_info}")
            else:
                print(f"[veo] Operation done but no video URL found in response keys: {list(payload.keys())}")
            return None

        err = payload.get("error")
        if err:
            _veo_debug("google-poll-error", payload)
            print(f"[veo] Operation error: {err}")
            return None

        time.sleep(max(1, poll_every))

    return None


def _try_generic_endpoint(
    endpoint: str,
    api_key: str,
    prompt: str,
    output: Path,
    duration_seconds: float,
    aspect_ratio: str,
    timeout_seconds: int,
) -> dict[str, Any] | None:
    headers, params = _build_auth(api_key)
    payload = {
        "prompt": prompt,
        "duration_seconds": duration_seconds,
        "aspect_ratio": aspect_ratio,
        "model": os.getenv("VEO_MODEL", "veo-3.1"),
    }

    resp = requests.post(endpoint, json=payload, headers=headers, params=params, timeout=180)
    resp.raise_for_status()

    ctype = resp.headers.get("content-type", "").lower()
    if "video/" in ctype:
        output.write_bytes(resp.content)
        return {
            "path": str(output),
            "duration_seconds": _probe_duration(output),
            "file_size_bytes": output.stat().st_size if output.exists() else None,
            "resolution": _probe_resolution(output),
            "provider": "veo-http-binary",
        }

    json_payload = _json_response(resp)

    base64_paths = _env_csv("VEO_RESPONSE_VIDEO_BASE64_PATHS", "video_base64,result.video_base64,data.video_base64")
    b64_data = _extract_first(json_payload, base64_paths)
    if b64_data:
        output.write_bytes(base64.b64decode(str(b64_data)))
        return {
            "path": str(output),
            "duration_seconds": _probe_duration(output),
            "file_size_bytes": output.stat().st_size if output.exists() else None,
            "resolution": _probe_resolution(output),
            "provider": "veo-http-base64",
        }

    url_paths = _env_csv("VEO_RESPONSE_VIDEO_URL_PATHS", "video_url,result.video_url,data.video_url")
    video_url = _extract_first(json_payload, url_paths)

    if not video_url:
        op_paths = _env_csv("VEO_RESPONSE_OPERATION_PATHS", "operation_id,operation.id,operation.name,name")
        op_id = _extract_first(json_payload, op_paths)
        if op_id:
            video_url = _poll_operation_video_url(
                operation_id=str(op_id),
                headers=headers,
                timeout_seconds=timeout_seconds,
                params=params,
            )

    if video_url:
        download_headers = {k: v for k, v in headers.items() if k.lower() != "content-type"}
        _download_to_file(str(video_url), output, headers=download_headers or None, params=params or None)
        return {
            "path": str(output),
            "duration_seconds": _probe_duration(output),
            "file_size_bytes": output.stat().st_size if output.exists() else None,
            "resolution": _probe_resolution(output),
            "provider": "veo-http-url",
        }

    return None


def _try_google_genai_veo(
    api_key: str,
    prompt: str,
    output: Path,
    duration_seconds: float,
    aspect_ratio: str,
    timeout_seconds: int,
    reference_image_paths: list[str] | None = None,
) -> dict[str, Any] | None:
    if not api_key:
        return None

    base = os.getenv("VEO_GOOGLE_BASE_URL", "https://generativelanguage.googleapis.com/v1beta").rstrip("/")
    model = os.getenv("VEO_MODEL", "veo-3.1-generate-preview")
    clamped_duration = int(max(4, min(120, round(duration_seconds))))

    # Build reference images for Veo 3.1 (up to 3 per API constraint)
    reference_images: list[dict[str, Any]] = []
    if reference_image_paths:
        ref_type = os.getenv("VEO_REFERENCE_TYPE", "REFERENCE_TYPE_STYLE")
        for img_path in reference_image_paths[:3]:
            img_file = Path(img_path)
            if img_file.exists():
                raw = img_file.read_bytes()
                img_b64 = base64.b64encode(raw).decode("ascii")
                # Detect MIME from magic bytes, not file extension
                if raw[:2] == b'\xff\xd8':
                    mime = "image/jpeg"
                elif raw[:4] == b'\x89PNG':
                    mime = "image/png"
                elif raw[:4] == b'RIFF' and raw[8:12] == b'WEBP':
                    mime = "image/webp"
                else:
                    mime = "image/jpeg"  # safe default
                reference_images.append({
                    "referenceType": ref_type,
                    "referenceImage": {
                        "image": {
                            "imageBytes": img_b64,
                            "mimeType": mime,
                        }
                    },
                })
    # Force 8s duration when references are used (API requirement)
    if reference_images:
        clamped_duration = 8

    method_mode = os.getenv("VEO_GOOGLE_METHOD", "auto").strip().lower()
    supported = {m.lower() for m in _get_google_supported_methods(base, model, api_key)}
    if supported:
        _veo_debug("google-supported-methods", {"model": model, "methods": sorted(supported)})

    if method_mode == "predictlongrunning":
        method_candidates = ["predictLongRunning"]
    elif method_mode == "generatevideos":
        method_candidates = ["generateVideos"]
    else:
        if "predictlongrunning" in supported and "generatevideos" not in supported:
            method_candidates = ["predictLongRunning"]
        elif "generatevideos" in supported and "predictlongrunning" not in supported:
            method_candidates = ["generateVideos"]
        else:
            method_candidates = ["generateVideos", "predictLongRunning"]

    data: dict[str, Any] = {}
    last_error: Exception | None = None

    for method in method_candidates:
        endpoint = f"{base}/models/{model}:{method}"
        if method == "predictLongRunning":
            min_seconds = int(os.getenv("VEO_GOOGLE_MIN_DURATION_SECONDS", "4"))
            max_seconds = int(os.getenv("VEO_GOOGLE_MAX_DURATION_SECONDS", "8"))
            method_duration = int(max(min_seconds, min(max_seconds, clamped_duration)))
            payload = {
                "instances": [{"prompt": prompt}],
                "parameters": {
                    "durationSeconds": method_duration,
                    "aspectRatio": aspect_ratio,
                },
            }
        else:
            payload = {
                "prompt": {"text": prompt},
                "config": {
                    "durationSeconds": clamped_duration,
                    "aspectRatio": aspect_ratio,
                },
            }
            if reference_images:
                payload["referenceImages"] = reference_images

        try:
            _veo_debug("google-request", {"endpoint": endpoint, "method": method, "aspect_ratio": aspect_ratio})
            resp = requests.post(
                endpoint,
                params={"key": api_key},
                headers={"Content-Type": "application/json"},
                json=payload,
                timeout=180,
            )
            resp.raise_for_status()
            data = _json_response(resp)
            _veo_debug("google-create-response", data)
            break
        except requests.HTTPError as exc:
            last_error = exc
            status = exc.response.status_code if exc.response is not None else None
            error_payload = _json_response(exc.response) if exc.response is not None else {}
            _veo_debug("google-create-error", {"status": status, "payload": error_payload})
            # Try next method when endpoint is not found/supported
            if status == 404:
                continue
            raise

    if not data:
        if last_error:
            raise last_error
        return None

    # Some providers may return completed payload immediately.
    direct_url = _extract_first(
        data,
        _env_csv(
            "VEO_GOOGLE_DIRECT_VIDEO_URL_PATHS",
            "generateVideoResponse.generatedSamples.0.video.uri,generatedVideos.0.video.uri,videos.0.uri,video.uri,video_url",
        ),
    )
    if direct_url:
        parsed = urlparse(str(direct_url))
        if parsed.scheme in {"http", "https"}:
            _download_to_file(str(direct_url), output, params=_google_download_params(str(direct_url), api_key))
            return {
                "path": str(output),
                "duration_seconds": _probe_duration(output),
                "file_size_bytes": output.stat().st_size if output.exists() else None,
                "resolution": _probe_resolution(output),
                "provider": "veo-google-direct-url",
            }

    op_name = _extract_first(data, _env_csv("VEO_GOOGLE_OPERATION_PATHS", "name,operation.name,operation.id,id"))
    if not op_name:
        return None

    video_url = _poll_google_operation_video_url(
        operation_name_or_id=str(op_name),
        api_key=api_key,
        timeout_seconds=timeout_seconds,
    )
    if not video_url:
        _veo_debug("google-operation-no-video", {"operation": str(op_name)})
        return None

    parsed = urlparse(video_url)
    if parsed.scheme not in {"http", "https"}:
        return None

    _download_to_file(video_url, output, params=_google_download_params(video_url, api_key))
    return {
        "path": str(output),
        "duration_seconds": _probe_duration(output),
        "file_size_bytes": output.stat().st_size if output.exists() else None,
        "resolution": _probe_resolution(output),
        "provider": "veo-google-operation-url",
    }


def _sanitize_prompt_for_veo(prompt: str) -> str:
    """Strip real people's names and politically sensitive terms from video prompts
    to avoid Veo RAI content filter rejections.

    Veo rejects prompts containing real people's names/likenesses and certain
    politically charged imagery.
    """
    import re

    # Replace patterns like "Rep. Letlow", "Sen. Whitehouse", "Representative Julia Letlow"
    prompt = re.sub(
        r"\b(Rep(?:resentative)?|Sen(?:ator)?)\.\s+[A-Z][a-z]+(?:\s+[A-Z][a-z]+)*",
        r"an official",
        prompt,
    )
    prompt = re.sub(
        r"\b(Representative|Senator)\s+[A-Z][a-z]+(?:\s+[A-Z][a-z]+)*",
        r"an official",
        prompt,
    )
    # Replace "'Rep. Lastname | TICKER'" patterns in overlaid text
    prompt = re.sub(
        r"'(?:Rep|Sen)\.\s+[A-Z][a-z]+\s*\|",
        "'An Official |",
        prompt,
    )
    # Catch bare proper names (2-4 capitalized words) followed by possessive,
    # e.g. "Marjorie Taylor Greene's name" -> "an official's name"
    prompt = re.sub(
        r"\b[A-Z][a-z]+(?:\s+[A-Z][a-z]+){1,3}'s\b",
        "an official's",
        prompt,
    )
    # Catch "with <Full Name>" patterns (2-4 capitalized words not after title)
    prompt = re.sub(
        r"\bwith\s+[A-Z][a-z]+(?:\s+[A-Z][a-z]+){1,3}\b",
        "with an official",
        prompt,
    )
    # Catch "by <Full Name>" patterns
    prompt = re.sub(
        r"\bby\s+[A-Z][a-z]+(?:\s+[A-Z][a-z]+){1,3}\b",
        "by an official",
        prompt,
    )
    # Replace standalone "Firstname Lastname" patterns (2-4 capitalized words
    # preceded by common intro words like showing/displaying/naming/featuring)
    prompt = re.sub(
        r"\b(showing|displaying|naming|featuring|labeled|labelled)\s+[A-Z][a-z]+(?:\s+[A-Z][a-z]+){1,3}\b",
        r"\1 an official",
        prompt,
    )
    # Strip real ticker symbols that map to famous people (Veo associates TSLA → Elon Musk)
    ticker_map = {
        "TSLA": "an electric vehicle stock",
        "AMZN": "a tech conglomerate stock",
        "META": "a social media stock",
        "GOOG": "a search engine stock",
        "GOOGL": "a search engine stock",
    }
    for ticker, replacement in ticker_map.items():
        prompt = re.sub(rf"\b{ticker}\b", replacement, prompt)
    # Soften political landmarks and charged terms
    prompt = re.sub(r"\bthe\s+Capitol\s+building\b", "a government building", prompt, flags=re.IGNORECASE)
    prompt = re.sub(r"\bCapitol\s+building\b", "a government building", prompt, flags=re.IGNORECASE)
    prompt = re.sub(r"\bthe\s+Capitol\b", "a government building", prompt, flags=re.IGNORECASE)
    prompt = re.sub(r"\bUS\s+Capitol\b", "a government building", prompt, flags=re.IGNORECASE)
    prompt = re.sub(r"\bpolitical\s+commentary\b", "opinion", prompt, flags=re.IGNORECASE)
    prompt = re.sub(r"\ba\s+senator's\b", "an official's", prompt, flags=re.IGNORECASE)
    prompt = re.sub(r"\ba\s+congressman's\b", "an official's", prompt, flags=re.IGNORECASE)
    # Final pass: strip any remaining political role words that Veo flags
    prompt = re.sub(r"\blawmaker", "person", prompt, flags=re.IGNORECASE)
    prompt = re.sub(r"\bsenator\b", "person", prompt, flags=re.IGNORECASE)
    prompt = re.sub(r"\bcongressman\b", "person", prompt, flags=re.IGNORECASE)
    prompt = re.sub(r"\bcongresswoman\b", "person", prompt, flags=re.IGNORECASE)
    prompt = re.sub(r"\bpolitician\b", "person", prompt, flags=re.IGNORECASE)
    return prompt


def generate_video_from_prompt(
    prompt: str,
    output_path: str,
    duration_seconds: float,
    aspect_ratio: str = "9:16",
    reference_image_paths: list[str] | None = None,
) -> dict[str, Any]:
    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)

    # Sanitize prompt to avoid Veo RAI content filter rejections
    prompt = _sanitize_prompt_for_veo(prompt)

    endpoint = os.getenv("VEO_API_ENDPOINT", "").strip()
    api_key = os.getenv("VEO_API_KEY", "").strip() or os.getenv("GEMINI_API_KEY", "").strip()
    timeout_seconds = int(os.getenv("VEO_TIMEOUT_SECONDS", "600"))
    provider = os.getenv("VEO_PROVIDER", "auto").strip().lower()

    max_retries = int(os.getenv("VEO_RETRIES", "2"))
    last_veo_error: str | None = None

    if provider in {"google", "google-genai", "genai", "auto"} and not endpoint:
        for attempt in range(max_retries + 1):
            # Drop reference images on retries — they may contain text/faces
            # that trigger Veo's RAI content filter.
            ref_paths = reference_image_paths if attempt == 0 else None
            try:
                result = _try_google_genai_veo(
                    api_key=api_key,
                    prompt=prompt,
                    output=output,
                    duration_seconds=duration_seconds,
                    aspect_ratio=aspect_ratio,
                    timeout_seconds=timeout_seconds,
                    reference_image_paths=ref_paths,
                )
                if result:
                    return result
                last_veo_error = f"Veo attempt {attempt+1}: returned no video (operation may have failed or timed out)"
            except Exception as exc:
                last_veo_error = f"Veo attempt {attempt+1}: {exc}"
            _veo_debug("google-attempt-failed", {"attempt": attempt + 1, "error": last_veo_error})
            if attempt < max_retries:
                wait = 10 * (attempt + 1)
                if ref_paths:
                    _veo_debug("google-retry-no-refs", {"reason": "dropping reference images for retry"})
                _veo_debug("google-retry", {"attempt": attempt + 1, "max_retries": max_retries, "wait_seconds": wait})
                time.sleep(wait)

    if endpoint:
        try:
            result = _try_generic_endpoint(
                endpoint=endpoint,
                api_key=api_key,
                prompt=prompt,
                output=output,
                duration_seconds=duration_seconds,
                aspect_ratio=aspect_ratio,
                timeout_seconds=timeout_seconds,
            )
            if result:
                return result
        except Exception as exc:
            last_veo_error = f"Generic endpoint: {exc}"

    # Always keep pipeline runnable even if Veo is not configured
    fallback = _generate_placeholder_video(output, duration_seconds=duration_seconds)
    if last_veo_error:
        fallback["error"] = last_veo_error
    return fallback
