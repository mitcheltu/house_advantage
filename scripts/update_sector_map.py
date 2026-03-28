"""Update _combined_sector_map.json to support multi-sector tickers."""
import json
import os

MAP_PATH = os.path.join(os.path.dirname(__file__), "..", "backend", "data", "raw", "_combined_sector_map.json")

MULTI_SECTOR = {
    "MSFT": ["tech", "defense"],
    "AMZN": ["tech", "telecom"],
    "GOOG": ["tech", "telecom"],
    "GOOGL": ["tech", "telecom"],
    "META": ["tech", "telecom"],
    "GE": ["defense", "energy", "healthcare"],
    "HON": ["defense", "tech", "energy"],
    "MMM": ["defense", "healthcare"],
    "UNH": ["healthcare", "finance"],
    "VZ": ["telecom", "tech"],
    "T": ["telecom", "tech"],
    "CRM": ["tech", "defense"],
    "ORCL": ["tech", "defense"],
    "IBM": ["tech", "defense"],
    "INTC": ["tech", "defense"],
    "PLTR": ["tech", "defense"],
    "LHX": ["defense", "tech"],
    "CSCO": ["tech", "telecom", "defense"],
    "ACN": ["tech", "defense"],
    "ABT": ["healthcare", "tech"],
    "MDT": ["healthcare", "tech"],
    "TMO": ["healthcare", "tech"],
    "DHR": ["healthcare", "tech"],
    "SYK": ["healthcare", "tech"],
    "BDX": ["healthcare", "tech"],
    "CI": ["healthcare", "finance"],
    "HUM": ["healthcare", "finance"],
    "AIG": ["finance", "healthcare"],
    "BRK.B": ["finance", "energy", "defense"],
    "DUK": ["energy", "tech"],
    "NEE": ["energy", "tech"],
    "QCOM": ["tech", "telecom", "defense"],
    "AVGO": ["tech", "telecom"],
}

def main():
    with open(MAP_PATH) as f:
        m = json.load(f)

    updated = 0
    for ticker, sectors in MULTI_SECTOR.items():
        if ticker in m:
            old = m[ticker]
            m[ticker] = sectors
            updated += 1
            print(f"  {ticker}: \"{old}\" -> {sectors}")
        else:
            print(f"  {ticker}: NOT IN MAP (skipping)")

    print(f"\nUpdated {updated} tickers to multi-sector")
    print(f"Total map size: {len(m)}")

    from collections import Counter
    types = Counter(type(v).__name__ for v in m.values())
    print(f"Value types: {types}")

    with open(MAP_PATH, "w") as f:
        json.dump(m, f, indent=2)
    print("Saved updated _combined_sector_map.json")

if __name__ == "__main__":
    main()
