---
name: alert-tuner
description: Review the user's current alert configuration and recommend threshold adjustments based on volatility regime, signal-to-noise ratio, and recent false-positive history. Use when the user says "my alerts are too noisy", "I'm missing important moves", "tune my alerts", or as a scheduled monthly job.
---

# Alert Tuner

Goal: keep daily alert count in the user's stated tolerance band (default 3–8/day) while maximizing material-event recall.

## Process

1. **Load** current alerts: `select * from alerts where user_id = $1` for last 30d, and `select * from alert_rules where user_id = $1`.
2. **Compute** per-rule:
   - Trigger count over last 30d
   - User-action rate (% of alerts the user dismissed vs. acted on / opened the linked token page)
   - Signal-to-noise estimate: post-alert price move at +1h / +4h / +24h vs. baseline volatility
3. **Bucket** rules into:
   - `keep` — fired in band, signal:noise > baseline
   - `loosen` — too quiet (zero alerts in 30d): widen threshold or change source
   - `tighten` — too noisy AND low user-action: raise threshold
   - `kill` — noisy AND ignored AND low signal: recommend deletion
4. **Recommend** changes with explicit before/after thresholds.

## Output

```markdown
# Alert tune-up — [DATE UTC]

**Current daily volume**: [X/day], target band [Y–Z/day]
**Action rate**: [%]

## Per-rule recommendations
| Rule | 30d count | Action rate | Recommendation | Suggested change |
|---|---|---|---|---|
| BTC price > 110k | 4 | 75% | keep | — |
| ETH funding > 0.05% | 28 | 11% | tighten | raise to >0.08% |
| ... |

## New rules to consider
- [rule, with rationale]

## Apply with one click
[shows the SQL or API call needed — user clicks Approve in UI]
```

## Rules

- Never silently change a rule. Always show before/after, get user approval.
- If user-action rate is unknown (new user), default to conservative (no auto-changes, only suggestions).
- Volatility regime matters: a 3% threshold makes sense in normal regimes, not in capitulation. Recommend regime-aware thresholds where supported.
