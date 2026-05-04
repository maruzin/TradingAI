"""Weight tuner — closes the self-improvement loop.

Once we have enough graded ai_calls (real outcomes from the
backtest_evaluator worker), this module measures per-component accuracy
and proposes new weights for the bot decider. The tuned weights get
written to ``system_flags['bot_weights']`` and read at the start of every
``fuse()`` call.

We deliberately don't update weights aggressively. The procedure:
  1. Look at the last N graded calls per component (default 60 days).
  2. For each component, compute hit rate (correct / evaluated).
  3. Map hit rate → relative weight adjustment, capped at ±20% per cycle.
  4. Renormalize so weights still sum to ~1.0.

If the evaluator hasn't graded enough calls yet (< MIN_SAMPLE per
component), we keep the defaults. This protects against early-life
overreaction to noise.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from .. import db
from ..logging_setup import get_logger
from .bot_decider import PERSONA_WEIGHTS

log = get_logger("weight_tuner")

# Minimum graded samples per component before its weight is updated.
MIN_SAMPLE = 30
# Maximum per-cycle relative adjustment, ±.
MAX_ADJUST = 0.20


@dataclass
class TunedWeights:
    """The weight set proposed by the tuner for one persona, plus diagnostics."""
    persona: str
    base_weights: dict[str, float]
    component_accuracy: dict[str, float]
    component_n: dict[str, int]
    new_weights: dict[str, float]
    notes: list[str]

    def as_dict(self) -> dict[str, Any]:
        return {
            "persona": self.persona,
            "base_weights": self.base_weights,
            "component_accuracy": self.component_accuracy,
            "component_n": self.component_n,
            "new_weights": self.new_weights,
            "notes": self.notes,
        }


async def measure_component_accuracy(*, since_days: int = 60) -> dict[str, tuple[int, float]]:
    """Read graded calls and compute per-component hit rate.

    The bot stores its `inputs` jsonb on each `bot_decisions` row, but we
    grade `ai_calls` rows. Until we have a full attribution chain, we
    approximate with a single overall accuracy applied uniformly. When
    bot_decisions get evaluated (next phase of evaluator work), this
    function gets per-component numbers.
    """
    rows = await db.fetch(
        """
        select call_type,
               count(*) filter (where outcome is not null) as n,
               avg((outcome = 'correct')::int) filter (where outcome is not null) as acc
          from ai_calls
         where created_at > now() - ($1 * interval '1 day')
         group by call_type
        """,
        since_days,
    )
    out: dict[str, tuple[int, float]] = {}
    for r in rows:
        n = int(r["n"] or 0)
        acc = float(r["acc"] or 0.0)
        out[r["call_type"]] = (n, acc)
    return out


def propose_weights(
    persona: str,
    component_accuracy: dict[str, float],
    component_n: dict[str, int],
) -> TunedWeights:
    """Apply the rule: weight × (1 + (acc − 0.5) × MAX_ADJUST × 2). A 60%-
    accurate component gets +4% weight; a 40% one loses 4%; a 70% one gets
    +8%. Components with insufficient samples keep their base weight.
    """
    base = PERSONA_WEIGHTS.get(persona, PERSONA_WEIGHTS["balanced"]).copy()
    new_weights: dict[str, float] = {}
    notes: list[str] = []
    for component, weight in base.items():
        n = component_n.get(component, 0)
        if n < MIN_SAMPLE:
            new_weights[component] = weight
            continue
        acc = component_accuracy.get(component, 0.5)
        # Map accuracy delta to weight scale, capped at ±MAX_ADJUST.
        delta = max(-MAX_ADJUST, min(MAX_ADJUST, (acc - 0.5) * 2 * MAX_ADJUST))
        new_w = max(0.0, weight * (1 + delta))
        new_weights[component] = round(new_w, 4)
        notes.append(
            f"{component}: n={n} acc={acc:.2f} → weight {weight:.3f} → {new_w:.3f}"
        )

    # Renormalize so total stays ~1.0
    total = sum(new_weights.values())
    if total > 0:
        scale = 1.0 / total
        new_weights = {k: round(v * scale, 4) for k, v in new_weights.items()}

    return TunedWeights(
        persona=persona,
        base_weights=base,
        component_accuracy=component_accuracy,
        component_n=component_n,
        new_weights=new_weights,
        notes=notes or [f"Insufficient samples — kept base {persona} weights"],
    )


async def persist_tuned_weights(tuned: TunedWeights) -> None:
    """Write the tuned weights to system_flags so bot_decider can read them."""
    flag_key = f"bot_weights_{tuned.persona}"
    await db.execute(
        """
        insert into system_flags (key, value)
        values ($1, $2::jsonb)
        on conflict (key) do update
            set value = excluded.value, updated_at = now()
        """,
        flag_key, json.dumps(tuned.as_dict(), default=str),
    )


async def load_tuned_weights(persona: str) -> dict[str, float] | None:
    """Read the most recent tuned weights for `persona`, or None if absent."""
    row = await db.fetchrow(
        "select value from system_flags where key = $1",
        f"bot_weights_{persona}",
    )
    if not row:
        return None
    try:
        payload = row["value"] if isinstance(row["value"], dict) else json.loads(row["value"])
        return payload.get("new_weights")
    except Exception:
        return None
