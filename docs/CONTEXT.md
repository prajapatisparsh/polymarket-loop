# Polymarket Autonomous Loop — Project Context

## What We Are Building
An autonomous prediction market agent that runs overnight, researches events, places paper bets on Polymarket, measures calibration via Brier score, and self-improves its own strategy prompts using the autoresearch loop pattern (inspired by Karpathy's autoresearch).

No human intervention after setup. No real money in Phase 1.

---

## Stack
- **autoresearch-anything** — the loop engine (cloned at `~/autoresearch-anything`). Generates `setup.md` which tells the AI agent how to run the improvement loop. Loop pattern: mutate prompt files → run agents → measure Brier score → keep if improved, git revert if not.
- **OpenClaw** — multi-subagent orchestration (Phase 2)
- **Polymarket Gamma API** — active market data. Base URL: `https://gamma-api.polymarket.com/markets`. Filters: `active=true`, `closed=false`, `tag_slug={tag}`. CLOB API (`https://clob.polymarket.com`) used for resolving closed bets, price momentum, and orderbook depth.
- **Groq API** — LLM inference using `moonshotai/kimi-k2-instruct-0905`
- **Supabase** — stores paper bets, resolved results, Brier score log, strategy versions, eval runs, prompt versions
- **WSL cron** — runs the loop only at night (11pm → 6am). Not yet configured — do after Windows development is complete.

## What is NOT in Phase 1
- No Paperclip.ing (Phase 2)
- No MiroFish swarm simulation (Phase 2)
- No real money execution (Phase 2)
- No Kalshi (Phase 2)
- No OpenClaw multi-agent orchestration (Phase 2)

---

## Project Structure
```
polymarket-loop/
├── run.py              # main orchestration — fetches markets, runs 3 agents, logs bets
├── eval.py             # Brier score entry point; delegates to eval/harness.py for rich mode
├── eval/
│   └── harness.py      # full eval harness: backtest, shadow, production splits + mutation gate
├── _run_exp.py         # experiment runner: commit → eval → keep/revert → log to results.tsv
├── setup.md            # autoresearch loop instructions for the AI coding agent
├── results.tsv         # experiment log (commit, brier_score, status, description)
├── run.log             # last eval output (redirected from eval.py --check-mutation)
├── .env                # SUPABASE_URL, SUPABASE_KEY, GROQ_API_KEY
├── prompts/
│   ├── macro.md        # Layer 1: geopolitical + macro analyst agent prompt
│   ├── domains.md      # Layer 2: domain filter agent — decides if market is worth analyzing
│   └── analyst.md      # Layer 3: superforecaster analyst — outputs final P(yes)
└── .venv/              # Python 3.12 venv
```

---

## Agent Architecture
Three prompt files are the "weights" that the autoresearch loop mutates:

### prompts/macro.md — Layer 1
Geopolitical and macro analyst. Given a market question, outputs:
- macro_regime (bullish/bearish/neutral)
- key_factors (top 3)
- base_rate (historical probability)
- sentiment (positive/negative/mixed)

### prompts/domains.md — Layer 2
Domain filter. Given a market + macro brief, outputs JSON:
```json
{
  "current_event": boolean,
  "domain": "politics|crypto|economics|science|climate|other",
  "liquidity_tier": "high|medium|low",
  "proceed": boolean,
  "reason": string
}
```
Only proceeds if: event is **2026+**, domain is relevant, liquidity is medium/high.

### prompts/analyst.md — Layer 3
Superforecaster-style analyst (evolved from dual contrarian/consensus design — removed in exp3). Outputs JSON only:
```json
{
  "reasoning": string,
  "final_prob": float
}
```
Current best behavior: base-rate anchoring, decisive predictions, 5pp extremization removed (exp40 reverted it), threshold at 0.65/0.35 (exp41).

---

## Supabase Tables

### bets
```sql
id uuid primary key
market_id text
question text
predicted_prob float
market_price float
outcome float
resolved boolean default false
created_at timestamptz
resolved_at timestamptz
eval_split text          -- 'production' | 'shadow' | 'backtest'
prompt_hash text         -- SHA256[:12] of prompt files at bet time
market_context jsonb     -- full context snapshot: spread, volume, days_left, momentum, depth, macro, domain_summary, calibration_note
```

### strategy_versions
```sql
id uuid primary key
content text
brier_at_mutation float
created_at timestamptz
```

### prompt_versions
```sql
id uuid primary key
hash text                -- SHA256[:12] of all three prompt files
prompt_content text      -- full text of all three prompts
metrics jsonb            -- eval metrics at time of save
created_at timestamptz
```

### eval_runs
```sql
market_id text           -- references bets.id (historical bet being re-evaluated)
question text
predicted_prob float
outcome float
prompt_hash text
eval_split text          -- always 'backtest'
run_at timestamptz
```

RLS is disabled on all tables.

---

## Fitness Function
Brier score = mean((predicted_prob - outcome)^2) over last **15** resolved bets.
Lower is better. This is what the autoresearch loop optimizes.
`eval.py` prints: `brier_score: 0.0665` (current best, exp41)
If fewer than 3 resolved bets exist, prints: `brier_score: not_enough_data`

---

## Eval System

### eval.py (entry point)
- Default mode: prints `brier_score: X.XXXX` — this exact format is read by the autoresearch loop and must never change.
- `--rich` / `--check-mutation`: delegates to `eval/harness.py`

### eval/harness.py (full harness)
Three dataset splits:
- **backtest** — re-runs current analyst prompt against the 20 most recent resolved live bets that have `market_context`. Inserts results into `eval_runs`. Used to gate prompt mutations.
- **shadow** — live bets tagged `eval_split='shadow'`, scored after resolution.
- **production** — all production paper bets (default).

Metrics computed: Brier score, ECE (Expected Calibration Error), confidence bands (0.50-0.60, 0.60-0.70, 0.70-0.80, 0.80+).

Mutation gate: compares new backtest Brier against previous `prompt_versions` entry. Accepts if improved (lower), rejects if equal or worse. Requires minimum 10 samples to make a call.

### _run_exp.py (experiment runner)
Automates the commit → eval → keep/revert cycle:
1. `git add -A && git commit -m EXP_MSG`
2. Runs `eval.py --check-mutation`
3. Parses brier_score from output
4. Appends result to `results.tsv`
5. If improved: keeps commit. If not: `git reset --hard HEAD~1`
6. Writes `_exp_result.md` with full summary

---

## run.py Logic
1. Call `eval_resolved()` — polls Polymarket CLOB for closed markets, updates Supabase bets with `outcome` and `resolved_at`. Falls back to Gamma API for markets pruned from CLOB.
2. Call `calibration_summary()` — computes directional accuracy + avg Brier over all resolved bets; returns a single-line note injected into every analyst call.
3. Load `open_market_ids` — set of condition IDs already in open bets, used to skip duplicates.
4. Fetch markets from **Gamma API** across tags: `crypto`, `bitcoin`. Plus keyword searches for: `bitcoin price`, `btc`, `ethereum price`, `crypto`, `5 minute bitcoin`. Deduped by `conditionId`, filtered to future-only (end date > now). Gaming/entertainment markets filtered via `GAMING_BLACKLIST`. A `CRYPTO_KEYWORDS` allowlist pre-filters market questions *before* any LLM call — only markets mentioning bitcoin, btc, ethereum, crypto, blockchain, etc. reach the LLM agents. Normalized fields: `condition_id`, `question`, `tokens[0].price`, `_end_date`, `_days_left`, `_spread`, `_volume`, `_yes_token_id`.
5. For each market (up to **15**), skipping any in `open_market_ids`:
   - Fetch CLOB signals: `fetch_price_momentum()` (24h + 1w price history) and `fetch_orderbook_depth()` (top-3 bids/asks, book imbalance ratio)
   - `time.sleep(3)` before macro call (rate-limit pacing)
   - Call macro.md agent via Groq
   - `time.sleep(2)` before domains call
   - Call domains.md agent via Groq — skip if `proceed: false`
   - `time.sleep(2)` before analyst call
   - Build enriched market context: question, market price, days until close, bid-ask spread, volume, momentum, orderbook depth, macro output, domain JSON, calibration note
   - Call analyst.md agent via Groq
   - If `place_paper_bet: true` → insert into Supabase `bets` table with full `market_context` snapshot and `prompt_hash`
6. Print results per market

---

## CLOB Signal Enrichment

### fetch_price_momentum(yes_token_id)
Calls `GET https://clob.polymarket.com/prices-history` for 24h (60-min fidelity) and 1w (6h fidelity).
Returns: `24h_change_pct`, `1w_change_pct`, `momentum` label (strong_up/mild_up/flat/mild_down/strong_down), `recent_prices` (last 6 points).

### fetch_orderbook_depth(yes_token_id)
Calls `GET https://clob.polymarket.com/book?token_id={yes_token_id}`.
Returns: `top_bids`, `top_asks` (top 3 each), `book_imbalance` ratio (>1 = buy pressure, <1 = sell pressure).

---

## Environment Variables (.env)
```
SUPABASE_URL=your_supabase_project_url
SUPABASE_KEY=your_supabase_anon_legacy_key
GROQ_API_KEY=your_groq_api_key
```

On Windows load with:
```python
from dotenv import load_dotenv
load_dotenv()
```

On WSL load with:
```bash
export $(cat .env | xargs)
```

---

## Experiment History Summary (44 experiments)

Best Brier scores achieved:
- **exp35**: 0.0448 — remove step 4 market comparison + 5pp extremization + stripped output
- **exp32**: 0.0468 — remove edge+place_paper_bet fields, focus on prob only
- **exp29**: 0.0484 — 5pp more extreme than market when agreeing
- **exp25**: 0.0504 — decisiveness rule, push past 0.75/0.25
- **exp41**: 0.0665 — threshold to 0.65/0.35 (current HEAD, edc5a01)

Current best (HEAD): **0.0665** (exp41, commit `edc5a01`)

Key learnings from experiments:
- Simpler prompts consistently outperform complex ones (exp3, exp8, exp32, exp35)
- Removing fields (confidence, edge, place_paper_bet) improved focus and accuracy
- Extremization helps when moderate (5pp), hurts when aggressive (10pp+)
- Dual contrarian/consensus framing added noise — pure superforecaster is better
- Pre-mortem steps, outside-view/inside-view framing, and heavy base-rate anchoring all hurt
- Short-term markets (days_left < 1) behave differently — momentum/news > base rates (exp39 crashed, exp40 reverted the rule)
- Confidence bands consistently show 100% accuracy at 0.70+ when the model is well-calibrated

---

## Current Status
- 44 experiments completed
- Current HEAD: `edc5a01` (exp41, Brier 0.0665)
- All-time best: exp35 at Brier **0.0448** (commit `7e85a1b`)
- Production bets: n=3, Brier=0.0333, ECE=0.18 (statistically weak — need more resolved bets)
- Backtest: n=18 resolved bets with market_context available
- UnicodeEncodeError on Windows terminal when printing `→` in mutation gate reason — cosmetic only, does not affect scoring
- WSL cron not set up yet — do after Windows development is complete

---

## Phase 2 (do not build yet)
- Paperclip.ing — wraps everything into a "company" with CEO agent, per-agent budgets, heartbeat scheduler replacing cron
- MiroFish — swarm simulation of crowd belief dynamics, feeds into probability agent as reflexivity signal
- Soros reflexivity layer — models how market price itself influences outcome (price → narrative → outcome feedback)
- OpenClaw — proper multi-subagent orchestration
- Real money execution via Polymarket CLOB write API
- Kalshi integration

---

## Key Principles
- The prompt files are the weights. The Brier score is the loss function. git is the version control for the loop.
- Domain filter agent (not keyword lists) decides what to analyze
- Paper bets only in Phase 1 — no execution agent
- Groq Kimi K2 for all LLM calls
- Keep it running only at night to save compute costs
- Simpler is better — a small improvement that adds complexity is not worth it
