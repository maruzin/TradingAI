# How TradingAI "learns" over time

The user has rightly asked: *can the AI get better with time?* The answer is yes, but **not** through magical fine-tuning of the base LLM. That would be expensive, slow, and brittle. Instead, the system learns through four concrete mechanisms — three are active in phase 1, the fourth unlocks in phase 2.

This document is the engineering plan behind that promise.

---

## Mechanism 1 — Persistent memory (active phase 1)

Every interaction the system has is logged with structured context. Specifically:

| Table | What it captures | Used for |
|---|---|---|
| `price_ticks` | Time-series prices, market cap, volume, per source | Backtesting, regime detection |
| `sentiment_ticks` | Social volume + sentiment per token, per source | Calibrating sentiment as a signal |
| `news_items` | Headlines + URLs + summary per token | RAG retrieval, narrative tracking |
| `briefs` | Every AI-generated brief — full markdown + structured JSON | Self-reference, RAG context, calibration |
| `theses` + `thesis_evaluations` | User theses + per-eval status changes | "What did I think then? What changed?" |
| `alerts` + `alert_rules` | Every alert rule, every fire, user actions | Tune thresholds, signal-quality scoring |
| `ai_calls` | Every directional claim with target horizon | The truth-meter for the whole system |
| `audit_log` | Every AI-initiated action with args + result | Compliance trail; debugging when things drift |

This is not "training data" in the ML sense. It's **institutional memory**. Without it, the system is goldfish-brained. With it, every future brief on a token can be conditioned on the user's full history with that token.

## Mechanism 2 — Calibration scoring loop (active phase 1, sprint 5)

Every directional claim the AI makes (`bull/bear/neutral` in a brief, an alert's predicted move, a thesis verdict) is logged in `ai_calls` with the time horizon attached. The `backtest-eval` skill scores them retrospectively.

The output is a calibration dashboard with three numbers per claim type:
- **Accuracy at horizon** — % of directional calls that proved correct.
- **Brier score** — confidence-weighted accuracy. Punishes overconfidence.
- **Reliability diagram** — are 70%-confidence calls right ~70% of the time?

These numbers are public to the user and get reviewed weekly. **If the AI is below coin-flip accuracy after a meaningful sample, we don't ship that prompt.** It's that simple.

This is how we know the AI is actually getting better, rather than just *feeling* like it is.

## Mechanism 3 — RAG over the user's own history (active phase 1, sprint 6)

The `briefs`, `theses`, and `news_items` tables get embeddings via the LLMProvider's `embed()` method, stored in `pgvector`. When generating a new brief, the agent retrieves:

- The 5 most recent briefs on the same token (so it can reference its own prior reasoning).
- The user's open thesis on this token, if any (so the brief explicitly engages with it).
- The 10 most semantically similar past briefs across all tokens (for analogous setups).
- The user's saved notes / annotations on past briefs (when that feature lands).

The agent then incorporates this in two ways:
1. **In-context examples.** The "see how I framed BTC at the last halving cycle" effect. Few-shot the model with its own past best-graded outputs.
2. **Self-correction.** "My prior brief 30 days ago said X. The price has done Y. Was X right? What does that tell me about now?"

This is where the "real senior advisor" feeling comes from — an advisor with a long memory who actually remembers what they told you last quarter.

## Mechanism 4 — Optional fine-tuning on the local model (phase 2 stretch)

When the M-series Mac is online running Ollama / MLX, fine-tuning becomes a realistic option because:
- The training compute is local (free, just time).
- The training data is your own brief/outcome pairs (unique, high-signal).
- The risk is contained — if the fine-tune is worse, just don't use it.

Process:
1. After phase-2 has been running for ~3 months, harvest brief/outcome pairs from `ai_calls` joined to `briefs`.
2. Filter to **high-confidence calls that were correct**. Drop the misses.
3. LoRA-fine-tune the local model on these pairs using MLX (a few hours on a 64GB+ Mac).
4. Run the hallucination harness against the fine-tuned variant.
5. If it beats the base on the harness AND on the calibration dashboard, promote it. Otherwise, throw it away.

This is a stretch goal, not a phase-2 commitment. The first three mechanisms deliver the bulk of the "improves over time" promise.

---

## What this is *not*

- **Not magical.** The AI does not silently get smarter. It gets more *grounded*, because we feed it more relevant context (mechanism 3), and we measure whether it's right (mechanism 2).
- **Not a substitute for prompt engineering.** When calibration tanks, a human (or the `prompt-engineer` agent) tunes the prompt. Mechanism 2 is the trigger; tuning is the action.
- **Not a path to alpha-by-itself.** Calibration ≠ profit. A 70%-accurate directional call doesn't make money if it's on a coin nobody can size into. The user still owns the trade.

## Definition of "the AI is working"

After 3 months of phase-1 operation, the calibration dashboard should show:

- ≥60% directional accuracy on `position`-horizon briefs (vs ~50% coin-flip baseline)
- Brier score < 0.22 across brief types
- Citation rate ≥ 95% on hallucination harness
- Zero "you should buy/sell" leakage in the harness regression suite
- User-rated brief usefulness (manual thumbs-up rate) ≥ 60%

If we don't hit those, we change the prompts, change the model, or change the framework — but we don't pretend.

---

## How to extend this

When adding a new feature that produces an AI claim:

1. Decide its **target horizon**. (1h, 1d, 7d, 30d, 90d.)
2. Log it as an `ai_calls` row at creation time.
3. Add a resolver in `app/workers/backtest_evaluator.py` that knows how to grade it at horizon.
4. Add at least one regression case to `eval/hallucination_harness.py`.
5. If the feature retrieves context, hook it into the embeddings/RAG layer.
6. Update this doc.

Without those five steps, the feature can't claim to "learn over time" — it'll just produce output and forget.
