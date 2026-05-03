"""Wallet-tracker polling worker. Runs every 5 minutes.

For each enabled tracked wallet whose `last_polled_at` is older than the
threshold, fetch recent transfers via Etherscan family, dedup-insert into
`wallet_events`, and emit alerts when a transfer's USD value crosses the
configured threshold (default: $250k).

Cost guard: skips wallets whose chain has no API key configured (free tier
still works on Etherscan but is slower; you can set chain-specific keys in
.env to lift rate limits).
"""
from __future__ import annotations

import time
from typing import Any

from ..logging_setup import get_logger
from ..repositories import alerts as alert_repo
from ..repositories import audit as audit_repo
from ..repositories import wallets as wallet_repo
from ..services.coingecko import CoinGeckoClient
from ..services.wallet_tracker import WalletTrackerClient

log = get_logger("worker.wallet_poller")

# Minimum USD value of a single transfer to fire an alert. Lower this in
# system_flags later if a power user wants more granular signals.
ALERT_THRESHOLD_USD = 250_000.0

# Maximum number of wallets to poll in one cycle. Etherscan free tier is
# 5 calls/s, so 50 wallets × 2 calls (native + ERC-20) = ~20s minimum.
MAX_WALLETS_PER_CYCLE = 50


async def run(_ctx: dict | None = None) -> dict[str, Any]:
    started = time.time()
    polled = 0
    inserted = 0
    alerts_fired = 0

    try:
        wallets = await wallet_repo.list_due_for_polling(
            max_age_seconds=300, limit=MAX_WALLETS_PER_CYCLE,
        )
    except Exception as e:
        log.warning("wallet_poller.list_failed", error=str(e))
        return {"polled": 0, "inserted": 0, "alerts": 0, "error": str(e)}

    if not wallets:
        return {"polled": 0, "inserted": 0, "alerts": 0}

    cg = CoinGeckoClient()
    tracker = WalletTrackerClient()
    try:
        for w in wallets:
            wallet_id = w["id"]
            chain = w["chain"]
            address = w["address"]
            label = w["label"]
            try:
                txs = await tracker.recent_transfers(chain, address, page_size=25)
            except Exception as e:
                log.warning("wallet_poller.fetch_failed",
                            wallet=label, chain=chain, error=str(e))
                continue

            for tx in txs:
                # Best-effort USD pricing. Symbol-only lookup; misses for
                # very long-tail tokens, which is fine — we'll report the
                # transfer with amount_usd=None and let the UI render "—".
                amount_usd = None
                if tx.amount and tx.token_symbol:
                    try:
                        snap = await cg.snapshot(tx.token_symbol)
                        if snap and snap.price_usd:
                            amount_usd = float(tx.amount) * float(snap.price_usd)
                    except Exception:
                        amount_usd = None

                try:
                    new_id = await wallet_repo.insert_event(
                        wallet_id=wallet_id, chain=tx.chain, address=tx.address,
                        tx_hash=tx.tx_hash, block_number=tx.block_number,
                        ts_unix=tx.ts_unix, direction=tx.direction,
                        token_symbol=tx.token_symbol, token_address=tx.token_address,
                        amount=tx.amount, amount_usd=amount_usd,
                        counterparty=tx.counterparty,
                        counterparty_label=tx.counterparty_label,
                        payload=tx.payload,
                    )
                except Exception as e:
                    log.debug("wallet_poller.insert_failed",
                              wallet=label, tx=tx.tx_hash[:10], error=str(e))
                    continue

                if new_id is None:
                    continue  # already had this event
                inserted += 1

                # Alert on large transfers, scoped to the wallet's owner so
                # global/curated wallets fire alerts to every user that
                # follows them. For now: only fire when the wallet is owned
                # by a specific user (curated wallets emit gossip events
                # via a separate path).
                if (
                    amount_usd is not None
                    and amount_usd >= ALERT_THRESHOLD_USD
                    and w.get("user_id")
                ):
                    try:
                        await alert_repo.fire_alert(
                            user_id=w["user_id"],
                            rule_id=None,
                            token_id=None,
                            severity="warn" if amount_usd < 1_000_000 else "critical",
                            title=f"{label} moved {tx.amount:.4g} {tx.token_symbol}",
                            body=(
                                f"${amount_usd:,.0f} {tx.direction} "
                                f"({tx.counterparty_label or (tx.counterparty or 'unknown')[:10]+'…'})"
                            ),
                            payload={
                                "kind": "wallet_movement",
                                "wallet_id": wallet_id,
                                "tx_hash": tx.tx_hash,
                                "chain": tx.chain,
                                "amount": tx.amount,
                                "amount_usd": amount_usd,
                                "direction": tx.direction,
                                "token_symbol": tx.token_symbol,
                            },
                        )
                        alerts_fired += 1
                    except Exception as e:
                        log.debug("wallet_poller.alert_failed",
                                  wallet=label, error=str(e))

            try:
                await wallet_repo.mark_polled(wallet_id)
            except Exception:
                pass
            polled += 1

        # One audit row per cycle so the trail records the worker ran.
        await audit_repo.write(
            user_id=None, actor="system", action="wallet_poller.cycle",
            target="tracked_wallets",
            args={"max_wallets": MAX_WALLETS_PER_CYCLE},
            result={"polled": polled, "inserted": inserted, "alerts": alerts_fired},
        )
    finally:
        await tracker.close()
        await cg.close()

    log.info("wallet_poller.done",
             polled=polled, inserted=inserted, alerts=alerts_fired,
             latency_s=int(time.time() - started))
    return {"polled": polled, "inserted": inserted, "alerts": alerts_fired}
