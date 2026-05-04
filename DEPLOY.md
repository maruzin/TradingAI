# TradingAI — Deployment Walkthrough

This guide gets a fresh deploy from `git push` to "users see real data" in under 30 minutes. It assumes you already have:

- A Supabase project (free tier OK)
- A Vercel project pointed at this repo (auto-deploys on push to `main`)
- A Fly.io account + the `fly` CLI installed

If you don't have these yet, create them first — Supabase: <https://supabase.com/dashboard/projects>, Vercel: connect the GitHub repo, Fly: `flyctl auth signup`.

---

## Step 1 — Run the SQL bundle in Supabase

Open the Supabase SQL Editor for your project and paste the contents of [`infra/supabase/SUPABASE_BUNDLE.sql`](infra/supabase/SUPABASE_BUNDLE.sql). Click **Run**.

The bundle is idempotent: every `create` is guarded with `if not exists`, every policy creation is in a `do` block that catches `42710` (already-exists). Re-running on an existing schema is safe.

After the run you should see ~30 tables + RLS policies + audit triggers + 2 calibrated views in the public schema.

---

## Step 2 — Set environment variables

### On Supabase

Nothing to set — Supabase manages its own envs.

### On Fly (backend)

```bash
fly secrets set -a <your-fly-app-name> \
  ENVIRONMENT=production \
  ALLOW_DEV_AUTH=false \
  SUPABASE_URL="https://<project-ref>.supabase.co" \
  SUPABASE_ANON_KEY="eyJ..." \
  SUPABASE_SERVICE_ROLE_KEY="eyJ..." \
  SUPABASE_DB_URL="postgresql://postgres.<project-ref>:<password>@aws-0-eu-central-1.pooler.supabase.com:5432/postgres" \
  REDIS_URL="redis://default:<password>@<host>:<port>" \
  ANTHROPIC_API_KEY="sk-ant-..." \
  COINGECKO_API_KEY="" \
  CRYPTOPANIC_API_KEY="..." \
  LUNARCRUSH_API_KEY="..." \
  ETHERSCAN_API_KEY="..." \
  POLYGONSCAN_API_KEY="..." \
  ARBISCAN_API_KEY="..." \
  BSCSCAN_API_KEY="..." \
  COINGLASS_API_KEY="..." \
  TELEGRAM_BOT_TOKEN="..." \
  CORS_ORIGINS='["https://<your-vercel-domain>"]' \
  SENTRY_DSN="https://<id>@<org>.ingest.sentry.io/<project>"
```

If you want CI to auto-deploy on push to `main`, add a Fly deploy token as a
GitHub Actions repo secret:

```bash
# Mint via the Fly dashboard → Tokens, or:
fly tokens create deploy --name github-actions --expiry 8760h

# Then in GitHub: Settings → Secrets and variables → Actions → New secret:
# Name:  FLY_API_TOKEN
# Value: <paste the FlyV1 token>
```

A workflow that consumes it would then call `flyctl deploy --remote-only` with
`FLY_API_TOKEN` exported in the env.

The values for SUPABASE_* live in **Supabase → Project Settings → API** and **Database → Connection String → URI**.

The `SUPABASE_DB_URL` should be the **Session pooler** connection string for production — it survives serverless cold starts better than the direct connection.

Restart Fly after setting:

```bash
fly apps restart <your-fly-app-name>
```

### On Vercel (frontend)

In Vercel → your project → Settings → Environment Variables, set:

```
NEXT_PUBLIC_SUPABASE_URL=https://<project-ref>.supabase.co
NEXT_PUBLIC_SUPABASE_ANON_KEY=eyJ...
NEXT_PUBLIC_API_BASE_URL=https://<your-fly-app>.fly.dev
NEXT_PUBLIC_SENTRY_DSN=https://<id>@<org>.ingest.sentry.io/<project>
NEXT_PUBLIC_ENV=production
```

Then redeploy: Vercel → Deployments → Redeploy latest.

---

## Step 3 — Seed the dashboard so it isn't empty on first visit

These three commands populate the homepage hero + verdict surfaces with real numbers immediately rather than waiting for the next cron tick.

```bash
fly ssh console -a <your-fly-app-name>
cd /app

# Backfill 2 years of synthetic-graded calls so the calibration hero shows
# real Brier scores from minute one. ~2 minutes for the default universe.
uv run python -m app.workers.calibration_seeder \
  --pairs BTC/USDT,ETH/USDT,SOL/USDT,BNB/USDT,XRP/USDT \
  --years 2

# Trigger one TA snapshot cycle for each timeframe so the multi-TF panel
# on token pages renders immediately rather than waiting up to 12 hours.
uv run python -c "
import asyncio
from app.workers import ta_snapshotter
for tf in ('1h','3h','6h','12h'):
    print(asyncio.run(ta_snapshotter.run_for_tf(tf)))
"

# Run the bot decider once so the verdict card on every token page has
# a current decision. Cron then re-runs it every hour.
uv run python -c "
import asyncio
from app.workers import bot_decider
print(asyncio.run(bot_decider.run()))
"
```

You don't need to run `predictor_trainer` manually — the lazy-train path triggers on the first `/forecast` request.

---

## Step 4 — Verify

```bash
# Backend health
curl https://<your-fly-app>.fly.dev/healthz
curl https://<your-fly-app>.fly.dev/readyz

# Public probe — should all return 200 with sensible bodies
curl https://<your-fly-app>.fly.dev/api/regime/snapshot
curl https://<your-fly-app>.fly.dev/api/regime/sectors
curl https://<your-fly-app>.fly.dev/api/track-record
curl https://<your-fly-app>.fly.dev/api/picks/today
curl https://<your-fly-app>.fly.dev/api/bot/decisions
curl https://<your-fly-app>.fly.dev/api/tokens/btc/ta
```

Then visit the deployed Vercel URL. The dashboard should show:

- SectorTile populated
- CalibrationHero with real Brier numbers
- A TokenCard grid

A token deep-dive should show:

- Price + chart (lazy-loaded)
- BotVerdictCard with stance + reasoning
- TAPanel (1h/3h/6h/12h verdicts)
- Brief generation works on demand

---

## Common gotchas

| Symptom | Likely cause | Fix |
|---|---|---|
| Every API call returns 500 | `SUPABASE_DB_URL` not set or wrong format | Re-fetch the connection string from Supabase → Database → Connection String → URI (use the **session pooler** for prod) |
| RLS errors mentioning "infinite recursion" | Old policies from a prior schema | In SQL editor: `select * from rls_audit();` to find suspect policies, then re-run the bundle |
| `/api/picks/today` always 404 | The daily-picks worker hasn't run | Trigger it once: `fly ssh console`, then `uv run python -m app.workers.daily_picks` |
| `/api/bot/decisions` empty | Bot worker hasn't run | Trigger: see Step 3 |
| `/api/tokens/X/forecast` 404 | LightGBM model never trained for that pair | First `/forecast` call lazy-trains automatically (~10s); or run `uv run python -m app.workers.predictor_trainer` |
| Frontend shows raw error JSON | Vercel can't reach the Fly backend | Verify `NEXT_PUBLIC_API_BASE_URL` matches the Fly URL (no trailing slash) |
| Telegram alerts don't arrive | Bot token missing or bot not started | `fly secrets list` to confirm `TELEGRAM_BOT_TOKEN`; verify the user linked their Telegram via Settings page |

---

## Ongoing operations

| Task | Cadence | Owner |
|---|---|---|
| Watch Sentry for new error spikes | Daily glance | You |
| Review `/admin/health` page | Weekly | You (admin) |
| Run `python -m app.workers.predictor_trainer` | Auto (Sunday 02:00 UTC cron) | The system |
| Run `python -m app.workers.calibration_seeder` again | Quarterly, to keep the calibration window rolling | You |
| Check Supabase storage / row counts | Monthly | You |
| Rotate API keys | Every 90 days | You |

Everything else runs on cron.
