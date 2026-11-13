"""Public dashboard and controlled settings routes for the paper stock scanner."""
from fastapi import FastAPI, Header, HTTPException, Response, Query
from pydantic import BaseModel, ConfigDict, StrictBool, conint

from database import get_db_connection
from position_charts import position_chart_bytes, signal_chart_bytes
from scanner_engine import dashboard_payload, quotes_payload, set_active_strategy, set_news_watchlist
from services import _get_agent_by_token
from stock_scanner import public_status
from utils import _extract_token


class ExitStrategyRequest(BaseModel):
    strategy: str


class NewsWatchlistRequest(BaseModel):
    ticker: str
    company: str | None = None


class EntryEmergencyRequest(BaseModel):
    paused: StrictBool
    expected_revision: conint(strict=True, ge=0)

    model_config = ConfigDict(extra='forbid')


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
    @app.get('/api/scanner/trump-media/{token}')
    def trump_truth_asset(token: str):
        from trump_truth_public import asset_payload
        try:
            data, mime = asset_payload(token)
        except Exception:
            raise HTTPException(404, 'trump_media_unavailable') from None
        return Response(content=data, media_type=mime, headers={'Cache-Control':'no-store',
            'X-Content-Type-Options':'nosniff','Content-Security-Policy':"default-src 'none'; sandbox"})

    @app.get('/api/scanner/trump-posts')
    def trump_truth_archive(response: Response, limit: int = Query(20, ge=1, le=20),
                            before: str | None = Query(None, pattern=r'^(?:[1-9][0-9]{15,19}|tg:1462338131:[1-9][0-9]{0,9})$')):
        response.headers['Cache-Control'] = 'no-store'
        from trump_truth_public import payload
        try:
            return payload(limit=limit, before=before)
        except ValueError:
            raise HTTPException(422, 'trump_archive_page_invalid') from None
        except Exception:
            raise HTTPException(503, 'trump_archive_unavailable') from None

    @app.get('/api/scanner/strategy-performance')
    def strategy_performance(response: Response, hours: int = Query(48, ge=24, le=168)):
        # The existing community statistics are public READ ONLY. No control,
        # raw contract, private identifiers or currency account data is exposed.
        response.headers['Cache-Control'] = 'no-store'
        if hours not in (24, 48, 168):
            raise HTTPException(422, 'Supported windows: 24, 48, 168 hours')
        from strategy_performance import payload
        try:
            return payload(hours)
        except Exception:
            raise HTTPException(503, 'strategy_performance_unavailable') from None

    @app.get('/api/scanner/settings/entry-emergency')
    def entry_emergency_status(response: Response, authorization: str = Header(None)):
        _require_scanner_manager(authorization)
        response.headers['Cache-Control'] = 'no-store, private'
        response.headers['Vary'] = 'Authorization'
        from entry_emergency import status
        with get_db_connection() as conn:
            return status(conn.cursor())

    @app.put('/api/scanner/settings/entry-emergency')
    def entry_emergency_change(data: EntryEmergencyRequest, response: Response,
                               authorization: str = Header(None)):
        # Private logs membership grants observation only, never this write.
        _require_scanner_manager(authorization)
        response.headers['Cache-Control'] = 'no-store, private'
        response.headers['Vary'] = 'Authorization'
        from entry_emergency import set_paused
        try:
            result = set_paused(data.paused, data.expected_revision)
        except ValueError as exc:
            code = str(exc)
            if code in {'entry_emergency_revision_conflict', 'entry_emergency_history_capacity'}:
                raise HTTPException(409, code) from None
            if code == 'entry_emergency_invalid_request':
                raise HTTPException(400, code) from None
            raise HTTPException(503, 'entry_emergency_control_invalid') from None
        except Exception:
            raise HTTPException(503, 'entry_emergency_control_unavailable') from None
        return {'version': result['version'], 'paused': result['paused'],
                'revision': result['revision'], 'exits_continue': True}

    @app.get('/api/admin/system-status')
    def admin_system_status(response: Response, authorization: str = Header(None),
                            x_telegram_init_data: str = Header(None)):
        response.headers['Cache-Control'] = 'no-store, private'
        response.headers['Vary'] = 'Authorization, X-Telegram-Init-Data'
        if x_telegram_init_data:
            from telegram_admin_access import require_logs_member
            require_logs_member(x_telegram_init_data)
        else:
            _require_scanner_manager(authorization)
        from admin_system_status import payload
        try:
            return payload()
        except Exception:
            raise HTTPException(503, 'system_observation_unavailable') from None

    @app.get("/api/scanner/sec-intelligence/status")
    def sec_intelligence_status(authorization: str = Header(None)):
        _require_scanner_manager(authorization)
        from sec_intelligence import coverage_status
        return coverage_status()

    @app.get("/api/scanner/research")
    def scanner_research(hours: int = Query(48, ge=24, le=168)):
        from signal_research import payload
        if hours not in (24, 48, 168):
            raise HTTPException(status_code=422, detail="Supported windows: 24, 48, 168 hours")
        return payload(hours)

    @app.get("/api/scanner/dashboard")
    def scanner_dashboard():
        # These synchronous DB projections belong in FastAPI's bounded worker
        # pool, not the event loop used by health and concurrent mobile reads.
        payload = dashboard_payload()
        payload["activity"] = public_status()
        return payload

    @app.get("/api/scanner/quotes")
    def scanner_quotes():
        return quotes_payload()

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
