"""Test Senate parser against both real HTML examples."""
from backend.ingest.collectors.collect_senate_disclosures import SenateScraper

# Example 1: ticker="--", asset="starbuck", type="Stock"
HTML_1 = """
<table class="table table-striped">
    <thead><tr class="header">
        <th scope="col">&#35;</th>
        <th scope="col">Transaction Date</th>
        <th scope="col">Owner</th>
        <th scope="col">Ticker</th>
        <th scope="col">Asset Name</th>
        <th scope="col">Asset Type</th>
        <th scope="col">Type</th>
        <th scope="col">Amount</th>
        <th scope="col">Comment</th>
    </tr></thead>
    <tbody>
        <tr>
            <td>1</td><td>08/04/2025</td><td>Self</td>
            <td>--</td><td>starbuck</td><td>Stock</td>
            <td>Purchase</td><td>$1,001 - $15,000</td><td>--</td>
        </tr>
    </tbody>
</table>
"""

# Example 2: ticker=link, asset type="Other"
HTML_2 = """
<table class="table table-striped">
    <thead><tr class="header">
        <th scope="col">&#35;</th>
        <th scope="col">Transaction Date</th>
        <th scope="col">Owner</th>
        <th scope="col">Ticker</th>
        <th scope="col">Asset Name</th>
        <th scope="col">Asset Type</th>
        <th scope="col">Type</th>
        <th scope="col">Amount</th>
        <th scope="col">Comment</th>
    </tr></thead>
    <tbody>
        <tr>
            <td>1</td><td>02/18/2025</td><td>Joint</td>
            <td><a href="https://finance.yahoo.com/quote/YUM" target="_blank">YUM</a></td>
            <td>Yum! Brands<div class="text-muted"><em>Company:</em> Yum&nbsp;(Louisville, KY)</div>
                <div class="text-muted"><em>Description:</em>&nbsp;Food</div></td>
            <td>Other</td>
            <td>Sale (Full)</td>
            <td>$1,001 - $15,000</td><td>--</td>
        </tr>
    </tbody>
</table>
"""

filing = {"first_name": "James", "last_name": "Banks",
          "full_name": "James Banks", "filing_date": "03/10/2025",
          "report_id": "test-456"}

scraper = SenateScraper.__new__(SenateScraper)
scraper._debug_logged = True

# Test 1
trades1 = scraper._parse_report_page(HTML_1, filing)
print(f"Example 1: {len(trades1)} trade(s)")
for t in trades1:
    print(f"  {t['ticker']:>5}  {t['trade_type']:<4}  {t['trade_date']}")
assert len(trades1) == 1
assert trades1[0]["ticker"] == "SBUX"
assert trades1[0]["trade_type"] == "buy"

# Test 2
trades2 = scraper._parse_report_page(HTML_2, filing)
print(f"Example 2: {len(trades2)} trade(s)")
for t in trades2:
    print(f"  {t['ticker']:>5}  {t['trade_type']:<4}  {t['trade_date']}  asset_type_from_page=Other")
assert len(trades2) == 1
assert trades2[0]["ticker"] == "YUM"
assert trades2[0]["trade_type"] == "sell"

print("\nBoth examples passed!")
