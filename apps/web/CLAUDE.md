# Frontend (apps/web) — Conventions for Claude

Read the root `CLAUDE.md` first. This file covers frontend specifics only.

## Stack

- **Next.js 14** App Router, **React 18**, **TypeScript 5** strict
- **Tailwind CSS** + **shadcn/ui** (copy-paste, not a library) for primitives
- **TanStack Query** for server state, **Zustand** for client state (minimal use)
- **TradingView**: free embed widget for visual charts; **`lightweight-charts`** for custom panels (volume profile, sentiment overlays)
- **`pnpm`** package manager, **`vitest`** for unit tests, **`playwright`** for E2E
- Auth via **Supabase JS client** (passkeys / magic link)

## Folder layout

```
apps/web/
├── package.json
├── next.config.mjs
├── tsconfig.json
├── tailwind.config.ts
├── app/
│   ├── layout.tsx           # root layout, theme, query client
│   ├── globals.css
│   ├── page.tsx             # /  → dashboard
│   ├── token/[symbol]/page.tsx   # /token/:symbol → deep-dive
│   ├── alerts/page.tsx      # /alerts → inbox
│   ├── thesis/page.tsx      # /thesis → open theses
│   └── api/                 # server actions / route handlers
├── components/
│   ├── ui/                  # shadcn primitives
│   ├── charts/
│   ├── token/               # token-specific composites
│   └── disclaimers/
├── lib/
│   ├── api.ts               # backend client (typed)
│   ├── supabase.ts
│   └── format.ts            # money / pct / time formatters
└── tests/
```

## Three core surfaces (resist scope creep)

1. **Dashboard** (`/`) — watchlist as cards: price, 24h change chip, AI sentiment chip, last material event timestamp, single-tap to deep dive.
2. **Token deep-dive** (`/token/:symbol`) — five-dimension brief, charts, news feed, sentiment timeline, "Ask the analyst" chat scoped to this token.
3. **Alerts inbox** (`/alerts`) — chronological, severity-colored, dismissable.

Bonus surfaces only after MVP signs off: `/thesis`, `/portfolio`, `/settings`.

## Design rules

- **Confidence is visible.** Every AI claim renders with an inline confidence chip and a "Sources (n)" expandable. No silent assertions.
- **"Not investment advice"** banner is persistent in the footer of `/token/*` and `/alerts`. Do not let it scroll out.
- **Dark mode first**, light mode second. Crypto users live in dark.
- **Mobile sane.** PWA-ready. Charts collapse to summary on narrow viewports.
- **Color discipline.** Greens/reds only for price movement and signal severity. Don't decorate UI chrome with them.
- **No animations on numbers** that update faster than 1Hz (dashboards become unreadable). Smooth transitions only for layout.

## Accessibility (WCAG 2.1 AA — non-negotiable)

- Color contrast ≥4.5:1 for all text. Never red-on-green or green-on-red as the only signal — always pair with an icon or label.
- Keyboard-navigable everywhere; focus rings visible.
- Charts: every chart has a text-equivalent summary readable by screen reader.
- Run `design:accessibility-review` skill before any major UI ship.

## Data fetching pattern

- Use TanStack Query everywhere. **Do not** call `fetch` from components.
- One query key prefix per resource (`['token', symbol]`, `['watchlist']`, `['alerts']`).
- Background refetch intervals:
  - Prices: 15s
  - News/sentiment: 5min
  - AI brief: stale-while-revalidate, manual refresh button
- Server components for initial render; client components for anything interactive.

## Forms

- React Hook Form + Zod schemas. Schemas live next to the form component.
- Error messages: human, specific, suggest a fix. Use `design:ux-copy` skill for review.

## Disclaimers component

`<Disclaimer kind="not-financial-advice" />` and `<Disclaimer kind="speculative" />` are mandatory placements; ESLint rule (planned) will fail builds that render token analysis without them.

## Definition of done for a frontend task

- [ ] Type-checks (`tsc --noEmit`) and lints clean
- [ ] Unit tests for non-trivial components
- [ ] Mobile (375px), tablet (768px), desktop (1280px) all sane
- [ ] Keyboard navigation works
- [ ] Loading + empty + error states all designed
- [ ] Disclaimers in place where required
- [ ] No raw `fetch` — uses TanStack Query
