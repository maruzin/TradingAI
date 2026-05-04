"""Theses API."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from ..agents.thesis_evaluator import ThesisEvaluatorAgent
from ..auth import CurrentUser
from ..deps import get_current_user
from ..repositories import theses as theses_repo
from ..services.coingecko import CoinGeckoClient
from ._errors import safe_detail

router = APIRouter()


class CreateThesisRequest(BaseModel):
    token: str = Field(..., description="ticker, CG id, or contract address")
    stance: str = Field(..., pattern="^(bullish|bearish)$")
    horizon: str = Field(..., pattern="^(swing|position|long)$")
    core_thesis: str = Field(..., min_length=1, max_length=4000)
    key_assumptions: list[str] = Field(..., min_length=1, max_length=20)
    invalidation: list[str] = Field(..., min_length=1, max_length=20,
                                     description="≥1 invalidation criterion required")
    review_cadence: str = Field("weekly", pattern="^(daily|weekly|monthly)$")


@router.get("")
async def list_my_theses(
    user: CurrentUser = Depends(get_current_user),
    status: str | None = None,
) -> dict:
    return {"theses": await theses_repo.list_for_user(user.id, status=status)}


@router.post("")
async def create(
    body: CreateThesisRequest,
    user: CurrentUser = Depends(get_current_user),
) -> dict:
    cg = CoinGeckoClient()
    try:
        snap = await cg.snapshot(body.token)
    except ValueError as e:
        raise HTTPException(
            404, detail=safe_detail(e, f"token {body.token} not found"),
        ) from e
    finally:
        await cg.close()

    return await theses_repo.create(
        user.id,
        token_symbol=snap.symbol, token_name=snap.name,
        chain=snap.chain, coingecko_id=snap.coingecko_id,
        address=snap.contract_address,
        stance=body.stance, horizon=body.horizon,
        core_thesis=body.core_thesis,
        key_assumptions=body.key_assumptions,
        invalidation=body.invalidation,
        review_cadence=body.review_cadence,
    )


@router.get("/{thesis_id}")
async def get_one(
    thesis_id: str, user: CurrentUser = Depends(get_current_user),
) -> dict:
    th = await theses_repo.get(user.id, thesis_id)
    if not th:
        raise HTTPException(404, detail="not found")
    th["latest_evaluation"] = await theses_repo.latest_evaluation(thesis_id)
    return th


@router.post("/{thesis_id}/evaluate")
async def evaluate_now(
    thesis_id: str, user: CurrentUser = Depends(get_current_user),
) -> dict:
    th = await theses_repo.get(user.id, thesis_id)
    if not th:
        raise HTTPException(404, detail="not found")
    agent = ThesisEvaluatorAgent()
    try:
        ev = await agent.evaluate(th)
    finally:
        await agent.close()
    eval_id = await theses_repo.insert_evaluation(
        thesis_id=thesis_id,
        overall=ev.get("overall", "drifting"),
        per_assumption=ev.get("per_assumption", []),
        per_invalidation=ev.get("per_invalidation", []),
        notes=ev.get("notes"),
    )
    return {"evaluation_id": eval_id, **ev}


@router.post("/{thesis_id}/close")
async def close_thesis(
    thesis_id: str, status: str = "closed",
    user: CurrentUser = Depends(get_current_user),
) -> dict:
    if status not in ("closed", "invalidated"):
        raise HTTPException(400, detail="status must be closed or invalidated")
    if not await theses_repo.close(user.id, thesis_id, status):
        raise HTTPException(404, detail="not found")
    return {"ok": True}
