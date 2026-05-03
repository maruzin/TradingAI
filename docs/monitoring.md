# External monitoring setup

Once deployed (Vercel + Fly), wire one of these free uptime services so a
broken cron or backend silently going down doesn't sit unnoticed for days.

The endpoints below are designed to give a clean 200 when healthy and a
non-2xx when material state is wrong.

## Endpoints to monitor

| Endpoint | Healthy meaning | Cadence |
|---|---|---|
| `GET /healthz` | Process alive (FastAPI responds) | every 1 min |
| `GET /readyz` | DB reachable + LLM creds configured | every 5 min |
| `GET /api/regime/snapshot` | Regime cache populated (≥1 field non-null) | every 15 min |
| `GET /api/picks/today` | Daily-picks worker ran today | every hour after 07:30 UTC |

`/api/admin/health/snapshot` exposes more (cron last-runs, breaker state,
LLM spend) but is admin-auth-only — point an admin token at it from your
own browser, not from a public uptime probe.

## Recommended free services

1. **Better Uptime** — 10 monitors free, 3-min cadence. Slack/email alerts.
2. **Cronitor** — 5 monitors free, supports cron-style "should run by"
   alerts. Use this for `picks_today` ("should be populated by 07:30 UTC").
3. **UptimeRobot** — 50 monitors free, 5-min cadence. Email/Telegram.

## Alert routing

Send monitor failures to the same Telegram channel as user-facing alerts —
the project owner already gets daily morning briefs there, so adding
"backend down" makes it the single observability surface.

For paid alternatives once usage grows: PagerDuty (incidents), Sentry
Crons (already wired), Grafana Cloud (free 14-day metrics).
