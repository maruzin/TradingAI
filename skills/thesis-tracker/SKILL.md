---
name: thesis-tracker
description: Evaluate a user's open investment thesis against current data and call out drift or invalidation. Use when the user says "check my thesis on [TOKEN]", "is my [TOKEN] thesis still good", or when run as a scheduled job. Reads the stored thesis (assumptions + invalidation criteria), pulls fresh data, scores each criterion, and produces a status report with a clear stay/reassess/exit recommendation framing.
---

# Thesis Tracker

A user's investment thesis is a structured object stored in the `theses` table:

```yaml
token: BTC
opened_at: 2026-04-01T00:00:00Z
horizon: position  # swing | position | long
stance: bullish    # bullish | bearish
core_thesis: >
  ETF inflows + post-halving supply shock + macro liquidity easing drives
  BTC into a new cycle high zone over 6–12 months.
key_assumptions:
  - cumulative_etf_net_inflows_30d > 0
  - hashrate_trend_90d in [flat, up]
  - fed_funds_path = cutting OR holding
  - btc_above_realized_price = true
invalidation:
  - 12w close below 200-week MA
  - cumulative ETF outflows > $X over rolling 30d
  - macro: emergency rate hike OR USD index spikes >5% in 30d
review_cadence: weekly
```

## Process

1. **Load** the thesis from the DB (or from the user's pasted YAML).
2. **Pull current data** for each assumption and invalidation condition. Use the same data sources listed in `crypto-research`.
3. **Score** each line: ✅ holding / ⚠️ drifting / ❌ broken / ❓ unobservable.
4. **Aggregate**: stance status = healthy (all ✅) / drifting (any ⚠️) / under stress (any ❌).
5. **Recommend a framing**, not an action:
   - healthy → "thesis intact, no action implied"
   - drifting → "watch list: [items]; consider tightening risk"
   - under stress → "your stated invalidation has triggered; revisit position sizing per your own rules"

## Output

```markdown
# Thesis check — [TOKEN] — [DATE UTC]

**Stance**: [bullish/bearish] · opened [DATE] · horizon: [horizon]

**Status**: 🟢 healthy / 🟡 drifting / 🔴 under stress

## Assumptions
- ✅ / ⚠️ / ❌ / ❓ [assumption] — [current reading + source]
- ...

## Invalidation criteria
- ✅ / ❌ [criterion] — [current reading + source]
- ...

## Drift since last check
- [what changed since the last evaluation]

## Framing (not advice)
[one paragraph — never "buy" or "sell"; describe what the user's own stated rules imply]

[N] sources · *Not investment advice. Your thesis, your rules, your decision.*
```

## Rules

- **Never** issue buy/sell instructions. Only mirror back what the user's own invalidation criteria imply.
- If an assumption is unobservable from available data, mark `❓` and explain — don't guess.
- If the thesis is missing invalidation criteria, refuse the check and prompt the user to add them. A thesis without invalidation is a hope.
