"""Debug Nano Banana image generation — see raw API response."""
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from dotenv import load_dotenv
load_dotenv(".env")

import requests

api_key = os.getenv("GEMINI_API_KEY", "").strip()
base = os.getenv("GEMINI_API_BASE", "https://generativelanguage.googleapis.com/v1beta").rstrip("/")
model = os.getenv("IMAGE_GEN_MODEL", "gemini-3.1-flash-image-preview")
endpoint = f"{base}/models/{model}:generateContent"

# Use the same type of prompts that the daily scriptwriter generates
test_prompts = [
    # Simple, short prompt
    "Create a clean data visualization card showing a flagged stock trade anomaly with red warning indicators, formal civic design, white background.",
    # Prompt that likely contains political content
    "A flagged stock trade by a public official in an electric vehicle stock, with anomaly score indicators and formal civic design.",
    # The prompt that worked (citation 2 succeeded) - generic
    "Generate a professional citation card image showing statistical data about suspicious congressional trading patterns.",
]

for i, prompt in enumerate(test_prompts):
    print(f"\n{'='*60}")
    print(f"Test {i+1}: {prompt[:80]}...")
    print(f"{'='*60}")

    payload = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {
            "responseModalities": ["IMAGE"],
        },
    }

    resp = requests.post(
        endpoint,
        params={"key": api_key},
        headers={"Content-Type": "application/json"},
        json=payload,
        timeout=120,
    )
    print(f"Status: {resp.status_code}")

    data = resp.json()

    # Print full response structure (without base64 data)
    def strip_b64(obj):
        if isinstance(obj, dict):
            return {k: ("<base64 data>" if k == "data" and isinstance(v, str) and len(v) > 100 else strip_b64(v)) for k, v in obj.items()}
        if isinstance(obj, list):
            return [strip_b64(item) for item in obj]
        return obj

    print(json.dumps(strip_b64(data), indent=2))

    # Check for image data
    candidates = data.get("candidates", [])
    found_image = False
    for cand in candidates:
        parts = cand.get("content", {}).get("parts", [])
        for part in parts:
            inline = part.get("inlineData") or part.get("inline_data") or {}
            if inline.get("data"):
                found_image = True
                print(f"  -> IMAGE FOUND ({len(inline['data'])} chars b64, mime={inline.get('mimeType')})")
            elif part.get("text"):
                print(f"  -> TEXT response: {part['text'][:200]}")

    if not found_image:
        print("  -> NO IMAGE DATA")

    # Check for blocked/filtered
    if data.get("promptFeedback"):
        print(f"  -> promptFeedback: {data['promptFeedback']}")
    for cand in candidates:
        if cand.get("finishReason"):
            print(f"  -> finishReason: {cand['finishReason']}")
