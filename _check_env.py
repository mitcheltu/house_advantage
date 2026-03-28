from dotenv import load_dotenv
load_dotenv(".env")
import os
k = os.getenv("GEMINI_API_KEY", "")
print(f"GEMINI_API_KEY set: {bool(k)} ({len(k)} chars)")
print(f"FFMPEG_BIN: {os.getenv('FFMPEG_BIN', 'not set')}")
print(f"VEO_PROVIDER: {os.getenv('VEO_PROVIDER', 'not set')}")
print(f"TTS_PROVIDER: {os.getenv('TTS_PROVIDER', 'not set')}")
import shutil
ff = shutil.which("ffmpeg")
print(f"ffmpeg in PATH: {ff}")
