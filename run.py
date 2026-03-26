from dotenv import load_dotenv
load_dotenv()
import hashlib, os, json, time, requests
from groq import Groq, RateLimitError
from supabase import create_client
from datetime import datetime, timezone

sb = create_client(os.environ["SUPABASE_URL"], os.environ["SUPABASE_KEY"])
groq = Groq(api_key=os.environ["GROQ_API_KEY"])
MODEL = "moonshotai/kimi-k2-instruct-0905"

macro_prompt = open("prompts/macro.md").read()
domains_prompt = open("prompts/domains.md").read()
analyst_prompt = open("prompts/analyst.md").read()


def _prompt_hash() -> str:
    """SHA256[:12] of current prompt files — used to tag bets with their generating prompt version."""
    content = macro_prompt + domains_prompt + analyst_prompt
    return hashlib.sha256(content.encode()).hexdigest()[:12]



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
            # Extract YES token ID from clobTokenIds — needed for CLOB /book and /prices-history
            clob_token_ids_raw = m.get("clobTokenIds", "[]")
            try:
                clob_token_ids = json.loads(clob_token_ids_raw) if isinstance(clob_token_ids_raw, str) else clob_token_ids_raw
                yes_token_id = clob_token_ids[0] if clob_token_ids else None
            except Exception:
                yes_token_id = None
            markets.append({
                "condition_id": cid,
                "question": m.get("question", ""),
                "tokens": [{"price": float(price_raw)}],
                "_end_date": end_raw[:10],
                "_days_left": days_left,
                "_spread": spread,
                "_volume": volume,
                "_yes_token_id": yes_token_id,
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


def fetch_price_momentum(yes_token_id: str) -> dict:
    """
    Calls CLOB /prices-history for the last 24h and 1-week on the YES token.
    Returns dict with 24h_change, 1w_change, momentum_label, and recent_prices.
    Falls back to empty dict on any error.

    API: GET https://clob.polymarket.com/prices-history?market={token_id}&interval=1d&fidelity=60
    """
    if not yes_token_id:
        return {}
    try:
        # 24-hour price history (60-minute fidelity)
        r24 = requests.get("https://clob.polymarket.com/prices-history",
            params={"market": yes_token_id, "interval": "1d", "fidelity": 60},
            timeout=8)
        history_24h = r24.json().get("history", []) if r24.ok else []

        # 1-week price history (6-hour fidelity)
        r1w = requests.get("https://clob.polymarket.com/prices-history",
            params={"market": yes_token_id, "interval": "1w", "fidelity": 360},
            timeout=8)
        history_1w = r1w.json().get("history", []) if r1w.ok else []

        def pct_change(hist):
            if len(hist) < 2:
                return None
            p_old = float(hist[0]["p"])
            p_new = float(hist[-1]["p"])
            if p_old == 0:
                return None
            return round((p_new - p_old) / p_old * 100, 1)

        ch24 = pct_change(history_24h)
        ch1w = pct_change(history_1w)

        # Summarize recent 6 price points (last 6h) if available
        recent = [round(float(h["p"]), 3) for h in history_24h[-6:]]

        # Momentum label: strong_up / mild_up / flat / mild_down / strong_down
        if ch24 is None:
            label = "unknown"
        elif ch24 > 10:
            label = "strong_up"
        elif ch24 > 3:
            label = "mild_up"
        elif ch24 < -10:
            label = "strong_down"
        elif ch24 < -3:
            label = "mild_down"
        else:
            label = "flat"

        return {
            "24h_change_pct": ch24,
            "1w_change_pct": ch1w,
            "momentum": label,
            "recent_prices": recent,
        }
    except Exception:
        return {}


def fetch_orderbook_depth(yes_token_id: str) -> dict:
    """
    Calls CLOB /book for the YES token.
    Returns top-3 bid/ask prices and a book_imbalance ratio
    (>1 = more buying pressure, <1 = more selling pressure).

    API: GET https://clob.polymarket.com/book?token_id={yes_token_id}
    """
    if not yes_token_id:
        return {}
    try:
        r = requests.get("https://clob.polymarket.com/book",
            params={"token_id": yes_token_id}, timeout=8)
        if not r.ok:
            return {}
        book = r.json()
        bids = book.get("bids", [])[:3]   # [{price, size}, ...]
        asks = book.get("asks", [])[:3]
        bid_vol = sum(float(b.get("size", 0)) for b in bids)
        ask_vol = sum(float(a.get("size", 0)) for a in asks)
        imbalance = round(bid_vol / ask_vol, 2) if ask_vol > 0 else None
        return {
            "top_bids": [{"p": b.get("price"), "sz": b.get("size")} for b in bids],
            "top_asks": [{"p": a.get("price"), "sz": a.get("size")} for a in asks],
            "book_imbalance": imbalance,  # >1 buy pressure, <1 sell pressure
        }
    except Exception:
        return {}

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
        yes_token_id = m.get("_yes_token_id")

        if cid in open_market_ids:
            print(f"  Skipping duplicate open bet: {q[:50]}")
            continue

        print(f"\nAnalyzing: {q[:60]}")

        # Fetch CLOB signals before calling LLMs (no extra Groq rate-limit cost)
        momentum = fetch_price_momentum(yes_token_id)
        depth = fetch_orderbook_depth(yes_token_id)

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
        momentum_str = ""
        if momentum:
            momentum_str = (
                f"\nPrice momentum (24h): {momentum.get('24h_change_pct', 'n/a')}% "
                f"[{momentum.get('momentum', 'unknown')}]"
                f" | 1-week change: {momentum.get('1w_change_pct', 'n/a')}%"
                f"\nRecent price path: {momentum.get('recent_prices', [])}"
            )
        depth_str = ""
        if depth:
            depth_str = (
                f"\nOrder book imbalance: {depth.get('book_imbalance', 'n/a')} "
                f"(>1=buy pressure, <1=sell pressure)"
                f"\nTop bids: {depth.get('top_bids', [])} | Top asks: {depth.get('top_asks', [])}"
            )

        market_context = (
            f"Market: {q}\n"
            f"Market price (YES): {price}\n"
            f"Days until close: {days_left}\n"
            f"Bid-ask spread: {spread} (wide=uncertain crowd, tight=confident crowd)\n"
            f"Volume traded: ${volume:,.0f} (high=liquid, low=thin)"
            f"{momentum_str}"
            f"{depth_str}\n"
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
                    "created_at": datetime.now(timezone.utc).isoformat(),
                    "eval_split": "production",
                    "prompt_hash": _prompt_hash(),
                }).execute()
                edge_val = result.get("edge") or 0
                print(f"✓ Paper bet logged | edge: {edge_val:.3f}")
            else:
                print(f"No edge found")
        except Exception as e:
            print(f"Parse error: {e}")

if __name__ == "__main__":
    run()
