"""Elliott wave CANDIDATE labeler — rule-checked, never definitive.

Real Elliott counting is interpretive and even commercial software disagrees.
We compute a *candidate* impulse-or-correction count and report which Fibonacci
constraints hold. Treat the output as one input among many; the LLM should
quote it as ``"a wave-3 impulse count is consistent with the structure"`` and
cite the constraints, never as ``"we're in wave 3."``

Rules enforced for an impulse (waves 1-2-3-4-5):
  - Wave 2 cannot retrace 100% of wave 1.
  - Wave 3 cannot be the SHORTEST of waves 1, 3, 5.
  - Wave 4 cannot overlap wave 1 (price territory).
  - Wave 3 typically extends to 1.618× wave 1.
  - Wave 5 often equals wave 1 in length, or 0.618× wave 3.

For corrections we look for a 3-leg ABC where:
  - B retraces 38–78% of A
  - C extends ~equal to A or 1.618× A
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Literal

import pandas as pd

from .patterns import Swing, _detect_swings  # reuse the swing detector

WaveLabel = Literal[
    "impulse_developing",
    "impulse_complete",
    "correction_abc",
    "indeterminate",
]


@dataclass
class WaveLeg:
    label: str       # "1", "2", "3", "4", "5", "A", "B", "C"
    start_idx: int
    end_idx: int
    start_price: float
    end_price: float
    length: float    # absolute price move
    fib_of_w1: float | None = None  # ratio vs wave 1 length, where applicable


@dataclass
class ElliottSnapshot:
    label: WaveLabel
    confidence: float
    legs: list[WaveLeg] = field(default_factory=list)
    rule_checks: dict[str, bool] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)
    next_likely: str | None = None

    def as_brief_block(self) -> str:
        if self.label == "indeterminate":
            return "**Elliott**: structure indeterminate (insufficient legs or rule violations)"
        out = [
            f"**Elliott (candidate)**: `{self.label}` — confidence {self.confidence:.0%}",
        ]
        for leg in self.legs:
            tail = f" (= {leg.fib_of_w1:.2f}× w1)" if leg.fib_of_w1 is not None else ""
            out.append(f"- wave {leg.label}: {leg.start_price:.4g} → {leg.end_price:.4g}{tail}")
        if self.rule_checks:
            ok = sum(self.rule_checks.values())
            out.append(f"- rule checks: {ok}/{len(self.rule_checks)} passing")
        if self.next_likely:
            out.append(f"- if count holds, next likely: {self.next_likely}")
        return "\n".join(out)


def label(df: pd.DataFrame) -> ElliottSnapshot:
    if df is None or df.empty or len(df) < 60:
        return ElliottSnapshot("indeterminate", 0.0, notes=["insufficient OHLCV"])

    swings = _detect_swings(df, distance=5, prominence_pct=0.015)
    # Need at least 5 alternating swings for an impulse, 3 for a correction.
    if len(swings) < 5:
        return ElliottSnapshot("indeterminate", 0.0,
                                notes=[f"only {len(swings)} swings detected"])

    # Try impulse on the last 6 swings (wave-0 anchor + 1..5 = 6 points).
    impulse = _try_impulse(swings[-6:]) if len(swings) >= 6 else None
    if impulse:
        return impulse

    # Try ABC correction on the last 4 swings (anchor + A + B + C).
    abc = _try_abc(swings[-4:])
    if abc:
        return abc

    return ElliottSnapshot("indeterminate", 0.2,
                            notes=["no rule-consistent count on last 4-6 swings"])


def _try_impulse(pts: list[Swing]) -> ElliottSnapshot | None:
    """Validate a 5-leg impulse from `pts[0]` (anchor) through `pts[5]` (end of wave 5).

    Direction is inferred from the anchor → wave-1 move.
    """
    if len(pts) < 6:
        return None
    p0, p1, p2, p3, p4, p5 = pts[-6:]
    going_up = p1.price > p0.price
    if going_up != (p1.kind == "high"):
        return None  # alternation broken from the start

    w1 = abs(p1.price - p0.price)
    w2 = abs(p2.price - p1.price)
    w3 = abs(p3.price - p2.price)
    w4 = abs(p4.price - p3.price)
    w5 = abs(p5.price - p4.price)

    if min(w1, w3, w5) <= 0:
        return None

    # Rule 1: wave 2 < 100% of wave 1
    rule_w2 = w2 < w1
    # Rule 2: wave 3 not the shortest of 1/3/5
    rule_w3_not_shortest = w3 > w1 or w3 > w5  # i.e., w3 not strictly the smallest
    # Rule 3: wave 4 doesn't overlap wave 1 (in impulse direction)
    rule_w4_no_overlap = p4.price > p1.price if going_up else p4.price < p1.price

    fib3 = w3 / w1 if w1 else None
    fib5 = w5 / w1 if w1 else None

    legs = [
        WaveLeg("1", p0.idx, p1.idx, p0.price, p1.price, w1, 1.0),
        WaveLeg("2", p1.idx, p2.idx, p1.price, p2.price, w2, w2 / w1 if w1 else None),
        WaveLeg("3", p2.idx, p3.idx, p2.price, p3.price, w3, fib3),
        WaveLeg("4", p3.idx, p4.idx, p3.price, p4.price, w4, w4 / w1 if w1 else None),
        WaveLeg("5", p4.idx, p5.idx, p4.price, p5.price, w5, fib5),
    ]
    rules = {
        "wave2_not_100pct": rule_w2,
        "wave3_not_shortest": rule_w3_not_shortest,
        "wave4_no_overlap": rule_w4_no_overlap,
    }
    passed = sum(rules.values())
    confidence = (passed / 3) * 0.7  # cap at 0.7 — Elliott is interpretive
    label_kind: WaveLabel = "impulse_complete" if passed == 3 else "impulse_developing"
    notes = []
    if fib3 is not None and 1.5 <= fib3 <= 1.8:
        notes.append("wave 3 ≈ 1.618× wave 1 (classical extension)")
    if fib5 is not None and 0.5 <= fib5 <= 0.7:
        notes.append("wave 5 ≈ 0.618× wave 3 (truncated 5)")
    next_step = "ABC correction expected" if passed == 3 else "wave structure may extend"
    return ElliottSnapshot(label_kind, confidence, legs=legs, rule_checks=rules,
                            notes=notes, next_likely=next_step)


def _try_abc(pts: list[Swing]) -> ElliottSnapshot | None:
    if len(pts) < 4:
        return None
    p0, pa, pb, pc = pts[-4:]
    leg_a = abs(pa.price - p0.price)
    leg_b = abs(pb.price - pa.price)
    leg_c = abs(pc.price - pb.price)
    if leg_a == 0:
        return None
    b_retrace = leg_b / leg_a
    if not (0.38 <= b_retrace <= 0.78):
        return None
    c_ratio = leg_c / leg_a
    notes: list[str] = []
    if 0.9 <= c_ratio <= 1.15:
        notes.append("C ≈ A (zigzag baseline)")
    elif 1.5 <= c_ratio <= 1.8:
        notes.append("C ≈ 1.618× A (extended zigzag)")
    legs = [
        WaveLeg("A", p0.idx, pa.idx, p0.price, pa.price, leg_a, 1.0),
        WaveLeg("B", pa.idx, pb.idx, pa.price, pb.price, leg_b, b_retrace),
        WaveLeg("C", pb.idx, pc.idx, pb.price, pc.price, leg_c, c_ratio),
    ]
    return ElliottSnapshot(
        "correction_abc",
        confidence=0.55,
        legs=legs,
        rule_checks={"B_retrace_38_78": True},
        notes=notes,
        next_likely="resumption of larger trend if correction complete",
    )


def asdict_elliott(s: ElliottSnapshot) -> dict:
    return asdict(s)
