"""Public dashboard and controlled settings routes for the paper stock scanner."""
from fastapi import FastAPI, Header, HTTPException, Response
from pydantic import BaseModel

from database import get_db_connection
from position_charts import position_chart_bytes, signal_chart_bytes
from scanner_engine import dashboard_payload, set_active_strategy, set_news_watchlist
from services import _get_agent_by_token
from stock_scanner import public_status
from utils import _extract_token


class ExitStrategyRequest(BaseModel):
    strategy: str


class NewsWatchlistRequest(BaseModel):
    ticker: str
    company: str | None = None


def _require_scanner_manager(authorization: str):
    agent = _get_agent_by_token(_extract_token(authorization))
    if not agent:
        raise HTTPException(status_code=401, detail="Authentication required")
    if agent.get("role") == "admin":
        return agent
    conn = get_db_connection()
    try:
        allowed = conn.execute(
            "SELECT 1 FROM scanner_operators WHERE agent_id = ?",
            (agent["id"],),
        ).fetchone()
    finally:
        conn.close()
    if not allowed:
        raise HTTPException(status_code=403, detail="Scanner manager permission required")
    return agent


def register_scanner_routes(app: FastAPI) -> None:
    @app.get("/api/scanner/dashboard")
    async def scanner_dashboard():
        payload = dashboard_payload()
        payload["activity"] = public_status()
        return payload

    @app.get("/api/scanner/trades/{trade_id}/chart")
    def scanner_trade_chart(trade_id: int):
        try:
            png = position_chart_bytes(trade_id)
        except LookupError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except Exception as exc:
            raise HTTPException(status_code=503, detail="Position chart is temporarily unavailable") from exc
        return Response(content=png, media_type="image/png", headers={"Cache-Control": "public, max-age=300"})

    @app.get("/api/scanner/signals/{signal_id}/chart")
    def scanner_signal_chart(signal_id: int):
        try:
            png = signal_chart_bytes(signal_id)
        except LookupError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except Exception as exc:
            raise HTTPException(status_code=503, detail="Signal chart is temporarily unavailable") from exc
        return Response(content=png, media_type="image/png", headers={"Cache-Control": "public, max-age=300"})

    @app.put("/api/scanner/settings/exit-strategy")
    async def update_exit_strategy(data: ExitStrategyRequest, authorization: str = Header(None)):
        _require_scanner_manager(authorization)
        try:
            strategy = set_active_strategy(data.strategy)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {"success": True, "active_strategy": strategy, "applies_to": "new_trades_only"}

    @app.post("/api/scanner/news-watchlist")
    async def add_news_watchlist(data: NewsWatchlistRequest, authorization: str = Header(None)):
        _require_scanner_manager(authorization)
        try:
            row = set_news_watchlist(data.ticker, data.company, True)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {"success": True, "item": row, "paper_trade_created": False}

    @app.delete("/api/scanner/news-watchlist/{ticker}")
    async def remove_news_watchlist(ticker: str, authorization: str = Header(None)):
        _require_scanner_manager(authorization)
        try:
            row = set_news_watchlist(ticker, enabled=False)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {"success": True, "item": row}
