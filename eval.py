from dotenv import load_dotenv
load_dotenv()
import os
from supabase import create_client

url = os.environ["SUPABASE_URL"]
key = os.environ["SUPABASE_KEY"]
sb = create_client(url, key)

bets = sb.table("bets").select("*").eq("resolved", True).order("resolved_at", desc=True).limit(15).execute().data

if len(bets) < 3:
    print("brier_score: not_enough_data")
else:
    score = sum((b["predicted_prob"] - b["outcome"])**2 for b in bets) / len(bets)
    print(f"brier_score: {score:.4f}")
