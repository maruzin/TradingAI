"""Portfolio analysis endpoint.

POST /api/portfolio/analyze with a holdings array → PortfolioRisk snapshot.

Phase 1 takes explicit holdings (the user pastes their balances). Phase 2
will pull from the encrypted exchange_keys + Vault and recompute on cron.
"""
from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from ..auth import CurrentUser
from ..deps import get_current_user
from ..repositories import audit as audit_repo
from ..services.portfolio import Holding, compute_risk

router = APIRouter()


class HoldingIn(BaseModel):
    symbol: str = Field(min_length=1, max_length=20)
    quantity: float = Field(gt=0)
    cost_basis_usd: float | None = None


class AnalyzeRequest(BaseModel):
    holdings: list[HoldingIn] = Field(default_factory=list, max_length=100)


@router.post("/analyze")
async def analyze(
    body: AnalyzeRequest,
    user: Annotated[CurrentUser, Depends(get_current_user)],
) -> dict:
    holdings = [
        Holding(symbol=h.symbol, quantity=h.quantity, cost_basis_usd=h.cost_basis_usd)
        for h in body.holdings
    ]
    risk = await compute_risk(holdings)
    await audit_repo.write(
        user_id=user.id, actor="user", action="portfolio.analyze",
        target=None,
        args={"n_holdings": len(holdings)},
        result={"top_pct": risk.top_position_pct,
                "btc_beta": risk.btc_beta,
                "avg_corr": risk.avg_correlation_to_btc},
    )
    return risk.as_dict()
