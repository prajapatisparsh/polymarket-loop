"""Quick test: what does Polymarket API actually return?"""
import requests, json

def fetch(tag=None, kw=None):
    params = {"active": "true", "closed": "false", "limit": 15}
    if tag: params["tag_slug"] = tag
    if kw: params["q"] = kw
    r = requests.get("https://gamma-api.polymarket.com/markets", params=params, timeout=15)
    data = r.json() if r.ok else []
    if not isinstance(data, list):
        data = data.get("markets", [])
    return data

lines = []

for label, tag, kw in [
    ("TAG: bitcoin", "bitcoin", None),
    ("TAG: crypto", "crypto", None),
    ("KW: bitcoin price", None, "bitcoin price"),
    ("KW: 5 minute bitcoin", None, "5 minute bitcoin"),
    ("KW: btc", None, "btc"),
]:
    lines.append("=" * 70)
    lines.append(label)
    lines.append("=" * 70)
    data = fetch(tag=tag, kw=kw)
    lines.append(f"  Count: {len(data)}")
    for m in data:
        q = m.get("question", "")[:80]
        vol = m.get("volumeClob") or m.get("volume") or 0
        end = (m.get("endDateIso") or "?")[:10]
        lines.append(f"  Q: {q}")
        lines.append(f"     vol={vol} | end={end}")
    lines.append("")

with open("api_results.txt", "w", encoding="utf-8") as f:
    f.write("\n".join(lines))
print("Done! See api_results.txt")
