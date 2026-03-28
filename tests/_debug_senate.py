"""Quick debug script to inspect Senate eFD search page."""
import requests
from bs4 import BeautifulSoup
import re

s = requests.Session()
s.headers.update({
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                  "AppleWebKit/537.36 (KHTML, like Gecko) "
                  "Chrome/120.0.0.0 Safari/537.36"
})

# Accept agreement
r1 = s.get("https://efdsearch.senate.gov/search/", timeout=15)
soup = BeautifulSoup(r1.text, "html.parser")
csrf = soup.find("input", {"name": "csrfmiddlewaretoken"})
token = csrf["value"] if csrf else ""
print(f"CSRF: {token[:20]}...")

r2 = s.post(
    "https://efdsearch.senate.gov/search/",
    data={"csrfmiddlewaretoken": token, "prohibition_agreement": "1"},
    headers={"Referer": "https://efdsearch.senate.gov/search/"},
    timeout=15,
)
print(f"Agreement: {r2.status_code}")

# Get the search home page
r3 = s.get("https://efdsearch.senate.gov/search/home/", timeout=15)
soup3 = BeautifulSoup(r3.text, "html.parser")

# Look for ajax, datatable, or API references in scripts
scripts = soup3.find_all("script")
for sc in scripts:
    txt = sc.string or ""
    if "ajax" in txt.lower() or "datatable" in txt.lower() or "api" in txt.lower():
        print("SCRIPT WITH AJAX/DATATABLE:")
        print(txt[:800])
        print("---")

# Check forms
forms = soup3.find_all("form")
for f in forms:
    action = f.get("action", "")
    method = f.get("method", "")
    print(f"FORM: action={action}, method={method}")
    inputs = f.find_all("input")
    for inp in inputs:
        name = inp.get("name", "")
        itype = inp.get("type", "")
        val = str(inp.get("value", ""))[:50]
        print(f"  INPUT: name={name}, type={itype}, value={val}")

# Try the DataTables AJAX endpoint pattern
print("\n--- Testing AJAX search ---")
csrf2 = soup3.find("input", {"name": "csrfmiddlewaretoken"})
token2 = csrf2["value"] if csrf2 else token

r4 = s.post(
    "https://efdsearch.senate.gov/search/home/",
    data={
        "csrfmiddlewaretoken": token2,
        "first_name": "",
        "last_name": "",
        "filer_type": "1",
        "report_type": "11",
        "submitted_start_date": "01/01/2025",
        "submitted_end_date": "06/30/2025",
    },
    headers={
        "Referer": "https://efdsearch.senate.gov/search/home/",
        "X-Requested-With": "XMLHttpRequest",
    },
    timeout=30,
)
print(f"Search response: {r4.status_code}")
print(f"Content-Type: {r4.headers.get('Content-Type', '?')}")
print(f"Body length: {len(r4.text)}")
print(f"Body preview: {r4.text[:500]}")
