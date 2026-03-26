from dotenv import load_dotenv
load_dotenv()
import os
import sys
from supabase import create_client

url = os.environ["SUPABASE_URL"]
key = os.environ["SUPABASE_KEY"]
sb = create_client(url, key)

# ── default mode ──────────────────────────────────────────────────────────────
# Prints "brier_score: 0.0333" — this exact format is read by the autoresearch
# loop in setup.md and must never change. Do NOT modify this output.

if "--rich" not in sys.argv and "--check-mutation" not in sys.argv:
    bets = (
        sb.table("bets")
        .select("*")
        .eq("resolved", True)
        .order("resolved_at", desc=True)
        .limit(15)
        .execute()
        .data
    )
    if len(bets) < 3:
        print("brier_score: not_enough_data")
    else:
        score = sum((b["predicted_prob"] - b["outcome"]) ** 2 for b in bets) / len(bets)
        print(f"brier_score: {score:.4f}")

# ── rich mode ─────────────────────────────────────────────────────────────────
# Human-facing: full harness metrics. Passes all args down to harness.py.
# Usage:
#   python eval.py --rich [--split backtest|shadow|production|all] [--json]
#   python eval.py --check-mutation   (backtest + mutation gate + save version)

else:
    import subprocess
    import pathlib

    harness = pathlib.Path(__file__).parent / "eval" / "harness.py"
    # Strip --rich from the forwarded args; keep everything else
    forward = [a for a in sys.argv[1:] if a != "--rich"]
    result = subprocess.run([sys.executable, str(harness)] + forward, check=False)
    sys.exit(result.returncode)
