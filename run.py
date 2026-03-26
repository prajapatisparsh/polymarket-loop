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

GAMING_BLACKLIST = [
    "gta vi", "gta 6", "grand theft auto", "before gta", "rockstar",
    "call of duty", "cod ", "minecraft", "fortnite", "video game release",
    "gaming", "game release",
]

def _iter_raw_markets(tag=None, keyword=None):
    """Yield raw market dicts from Gamma API by tag slug or keyword search."""
    params = {"active": "true", "closed": "false", "limit": 100}
    if tag:
        params["tag_slug"] = tag
    if keyword:
        params["q"] = keyword
    r = requests.get("https://gamma-api.polymarket.com/markets", params=params, timeout=10)
    data = r.json() if r.ok else []
    if not isinstance(data, list):
        data = data.get("markets", [])
    yield from data

def fetch_markets():
    # Use Gamma API — it supports active/closed filters and returns current markets
    # Tags: standard categories + bitcoin for BTC price prediction markets
    tags = ["politics", "crypto", "economics", "science", "climate", "bitcoin"]
    seen = set()
    markets = []
    now = datetime.now(timezone.utc)

    # Build source list: tag-based scans + dedicated Bitcoin price keyword search
    sources = [(tag, None) for tag in tags] + [(None, "bitcoin price")]

    for tag, keyword in sources:
        for m in _iter_raw_markets(tag=tag, keyword=keyword):
            cid = m.get("conditionId")
            q_lower = m.get("question", "").lower()
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
            # Skip gaming/entertainment noise (GTA VI benchmark questions etc.)
            if any(kw in q_lower for kw in GAMING_BLACKLIST):
                continue
            seen.add(cid)
            # normalize to the field names run() expects
            price_raw = m.get("lastTradePrice") or m.get("bestAsk") or 0.5
            best_bid = float(m.get("bestBid") or price_raw)
            best_ask = float(m.get("bestAsk") or price_raw)
            spread = round(best_ask - best_bid, 4)
            volume = float(m.get("volumeClob") or m.get("volume") or 0)
            # days until close (0 if unknown)
            days_left = 0
            if end_raw:
                try:
                    end_dt = datetime.fromisoformat(end_raw.replace("Z", "+00:00"))
                    if end_dt.tzinfo is None:
                        end_dt = end_dt.replace(tzinfo=timezone.utc)
                    days_left = max(0, (end_dt - now).days)
                except ValueError:
                    pass
            markets.append({
                "condition_id": cid,
                "question": m.get("question", ""),
                "tokens": [{"price": float(price_raw)}],
                "_end_date": end_raw[:10],
                "_days_left": days_left,
                "_spread": spread,
                "_volume": volume,
            })
    print(f"Fetched {len(markets)} relevant markets (future/active only)")
    return markets

def calibration_summary():
    """
    Compute directional accuracy from resolved bets to ground the analyst.
    Returns a single-line calibration note passed as context to the analyst agent.
    """
    resolved = sb.table("bets").select("*").eq("resolved", True).execute().data
    if not resolved:
        return "No resolved bets yet — treat all confidence levels as provisional."
    correct = sum(1 for b in resolved
                  if (b["predicted_prob"] >= 0.5 and b["outcome"] == 1.0) or
                     (b["predicted_prob"] < 0.5 and b["outcome"] == 0.0))
    total = len(resolved)
    avg_brier = sum((b["predicted_prob"] - b["outcome"]) ** 2 for b in resolved) / total
    return (f"Your past {total} resolved bets: {correct}/{total} directionally correct "
            f"({100*correct//total}%), avg Brier={avg_brier:.4f}. "
            f"Recalibrate if overconfident (high confidence but wrong) or underconfident (hedging clear signals).")

def _resolve_outcome_from_clob(market_id):
    """
    Returns (closed: bool, outcome: float|None) from CLOB API.
    outcome is 1.0 if YES wins, 0.0 if NO wins, None if not yet resolved.
    """
    resp = requests.get(f"https://clob.polymarket.com/markets/{market_id}", timeout=10)
    if not resp.ok:
        return False, None
    r = resp.json()
    if not r.get("closed"):
        return False, None
    tokens = r.get("tokens", [])
    winner = next((t for t in tokens if t.get("winner")), None)
    if winner is None:
        return True, None  # closed but winner not yet set
    return True, 1.0 if winner.get("outcome", "").lower() == "yes" else 0.0


def _resolve_outcome_from_gamma(market_id):
    """
    Fallback resolver via Gamma API (handles markets pruned from CLOB).
    Returns (closed: bool, outcome: float|None).
    """
    resp = requests.get("https://gamma-api.polymarket.com/markets",
                        params={"conditionId": market_id, "limit": 1}, timeout=10)
    if not resp.ok:
        return False, None
    data = resp.json()
    if not isinstance(data, list):
        data = data.get("markets", [])
    for gm in data:
        if gm.get("conditionId") != market_id:
            continue
        if not gm.get("closed"):
            return False, None
        prices_raw = gm.get("outcomePrices", "[]")
        try:
            prices = json.loads(prices_raw) if isinstance(prices_raw, str) else prices_raw
            yes_price = float(prices[0]) if prices else None
            if yes_price in (0.0, 1.0):
                return True, yes_price
        except Exception:
            pass
        return True, None  # closed but prices ambiguous
    return False, None


def eval_resolved():
    unresolved = sb.table("bets").select("*").eq("resolved", False).execute().data
    for bet in unresolved:
        mid = bet["market_id"]
        closed, outcome = _resolve_outcome_from_clob(mid)
        if not closed:
            # CLOB couldn't confirm — try Gamma fallback (handles pruned markets)
            closed, outcome = _resolve_outcome_from_gamma(mid)
        if closed and outcome is not None:
            sb.table("bets").update({
                "resolved": True,
                "outcome": outcome,
                "resolved_at": datetime.now(timezone.utc).isoformat()
            }).eq("id", bet["id"]).execute()
            print(f"Resolved: {bet['question'][:50]} → {outcome}")
        elif closed:
            print(f"  Market closed but outcome unclear, skipping: {mid[:20]}...")

def run():
    print("=== polymarket-loop run ===")
    eval_resolved()
    markets = fetch_markets()

    # Load calibration feedback once — passed to every analyst call
    cal_note = calibration_summary()

    # Load existing open bets to skip duplicate markets
    open_market_ids = {b["market_id"] for b in sb.table("bets").select("market_id").eq("resolved", False).execute().data}

    for m in markets[:15]:
        q = m.get("question", "")
        cid = m.get("condition_id", "")
        price = float(m.get("tokens", [{}])[0].get("price", 0.5))
        days_left = m.get("_days_left", 0)
        spread = m.get("_spread", 0.0)
        volume = m.get("_volume", 0.0)

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

        # Build enriched market context with all innovation signals
        market_context = (
            f"Market: {q}\n"
            f"Market price (YES): {price}\n"
            f"Days until close: {days_left}\n"
            f"Bid-ask spread: {spread} (wide=uncertain crowd, tight=confident crowd)\n"
            f"Volume traded: ${volume:,.0f} (high=liquid, low=thin)\n"
            f"Macro: {macro}\n"
            f"Domain: {domain_summary}\n"
            f"Calibration note: {cal_note}"
        )

        raw = ask(analyst_prompt, market_context)

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
