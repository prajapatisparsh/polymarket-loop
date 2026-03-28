# Autonomous Improvement Loop

> Autonomous prediction market agent that bets on crypto/bitcoin markets on Polymarket by researching events and calibrating probabilities

## Architecture

```
Polymarket Gamma API (/events)
    ↓ fetch all active events, filter for crypto/bitcoin client-side
    ↓ 
run.py → [macro agent] → [domain filter] → [analyst agent]
    ↓                                            ↓
    ↓                                      edge ≥ 0.03?
    ↓                                            ↓ YES
    ↓                                    Supabase: bets table
    ↓
eval_resolved() ← Polymarket CLOB API (checks if bet outcome resolved)
    ↓
    ↓ outcome → update bets table (resolved=true, outcome=0|1)
    ↓
eval.py → Brier score from last 15 resolved bets
    ↓
setup.md loop → mutate prompts → re-eval → keep if improved
```

### Critical Data Flow
- **Market discovery**: `GET https://gamma-api.polymarket.com/events?active=true&closed=false` (paginated, up to 2000 events). The `/markets` endpoint with `tag_slug` is BROKEN — it returns ancient 2020 data. NEVER use it.
- **Crypto filtering**: Client-side keyword matching on event titles + market questions. See `CRYPTO_KEYWORDS` and `CRYPTO_TITLE_KEYWORDS` in `run.py`.
- **Bet placement**: Edge-based threshold. If `|analyst_prob - market_price| >= MIN_EDGE (0.03)`, insert into `bets` table.
- **LLM**: Groq API using model `moonshotai/kimi-k2-instruct-0905`. All 3 agents (macro, domain, analyst) use this model. Relevant for rate limit math and future model-swap experiments.
- **Resolution**: `eval_resolved()` queries unresolved bets, checks condition IDs against Polymarket's CLOB/Gamma API for settlement.
- **Evaluation**: Brier score = mean of (predicted_prob - outcome)² over last 15 resolved bets. Lower is better (0.0 = perfect, 0.25 = random).

### prompt_hash
`run.py` computes `prompt_hash` automatically by hashing the contents of `macro.md + domains.md + analyst.md` (via `_prompt_hash()`). Every bet stores this hash. When you modify any prompt file and run `run.py`, new bets get a new hash automatically — no manual step needed. This is how `eval.py` distinguishes bets from different prompt versions.

### Supabase Tables
- **bets**: All paper bets with `market_id`, `question`, `predicted_prob`, `market_price`, `resolved`, `outcome`, `prompt_hash`, `market_context`
- **run_logs**: Every `run.py` execution — markets fetched, analyzed, bets placed, errors
- **eval_runs**: Evaluation results per prompt version
- **strategy_versions**: Prompt version history

## Setup

To set up a new experiment run:

1. **Create branch**: `git checkout -b autoloop/<tag>` from main. Pick a tag based on today's date (e.g. `mar28`). Use ONE branch for the entire experiment series — keep committing to it until the human creates a new one. Do NOT create new branches daily.
2. **Read the codebase** for full context:
   - `prompts/macro.md` — macro research agent prompt
   - `prompts/domains.md` — domain filter agent prompt (decides: proceed or skip)
   - `prompts/analyst.md` — analyst agent prompt (outputs `{reasoning, final_prob}`)
   - `run.py` — main orchestration: fetch markets → macro → domain filter → analyst → bet
   - `eval.py` — Brier score evaluator (reads resolved bets from Supabase)
3. **Verify prerequisites**: `.venv\Scripts\pip install groq supabase python-dotenv requests`. If anything is missing, tell the human and stop.
4. **Check data readiness**: Run `python run.py --status` to verify:
   - How many real bets exist (prompt_hash ≠ 'seed')
   - How many are resolved (need 15+ for meaningful Brier score)
   - Current Brier score
5. **If <15 resolved bets**: The autoresearch loop CANNOT run yet. Instead, run `python run.py` multiple times (with 10+ minute gaps between runs for rate limits) to place paper bets, then wait for markets to resolve. Most crypto markets on Polymarket resolve within **24–72 hours** of their deadline, though some long-dated markets (e.g. "by December 2026") won't resolve for months. Prioritize short-dated markets for faster data collection.
6. **Create results.tsv** with this header row:
   `commit	brier_score	status	description`
7. **Establish baseline**: Run the eval command as-is before making any changes. Log the result as the first row.
8. **Confirm and go**: Confirm setup looks good with the human, then begin the loop.

## Daily Operations

### Place paper bets (data collection)
```powershell
# Real run — places bets into Supabase
.venv\Scripts\python.exe run.py

# Preview mode — shows what would happen without writing to DB
.venv\Scripts\python.exe run.py --dry-run

# Check current state
.venv\Scripts\python.exe run.py --status
```

### What run.py does each time:
1. Calls `eval_resolved()` — checks all open bets for settlement
2. Fetches ALL active Polymarket events via `/events` endpoint (paginated)
3. Filters to crypto/bitcoin events via `CRYPTO_KEYWORDS` (client-side)
4. Extracts individual markets from matching events
5. Sorts by volume (most liquid first)
6. For each market (up to 15 per run):
   - Calls **macro agent** (big-picture context)
   - Calls **domain filter agent** (proceed/skip decision)
   - If proceed: calls **analyst agent** (outputs `{reasoning, final_prob}`)
   - If edge ≥ MIN_EDGE: inserts paper bet into `bets` table
7. Prints run summary + logs to `run_logs` table

### Rate Limits
Each run makes up to 45 Groq API calls (15 markets × 3 agents). Groq's free tier allows ~30 req/min. `run.py` already has `time.sleep()` pacing between calls, but if you hit rate limits:
- The built-in retry with exponential backoff (1s, 2s, 4s…) handles transient limits.
- Wait at least **10 minutes** between full `run.py` executions.
- Do NOT run `run.py` in a tight loop.

## Rules

**What you CAN do:**
- Modify `prompts/macro.md`, `prompts/domains.md`, `prompts/analyst.md`. Everything in these files is fair game.
- Modify `CRYPTO_KEYWORDS`, `CRYPTO_TITLE_KEYWORDS`, `GAMING_BLACKLIST` in run.py to tune market filtering.
- Adjust `MIN_EDGE` threshold in run.py. **Practical range: 0.01–0.15.** Below 0.01 bets on everything (noisy). Above 0.15 rarely bets (starves eval of data).

**What you CANNOT do:**
- Do NOT modify `eval.py`.
- Do NOT install new packages or add dependencies.
- Do NOT modify test fixtures, test cases, or expected outputs.
- Do NOT use the `/markets?tag_slug=` endpoint — it returns stale 2020 data.
- Only run between 11pm and 6am. Never place real money bets. Log all paper bets to Supabase.

**Goal: minimize `brier_score`.**

**Simplicity criterion**: All else being equal, simpler is better. A Brier improvement of **less than 0.005 does not justify adding more than 5 lines of prompt complexity**. Removing something and getting equal or better results is a great outcome.

## Eval Command

```powershell
.venv\Scripts\python.exe eval.py
```

The score line in stdout looks like: `brier_score: 0.2314`
Extract it with: `findstr "brier_score:" run.log`

### `--check-mutation` flag
```powershell
.venv\Scripts\python.exe eval.py --check-mutation > run.log 2>&1
```
This runs the full eval harness (`eval/harness.py`) which:
1. Computes Brier score on `backtest` split bets
2. Compares against the stored best score for the current strategy version
3. Prints `Mutation gate: ACCEPT` if the new score is strictly lower (better), or `Mutation gate: REJECT` otherwise
4. Saves the new version to `strategy_versions` table if accepted

**Mechanically**: `ACCEPT` = your prompt change improved the score, keep the commit. `REJECT` = it didn't, revert it. The numeric Brier comparison is the source of truth — use the gate as confirmation, not the other way around.

**Important**: If eval returns `brier_score: not_enough_data`, you need more resolved bets. Run `python run.py` to place bets, then wait for resolution. Most crypto markets resolve within 24–72 hours of their deadline.

## Statistical Note on Small Samples

At n=15 resolved bets, the Brier score has high variance. A single bet on a 0.50 market shifts the score by ~0.017. **Treat score differences < 0.01 as noise.** Only keep a mutation if the improvement is ≥ 0.01 — anything smaller is likely random fluctuation. As n grows past 50, smaller differences become meaningful.

## Results Format

Log every experiment to `results.tsv` (tab-separated). The TSV has this header:

```
commit	brier_score	status	description
```

- **commit**: short git hash (7 chars)
- **brier_score**: the score achieved (use `0` for crashes)
- **status**: `keep`, `discard`, or `crash`
- **description**: short text describing what the experiment tried

## The Experiment Loop

LOOP FOREVER:

1. Check data readiness first: `python run.py --status`. If <15 resolved bets, collect more data before experimenting.
2. Look at the git state and results so far for context.
3. Modify `prompts/macro.md`, `prompts/domains.md`, `prompts/analyst.md` with an experimental idea.
4. `git commit -m "short description of what you changed"`
5. Run the experiment:
   ```powershell
   .venv\Scripts\python.exe eval.py --check-mutation > run.log 2>&1
   ```
   IMPORTANT: Always redirect `eval.py` output to run.log. The eval harness prints verbose per-bet analysis that will flood your context.
   
   `run.py` output is short and useful (market names, edges, bet confirmations) — read it directly, do NOT redirect it.
6. Read the result: `findstr "brier_score:" run.log`
7. If the result is empty or shows `not_enough_data`, the run crashed. Run `Get-Content run.log -Tail 50` to see the error.
8. Record the result in results.tsv.
9. If brier_score improved by **≥ 0.01** compared to the current best, **keep** the commit (advance the branch).
10. If brier_score is worse, equal, or improved by < 0.01: **discard** and revert:
    ```powershell
    # Step A: Capture the prompt_hash BEFORE reverting
    .venv\Scripts\python.exe -c "from run import _prompt_hash; print(_prompt_hash())"
    # (save the output, e.g. 'a3f9c1b')

    # Step B: Revert the code
    git reset --hard HEAD~1

    # Step C: Delete the bad bets from Supabase (git reset only reverts code, NOT DB)
    .venv\Scripts\python.exe -c "from dotenv import load_dotenv; load_dotenv(); import os; from supabase import create_client; sb = create_client(os.environ['SUPABASE_URL'], os.environ['SUPABASE_KEY']); sb.table('bets').delete().eq('prompt_hash', '<HASH_FROM_STEP_A>').eq('resolved', False).execute()"
    ```
    If you skip Step C, garbage bets from bad prompts stay in the DB and pollute future Brier scores.

**Timeout**: If a run exceeds 30 minutes, kill it and treat it as a crash.

**Crashes**: Use your judgment. If it's something trivial to fix (typo, missing import), fix and re-run. If the idea is fundamentally broken, log it as `crash` and move on. If you can't get things working after 2-3 attempts, give up on that idea.

**NEVER STOP**: Once the loop has begun, do NOT pause to ask the human anything. Do NOT ask "should I keep going?" or "is this a good stopping point?" The human might be asleep and expects you to continue working indefinitely. You are autonomous. If you run out of ideas, think harder — re-read the codebase for new angles, try combining previous near-misses, try more radical changes. The loop runs until the human manually stops you.

## Resuming After a Crash or Context Reset

If your context resets mid-loop (crash, timeout, fresh session):

1. `cd` to the project directory.
2. Read `results.tsv` to see what experiments have been run and what the current best score is.
3. Run `git log --oneline -5` to see the current branch state.
4. Run `python run.py --status` to see the current Supabase state.
5. The **current best** is the lowest `brier_score` with `status=keep` in results.tsv. If no `keep` rows exist, the baseline is the first row.
6. Continue the loop from step 2 of "The Experiment Loop" using the current best as your comparison target.
7. Do NOT re-run previous experiments — they're already logged. Pick up where you left off.

## Troubleshooting

| Problem | Solution |
|---------|----------|
| `brier_score: not_enough_data` | Need 15+ resolved bets. Run `python run.py` to place bets, wait 24–72h for resolution. |
| `python run.py --status` shows 0 bets | Run `python run.py` to start placing paper bets. |
| Markets are all politics/sports | Check `CRYPTO_KEYWORDS` in run.py — keywords may need updating. |
| No edge found on any market | Lower `MIN_EDGE` (currently 0.03, range 0.01–0.15) or check if analyst prompt is too conservative. |
| API timeout errors | Polymarket Gamma API may be down. Wait 5 min and retry. |
| `prompt_hash='seed'` bets in DB | These are fake seed data. Delete: `DELETE FROM bets WHERE prompt_hash = 'seed'` |
| Groq rate limit errors | Built-in retry handles this. If persistent, wait 10+ min between runs. |
| Score fluctuating wildly | Normal at n<30. Differences < 0.01 are noise. Collect more data. |
| `git reset` didn't fix bad bets | Git only reverts code. Delete bad bets by prompt_hash (see step 10 in loop). |
