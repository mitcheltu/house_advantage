"""Generate the expanded TICKER_SECTOR_MAP dict and save to a JSON for merge_trades.py."""
import json
import sys
sys.path.insert(0, ".")
from backend.ingest.collectors.merge_trades import TICKER_SECTOR_MAP

new_mapped = json.load(open("backend/data/raw/_new_sector_mappings.json"))
combined = {**TICKER_SECTOR_MAP, **new_mapped}

# Save combined as JSON for easy reference
json.dump(combined, open("backend/data/raw/_combined_sector_map.json", "w"), indent=2)

# Print grouped by sector
by_sector = {}
for t, s in sorted(combined.items()):
    by_sector.setdefault(s, []).append(t)

for sector in ["defense", "finance", "healthcare", "energy", "tech", "telecom", "agriculture"]:
    tickers = sorted(by_sector.get(sector, []))
    pairs = [f'"{t}": "{sector}"' for t in tickers]
    print(f"    # ── {sector.title()} ({len(tickers)}) ──")
    for i in range(0, len(pairs), 6):
        print("    " + ", ".join(pairs[i:i+6]) + ",")

print(f"\n# Total: {len(combined)}")
