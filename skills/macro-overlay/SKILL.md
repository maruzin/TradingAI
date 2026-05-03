---
name: macro-overlay
description: Produce the Dimension-5 macro & cross-asset overlay for a brief — US/world equities, DXY, oil, gold, real yields, Fed funds path, unemployment, CPI, market sessions, geopolitical pulse. Use when running a token brief that needs proper macro grounding, or as a standalone "what's the macro tape today" check. Always cites sources. Always frames implications for crypto risk-on / risk-off, never single-coin advice.
---

# Macro Overlay

Goal: tell the analyst (human or LLM) what the global financial weather is right now, so Dimension 5 of any token brief is grounded in real cross-asset reality, not vibes.

## Inputs you should pull

| Bucket | Series / sources | Cadence |
|---|---|---|
| US equities | SPX, NDX, DJIA, VIX (Yahoo Finance, free) | intraday |
| Dollar | DXY (Yahoo, ICE futures) | intraday |
| World equities | FTSE, DAX, Nikkei, Hang Seng | intraday |
| Commodities | WTI, Brent, gold, copper | intraday |
| US rates | Fed funds (FEDFUNDS), 10Y (DGS10), 2Y, 5Y break-evens | daily |
| US macro | Unemployment (UNRATE), CPI (CPIAUCSL), M2 (M2SL), PCE | monthly |
| World macro | ECB rate, BoE rate, BoJ rate, China PMI | as released |
| Geopolitics | GDELT high-impact events; curated headlines for war / sanctions / regulation | rolling 24h |
| Crypto-specific macro | BTC dominance, total stablecoin supply, perp funding rates | intraday |

Wrappers in this repo:
- `app/services/macro.py::MacroOverlay.snapshot()` — Yahoo Finance + FRED + market sessions
- (Sprint 1) `app/services/news.py::geopolitics_pulse()` — GDELT or curated feed

## Output structure

```markdown
# Macro overlay — {DATE UTC}

**Tape**: 🟢 risk-on / 🟡 mixed / 🔴 risk-off — [one-line rationale]

## Equities
- US: SPX [last] ([1d %], [5d %]); regime: [trending/range/etc.]
- World: FTSE / DAX / Nikkei / HSI — one line each

## Dollar & rates
- DXY [last] ([1d %]); 10Y yield [%]; Fed funds [%]
- Implication: USD-denominated risk: [supportive/headwind]

## Commodities
- WTI / Brent / Gold / Copper — one line each
- Implication: industrial vs safe-haven flows

## US macro (latest releases)
- Unemployment: [X%] ([YoY change]); CPI: [%] YoY; M2 trend
- Implication: liquidity regime [easing/tightening/neutral]

## Sessions right now
- NYSE open/closed; LSE; TSE; HKEX
- Liquidity window: [thick/thin]

## Geopolitical pulse (last 24h, high-impact only)
- [event] — [link]

## Implications for crypto
- BTC backdrop: [constructive / mixed / under stress]
- Sector rotation hint: [L1 / L2 / DeFi / AI / RWA / memes — what's bid?]
- Risk to thesis at large: [the single macro thing that could blow up the BTC long thesis right now]

## Sources
- [N] [Title](URL) — retrieved YYYY-MM-DD HH:MM UTC
```

## Rules

- **Frame state, not predictions.** "DXY is rising" is fine. "DXY will rise to 110" is not.
- **No specific equity/commodity recommendations.** This is overlay context for crypto briefs, not a multi-asset advisory.
- **Risk-on/risk-off label is one sentence** with explicit reasoning. If signals conflict, label 🟡 mixed and say so.
- **Macro changes regime slowly.** Don't hyperventilate over a single CPI print; show YoY trend.
- Cite every concrete number. If FRED is rate-limited or down, say so and degrade rather than fabricate.

## Refusals

- "Tell me to short SPY" → out of scope, refuse, explain.
- "Predict next CPI print" → produce conditional scenarios with priors, never a single-point number.
