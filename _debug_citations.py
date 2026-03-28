"""Debug why trades 3687, 3720, 4147, 6537 get no citation_image_prompts."""
import sys, json
sys.path.insert(0, ".")
from dotenv import load_dotenv; load_dotenv(".env")
from backend.gemini.contextualizer import _fetch_trade_context, _fetch_nearby_bills, build_initial_message

for tid in [3687, 3720, 4147, 6537]:
    print(f"\n=== Trade {tid} ===")
    trade = _fetch_trade_context(tid)
    if not trade:
        print("  NOT FOUND")
        continue
    print(f"  Ticker: {trade.get('ticker')}")
    print(f"  Date: {trade.get('trade_date')}")
    print(f"  Sector: {trade.get('sector')}")
    print(f"  Politician: {trade.get('full_name')}")

    bills = _fetch_nearby_bills(trade.get("trade_date"), trade.get("sector"))
    print(f"  Nearby bills: {len(bills)}")
    for b in bills:
        print(f"    - {b.get('bill_id')}: {b.get('title', '')[:80]}")

    msg = build_initial_message(trade)
    if "No relevant bills found" in msg or "nearby_bills" in msg:
        if "nearby_bills\": []" in msg or "nearby_bills\":[]" in msg:
            print("  ** No bills in the message context **")
        elif "No relevant bills" in msg:
            print("  ** 'No relevant bills found' in message **")
