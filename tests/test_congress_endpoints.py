"""Quick test to verify corrected Congress.gov API endpoints."""
import requests
import os
from dotenv import load_dotenv

load_dotenv()
key = os.getenv("CONGRESS_GOV_API_KEY")
base = "https://api.congress.gov/v3"
params = {"api_key": key, "format": "json", "limit": 1}

print("=== TEST 1: House votes (was /vote/119/house, now /house-vote/119) ===")
r = requests.get(f"{base}/house-vote/119", params=params)
print(f"  Status: {r.status_code}")
data = r.json()
votes = data.get("houseRollCallVotes", [])
pag = data.get("pagination", {})
print(f"  Got {len(votes)} vote(s), total count: {pag.get('count', '?')}")
if votes:
    v = votes[0]
    print(f"  Sample: rollCall={v.get('rollCallNumber')}, url={v.get('url')}")
    vote_url = v.get("url", "")
    if vote_url:
        r2 = requests.get(
            f"{vote_url}/members",
            params={"api_key": key, "format": "json", "limit": 3},
        )
        print(f"  Members endpoint status: {r2.status_code}")
        vote_member_data = r2.json().get("houseRollCallVoteMemberVotes", {})
        members = vote_member_data.get("results", [])
        print(f"  Got {len(members)} member position(s)")
        if members:
            m = members[0]
            print(f"  Sample: bioguideID={m.get('bioguideID')}, voteCast={m.get('voteCast')}")

print()
print("=== TEST 2: Committee detail (was /committee/119/hsbu00, now /committee/119/house/hsbu00) ===")
r = requests.get(f"{base}/committee/119/house/hsbu00", params={"api_key": key, "format": "json"})
print(f"  Status: {r.status_code}")
detail = r.json().get("committee", {})
print(f"  Committee: {detail.get('systemCode', '?')}")
print(f"  Has currentMembers: {'currentMembers' in detail}")
print(f"  Has members: {'members' in detail}")
print(f"  Keys: {list(detail.keys())}")

print()
print("=== TEST 3: Senate committee (was /committee/119/ssbu00, now /committee/119/senate/ssbu00) ===")
r = requests.get(f"{base}/committee/119/senate/ssbu00", params={"api_key": key, "format": "json"})
print(f"  Status: {r.status_code}")
if r.status_code == 200:
    detail = r.json().get("committee", {})
    print(f"  Committee: {detail.get('systemCode', '?')}")
else:
    print(f"  Response: {r.text[:200]}")

print()
print("=== TEST 4: Old broken vote URL (should fail) ===")
r = requests.get(f"{base}/vote/119/house", params=params)
print(f"  Status: {r.status_code} (expected 404)")

print()
print("=== RESULTS ===")
print("If Tests 1-3 show status 200, the endpoints are fixed.")
