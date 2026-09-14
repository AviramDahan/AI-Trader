"""Public dashboard and controlled settings routes for the paper stock scanner."""
from fastapi import FastAPI, Header, HTTPException
from pydantic import BaseModel

from scanner_engine import dashboard_payload, set_active_strategy
from services import _get_agent_by_token
from stock_scanner import public_status
from utils import _extract_token


class ExitStrategyRequest(BaseModel):
    strategy: str


def register_scanner_routes(app: FastAPI) -> None:
    @app.get("/api/scanner/dashboard")
    async def scanner_dashboard():
        payload = dashboard_payload()
        payload["activity"] = public_status()
        return payload

    @app.put("/api/scanner/settings/exit-strategy")
    async def update_exit_strategy(data: ExitStrategyRequest, authorization: str = Header(None)):
        agent = _get_agent_by_token(_extract_token(authorization))
        if not agent or agent.get("role") != "admin":
            raise HTTPException(status_code=403, detail="Admin permission required")
        try:
            strategy = set_active_strategy(data.strategy)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {"success": True, "active_strategy": strategy, "applies_to": "new_trades_only"}
