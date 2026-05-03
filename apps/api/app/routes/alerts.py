"""Alerts API — rules CRUD + inbox."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from ..auth import CurrentUser
from ..deps import get_current_user
from ..repositories import alerts as alerts_repo

router = APIRouter()


class CreateRuleRequest(BaseModel):
    rule_type: str = Field(..., description="price_threshold, pct_move, news_keyword, thesis_drift, ...")
    config: dict = Field(...)
    token_id: str | None = None
    severity: str = Field("info", pattern="^(info|warn|critical)$")


@router.get("/rules")
async def list_rules(user: CurrentUser = Depends(get_current_user)) -> dict:
    return {"rules": await alerts_repo.list_rules(user.id)}


@router.post("/rules")
async def create_rule(
    body: CreateRuleRequest, user: CurrentUser = Depends(get_current_user),
) -> dict:
    return await alerts_repo.create_rule(
        user.id, rule_type=body.rule_type, config=body.config,
        token_id=body.token_id, severity=body.severity,
    )


@router.delete("/rules/{rule_id}")
async def delete_rule(
    rule_id: str, user: CurrentUser = Depends(get_current_user),
) -> dict:
    if not await alerts_repo.delete_rule(user.id, rule_id):
        raise HTTPException(404, detail="rule not found")
    return {"ok": True}


@router.patch("/rules/{rule_id}/enabled")
async def toggle_rule(
    rule_id: str, enabled: bool,
    user: CurrentUser = Depends(get_current_user),
) -> dict:
    if not await alerts_repo.set_rule_enabled(user.id, rule_id, enabled):
        raise HTTPException(404, detail="rule not found")
    return {"ok": True}


@router.get("")
async def list_alerts(
    user: CurrentUser = Depends(get_current_user),
    limit: int = 100,
) -> dict:
    return {"alerts": await alerts_repo.list_for_user(user.id, limit=limit)}


@router.post("/{alert_id}/read")
async def mark_read(
    alert_id: str, user: CurrentUser = Depends(get_current_user),
) -> dict:
    if not await alerts_repo.mark_read(user.id, alert_id):
        raise HTTPException(404, detail="not found")
    return {"ok": True}
