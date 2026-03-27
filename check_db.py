import os, json
from supabase import create_client
from dotenv import load_dotenv

load_dotenv()
sb = create_client(os.environ['SUPABASE_URL'], os.environ['SUPABASE_KEY'])

# Fetch some stats about the bets table
all_bets = sb.table('bets').select('*').execute().data
resolved_bets = [b for b in all_bets if b.get('resolved')]
unresolved_bets = [b for b in all_bets if not b.get('resolved')]

with open('db_stats.txt', 'w') as f:
    f.write(f"Total bets: {len(all_bets)}\n")
    f.write(f"Resolved bets: {len(resolved_bets)}\n")
    f.write(f"Unresolved bets: {len(unresolved_bets)}\n")
    f.write(f"Resolved with context: {len(has_context)}\n")
    f.write(f"Resolved WITHOUT context: {len(missing_context)}\n")
    f.write("Resolved bets by split: " + str(splits) + "\n")
