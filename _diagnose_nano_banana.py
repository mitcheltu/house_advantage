"""Diagnose Nano Banana API response for citation image generation."""
import os, json, requests, base64
from dotenv import load_dotenv
from pathlib import Path

load_dotenv(Path(__file__).resolve().parent / ".env")

api_key = os.getenv("GEMINI_API_KEY", "").strip()
base = os.getenv("GEMINI_API_BASE", "https://generativelanguage.googleapis.com/v1beta").rstrip("/")
model = os.getenv("IMAGE_GEN_MODEL", "gemini-3.1-flash-image-preview")

endpoint = f"{base}/models/{model}:generateContent"
print(f"Model: {model}")
print(f"Endpoint: {endpoint}")
print()

# Test prompts - one simple, one like what the daily scriptwriter generates
test_prompts = [
    "Create a clean data visualization card showing anomaly scores for a stock trade. Professional infographic with blue and gray tones, bar chart indicators, formal civic design.",
    "Generate an infographic card: A flagged electric vehicle stock trade by multiple public officials shows cohort anomaly index of 67-71. Clean design, data-centric, no photos of real people.",
]

for idx, prompt in enumerate(test_prompts):
    print(f"--- Test {idx+1} ---")
    print(f"Prompt: {prompt[:120]}...")

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

    # Check for blocked / filtered
    pf = data.get("promptFeedback")
    if pf:
        print(f"promptFeedback: {json.dumps(pf, indent=2)}")

    candidates = data.get("candidates", [])
    print(f"Candidates: {len(candidates)}")

    if not candidates:
        print("NO CANDIDATES - full response keys:", list(data.keys()))
        # Print any error info
        if "error" in data:
            print(f"Error: {json.dumps(data['error'], indent=2)}")
        print()
        continue

    for i, c in enumerate(candidates):
        finish = c.get("finishReason", "unknown")
        print(f"  Candidate {i}: finishReason={finish}")
        parts = c.get("content", {}).get("parts", [])
        print(f"  Parts: {len(parts)}")
        for j, p in enumerate(parts):
            keys = list(p.keys())
            print(f"    Part {j}: keys={keys}")
            if "text" in p:
                print(f"      text: {p['text'][:300]}")
            idata = p.get("inlineData") or p.get("inline_data") or {}
            if idata:
                mime = idata.get("mimeType", "unknown")
                b64data = idata.get("data", "")
                print(f"      image: mime={mime}, b64_len={len(b64data)}")
                if b64data:
                    raw = base64.b64decode(b64data)
                    print(f"      decoded: {len(raw)} bytes, magic={raw[:4].hex()}")

        safety = c.get("safetyRatings", [])
        flagged = [s for s in safety if s.get("probability", "NEGLIGIBLE") != "NEGLIGIBLE"]
        if flagged:
            for s in flagged:
                print(f"  SAFETY FLAG: {s}")

    print()

# Also try with TEXT+IMAGE modality to see if that helps
print("--- Test 3: TEXT+IMAGE modality ---")
prompt3 = test_prompts[0]
payload3 = {
    "contents": [{"parts": [{"text": prompt3}]}],
    "generationConfig": {
        "responseModalities": ["TEXT", "IMAGE"],
    },
}
resp3 = requests.post(
    endpoint, params={"key": api_key},
    headers={"Content-Type": "application/json"},
    json=payload3, timeout=120,
)
print(f"Status: {resp3.status_code}")
data3 = resp3.json()
candidates3 = data3.get("candidates", [])
print(f"Candidates: {len(candidates3)}")
for i, c in enumerate(candidates3):
    finish = c.get("finishReason", "unknown")
    parts = c.get("content", {}).get("parts", [])
    print(f"  Candidate {i}: finishReason={finish}, parts={len(parts)}")
    for j, p in enumerate(parts):
        keys = list(p.keys())
        if "text" in p:
            print(f"    Part {j}: text={p['text'][:200]}")
        idata = p.get("inlineData") or p.get("inline_data") or {}
        if idata:
            b64data = idata.get("data", "")
            mime = idata.get("mimeType", "unknown")
            print(f"    Part {j}: image mime={mime}, b64_len={len(b64data)}")
