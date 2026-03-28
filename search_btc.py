"""Properly query Polymarket events endpoint and debug the response format."""
import requests, json

# Step 1: Fetch active events and inspect format
print("=== DEBUGGING EVENT RESPONSE FORMAT ===")
r = requests.get("https://gamma-api.polymarket.com/events", params={
    "active": "true", "closed": "false", "limit": 5,
    "order": "volume_24hr", "ascending": "false"
}, timeout=15)
data = r.json()
print(f"Type: {type(data)}")
if isinstance(data, list):
    print(f"Length: {len(data)}")
    if data:
        print(f"First item type: {type(data[0])}")
        print(f"First item: {json.dumps(data[0], indent=2)[:500]}")
elif isinstance(data, dict):
    print(f"Keys: {list(data.keys())}")
    print(f"Sample: {json.dumps(data, indent=2)[:500]}")

# Step 2: Try different approaches
print("\n=== EVENTS with tag_id for Bitcoin ===")
for tag_id in [101531, 101944]:
    r = requests.get("https://gamma-api.polymarket.com/events", params={
        "tag_id": str(tag_id), "active": "true", "closed": "false", "limit": 20
    }, timeout=15)
    events = r.json()
    print(f"\ntag_id={tag_id}: {len(events) if isinstance(events, list) else 'dict'} events")
    if isinstance(events, list):
        for e in events[:5]:
            if isinstance(e, dict):
                print(f"  {e.get('title', '?')[:70]}")
            else:
                print(f"  raw: {str(e)[:100]}")
    elif isinstance(events, dict):
        print(f"  Keys: {list(events.keys())}")

# Step 3: Full active events with pagination, properly handle format
print("\n=== ALL ACTIVE EVENTS (paginated) ===")
all_events = []
offset = 0
while offset < 1000:
    r = requests.get("https://gamma-api.polymarket.com/events", params={
        "active": "true", "closed": "false", "limit": 100, "offset": offset
    }, timeout=15)
    chunk = r.json()
    if not chunk or (isinstance(chunk, list) and len(chunk) == 0):
        break
    if isinstance(chunk, list):
        all_events.extend(chunk)
    elif isinstance(chunk, dict) and "data" in chunk:
        all_events.extend(chunk["data"])
    else:
        all_events.append(chunk)
    offset += 100

print(f"Total active events fetched: {len(all_events)}")

# Filter for crypto
btc_kw = ["bitcoin", "btc", "crypto", "ethereum", "eth ", "solana", "defi", 
           "blockchain", "token", "stablecoin", "mining", "halving", "reserve",
           "coinbase", "binance", "sec crypto", "digital asset"]
crypto_events = []

for e in all_events:
    if isinstance(e, str):
        continue
    title = str(e.get("title", "")).lower()
    desc = str(e.get("description", "")).lower()
    combined = title + " " + desc
    # Check markets too
    markets = e.get("markets", [])
    if isinstance(markets, list):
        for m in markets:
            if isinstance(m, dict):
                combined += " " + str(m.get("question", "")).lower()
    if any(kw in combined for kw in btc_kw):
        crypto_events.append(e)

print(f"Crypto-related: {len(crypto_events)}")
for e in crypto_events:
    if isinstance(e, str):
        print(f"  (string): {e[:80]}")
        continue
    title = e.get("title", "?")[:70]
    markets = e.get("markets", []) if isinstance(e.get("markets"), list) else []
    print(f"\n  EVENT: {title} ({len(markets)} markets)")
    for m in markets[:5]:
        if isinstance(m, dict):
            q = m.get("question", "?")[:80]
            tokens = m.get("tokens", [])
            price = tokens[0].get("price", "?") if tokens and isinstance(tokens, list) and isinstance(tokens[0], dict) else "?"
            print(f"    [{price}] {q}")

if not crypto_events:
    print("\n  --> NO crypto events found in active events!")
    print("  --> Showing first 10 events for context:")
    for e in all_events[:10]:
        if isinstance(e, dict):
            print(f"    {e.get('title', '?')[:80]}")
        else:
            print(f"    (type={type(e).__name__}) {str(e)[:80]}")
