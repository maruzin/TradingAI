---
name: token-brief
description: Generate a short tactical brief on a single token — current state, last 24h material events, and the one thing the user should pay attention to next. Use when the user wants a fast pulse-check rather than a deep dive — "quick take on [TOKEN]", "what's [TOKEN] doing", "anything new on [TOKEN] today". Output is one screen, source-cited, ends with disclaimer.
---

# Token Brief — Tactical Pulse-Check

For when the user wants a fast read, not a 2,000-word deep dive. Aim for **one screen** of output.

## Output structure

```markdown
# [TOKEN] — [TIME UTC]

**Price**: $X (+Y% 24h, +Z% 7d) | **MC**: $X | **Vol 24h**: $X

**Signal**: 🟢 / 🟡 / 🔴 [one line — what's happening right now]

**Last 24h, material only:**
- [event] — [source]
- [event] — [source]
- (or: "nothing material" — be honest)

**Worth watching today:**
- [the single thing]

**Open thesis status** (if user has one): on-track / drifting / invalidated — [why, one line]

[N] sources cited inline · *Not investment advice.*
```

## Rules

- "Material" filter: ignore noise. A 2% move in a low-cap with no news is not material. A funding-rate flip is.
- If nothing is material, **say so**. Don't manufacture urgency.
- One screen. If you find yourself writing a 6th bullet, escalate to the `crypto-research` skill instead.
- Signal lights mean exactly:
  - 🟢 = constructive setup or thesis tracking
  - 🟡 = mixed / wait
  - 🔴 = warning / thesis under stress
