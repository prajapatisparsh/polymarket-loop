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
        resp = requests.get(f"https://clob.polymarket.com/markets/{bet['market_id']}", timeout=10)
        if not resp.ok:
            print(f"  CLOB fetch failed for {bet['market_id']}: {resp.status_code}")
            continue
        r = resp.json()
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

    # Load existing open bets to skip duplicate markets
    open_market_ids = {b["market_id"] for b in sb.table("bets").select("market_id").eq("resolved", False).execute().data}

    for m in markets[:15]:
        q = m.get("question", "")
        cid = m.get("condition_id", "")
        price = float(m.get("tokens", [{}])[0].get("price", 0.5))

        if cid in open_market_ids:
            print(f"  Skipping duplicate open bet: {q[:50]}")
            continue

        print(f"\nAnalyzing: {q[:60]}")
        time.sleep(3)  # pace before macro call

        macro = ask(macro_prompt, f"Market: {q}")
        time.sleep(2)  # pace before domain call
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

        # Pass clean JSON summary to analyst, not raw LLM output
        domain_summary = json.dumps(domain_result)
        time.sleep(2)  # pace before analyst call

        raw = ask(analyst_prompt, f"Market: {q}\nMarket price: {price}\nMacro: {macro}\nDomain: {domain_summary}")

        try:
            start = raw.find("{")
            end = raw.rfind("}") + 1
            result = json.loads(raw[start:end])
            if result.get("place_paper_bet"):
                sb.table("bets").insert({
                    "market_id": cid,
                    "question": q,
                    "predicted_prob": result["final_prob"],
                    "market_price": price,
                    "resolved": False,
                    "created_at": datetime.now(timezone.utc).isoformat()
                }).execute()
                edge_val = result.get("edge") or 0
                print(f"✓ Paper bet logged | edge: {edge_val:.3f}")
            else:
                print(f"No edge found")
        except Exception as e:
            print(f"Parse error: {e}")

if __name__ == "__main__":
    run()
