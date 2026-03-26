# Autonomous Improvement Loop

> Autonomous prediction market agent that bets on Polymarket by researching events and calibrating probabilities

## Setup

To set up a new experiment run:

1. **Create branch**: `git checkout -b autoloop/<tag>` from main. Pick a tag based on today's date (e.g. `mar9`). The branch must not already exist.
2. **Read the codebase** for full context:
   - `prompts/macro.md`
   - `prompts/domains.md`
   - `prompts/analyst.md`
   - `prompts/macro.md`
   - `prompts/domains.md`
   - `prompts/analyst.md`
3. **Verify prerequisites**: pip install groq supabase requests. If anything is missing, tell the human and stop.
4. **Create results.tsv** with this header row:
   `commit	brier_score	status	description`
5. **Establish baseline**: Run the eval command as-is before making any changes. Log the result as the first row.
6. **Confirm and go**: Confirm setup looks good with the human, then begin the loop.

## Rules

**What you CAN do:**
- Modify `prompts/macro.md`, `prompts/domains.md`, `prompts/analyst.md`. Everything in these files is fair game.

**What you CANNOT do:**
- Do NOT modify `eval.py`.
- Do NOT install new packages or add dependencies.
- Do NOT modify test fixtures, test cases, or expected outputs.
- Only run between 11pm and 6am. Never place real money bets. Log all paper bets to Supabase.

**Goal: minimize `brier_score`.**

**Simplicity criterion**: All else being equal, simpler is better. A small improvement that adds ugly complexity is not worth it. Removing something and getting equal or better results is a great outcome.

## Eval Command

```bash
python eval.py
```

The score line in stdout looks like: `brier_score: 0.2314`
Extract it with: `grep "^brier_score:" run.log`

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

1. Look at the git state and results so far for context.
2. Modify `prompts/macro.md`, `prompts/domains.md`, `prompts/analyst.md` with an experimental idea.
3. `git commit -m "short description of what you changed"`
4. Run the experiment:
   ```bash
   timeout 1800 python eval.py > run.log 2>&1
   ```
   IMPORTANT: Always redirect to run.log. Do NOT use tee or let output stream into your context window. It will flood your context and slow you down across experiments.
5. Read the result: `grep "^brier_score:" run.log`
6. If grep output is empty, the run crashed or timed out. Run `tail -50 run.log` to see the error.
7. Record the result in results.tsv.
8. If brier_score improved (lower) compared to the current best, **keep** the commit (advance the branch).
9. If brier_score is equal or worse (higher or same), **discard** and revert: `git reset --hard HEAD~1`.

**Timeout**: If a run exceeds 30 minutes, kill it and treat it as a crash.

**Crashes**: Use your judgment. If it's something trivial to fix (typo, missing import), fix and re-run. If the idea is fundamentally broken, log it as `crash` and move on. If you can't get things working after 2-3 attempts, give up on that idea.

**NEVER STOP**: Once the loop has begun, do NOT pause to ask the human anything. Do NOT ask "should I keep going?" or "is this a good stopping point?" The human might be asleep and expects you to continue working indefinitely. You are autonomous. If you run out of ideas, think harder — re-read the codebase for new angles, try combining previous near-misses, try more radical changes. The loop runs until the human manually stops you.
