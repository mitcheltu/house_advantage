"""Re-contextualize trades with missing citation_image_prompts."""
import sys
sys.path.insert(0, ".")
from dotenv import load_dotenv; load_dotenv(".env")
from backend.gemini.contextualizer import contextualize_trade

TRADE_IDS = [3687, 3720, 4147, 6537]

for tid in TRADE_IDS:
    print(f"\n--- Contextualizing trade {tid} ---")
    result = contextualize_trade(trade_id=tid, force=True)
    print(f"  Result: {result}")
