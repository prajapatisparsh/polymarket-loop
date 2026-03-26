"""
Polymarket eval harness — v1

Three dataset splits:
  backtest   — frozen historical dataset (eval/backtest.json), used to gate prompt mutations
  shadow     — live bets tagged eval_split='shadow' in bets table, scored after resolution
  production — all production paper bets (default)

Usage:
  python eval/harness.py                          # score all resolved bets (production)
  python eval/harness.py --split backtest         # run LLM on frozen dataset + score
  python eval/harness.py --split shadow           # score resolved shadow bets
  python eval/harness.py --split all              # all three splits
  python eval/harness.py --check-mutation         # backtest + run mutation gate
  python eval/harness.py --json                   # emit raw JSON instead of table
"""

import argparse
import hashlib
import json
import os
import time
from datetime import datetime, timezone

from dotenv import load_dotenv

load_dotenv()

from groq import Groq, RateLimitError
from supabase import create_client

# ── config ────────────────────────────────────────────────────────────────────

sb = create_client(os.environ["SUPABASE_URL"], os.environ["SUPABASE_KEY"])
groq_client = Groq(api_key=os.environ["GROQ_API_KEY"])
MODEL = "moonshotai/kimi-k2-instruct-0905"

BACKTEST_PATH = os.path.join(os.path.dirname(__file__), "backtest.json")

# Below this sample count, refuse to make accept/reject calls.
MIN_SAMPLE_FOR_OPTIMIZATION = 10


# ── prompt utilities ───────────────────────────────────────────────────────────

def prompt_hash() -> str:
    """SHA256[:12] of all three prompt files concatenated. Stable ID for a prompt version."""
    content = ""
    for f in ["prompts/macro.md", "prompts/domains.md", "prompts/analyst.md"]:
        try:
            content += open(f, encoding="utf-8").read()
        except OSError:
            pass
    return hashlib.sha256(content.encode()).hexdigest()[:12]


def prompt_content() -> str:
    """Full text of all three prompt files, labelled."""
    out = ""
    for f in ["prompts/macro.md", "prompts/domains.md", "prompts/analyst.md"]:
        try:
            out += f"=== {f} ===\n" + open(f, encoding="utf-8").read() + "\n\n"
        except OSError:
            out += f"=== {f} === [NOT FOUND]\n\n"
    return out


# ── scoring functions ─────────────────────────────────────────────────────────

def brier_score(preds: list[float], outcomes: list[float]) -> float | None:
    if len(preds) < 3:
        return None
    return sum((p - o) ** 2 for p, o in zip(preds, outcomes)) / len(preds)


def expected_calibration_error(preds: list[float], outcomes: list[float], n_bins: int = 5) -> float | None:
    """
    ECE: partition predictions into equal-width bins, compare mean predicted
    probability to mean observed outcome in each bin. Weighted by bin size.
    Lower ECE = better calibrated.
    """
    if len(preds) < 3:
        return None
    bins: list[list[tuple[float, float]]] = [[] for _ in range(n_bins)]
    for p, o in zip(preds, outcomes):
        idx = min(int(p * n_bins), n_bins - 1)
        bins[idx].append((p, o))
    ece = 0.0
    for b in bins:
        if b:
            avg_p = sum(x[0] for x in b) / len(b)
            avg_o = sum(x[1] for x in b) / len(b)
            ece += len(b) * abs(avg_p - avg_o)
    return ece / len(preds)


def confidence_bands(bets: list[dict]) -> dict:
    """
    Group bets by confidence (max(p, 1-p)) and report accuracy per band.
    A bet is 'correct' if the predicted direction matches the outcome.
    """
    bands: dict[str, list[int]] = {
        "0.50-0.60": [],
        "0.60-0.70": [],
        "0.70-0.80": [],
        "0.80+":     [],
    }
    for b in bets:
        p = float(b["predicted_prob"])
        o = float(b["outcome"])
        conf = max(p, 1.0 - p)
        correct = int((p >= 0.5 and o == 1.0) or (p < 0.5 and o == 0.0))
        if conf >= 0.80:
            bands["0.80+"].append(correct)
        elif conf >= 0.70:
            bands["0.70-0.80"].append(correct)
        elif conf >= 0.60:
            bands["0.60-0.70"].append(correct)
        else:
            bands["0.50-0.60"].append(correct)
    return {
        k: {
            "n": len(v),
            "correct": sum(v),
            "accuracy": round(sum(v) / len(v), 3) if v else None,
        }
        for k, v in bands.items()
    }


def compute_metrics(bets: list[dict], current_hash: str | None = None) -> dict:
    """Build the full metrics dict from a list of resolved bet dicts."""
    preds = [float(b["predicted_prob"]) for b in bets]
    outcomes = [float(b["outcome"]) for b in bets]
    n = len(bets)
    bs = brier_score(preds, outcomes)
    ece = expected_calibration_error(preds, outcomes)
    bands = confidence_bands(bets)
    return {
        "n": n,
        "brier_score": round(bs, 4) if bs is not None else None,
        "ece": round(ece, 4) if ece is not None else None,
        "confidence_bands": bands,
        "statistically_weak": n < MIN_SAMPLE_FOR_OPTIMIZATION,
        "prompt_hash": current_hash,
    }


# ── live split scoring ─────────────────────────────────────────────────────────

def score_live_split(split: str) -> dict:
    """
    Fetch resolved bets for the given split (shadow or production) from Supabase
    and return computed metrics.

    Falls back to unfiltered resolved bets if eval_split column does not yet exist
    (i.e. schemas.sql has not been run). Labels result with a migration_needed flag.
    """
    try:
        bets = (
            sb.table("bets")
            .select("*")
            .eq("resolved", True)
            .eq("eval_split", split)
            .execute()
            .data
        )
        migration_needed = False
    except Exception:
        # eval_split column missing — fall back to all resolved bets
        bets = (
            sb.table("bets")
            .select("*")
            .eq("resolved", True)
            .order("resolved_at", desc=True)
            .limit(50)
            .execute()
            .data
        )
        migration_needed = True

    if not bets:
        return {"split": split, "error": "no_resolved_bets"}
    metrics = compute_metrics(bets)
    metrics["split"] = split
    if migration_needed:
        metrics["note"] = "eval_split column missing — run eval/schemas.sql in Supabase. Showing all resolved bets."
    return metrics


# ── backtest eval ──────────────────────────────────────────────────────────────

def _llm_predict(analyst_prompt: str, context: str) -> float | None:
    """
    Call the analyst prompt with the given context, parse final_prob.
    Returns None on failure (logged, not raised).
    """
    for attempt in range(4):
        try:
            raw = groq_client.chat.completions.create(
                model=MODEL,
                messages=[
                    {"role": "system", "content": analyst_prompt},
                    {"role": "user", "content": context},
                ],
            ).choices[0].message.content
            s, e = raw.find("{"), raw.rfind("}") + 1
            result = json.loads(raw[s:e])
            return float(result.get("final_prob", 0.5))
        except RateLimitError:
            if attempt == 3:
                return None
            time.sleep(2 ** attempt)
        except Exception:
            return None
    return None


def run_backtest() -> dict:
    """
    Run the current analyst prompt against every entry in backtest.json.
    Inserts results into eval_runs. Returns full metrics.
    """
    if not os.path.exists(BACKTEST_PATH):
        return {"split": "backtest", "error": f"backtest.json not found at {BACKTEST_PATH}"}

    dataset: list[dict] = json.load(open(BACKTEST_PATH, encoding="utf-8"))
    analyst_prompt = ""
    try:
        analyst_prompt = open("prompts/analyst.md", encoding="utf-8").read()
    except OSError:
        return {"split": "backtest", "error": "prompts/analyst.md not found"}

    current_hash = prompt_hash()
    run_at = datetime.now(timezone.utc).isoformat()

    bets_for_scoring: list[dict] = []
    rows_to_insert: list[dict] = []

    for entry in dataset:
        market_ctx = (
            f"Market: {entry['question']}\n"
            f"Market price (YES): {entry['market_price']}\n"
            f"Days until close: {entry.get('days_left', 0)}\n"
            f"Bid-ask spread: {entry.get('spread', 0.02)}\n"
            f"Volume traded: ${entry.get('volume', 100000):,.0f}\n"
            f"Macro: {entry.get('macro_context', '')}\n"
            f"Domain: {json.dumps(entry.get('domain', {}))}\n"
            f"Calibration note: Historical backtest entry — treat as a live market."
        )

        p = _llm_predict(analyst_prompt, market_ctx)
        if p is None:
            print(f"  [backtest] skipped (LLM error): {entry['question'][:50]}")
            continue

        o = float(entry["outcome"])
        bets_for_scoring.append({"predicted_prob": p, "outcome": o})
        rows_to_insert.append(
            {
                "market_id": entry["id"],
                "question": entry["question"],
                "predicted_prob": p,
                "outcome": o,
                "prompt_hash": current_hash,
                "eval_split": "backtest",
                "run_at": run_at,
            }
        )
        time.sleep(1)  # gentle rate-limit pacing

    if rows_to_insert:
        try:
            sb.table("eval_runs").insert(rows_to_insert).execute()
        except Exception:
            pass  # table not yet created — run eval/schemas.sql in Supabase to persist results

    if not bets_for_scoring:
        return {"split": "backtest", "error": "all backtest entries failed — check LLM connectivity"}

    metrics = compute_metrics(bets_for_scoring, current_hash)
    metrics["split"] = "backtest"
    return metrics


# ── prompt version management ─────────────────────────────────────────────────

def save_prompt_version(metrics: dict) -> None:
    """Persist current prompt snapshot + metrics to prompt_versions table."""
    h = metrics.get("prompt_hash") or prompt_hash()
    try:
        # Upsert-style: if hash already exists, skip
        existing = sb.table("prompt_versions").select("id").eq("hash", h).execute().data
        if existing:
            return
        sb.table("prompt_versions").insert(
            {
                "hash": h,
                "prompt_content": prompt_content(),
                "metrics": json.dumps(metrics),
                "created_at": datetime.now(timezone.utc).isoformat(),
            }
        ).execute()
    except Exception:
        pass  # table not yet created — run eval/schemas.sql in Supabase


def get_previous_metrics() -> dict | None:
    """Return the metrics of the second-most-recent prompt version."""
    try:
        rows = (
            sb.table("prompt_versions")
            .select("metrics")
            .order("created_at", desc=True)
            .limit(2)
            .execute()
            .data
        )
    except Exception:
        return None  # table not yet created
    if len(rows) < 2:
        return None
    raw = rows[1].get("metrics")
    if not raw:
        return None
    return json.loads(raw) if isinstance(raw, str) else raw


# ── mutation gate ──────────────────────────────────────────────────────────────

def mutation_gate(new_metrics: dict, prev_metrics: dict | None) -> dict:
    """
    Evaluate whether a prompt mutation should be accepted.

    Rules:
      - If sample is too small → reject with statistically_weak label.
      - If no previous baseline → accept unconditionally.
      - Accept only if backtest Brier improves (lower).
      - Reject with reason if Brier is equal or worse.

    Returns: {"accept": bool, "reason": str, "delta": float | None}
    """
    n = new_metrics.get("n", 0)
    if new_metrics.get("statistically_weak"):
        return {
            "accept": False,
            "reason": f"Statistically weak — only {n} samples (minimum {MIN_SAMPLE_FOR_OPTIMIZATION} required). Cannot evaluate mutation.",
            "delta": None,
        }

    new_bs = new_metrics.get("brier_score")
    if new_bs is None:
        return {"accept": False, "reason": "New Brier score is missing — cannot compare.", "delta": None}

    if prev_metrics is None:
        return {
            "accept": True,
            "reason": "No prior version to compare against — accepting as baseline.",
            "delta": None,
        }

    prev_bs = prev_metrics.get("brier_score")
    if prev_bs is None:
        return {"accept": True, "reason": "Prior version has no Brier score — accepting as new baseline.", "delta": None}

    delta = new_bs - prev_bs  # negative = improvement
    if delta < 0:
        return {
            "accept": True,
            "reason": f"Brier improved by {abs(delta):.4f}  ({prev_bs:.4f} → {new_bs:.4f})",
            "delta": round(delta, 4),
        }
    elif delta == 0.0:
        return {
            "accept": False,
            "reason": f"No improvement (Brier unchanged at {new_bs:.4f}). Recommend keeping current version.",
            "delta": 0.0,
        }
    else:
        return {
            "accept": False,
            "reason": f"Brier degraded by {delta:.4f}  ({prev_bs:.4f} → {new_bs:.4f}). Recommend git revert.",
            "delta": round(delta, 4),
        }


# ── output ─────────────────────────────────────────────────────────────────────

def print_summary(results: list[dict]) -> None:
    width = 60
    print("\n" + "=" * width)
    print("POLYMARKET EVAL HARNESS SUMMARY")
    print("=" * width)
    for r in results:
        if "error" in r:
            print(f"\n[{r['split'].upper()}]  ERROR: {r['error']}")
            continue
        weak_tag = "  [STATISTICALLY WEAK]" if r.get("statistically_weak") else ""
        print(f"\n[{r['split'].upper()}]  n={r['n']}{weak_tag}")
        bs = r.get("brier_score")
        ece = r.get("ece")
        print(f"  Brier score : {bs if bs is not None else 'N/A'}")
        print(f"  ECE         : {ece if ece is not None else 'N/A'}")
        if r.get("prompt_hash"):
            print(f"  Prompt hash : {r['prompt_hash']}")
        bands = r.get("confidence_bands", {})
        if any(v["n"] > 0 for v in bands.values()):
            print("  Confidence bands:")
            for band, stats in bands.items():
                if stats["n"] > 0:
                    acc = f"{stats['accuracy']:.0%}" if stats["accuracy"] is not None else "N/A"
                    print(f"    {band}: n={stats['n']}, accuracy={acc}")
        gate = r.get("mutation_gate")
        if gate:
            verdict = "[ACCEPT]" if gate["accept"] else "[REJECT]"
            print(f"\n  Mutation gate: {verdict}")
            print(f"    {gate['reason']}")
    print()


# ── CLI ────────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(description="Polymarket eval harness")
    parser.add_argument(
        "--split",
        choices=["backtest", "shadow", "production", "all"],
        default="production",
        help="Which dataset split to evaluate (default: production)",
    )
    parser.add_argument(
        "--check-mutation",
        action="store_true",
        help="Run backtest, evaluate mutation gate, save prompt version",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Print raw JSON instead of formatted summary",
    )
    args = parser.parse_args()

    results: list[dict] = []
    run_backtest_flag = args.check_mutation or args.split in ("backtest", "all")

    if run_backtest_flag:
        print("Running backtest eval (calls LLM on 20 frozen historical markets)...")
        r = run_backtest()
        if args.check_mutation and "error" not in r:
            prev = get_previous_metrics()
            gate = mutation_gate(r, prev)
            r["mutation_gate"] = gate
            save_prompt_version(r)
        results.append(r)

    if args.split in ("shadow", "all"):
        results.append(score_live_split("shadow"))

    if args.split in ("production", "all"):
        results.append(score_live_split("production"))

    if args.json:
        print(json.dumps(results, indent=2))
    else:
        print_summary(results)


if __name__ == "__main__":
    main()
