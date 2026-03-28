import sys
sys.path.insert(0, ".")
from backend.gemini.media_generation import _sanitize_prompt_for_veo

tests = [
    "A 9:16 vertical video. Overlaid text: 'Rep. Letlow | UNH Buy'. Rep. Letlow's trade.",
    "Senator Sheldon Whitehouse's $32,500 sale of TSLA stock",
    "Rep. Evans' TSLA stock sale flagged",
    "Representative Julia Letlow's buy order for UNH",
    "Sen. Whitehouse sold TSLA near legislation",
]
for t in tests:
    print(f"IN:  {t}")
    print(f"OUT: {_sanitize_prompt_for_veo(t)}")
    print()
