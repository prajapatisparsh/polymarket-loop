from dotenv import load_dotenv
load_dotenv()
import os, json, time, requests
from groq import Groq, RateLimitError
from supabase import create_client
from datetime import datetime, timezone

sb = create_client(os.environ["SUPABASE_URL"], os.environ["SUPABASE_KEY"])
groq = Groq(api_key=os.environ["GROQ_API_KEY"])
MODEL = "moonshotai/kimi-k2-instruct-0905"

macro_prompt = open("prompts/macro.md").read()
domains_prompt = open("prompts/domains.md").read()
analyst_prompt = open("prompts/analyst.md").read()



def ask(system, user, retries=5):
    for attempt in range(retries):
        try:
            r = groq.chat.completions.create(
                model=MODEL,
                messages=[{"role": "system", "content": system}, {"role": "user", "content": user}]
            )
            return r.choices[0].message.content
        except RateLimitError as e:
            if attempt == retries - 1:
                raise
            wait = 2 ** attempt  # 1s, 2s, 4s, 8s, 16s
            print(f"  Rate limit hit, retrying in {wait}s...")
            time.sleep(wait)

def fetch_markets():
    # Use Gamma API — it supports active/closed filters and returns current markets
    tags = ["politics", "crypto", "economics", "science", "climate"]
    seen = set()
    markets = []
    now = datetime.now(timezone.utc)
    for tag in tags:
        r = requests.get("https://gamma-api.polymarket.com/markets",
            params={"active": "true", "closed": "false", "tag_slug": tag, "limit": 100},
            timeout=10)
        data = r.json() if r.ok else []
        if not isinstance(data, list):
            data = data.get("markets", [])
        for m in data:
            cid = m.get("conditionId")
            end_raw = m.get("endDateIso") or m.get("endDate") or ""
            if end_raw:
                try:
                    end_dt = datetime.fromisoformat(end_raw.replace("Z", "+00:00"))
                    if end_dt.tzinfo is None:
                        end_dt = end_dt.replace(tzinfo=timezone.utc)
                    if end_dt < now:
                        continue
                except ValueError:
                    pass
            if not cid or cid in seen:
                continue
            seen.add(cid)
            # normalize to the field names run() expects
            price_raw = m.get("lastTradePrice") or m.get("bestAsk") or 0.5
            markets.append({
                "condition_id": cid,
                "question": m.get("question", ""),
                "tokens": [{"price": float(price_raw)}],
                "_end_date": end_raw[:10],
            })
    print(f"Fetched {len(markets)} relevant markets (future/active only)")
    return markets

def eval_resolved():
    unresolved = sb.table("bets").select("*").eq("resolved", False).execute().data
    for bet in unresolved:
        r = requests.get(f"https://clob.polymarket.com/markets/{bet['market_id']}").json()
        if r.get("closed"):
            tokens = r.get("tokens", [])
            outcome = 1.0 if tokens and tokens[0].get("winner") else 0.0
            sb.table("bets").update({
                "resolved": True,
                "outcome": outcome,
                "resolved_at": datetime.now(timezone.utc).isoformat()
            }).eq("id", bet["id"]).execute()
            print(f"Resolved: {bet['question'][:50]} → {outcome}")

def run():
    print("=== polymarket-loop run ===")
    eval_resolved()
    markets = fetch_markets()

    for m in markets[:15]:
        q = m.get("question", "")
        price = float(m.get("tokens", [{}])[0].get("price", 0.5))
        print(f"\nAnalyzing: {q[:60]}")
        time.sleep(4)  # ~10k TPM / 3 calls per market = ~4s pacing

        macro = ask(macro_prompt, f"Market: {q}")
        domain_raw = ask(domains_prompt, f"Market: {q}\nMacro brief: {macro}")

        try:
            ds = domain_raw.find("{")
            de = domain_raw.rfind("}") + 1
            domain_result = json.loads(domain_raw[ds:de])
        except Exception:
            domain_result = {}

        if not domain_result.get("proceed", False):
            print(f"  Skipped: {domain_result.get('reason', 'domain filter rejected')}")
            continue

        domain = domain_raw

        raw = ask(analyst_prompt, f"Market: {q}\nMarket price: {price}\nMacro: {macro}\nDomain: {domain}")

        try:
            start = raw.find("{")
            end = raw.rfind("}") + 1
            result = json.loads(raw[start:end])
            if result.get("place_paper_bet"):
                sb.table("bets").insert({
                    "market_id": m.get("condition_id",""),
                    "question": q,
                    "predicted_prob": result["final_prob"],
                    "market_price": price,
                    "resolved": False,
                    "created_at": datetime.now(timezone.utc).isoformat()
                }).execute()
                print(f"✓ Paper bet logged | edge: {result.get('edge'):.3f}")
            else:
                print(f"No edge found")
        except Exception as e:
            print(f"Parse error: {e}")

if __name__ == "__main__":
    run()
