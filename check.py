from dotenv import load_dotenv
load_dotenv()
import requests
from datetime import datetime, timezone

now = datetime.now(timezone.utc)
tags = ["politics", "crypto", "economics", "science", "climate"]
seen = set(); markets = []

for tag in tags:
    r = requests.get("https://gamma-api.polymarket.com/markets",
        params={"active": "true", "closed": "false", "tag_slug": tag, "limit": 50},
        timeout=10)
    data = r.json() if r.ok else []
    if not isinstance(data, list):
        data = data.get("markets", [])
    for m in data:
        cid = m.get("conditionId")
        end_raw = m.get("endDateIso") or ""
        if end_raw:
            try:
                if datetime.fromisoformat(end_raw.replace("Z", "+00:00")) < now:
                    continue
            except Exception:
                pass
        if cid and cid not in seen:
            seen.add(cid)
            markets.append(m)

print(f"Future active markets: {len(markets)}")
for m in markets[:10]:
    print(f" - {m.get('question','')[:80]} | ends: {m.get('endDateIso','')[:10]}")
