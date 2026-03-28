from dotenv import load_dotenv
load_dotenv()
import hashlib, os, json, time, requests, sys
from groq import Groq, RateLimitError
from supabase import create_client
from datetime import datetime, timezone

sb = create_client(os.environ["SUPABASE_URL"], os.environ["SUPABASE_KEY"])
groq = Groq(api_key=os.environ["GROQ_API_KEY"])
MODEL = "moonshotai/kimi-k2-instruct-0905"

# Minimum edge (|predicted - market_price|) to place a paper bet
MIN_EDGE = 0.03

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

# Keywords that identify crypto/bitcoin-related events and markets
# These are matched against event TITLE + market QUESTION text (not descriptions)
CRYPTO_KEYWORDS = [
    # Core crypto
    "bitcoin", "btc", "$btc", "ethereum", "$eth", "solana", "$sol",
    # Crypto ecosystem
    "defi", "blockchain", "stablecoin", "halving",
    "coinbase", "binance", "kraken", "opensea", "metamask",
    "airdrop", "fdv", "microstr",  # MicroStrategy
    "nft", "web3", "dao",
    # Compound phrases (more precise than single words)
    "launch a token", "crypto hack", "crypto price", "crypto tax",
    "bitcoin reserve", "ethereum reserve", "digital asset",
    "mining",
]

# These words in event title immediately qualify as crypto
CRYPTO_TITLE_KEYWORDS = [
    "bitcoin", "btc", "ethereum", "eth", "solana", "crypto",
    "fdv", "airdrop", "token", "blockchain", "defi",
    "coinbase", "kraken", "binance", "opensea", "metamask",
    "microstrategy", "megaeth",
]

def _fetch_all_active_events():
    """Fetch all active events from the Gamma /events endpoint (paginated)."""
    all_events = []
    offset = 0
    while offset < 2000:
        try:
            r = requests.get("https://gamma-api.polymarket.com/events", params={
                "active": "true", "closed": "false", "limit": 100, "offset": offset,
            }, timeout=15)
            if not r.ok:
                break
            chunk = r.json()
            if isinstance(chunk, dict) and "error" in chunk:
                break
            if not chunk or (isinstance(chunk, list) and len(chunk) == 0):
                break
            if isinstance(chunk, list):
                all_events.extend(chunk)
            elif isinstance(chunk, dict) and "data" in chunk:
                all_events.extend(chunk["data"])
            offset += 100
        except Exception as e:
            print(f"  Event fetch error at offset {offset}: {e}")
            break
    return all_events

def _is_crypto_event(event):
    """Check if an event is crypto/bitcoin related. 
    Matches on event TITLE and market QUESTIONS only — not descriptions (too noisy)."""
    title = str(event.get("title", "")).lower()
    
    # Fast path: if title has a crypto keyword, it's crypto
    if any(kw in title for kw in CRYPTO_TITLE_KEYWORDS):
        return True
    
    # Slower path: check market questions only
    markets = event.get("markets", [])
    if isinstance(markets, list):
        for m in markets:
            if isinstance(m, dict):
                question = str(m.get("question", "")).lower()
                if any(kw in question for kw in CRYPTO_KEYWORDS):
                    return True
    return False

def fetch_markets():
    """Fetch active crypto/bitcoin markets from Polymarket using the /events endpoint."""
    now = datetime.now(timezone.utc)
    
    # Step 1: Fetch all active events
    all_events = _fetch_all_active_events()
    print(f"Fetched {len(all_events)} total active events from Polymarket")
    
    # Step 2: Filter for crypto/bitcoin events
    crypto_events = [e for e in all_events if isinstance(e, dict) and _is_crypto_event(e)]
    print(f"Filtered to {len(crypto_events)} crypto/bitcoin events")
    
    # Step 3: Extract individual markets from matching events
    seen = set()
    markets = []
    
    for event in crypto_events:
        event_markets = event.get("markets", [])
        if not isinstance(event_markets, list):
            continue
        for m in event_markets:
            if not isinstance(m, dict):
                continue
            cid = m.get("conditionId") or m.get("condition_id")
            if not cid or cid in seen:
                continue
            
            # Skip closed/inactive markets
            if m.get("closed") or not m.get("active", True):
                continue
            
            # Skip gaming/entertainment noise
            q_lower = (m.get("question", "") or "").lower()
            if any(kw in q_lower for kw in GAMING_BLACKLIST):
                continue
            
            # Skip past-end-date markets
            end_raw = m.get("endDateIso") or m.get("endDate") or m.get("end_date_iso") or ""
            if end_raw:
                try:
                    end_dt = datetime.fromisoformat(str(end_raw).replace("Z", "+00:00"))
                    if end_dt.tzinfo is None:
                        end_dt = end_dt.replace(tzinfo=timezone.utc)
                    if end_dt < now:
                        continue
                except (ValueError, TypeError):
                    pass
            
            seen.add(cid)
            
            # Normalize fields
            price_raw = m.get("lastTradePrice") or m.get("bestAsk") or m.get("outcomePrices")
            if isinstance(price_raw, str) and price_raw.startswith("["):
                try:
                    prices = json.loads(price_raw)
                    price_raw = prices[0] if prices else 0.5
                except Exception:
                    price_raw = 0.5
            price_raw = float(price_raw or 0.5)
            
            best_bid = float(m.get("bestBid") or price_raw)
            best_ask = float(m.get("bestAsk") or price_raw)
            spread = round(best_ask - best_bid, 4)
            volume = float(m.get("volumeClob") or m.get("volume") or 0)
            
            # Days until close
            days_left = 0
            if end_raw:
                try:
                    end_dt = datetime.fromisoformat(str(end_raw).replace("Z", "+00:00"))
                    if end_dt.tzinfo is None:
                        end_dt = end_dt.replace(tzinfo=timezone.utc)
                    days_left = max(0, (end_dt - now).days)
                except (ValueError, TypeError):
                    pass
            
            # Extract YES token ID
            clob_token_ids_raw = m.get("clobTokenIds", "[]")
            try:
                clob_token_ids = json.loads(clob_token_ids_raw) if isinstance(clob_token_ids_raw, str) else clob_token_ids_raw
                yes_token_id = clob_token_ids[0] if clob_token_ids else None
            except Exception:
                yes_token_id = None
            
            markets.append({
                "condition_id": cid,
                "question": m.get("question", ""),
                "tokens": [{"price": price_raw}],
                "_end_date": str(end_raw)[:10],
                "_days_left": days_left,
                "_spread": spread,
                "_volume": volume,
                "_yes_token_id": yes_token_id,
                "_event_title": event.get("title", ""),
            })
    
    # Sort by volume (highest first) so we analyze the most liquid markets first
    markets.sort(key=lambda m: m["_volume"], reverse=True)
    print(f"Found {len(markets)} tradeable crypto/bitcoin markets")
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
    if DRY_RUN:
        print("[DRY RUN MODE — no data will be written to Supabase]")
    
    run_stats = {
        "started_at": datetime.now(timezone.utc).isoformat(),
        "finished_at": None,
        "markets_fetched": 0,
        "markets_analyzed": 0,
        "bets_placed": 0,
        "markets_skipped_filter": 0,
        "markets_skipped_duplicate": 0,
        "errors": [],
    }

    eval_resolved()
    markets = fetch_markets()
    run_stats["markets_fetched"] = len(markets)

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
            run_stats["markets_skipped_duplicate"] += 1
            continue

        run_stats["markets_analyzed"] += 1
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
            run_stats["markets_skipped_filter"] += 1
            continue

        # Pass clean JSON summary to analyst, not raw LLM output
        domain_summary = json.dumps(domain_result)
        time.sleep(2)  # pace before analyst call

        # Build a structured payload to save to DB so we can evaluate it natively later
        context_json = {
            "spread": spread,
            "volume": volume,
            "days_left": days_left,
            "momentum": momentum,
            "depth": depth,
            "macro": macro,
            "domain_summary": domain_summary,
            "calibration_note": cal_note
        }

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

        market_context_prompt = (
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

        raw = ask(analyst_prompt, market_context_prompt)

        try:
            start = raw.find("{")
            end = raw.rfind("}") + 1
            result = json.loads(raw[start:end])
            final_prob = result.get("final_prob")
            if final_prob is None:
                print(f"  No final_prob in analyst output, skipping")
                run_stats["errors"].append(f"No final_prob: {q[:40]}")
                continue
            edge = abs(final_prob - price)
            direction = "YES" if final_prob > price else "NO"
            print(f"  Analyst: P={final_prob:.3f} vs Market={price:.3f} | edge={edge:.3f} | lean={direction}")
            print(f"  Reasoning: {result.get('reasoning', 'n/a')[:100]}")

            if edge >= MIN_EDGE:
                if DRY_RUN:
                    print(f"  [DRY RUN] Would place paper bet (edge={edge:.3f})")
                    run_stats["bets_placed"] += 1
                else:
                    sb.table("bets").insert({
                        "market_id": cid,
                        "question": q,
                        "predicted_prob": final_prob,
                        "market_price": price,
                        "resolved": False,
                        "created_at": datetime.now(timezone.utc).isoformat(),
                        "eval_split": "production",
                        "prompt_hash": _prompt_hash(),
                        "market_context": context_json,
                    }).execute()
                    run_stats["bets_placed"] += 1
                    print(f"  >>> PAPER BET PLACED | edge={edge:.3f} <<<")
            else:
                print(f"  Edge too small ({edge:.3f} < {MIN_EDGE}), skipping bet")
        except Exception as e:
            print(f"  Parse error: {e}")
            run_stats["errors"].append(str(e))

    # ── Run summary ─────────────────────────────────────────────────────
    run_stats["finished_at"] = datetime.now(timezone.utc).isoformat()
    print("\n" + "=" * 60)
    print(f"RUN COMPLETE")
    print(f"  Markets fetched:  {run_stats['markets_fetched']}")
    print(f"  Markets analyzed: {run_stats['markets_analyzed']}")
    print(f"  Bets placed:      {run_stats['bets_placed']}")
    print(f"  Skipped (filter): {run_stats['markets_skipped_filter']}")
    print(f"  Skipped (dup):    {run_stats['markets_skipped_duplicate']}")
    if run_stats["errors"]:
        print(f"  Errors:           {len(run_stats['errors'])}")
        for err in run_stats["errors"][:5]:
            print(f"    - {err[:80]}")
    print("=" * 60)

    # Log run to Supabase (if run_logs table exists)
    if not DRY_RUN:
        try:
            sb.table("run_logs").insert({
                "started_at": run_stats["started_at"],
                "finished_at": run_stats["finished_at"],
                "markets_fetched": run_stats["markets_fetched"],
                "markets_analyzed": run_stats["markets_analyzed"],
                "bets_placed": run_stats["bets_placed"],
                "markets_skipped_filter": run_stats["markets_skipped_filter"],
                "markets_skipped_duplicate": run_stats["markets_skipped_duplicate"],
                "errors": run_stats["errors"][:10],
                "prompt_hash": _prompt_hash(),
            }).execute()
        except Exception:
            pass  # run_logs table might not exist yet


def show_status():
    """Quick status check — shows DB state without running any agents."""
    print("=== polymarket-loop status ===")
    all_bets = sb.table("bets").select("*").execute().data
    resolved = [b for b in all_bets if b.get("resolved")]
    unresolved = [b for b in all_bets if not b.get("resolved")]
    real_bets = [b for b in all_bets if b.get("prompt_hash") != "seed"]
    seed_bets = [b for b in all_bets if b.get("prompt_hash") == "seed"]

    print(f"\nTotal bets:    {len(all_bets)}")
    print(f"  Real bets:   {len(real_bets)}")
    print(f"  Seed bets:   {len(seed_bets)}")
    print(f"  Resolved:    {len(resolved)}")
    print(f"  Open:        {len(unresolved)}")

    if resolved:
        brier = sum((b["predicted_prob"] - b["outcome"]) ** 2 for b in resolved) / len(resolved)
        correct = sum(1 for b in resolved
                      if (b["predicted_prob"] >= 0.5 and b["outcome"] == 1.0) or
                         (b["predicted_prob"] < 0.5 and b["outcome"] == 0.0))
        print(f"\nBrier score:   {brier:.4f}")
        print(f"Accuracy:      {correct}/{len(resolved)} ({100*correct//len(resolved)}%)")
        real_resolved = [b for b in resolved if b.get("prompt_hash") != "seed"]
        if real_resolved:
            real_brier = sum((b["predicted_prob"] - b["outcome"]) ** 2 for b in real_resolved) / len(real_resolved)
            print(f"\nReal-only Brier: {real_brier:.4f} (n={len(real_resolved)})")
        else:
            print(f"\nReal-only Brier: no resolved real bets yet")
    else:
        print(f"\nBrier score:   not enough data")

    # Recent bets
    recent = sorted(all_bets, key=lambda b: b.get("created_at", ""), reverse=True)[:5]
    if recent:
        print(f"\nLast 5 bets:")
        for b in recent:
            status = "RESOLVED" if b.get("resolved") else "OPEN"
            ph = b.get("prompt_hash", "?")[:8]
            print(f"  [{status}] {b['question'][:50]} | P={b['predicted_prob']:.2f} | hash={ph}")

    # Run logs
    try:
        logs = sb.table("run_logs").select("*").order("started_at", desc=True).limit(3).execute().data
        if logs:
            print(f"\nLast 3 runs:")
            for log in logs:
                t = log.get("started_at", "?")[:19]
                print(f"  {t} | fetched={log.get('markets_fetched',0)} analyzed={log.get('markets_analyzed',0)} bets={log.get('bets_placed',0)}")
    except Exception:
        pass  # run_logs table might not exist


DRY_RUN = "--dry-run" in sys.argv

if __name__ == "__main__":
    if "--status" in sys.argv:
        show_status()
    else:
        run()
