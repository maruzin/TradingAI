---
name: pattern-detector
description: Identify market structure (HH/HL/LH/LL, BOS, CHoCH), classical chart patterns (double top/bottom, head & shoulders, triangles, wedges), and divergences (RSI, MACD) on OHLCV data. Use when the user asks "what does the chart say", "any patterns on [TOKEN]", "is there a setup forming", or when a token brief needs structured technical patterns to ground Dimension 3.
---

# Pattern Detector

Reads OHLCV data, returns *structured* pattern hits, never free-form opinions. Outputs are consumed by the analyst prompt and the UI; both expect deterministic shapes.

## Inputs

- `df`: pandas OHLCV with columns `open, high, low, close, volume` indexed by timestamp.
- `timeframe`: 1h / 4h / 1d / 1w. Patterns are timeframe-relative.
- `swing_distance` (optional): minimum bars between swings; default 5.
- `swing_prominence_pct`: how big a wiggle to count; default 1.5%.

## What it produces

```python
PatternReport(
  swings=[Swing(idx, ts, price, kind="high"|"low"), ...],
  structure=StructureLabel(sequence="HH-HL-HH-LH", last_break="bos_up", trend="up"),
  patterns=[
    PatternHit(kind="double_top", confidence=0.74, target=...),
    PatternHit(kind="ascending_triangle", confidence=0.7),
  ],
  divergences=[
    DivergenceHit(kind="rsi_bullish_regular", confidence=0.7),
  ],
)
```

Detected pattern kinds: `double_top`, `double_bottom`, `head_and_shoulders`, `inverse_head_and_shoulders`, `ascending_triangle`, `descending_triangle`, `symmetrical_triangle`, `rising_wedge`, `falling_wedge`, `bull_flag`, `bear_flag`.

Detected divergence kinds: `rsi_bullish_regular`, `rsi_bearish_regular`, `rsi_bullish_hidden`, `rsi_bearish_hidden`, `macd_bullish_regular`, `macd_bearish_regular`.

## Quality bar

- **Geometric only.** No black-box ML. Every pattern is a rule on swings + slopes.
- **Confidence is a goodness-of-fit score, not a probability.** Communicate that to the user.
- **Below 0.6 confidence = "tentative".** Surface it but mark as such.
- **Patterns are a feature, not a thesis.** They feed the brief; they do not generate buy/sell calls on their own.
- **Targets are geometric extrapolations, not predictions.** A double-top target is `neckline - (top - neckline)`. Mark it as a *measured move*, never as a forecast.

## When to invoke

- Inside a token brief, called automatically by `AnalystAgent` to populate the patterns block.
- Standalone: user asks for the chart-only read on a token without the full brief.
- Inside `backtest-runner` to feed pattern-based strategies.
