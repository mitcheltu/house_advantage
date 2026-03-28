import os, requests, json
from dotenv import load_dotenv
load_dotenv()
key = os.getenv("GEMINI_API_KEY")
base = "https://generativelanguage.googleapis.com/v1beta"
model = "gemini-3.1-flash-image-preview"
endpoint = f"{base}/models/{model}:generateContent"

payload = {
    "contents": [{"parts": [{"text": "Create a dark-themed infographic card with a red stripe at top, title H.R. 3847, background #090d14, text #e5ebf5, 16:9 aspect ratio, no photographs"}]}],
    "generationConfig": {
        "responseModalities": ["IMAGE"],
    },
}

resp = requests.post(endpoint, params={"key": key}, headers={"Content-Type": "application/json"}, json=payload, timeout=120)
print(f"Status: {resp.status_code}")
data = resp.json()
if resp.status_code == 200:
    candidates = data.get("candidates", [])
    for c in candidates:
        parts = c.get("content", {}).get("parts", [])
        for p in parts:
            inline = p.get("inlineData") or p.get("inline_data") or {}
            mime = inline.get("mimeType") or inline.get("mime_type") or "unknown"
            b64 = inline.get("data", "")
            if b64:
                print(f"Got image! mimeType={mime}, data_len={len(b64)}")
            elif p.get("text"):
                print(f"Got text: {p['text'][:200]}")
else:
    print(f"Error: {json.dumps(data, indent=2)[:1000]}")
