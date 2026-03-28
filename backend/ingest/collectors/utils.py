"""
Shared utilities for all data collectors.
Handles rate limiting, retries, and common HTTP patterns.
"""
import os
import time
import logging
import requests
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

# ── Logging ───────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s] %(name)s — %(message)s",
    datefmt="%H:%M:%S",
)

# ── Paths ─────────────────────────────────────────────────────
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
DATA_RAW     = PROJECT_ROOT / "data" / "raw"
DATA_CLEANED = PROJECT_ROOT / "data" / "cleaned"
DATA_FEATURES = PROJECT_ROOT / "data" / "features"

for d in [DATA_RAW, DATA_CLEANED, DATA_FEATURES,
          DATA_RAW / "prices", DATA_RAW / "13f"]:
    d.mkdir(parents=True, exist_ok=True)


def get_env(key: str, required: bool = True, default: str = "") -> str:
    """Get an environment variable, raising if required and missing."""
    val = os.getenv(key, default).strip()
    if required and not val:
        raise EnvironmentError(
            f"Missing required environment variable: {key}. "
            f"Check your .env file."
        )
    return val


def rate_limited_get(
    url: str,
    headers: dict = None,
    params: dict = None,
    delay: float = 0.5,
    max_retries: int = 3,
    timeout: int = 60,
) -> requests.Response:
    """
    GET request with automatic retry on 429/5xx and inter-request delay.
    """
    log = logging.getLogger("http")
    for attempt in range(1, max_retries + 1):
        try:
            time.sleep(delay)
            resp = requests.get(url, headers=headers, params=params, timeout=timeout)

            if resp.status_code in (429, 403):
                try:
                    wait = int(resp.headers.get("Retry-After", 10 * attempt))
                except (ValueError, TypeError):
                    wait = 10 * attempt
                log.warning(f"Rate limited ({resp.status_code}) on {url}. "
                            f"Waiting {wait}s (attempt {attempt}/{max_retries})...")
                time.sleep(wait)
                continue

            if resp.status_code >= 500:
                log.warning(f"Server error {resp.status_code} on {url}. "
                            f"Retry {attempt}/{max_retries}...")
                time.sleep(5 * attempt)
                continue

            resp.raise_for_status()
            return resp

        except requests.exceptions.Timeout:
            log.warning(f"Timeout on {url}. Retry {attempt}/{max_retries}...")
            time.sleep(5 * attempt)
        except requests.exceptions.ConnectionError:
            log.warning(f"Connection error on {url}. Retry {attempt}/{max_retries}...")
            time.sleep(5 * attempt)

    raise RuntimeError(f"Failed after {max_retries} retries: {url}")


def rate_limited_post(
    url: str,
    json_body: list | dict,
    headers: dict = None,
    delay: float = 0.5,
    max_retries: int = 3,
    timeout: int = 60,
) -> requests.Response:
    """
    POST request with automatic retry on 429/5xx and inter-request delay.
    """
    log = logging.getLogger("http")
    for attempt in range(1, max_retries + 1):
        try:
            time.sleep(delay)
            resp = requests.post(url, json=json_body, headers=headers, timeout=timeout)

            if resp.status_code == 429:
                wait = int(resp.headers.get("Retry-After", 30))
                log.warning(f"Rate limited on POST {url}. Waiting {wait}s...")
                time.sleep(wait)
                continue

            if resp.status_code >= 500:
                log.warning(f"Server error {resp.status_code} on POST {url}. "
                            f"Retry {attempt}/{max_retries}...")
                time.sleep(5 * attempt)
                continue

            resp.raise_for_status()
            return resp

        except requests.exceptions.Timeout:
            log.warning(f"Timeout on POST {url}. Retry {attempt}/{max_retries}...")
            time.sleep(5 * attempt)
        except requests.exceptions.ConnectionError:
            log.warning(f"Connection error on POST {url}. Retry {attempt}/{max_retries}...")
            time.sleep(5 * attempt)

    raise RuntimeError(f"Failed after {max_retries} retries: POST {url}")
