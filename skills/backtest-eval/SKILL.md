---
name: backtest-eval
description: Score the historical performance of AI-generated calls (briefs, alerts, thesis verdicts) against subsequent market reality. Use when the user asks "how good are these calls", "is this AI actually right", "evaluate my AI's track record", or as a scheduled weekly job. Output is calibration metrics, not P&L claims.
---

# Backtest Evaluator

Every AI output that makes a directional claim (`stance: bull/bear`, alert severity, thesis verdict) is logged with timestamp, claim, confidence, and target horizon. This skill scores those calls retrospectively.

## Process

1. **Pull** `ai_calls` rows where `evaluated_at IS NULL AND created_at < now() - claim.horizon`.
2. **Resolve** each call: pull the actual price/state at the call's horizon; categorize outcome:
   - directional: did price move in the called direction by ≥ a meaningful amount (e.g., 1× ATR)?
   - thesis: did any invalidation criterion trigger?
   - alert: did a "material event" follow within the horizon?
3. **Score** with proper metrics:
   - **Accuracy** at horizon (% correct directional)
   - **Calibration**: are 70%-confidence calls correct ~70% of the time? Use reliability diagrams.
   - **Brier score** for confidence-weighted accuracy
   - **Lead time**: for alerts, how early relative to the move
4. **Update** `ai_calls.evaluated_at` and `ai_calls.outcome`.

## Output

```markdown
# AI Call Track Record — [WEEK ENDING DATE]

**Calls evaluated this period**: [N]

## Accuracy by claim type
| Type | N | Accuracy | Brier | Notes |
|---|---|---|---|---|
| Daily briefs (1d horizon) | 32 | 58% | 0.24 | barely above coin-flip; review prompt |
| Weekly briefs (7d horizon) | 7 | 71% | 0.19 | reasonable |
| Alerts (4h horizon) | 14 | 64% | 0.21 | acceptable |

## Calibration
[reliability table: bucket confidence [0.5,0.6) [0.6,0.7) ... → actual accuracy in bucket]

## Worst misses
- [token + date]: claimed [X], actual [Y]. Likely cause: [reason].

## Best calls
- [token + date]: claimed [X], actual [Y].

## Recommendations
- [if any prompt or rule clearly underperforms]
```

## Rules

- **No P&L claims.** This skill measures directional accuracy and calibration only. Translating to portfolio P&L requires execution, slippage, sizing — out of scope for phase 1.
- **Never report a single accuracy number without N and the period.** "70% accurate" without N is meaningless.
- If N < 20 in a bucket, mark as "insufficient sample".
- Surface the worst misses honestly. The user needs to see where the system fails.
