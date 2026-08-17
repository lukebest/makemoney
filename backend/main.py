"""FastAPI entry point for the A-share trading-discipline backend."""

from __future__ import annotations

import os
import re
import sqlite3
import threading
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Any, Callable, Literal, Mapping

from fastapi import FastAPI, HTTPException, Query, Request, status
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from .ai import AIService
from .db import Database, utc_now
from .market import CHINA_TZ, MarketService, is_hk_code, normalize_code, session_status
from .signals import review_statistics, stop_loss_status


class SettingsUpdate(BaseModel):
    total_capital: float = Field(gt=0)
    max_position_ratio: float | None = Field(default=None, gt=0, le=1)
    max_invested_ratio: float | None = Field(default=None, gt=0, le=1)


class PositionCreate(BaseModel):
    code: str
    name: str = Field(min_length=1, max_length=80)
    quantity: int = Field(gt=0)
    avg_price: float = Field(gt=0)
    stop_loss: float = Field(gt=0)
    tier: int = Field(default=1, ge=1, le=3)
    thesis: str = Field(default="", max_length=2000)


class PositionUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=80)
    quantity: int | None = Field(default=None, gt=0)
    avg_price: float | None = Field(default=None, gt=0)
    stop_loss: float | None = Field(default=None, gt=0)
    tier: int | None = Field(default=None, ge=1, le=3)
    thesis: str | None = Field(default=None, max_length=2000)


class TradeCreate(BaseModel):
    code: str
    name: str | None = Field(default=None, max_length=80)
    side: Literal["buy", "sell"]
    quantity: int = Field(gt=0)
    price: float | None = Field(default=None, gt=0)
    logic: str = Field(default="", max_length=2000)
    funds_confirmed: bool = False
    space_confirmed: bool = False
    stop_loss: float | None = Field(default=None, gt=0)
    tier: int = Field(default=1, ge=1, le=3)
    note: str = Field(default="", max_length=2000)


class TradeReviewRequest(BaseModel):
    code: str
    price: float | None = Field(default=None, gt=0)
    quantity: int | None = Field(default=None, gt=0)
    stop_loss: float | None = Field(default=None, gt=0)
    logic: str = Field(default="", max_length=2000)
    funds_answer: str = Field(default="", max_length=2000)
    space_answer: str = Field(default="", max_length=2000)


class JournalCreate(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    content: str = Field(min_length=1, max_length=20000)
    mood: str = Field(default="", max_length=80)
    tags: list[str] = Field(default_factory=list)
    trade_id: int | None = Field(default=None, gt=0)


class JournalUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=200)
    content: str | None = Field(default=None, min_length=1, max_length=20000)
    mood: str | None = Field(default=None, max_length=80)
    tags: list[str] | None = None
    trade_id: int | None = Field(default=None, gt=0)


def create_app(
    db_path: str | os.PathLike[str] | None = None,
    market_service: MarketService | None = None,
    ai_service: AIService | None = None,
) -> FastAPI:
    database = Database(db_path)
    market = market_service or MarketService()
    ai = ai_service or AIService()

    @asynccontextmanager
    async def lifespan(application: FastAPI):
        database.initialize()
        application.state.db = database
        application.state.market = market
        application.state.ai = ai

        def warmup() -> None:
            try:
                overview = market.overview()
                if overview.get("source") == "akshare":
                    database.save_snapshot("overview", overview)
                mainline = market.mainline()
                if mainline.get("source") == "akshare":
                    database.save_snapshot("mainline", mainline)
                preferred = market.preferred_stocks()
                if preferred.get("source") == "akshare":
                    database.save_snapshot("preferred", preferred)
            except Exception:
                pass

        threading.Thread(target=warmup, name="market-warmup", daemon=True).start()
        yield
        market.cache.clear()

    application = FastAPI(
        title="A股散户赚钱系统 API",
        version="1.0.0",
        description="交易纪律、仓位管理和复盘 API；市场数据仅供研究，不构成投资建议。",
        lifespan=lifespan,
    )
    origins = [
        item.strip()
        for item in os.getenv(
            "CORS_ORIGINS",
            "http://localhost:5173,http://127.0.0.1:5173",
        ).split(",")
        if item.strip()
    ]
    application.add_middleware(
        CORSMiddleware,
        allow_origins=origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @application.get("/health", tags=["system"])
    @application.get("/api/health", tags=["system"])
    def health(request: Request) -> dict[str, Any]:
        db = _db(request)
        healthy = db.healthcheck()
        if not healthy:
            raise HTTPException(status_code=503, detail="database unavailable")
        return {
            "status": "ok",
            "database": "ok",
            "market_data": "akshare_with_sample_fallback",
        }

    @application.get("/api/today", tags=["system"])
    def today_briefing(request: Request) -> dict[str, Any]:
        db = _db(request)
        session = session_status()
        screen = db.get_close_screen(for_date=session["for_date"]) or db.get_close_screen()
        positions = db.list_positions()
        alerts: list[dict[str, Any]] = []
        quotes, _ = _position_quotes(request, [row["code"] for row in positions])
        for row in positions:
            quote = quotes.get(row["code"]) or {}
            price = float(quote.get("price") or 0)
            if not price:
                continue
            status = stop_loss_status(price, float(row["stop_loss"]))
            if status["triggered"]:
                alerts.append(
                    {
                        "code": row["code"],
                        "name": row["name"],
                        "live_price": price,
                        "stop_loss": row["stop_loss"],
                        "message": "；".join(status["reasons"]),
                    }
                )
        picks = list((screen or {}).get("items") or [])[:5]
        quotes = _quotes_if_warm(request, [str(item.get("code")) for item in picks])
        tracked = []
        for item in picks:
            quote = quotes.get(str(item.get("code"))) or {}
            tracked.append(
                {
                    **item,
                    "live_price": quote.get("price"),
                    "live_change_pct": quote.get("change_pct"),
                }
            )
        return {
            "session": session,
            "close_screen": {
                "as_of_date": (screen or {}).get("as_of_date"),
                "for_date": (screen or {}).get("for_date"),
                "match_count": (screen or {}).get("match_count", len(tracked)),
                "needs_run": _close_screen_needs_run(session, screen),
                "items": tracked,
                "job": _close_job(request),
            },
            "stops": alerts,
            "position_count": len(positions),
            "discipline": _today_discipline(db, session),
            "has_journal": _has_journal_for_session(db, session),
        }

    @application.get("/api/market/overview", tags=["market"])
    def market_overview(request: Request) -> dict[str, Any]:
        return _fresh_or_snapshot(
            _db(request),
            _market(request),
            "market:overview",
            "overview",
            _market(request).overview,
        )

    @application.get("/api/market/mainline", tags=["market"])
    def market_mainline(request: Request) -> dict[str, Any]:
        return _fresh_or_snapshot(
            _db(request),
            _market(request),
            "market:mainline",
            "mainline",
            _market(request).mainline,
        )

    @application.get("/api/market/preferred", tags=["market"])
    def preferred_stocks(
        request: Request,
        limit: int = Query(default=8, ge=1, le=20),
        candidates: int = Query(default=12, ge=1, le=30),
    ) -> dict[str, Any]:
        count = max(limit, candidates)
        return _fresh_or_snapshot(
            _db(request),
            _market(request),
            f"market:preferred:{limit}:{count}",
            "preferred",
            lambda: _market(request).preferred_stocks(limit, count),
        )

    @application.get("/api/market/preferred/close-screen", tags=["market"])
    def get_close_screen(
        request: Request,
        for_date: str | None = Query(default=None),
    ) -> dict[str, Any]:
        saved = _db(request).get_close_screen(for_date=for_date)
        if saved is None:
            saved = {
                "items": [],
                "match_count": 0,
                "analyzed_count": 0,
                "source": "empty",
                "as_of_date": None,
                "for_date": for_date,
                "updated_at": None,
            }
        return _with_close_job(
            request,
            {**saved, "needs_run": _close_screen_needs_run(session_status(), saved)},
        )

    @application.post("/api/market/preferred/close-screen", tags=["market"])
    def run_close_screen(
        request: Request,
        max_candidates: int | None = Query(default=None, ge=10, le=2000),
    ) -> dict[str, Any]:
        saved = _db(request).get_close_screen() or {
            "items": [],
            "match_count": 0,
            "analyzed_count": 0,
            "source": "empty",
        }
        with _CLOSE_JOB_LOCK:
            if _close_job(request).get("status") == "running":
                return _with_close_job(request, saved)
            started = utc_now()
            request.app.state.close_screen_job = {
                "status": "running",
                "error": None,
                "started_at": started,
            }

        def work() -> None:
            try:
                def on_progress(stats: dict[str, int]) -> None:
                    request.app.state.close_screen_job = {
                        "status": "running",
                        "error": None,
                        "started_at": started,
                        "checked": int(stats.get("checked") or 0),
                        "total": int(stats.get("total") or 0),
                        "matches": int(stats.get("matches") or 0),
                    }

                result = _market(request).close_screen(
                    max_candidates, on_progress=on_progress
                )
                if result.get("source") == "sample":
                    raise RuntimeError("实时行情暂不可用，无法生成收盘精选")
                if result.get("fallback_reason") and not result.get("universe_count"):
                    raise RuntimeError(str(result["fallback_reason"]))
                if not result.get("as_of_date") or not result.get("for_date"):
                    raise RuntimeError("无法确定交易日")
                _db(request).save_close_screen(result)
                last = _close_job(request)
                request.app.state.close_screen_job = {
                    "status": "done",
                    "error": None,
                    "started_at": started,
                    "finished_at": utc_now(),
                    "checked": last.get("checked", result.get("analyzed_count")),
                    "total": last.get("total", result.get("analyzed_count")),
                    "matches": last.get("matches", result.get("match_count")),
                }
            except Exception as exc:
                last = _close_job(request)
                request.app.state.close_screen_job = {
                    "status": "error",
                    "error": str(exc),
                    "started_at": started,
                    "finished_at": utc_now(),
                    "checked": last.get("checked"),
                    "total": last.get("total"),
                    "matches": last.get("matches"),
                }

        threading.Thread(target=work, name="close-screen", daemon=True).start()
        return _with_close_job(request, saved)

    @application.get("/api/stocks/{code}", tags=["market"])
    @application.get("/api/market/stocks/{code}/daily", tags=["market"])
    def stock_daily(
        code: str,
        request: Request,
        days: int = Query(default=120, ge=60, le=500),
    ) -> dict[str, Any]:
        try:
            normalized = _valid_code(code)
            return _fresh_or_snapshot(
                _db(request),
                _market(request),
                f"daily:{normalized}:{days}",
                f"stock:{normalized}:{days}",
                lambda: _market(request).stock_daily(normalized, days),
            )
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @application.get("/api/market/quotes", tags=["market"])
    def market_quotes(codes: str, request: Request) -> dict[str, Any]:
        requested = [_valid_code(code) for code in codes.split(",") if code.strip()]
        if not requested or len(requested) > 100:
            raise HTTPException(status_code=422, detail="provide 1 to 100 stock codes")
        quotes = _market(request).quotes(requested)
        return {"items": [quotes[code] for code in requested]}

    @application.get("/api/ai/status", tags=["ai"])
    def ai_status(request: Request) -> dict[str, Any]:
        return _ai(request).status()

    @application.post("/api/ai/interpret/{code}", tags=["ai"])
    def ai_interpret(code: str, request: Request) -> dict[str, Any]:
        ai_service = _require_ai(request)
        try:
            analysis = _market(request).stock_daily(_valid_code(code), 120)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        if analysis["source"] == "sample":
            raise HTTPException(
                status_code=409, detail="行情为演示数据，AI 解读已禁用以免误导"
            )
        try:
            return ai_service.interpret_stock(analysis)
        except RuntimeError as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc

    @application.post("/api/ai/review-trade", tags=["ai"])
    def ai_review_trade(payload: TradeReviewRequest, request: Request) -> dict[str, Any]:
        ai_service = _require_ai(request)
        code = _valid_code(payload.code)
        try:
            analysis = _market(request).stock_daily(code, 120)
            if analysis["source"] == "sample":
                analysis = None
        except Exception:
            analysis = None
        db = _db(request)
        settings = db.get_settings()
        snapshot = db.portfolio_snapshot()
        portfolio = {
            "总资金": settings["total_capital"],
            "已用资金": snapshot["invested_cost"],
            "可用资金": snapshot["available_funds"],
        }
        trade = _dump(payload)
        trade["code"] = code
        try:
            return ai_service.review_trade(trade, analysis, portfolio)
        except RuntimeError as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc

    @application.post("/api/ai/review-report", tags=["ai"])
    def ai_review_report(request: Request) -> dict[str, Any]:
        ai_service = _require_ai(request)
        db = _db(request)
        trades = db.list_trades(limit=100000)
        stats = review_statistics(trades)
        try:
            return ai_service.review_report(stats, trades)
        except RuntimeError as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc

    @application.get("/api/settings", tags=["settings"])
    def get_settings(request: Request) -> dict[str, Any]:
        return _db(request).get_settings()

    @application.put("/api/settings", tags=["settings"])
    def update_settings(payload: SettingsUpdate, request: Request) -> dict[str, Any]:
        db = _db(request)
        values = _dump(payload, exclude_none=True)
        invested = db.portfolio_snapshot()["invested_cost"]
        if payload.total_capital < invested:
            raise HTTPException(
                status_code=409,
                detail="total capital cannot be below current invested cost",
            )
        return db.set_settings(values)

    @application.get("/api/positions", tags=["positions"])
    @application.get("/api/positions/status", tags=["positions"])
    def positions_status(request: Request) -> dict[str, Any]:
        db = _db(request)
        market = _market(request)
        positions = db.list_positions()
        codes = [row["code"] for row in positions]
        quotes, stale = _position_quotes(request, codes)
        if any(code not in quotes for code in codes):
            quotes = market.quotes(codes)
            if quotes:
                db.save_snapshot("position-quotes", quotes)
            stale = False
        settings = db.get_settings()
        total_capital = float(settings["total_capital"])
        items = []
        total_market_value = 0.0
        total_unrealized = 0.0
        alerts = []
        for row in positions:
            quote = quotes.get(row["code"]) or {}
            price = float(quote.get("price") or row["avg_price"])
            fx_rate = market.cny_rate(row["code"])
            market_value = price * int(row["quantity"]) * fx_rate
            unrealized = (
                (price - float(row["avg_price"])) * int(row["quantity"]) * fx_rate
            )
            cost = float(row["avg_price"]) * int(row["quantity"]) * fx_rate
            stop_status = stop_loss_status(price, float(row["stop_loss"]))
            stop_triggered = stop_status["triggered"]
            item = {
                **row,
                "live_price": price,
                "price_source": quote.get("source") or "cost",
                "market": quote.get("market", row.get("market", "A")),
                "currency": quote.get("currency", row.get("currency", "CNY")),
                "fx_rate": fx_rate,
                "change_pct": float(quote.get("change_pct") or 0),
                "market_value": round(market_value, 2),
                "unrealized_pnl": round(unrealized, 2),
                "unrealized_pnl_pct": round(unrealized / cost * 100, 2) if cost else 0.0,
                "allocation_pct": round(market_value / total_capital * 100, 2),
                "stop_triggered": stop_triggered,
                "stop_status": stop_status,
            }
            items.append(item)
            total_market_value += market_value
            total_unrealized += unrealized
            if stop_triggered:
                alerts.append(
                    {
                        "code": row["code"],
                        "name": row["name"],
                        "live_price": price,
                        "stop_loss": row["stop_loss"],
                        "message": "；".join(stop_status["reasons"]),
                    }
                )
        return {
            "items": items,
            "alerts": alerts,
            "stale": stale,
            "summary": {
                **db.portfolio_snapshot(),
                "market_value": round(total_market_value, 2),
                "unrealized_pnl": round(total_unrealized, 2),
                "position_ratio": round(total_market_value / total_capital, 4),
            },
        }

    @application.post(
        "/api/positions", tags=["positions"], status_code=status.HTTP_201_CREATED
    )
    def create_position(payload: PositionCreate, request: Request) -> dict[str, Any]:
        db = _db(request)
        values = _dump(payload)
        values["code"] = _valid_code(payload.code)
        hk = is_hk_code(values["code"])
        values["market"] = "HK" if hk else "A"
        values["currency"] = "HKD" if hk else "CNY"
        values["fx_rate"] = _market(request).cny_rate(values["code"])
        if payload.stop_loss >= payload.avg_price:
            raise HTTPException(status_code=422, detail="stop loss must be below cost price")
        settings = db.get_settings()
        current = db.portfolio_snapshot()
        cost = payload.quantity * payload.avg_price * values["fx_rate"]
        single_limit = float(settings["total_capital"]) * float(
            settings["max_position_ratio"]
        )
        invested_limit = float(settings["total_capital"]) * float(
            settings["max_invested_ratio"]
        )
        if cost > single_limit + 1e-6:
            raise HTTPException(
                status_code=409,
                detail=(
                    f"持仓成本 ¥{cost:,.2f} 超过单股仓位上限 ¥{single_limit:,.2f}"
                    f"（总资金的 {float(settings['max_position_ratio']):.0%}）"
                ),
            )
        if (
            float(current["invested_cost"]) + cost
            > invested_limit + 1e-6
        ):
            raise HTTPException(
                status_code=409,
                detail=(
                    f"新增后投入成本 ¥{float(current['invested_cost']) + cost:,.2f} "
                    f"超过总仓位上限 ¥{invested_limit:,.2f}"
                    f"（总资金的 {float(settings['max_invested_ratio']):.0%}）"
                ),
            )
        if cost > float(current["available_funds"]) + 1e-6:
            raise HTTPException(
                status_code=409,
                detail=(
                    f"持仓成本 ¥{cost:,.2f} 超过可用资金 "
                    f"¥{float(current['available_funds']):,.2f}；请调整数量、成本价或账户总资金"
                ),
            )
        try:
            return db.create_position(values)
        except sqlite3.IntegrityError as exc:
            raise HTTPException(status_code=409, detail="position already exists") from exc

    @application.put("/api/positions/{code}", tags=["positions"])
    @application.patch("/api/positions/{code}", tags=["positions"])
    def update_position(
        code: str, payload: PositionUpdate, request: Request
    ) -> dict[str, Any]:
        db = _db(request)
        code = _valid_code(code)
        current_position = db.get_position(code)
        if current_position is None:
            raise HTTPException(status_code=404, detail="position not found")
        quantity = payload.quantity or int(current_position["quantity"])
        avg_price = payload.avg_price or float(current_position["avg_price"])
        stop_loss = payload.stop_loss or float(current_position["stop_loss"])
        fx_rate = _market(request).cny_rate(code)
        if stop_loss >= avg_price:
            raise HTTPException(status_code=422, detail="stop loss must be below cost price")
        settings = db.get_settings()
        old_cost = (
            int(current_position["quantity"])
            * float(current_position["avg_price"])
            * float(current_position.get("fx_rate", 1.0))
        )
        proposed_cost = quantity * avg_price * fx_rate
        other_cost = float(db.portfolio_snapshot()["invested_cost"]) - old_cost
        single_limit = float(settings["total_capital"]) * float(
            settings["max_position_ratio"]
        )
        invested_limit = float(settings["total_capital"]) * float(
            settings["max_invested_ratio"]
        )
        if proposed_cost > single_limit + 1e-6:
            raise HTTPException(
                status_code=409,
                detail=f"持仓成本 ¥{proposed_cost:,.2f} 超过单股仓位上限 ¥{single_limit:,.2f}",
            )
        if other_cost + proposed_cost > invested_limit + 1e-6:
            raise HTTPException(
                status_code=409,
                detail=f"修改后投入成本 ¥{other_cost + proposed_cost:,.2f} 超过总仓位上限 ¥{invested_limit:,.2f}",
            )
        spendable_funds = float(db.portfolio_snapshot()["available_funds"]) + old_cost
        if proposed_cost > spendable_funds + 1e-6:
            raise HTTPException(
                status_code=409,
                detail=f"持仓成本 ¥{proposed_cost:,.2f} 超过可用资金 ¥{spendable_funds:,.2f}",
            )
        updates = _dump(payload, exclude_unset=True)
        updates["fx_rate"] = fx_rate
        result = db.update_position(code, updates)
        if result is None:
            raise HTTPException(status_code=404, detail="position not found")
        return result

    @application.delete("/api/positions/{code}", tags=["positions"])
    def delete_position(code: str, request: Request) -> dict[str, bool]:
        if not _db(request).delete_position(_valid_code(code)):
            raise HTTPException(status_code=404, detail="position not found")
        return {"deleted": True}

    @application.get("/api/trades", tags=["trades"])
    def list_trades(
        request: Request, limit: int = Query(default=200, ge=1, le=1000)
    ) -> dict[str, Any]:
        return {"items": _db(request).list_trades(limit)}

    @application.post(
        "/api/trades", tags=["trades"], status_code=status.HTTP_201_CREATED
    )
    def create_trade(payload: TradeCreate, request: Request) -> dict[str, Any]:
        code = _valid_code(payload.code)
        if (
            payload.side == "buy"
            and not is_hk_code(code)
            and payload.quantity % 100 != 0
        ):
            raise HTTPException(
                status_code=422, detail="A-share buy quantity must be a multiple of 100"
            )
        quote = _market(request).quotes([code])[code]
        values = _dump(payload)
        values["code"] = code
        values["name"] = payload.name or quote["name"]
        values["price"] = payload.price or quote["price"]
        values["market"] = quote.get("market", "HK" if is_hk_code(code) else "A")
        values["currency"] = quote.get("currency", "HKD" if is_hk_code(code) else "CNY")
        values["fx_rate"] = _market(request).cny_rate(code)
        if payload.side == "buy":
            session = session_status()
            plan_date = _session_plan_date(session)
            plan = _db(request).get_close_screen(for_date=plan_date) if plan_date else None
            codes = {
                str(item.get("code"))
                for item in (plan or {}).get("items") or []
                if item.get("code")
            }
            if codes and code not in codes:
                values["violated"] = True
                existing = str(values.get("note") or "").strip()
                if "不在当日精选清单" not in existing:
                    values["note"] = (
                        f"{existing}；买入不在当日精选清单" if existing else "买入不在当日精选清单"
                    )
        try:
            trade = _db(request).execute_trade(values)
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        return {"trade": trade, "portfolio": _db(request).portfolio_snapshot()}

    @application.get("/api/journal", tags=["journal"])
    def list_journal(
        request: Request, limit: int = Query(default=200, ge=1, le=1000)
    ) -> dict[str, Any]:
        return {"items": _db(request).list_journals(limit)}

    @application.get("/api/journal/{journal_id}", tags=["journal"])
    def get_journal(journal_id: int, request: Request) -> dict[str, Any]:
        item = _db(request).get_journal(journal_id)
        if item is None:
            raise HTTPException(status_code=404, detail="journal entry not found")
        return item

    @application.post(
        "/api/journal", tags=["journal"], status_code=status.HTTP_201_CREATED
    )
    def create_journal(payload: JournalCreate, request: Request) -> dict[str, Any]:
        try:
            return _db(request).create_journal(_dump(payload))
        except sqlite3.IntegrityError as exc:
            raise HTTPException(status_code=409, detail="linked trade does not exist") from exc

    @application.patch("/api/journal/{journal_id}", tags=["journal"])
    def update_journal(
        journal_id: int, payload: JournalUpdate, request: Request
    ) -> dict[str, Any]:
        try:
            item = _db(request).update_journal(
                journal_id, _dump(payload, exclude_unset=True)
            )
        except sqlite3.IntegrityError as exc:
            raise HTTPException(status_code=409, detail="linked trade does not exist") from exc
        if item is None:
            raise HTTPException(status_code=404, detail="journal entry not found")
        return item

    @application.delete("/api/journal/{journal_id}", tags=["journal"])
    def delete_journal(journal_id: int, request: Request) -> dict[str, bool]:
        if not _db(request).delete_journal(journal_id):
            raise HTTPException(status_code=404, detail="journal entry not found")
        return {"deleted": True}

    @application.get("/api/review", tags=["review"])
    @application.get("/api/review/stats", tags=["review"])
    def review_stats(request: Request) -> dict[str, Any]:
        return review_statistics(_db(request).list_trades(limit=100000))

    return application


def _db(request: Request) -> Database:
    return request.app.state.db


def _market(request: Request) -> MarketService:
    return request.app.state.market


_CLOSE_JOB_LOCK = threading.Lock()


def _close_job(request: Request) -> dict[str, Any]:
    job = getattr(request.app.state, "close_screen_job", None)
    return job if isinstance(job, dict) else {"status": "idle"}


def _with_close_job(request: Request, payload: dict[str, Any]) -> dict[str, Any]:
    return {**payload, "job": _close_job(request)}


def _trade_day(traded_at: str) -> str:
    raw = str(traded_at)
    try:
        moment = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return raw[:10]
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return moment.astimezone(CHINA_TZ).date().isoformat()


def _session_plan_date(session: Mapping[str, Any]) -> str:
    if session.get("code") in {"after_close", "weekend"}:
        return str(session.get("as_of_date") or "")
    return str(session.get("for_date") or "")


def _has_journal_for_session(db: Database, session: Mapping[str, Any]) -> bool:
    day = _session_plan_date(session)
    if not day:
        return False
    return any(
        _trade_day(str(item.get("created_at") or "")) == day
        for item in db.list_journals(limit=30)
    )


def _today_discipline(db: Database, session: Mapping[str, Any]) -> dict[str, Any]:
    plan_date = _session_plan_date(session)
    plan = db.get_close_screen(for_date=plan_date) if plan_date else None
    codes = {
        str(item.get("code"))
        for item in (plan or {}).get("items") or []
        if item.get("code")
    }
    buys: list[dict[str, Any]] = []
    for trade in db.list_trades(limit=200):
        if str(trade.get("side", "")).lower() != "buy":
            continue
        if plan_date and _trade_day(str(trade.get("traded_at") or "")) != plan_date:
            continue
        code = str(trade.get("code"))
        buys.append(
            {
                "code": code,
                "name": trade.get("name") or code,
                "on_list": bool(codes) and code in codes,
            }
        )
    return {
        "plan_date": plan_date or None,
        "has_plan": bool(codes),
        "plan_count": len(codes),
        "buy_count": len(buys),
        "off_list": [item for item in buys if codes and not item["on_list"]],
        "plan_codes": sorted(codes),
    }


def _close_screen_needs_run(session: Mapping[str, Any], screen: Mapping[str, Any] | None) -> bool:
    if session.get("code") not in {"after_close", "weekend"}:
        return False
    as_of = (screen or {}).get("as_of_date")
    return not as_of or str(as_of) != str(session.get("as_of_date"))


def _quotes_if_warm(request: Request, codes: list[str]) -> dict[str, Any]:
    """Return quotes only when the spot cache is already populated."""
    if not codes:
        return {}
    market = _market(request)
    peek = getattr(market.cache, "peek", None)
    spot = peek("market:spot") if callable(peek) else None
    hk_spot = peek("market:hk:spot") if callable(peek) else None
    if not isinstance(spot, dict) and not isinstance(hk_spot, dict):
        return {}
    return market.quotes(codes)


def _position_quotes(request: Request, codes: list[str]) -> tuple[dict[str, Any], bool]:
    """Return last-known quotes without blocking on a spot refresh when possible."""
    if not codes:
        return {}, False
    market = _market(request)
    db = _db(request)
    peek = getattr(market.cache, "peek", None)
    spot = peek("market:spot") if callable(peek) else None
    hk_spot = peek("market:hk:spot") if callable(peek) else None
    if isinstance(spot, dict) or isinstance(hk_spot, dict):
        quotes = market.quotes(codes)
        db.save_snapshot("position-quotes", quotes)
        return quotes, False
    saved = db.get_snapshot("position-quotes") or {}

    def refresh() -> None:
        try:
            data = market.quotes(codes)
            if data:
                db.save_snapshot("position-quotes", data)
        except Exception:
            pass

    threading.Thread(target=refresh, name="position-quotes", daemon=True).start()
    return saved, True


def _fresh_or_snapshot(
    db: Database,
    market: MarketService,
    cache_key: str,
    snapshot_key: str,
    loader: Callable[[], dict[str, Any]],
) -> dict[str, Any]:
    peek = getattr(market.cache, "peek", None)
    warm = peek(cache_key) if callable(peek) else None
    if isinstance(warm, dict):
        if warm.get("source") == "akshare":
            db.save_snapshot(snapshot_key, warm)
        return warm
    saved = db.get_snapshot(snapshot_key)
    if saved:
        def refresh() -> None:
            try:
                data = loader()
                if data.get("source") == "akshare":
                    db.save_snapshot(snapshot_key, data)
            except Exception:
                pass

        threading.Thread(
            target=refresh, name=f"refresh:{snapshot_key}", daemon=True
        ).start()
        return {**saved, "stale": True}
    data = loader()
    if data.get("source") == "akshare":
        db.save_snapshot(snapshot_key, data)
    return data


def _ai(request: Request) -> AIService:
    return request.app.state.ai


def _require_ai(request: Request) -> AIService:
    ai_service = _ai(request)
    if not ai_service.available:
        raise HTTPException(
            status_code=503,
            detail="AI 服务未启用：需要安装 cursor-sdk 并设置 CURSOR_API_KEY",
        )
    return ai_service


def _valid_code(code: str) -> str:
    normalized = normalize_code(code)
    if not re.fullmatch(r"(?:\d{5}|\d{6})", normalized):
        raise HTTPException(
            status_code=422,
            detail="stock code must contain 5 Hong Kong or 6 A-share digits",
        )
    return normalized


def _dump(model: BaseModel, **kwargs: Any) -> dict[str, Any]:
    """Keep the app friendly to both Pydantic 1 and 2 installations."""
    if hasattr(model, "model_dump"):
        return model.model_dump(**kwargs)
    return model.dict(**kwargs)


app = create_app()
