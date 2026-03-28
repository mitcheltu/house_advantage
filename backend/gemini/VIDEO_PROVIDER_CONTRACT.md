# Video Provider Contract Configuration

This project now supports two automated video generation modes through environment config only (no code edits needed).

## 1) Google GenAI Veo mode

Use when you want direct Veo calls via `GEMINI_API_KEY`.

Required:
- `VEO_PROVIDER=google-genai` (or `auto` with empty `VEO_API_ENDPOINT`)
- `GEMINI_API_KEY=...`
- Optional model override: `VEO_MODEL=veo-3.1-generate-preview`

The runner will:
1. POST `models/{VEO_MODEL}:generateVideos`
2. Poll the returned operation name
3. Extract the output URL from configured path list
4. Download and mux audio + video

## 2) Generic provider mode

Use when you have your own Veo-compatible endpoint.

Required:
- `VEO_PROVIDER=generic`
- `VEO_API_ENDPOINT=https://...`
- Optional `VEO_STATUS_ENDPOINT=https://...` (if async operation polling is required)
- Set auth mode:
  - `VEO_AUTH_MODE=bearer` (default)
  - `VEO_AUTH_MODE=header`
  - `VEO_AUTH_MODE=x-api-key`
  - `VEO_AUTH_MODE=query`

Response extraction paths are configurable:
- `VEO_RESPONSE_VIDEO_URL_PATHS`
- `VEO_RESPONSE_VIDEO_BASE64_PATHS`
- `VEO_RESPONSE_OPERATION_PATHS`

## Polling and timeout

- `VEO_TIMEOUT_SECONDS` controls end-to-end wait
- `VEO_POLL_INTERVAL_SECONDS` controls polling frequency

## Local fallback behavior

If real video generation is not available, pipeline falls back to placeholder video generation.

To enable fallback locally, install system `ffmpeg`.

## Common failure causes

- Missing/invalid API key
- Wrong auth mode (header vs query)
- Incorrect operation/result JSON paths
- `ffmpeg` not installed for fallback mode
