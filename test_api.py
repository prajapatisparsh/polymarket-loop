"""Quick test: what does Polymarket API actually return for crypto/bitcoin markets?"""
import requests, json
from datetime import datetime, timezone

now = datetime.now(timezone.utc)

def fetch_tag(tag):
    r = requests.get("https://gamma-api.polymarket.com/markets",
        params={"active": "true", "closed": "false", "tag_slug": tag, "limit": 20}, timeout=10)
    data = r.json() if r.ok else []
    if not isinstance(data, list):
        data = data.get("markets", [])
    return data

def fetch_keyword(kw):
    r = requests.get("https://gamma-api.polymarket.com/markets",
        params={"active": "true", "closed": "false", "q": kw, "limit": 20}, timeout=10)
    data = r.json() if r.ok else []
    if not isinstance(data, list):
        data = data.get("markets", [])
    return data

print("="*80)
print("TAG: bitcoin")
print("="*80)
for m in fetch_tag("bitcoin"):
    end = m.get("endDateIso", "?")[:10]
    vol = m.get("volumeClob") or m.get("volume") or 0
    q = m.get("question", "")[:80]
    print(f"  {q}")
    print(f"    vol={vol} | end={end} | cid={m.get('conditionId','?')[:20]}")

print()
print("="*80)
print("TAG: crypto")
print("="*80)
for m in fetch_tag("crypto"):
    end = m.get("endDateIso", "?")[:10]
    vol = m.get("volumeClob") or m.get("volume") or 0
    q = m.get("question", "")[:80]
    print(f"  {q}")
    print(f"    vol={vol} | end={end}")

print()
print("="*80)
print("KEYWORD: 'bitcoin price'")
print("="*80)
for m in fetch_keyword("bitcoin price"):
    q = m.get("question", "")[:80]
    vol = m.get("volumeClob") or m.get("volume") or 0
    print(f"  {q} | vol={vol}")

print()
print("="*80)
print("KEYWORD: '5 minute bitcoin'")
print("="*80)
for m in fetch_keyword("5 minute bitcoin"):
    q = m.get("question", "")[:80]
    vol = m.get("volumeClob") or m.get("volume") or 0
    print(f"  {q} | vol={vol}")

print()
print("="*80)
print("KEYWORD: 'btc'")
print("="*80)
for m in fetch_keyword("btc"):
    q = m.get("question", "")[:80]
    vol = m.get("volumeClob") or m.get("volume") or 0
    print(f"  {q} | vol={vol}")

# Also check ALL tags to see what tags exist
print()
print("="*80)
print("TAG: politics (to see if sports leak in)")
print("="*80)
for m in fetch_tag("politics")[:5]:
    q = m.get("question", "")[:80]
    print(f"  {q}")
