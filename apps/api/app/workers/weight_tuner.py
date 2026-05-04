"""Weight tuner worker — runs every Sunday 03:00 UTC.

Measures per-component accuracy from the last 60 days of graded ai_calls
and proposes adjusted weights for each persona. Writes the result to
``system_flags['bot_weights_<persona>']`` so the bot decider picks them
up on the next cycle.

Activation gate: components with fewer than ``MIN_SAMPLE`` graded calls
get their base weights kept. Until enough live data accumulates, this
worker is a no-op (it logs the diagnostic but doesn't move weights). That
is intentional — early-life overreaction to noise is worse than running
on the conservative defaults.
"""
from __future__ import annotations

import time
from typing import Any

from ..logging_setup import get_logger
from ..repositories import audit as audit_repo
from ..services.bot_decider import PERSONA_WEIGHTS
from ..services.weight_tuner import (
    measure_component_accuracy,
    persist_tuned_weights,
    propose_weights,
)

log = get_logger("worker.weight_tuner")


async def run(_ctx: dict | None = None) -> dict[str, Any]:
    started = time.time()
    try:
        accuracy = await measure_component_accuracy(since_days=60)
    except Exception as e:
        log.warning("weight_tuner.measure_failed", error=str(e))
        return {"updated": 0, "error": str(e)}

    component_acc = {k: v[1] for k, v in accuracy.items()}
    component_n = {k: v[0] for k, v in accuracy.items()}

    updated = 0
    persona_results: list[dict[str, Any]] = []
    for persona in PERSONA_WEIGHTS:
        tuned = propose_weights(persona, component_acc, component_n)
        try:
            await persist_tuned_weights(tuned)
            updated += 1
            persona_results.append({
                "persona": persona,
                "samples": sum(component_n.values()),
                "notes": tuned.notes[:3],
            })
        except Exception as e:
            log.warning("weight_tuner.persist_failed", persona=persona, error=str(e))

    try:
        await audit_repo.write(
            user_id=None, actor="system", action="weight_tuner.cycle",
            target="bot_weights",
            args={"window_days": 60},
            result={
                "updated_personas": updated,
                "personas": persona_results,
                "latency_s": int(time.time() - started),
            },
        )
    except Exception:
        pass

    log.info("weight_tuner.done", updated=updated,
             latency_s=int(time.time() - started))
    return {"updated_personas": updated, "personas": persona_results}
