"""FastAPI entry point for the A-share trading-discipline backend."""

from __future__ import annotations

import os
import re
import sqlite3
import uuid
from contextlib import asynccontextmanager
from typing import Any, Literal

from fastapi import FastAPI, Header, HTTPException, Query, Request, status
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from .ai import AIService
from .auth import AuthService, hash_token
from .config import load_config
from .db import LOCAL_OPENID, Database
from .market import MarketService, is_hk_code, normalize_code
from .payments import PaymentService
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
    request_id: str | None = Field(default=None, max_length=64)


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


class WechatLoginRequest(BaseModel):
    code: str = Field(min_length=1, max_length=128)


class DevLoginRequest(BaseModel):
    label: str = Field(default="dev", max_length=64)


class OrderCreateRequest(BaseModel):
    sku: str = Field(min_length=1, max_length=64)


class AIInterpretRequest(BaseModel):
    request_id: str | None = Field(default=None, max_length=64)


def create_app(
    db_path: str | os.PathLike[str] | None = None,
    market_service: MarketService | None = None,
    ai_service: AIService | None = None,
) -> FastAPI:
    database = Database(db_path)
    market = market_service or MarketService()
    ai = ai_service or AIService()
    config = load_config()
    auth = AuthService(database, config)
    payments = PaymentService(database, config)

    @asynccontextmanager
    async def lifespan(application: FastAPI):
        database.initialize()
        application.state.db = database
        application.state.market = market
        application.state.ai = ai
        application.state.auth = auth
        application.state.payments = payments
        application.state.config = config
        yield
        market.cache.clear()

    application = FastAPI(
        title="A股散户赚钱系统 API",
        version="1.1.0",
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
            "app_env": config.app_env,
            "payment_provider": config.payment_provider,
            "mock_pay_allowed": config.mock_pay_allowed,
        }

    @application.post("/api/auth/wechat", tags=["auth"])
    def auth_wechat(payload: WechatLoginRequest, request: Request) -> dict[str, Any]:
        return _auth(request).login_with_wechat_code(payload.code)

    @application.post("/api/auth/dev", tags=["auth"])
    def auth_dev(payload: DevLoginRequest, request: Request) -> dict[str, Any]:
        return _auth(request).login_dev(payload.label)

    @application.get("/api/auth/me", tags=["auth"])
    def auth_me(request: Request) -> dict[str, Any]:
        user = _user(request, require_auth=True)
        credits = _db(request).get_credit_balance(int(user["id"]))
        return {
            "user": {
                "id": user["id"],
                "openid": user["openid"],
                "mock": bool(user.get("mock")),
                "created_at": user.get("created_at"),
            },
            "credits": credits,
        }

    @application.post("/api/auth/logout", tags=["auth"])
    def auth_logout(
        request: Request, authorization: str | None = Header(default=None)
    ) -> dict[str, bool]:
        if authorization and authorization.lower().startswith("bearer "):
            _db(request).delete_session(hash_token(authorization[7:].strip()))
        return {"deleted": True}

    @application.get("/api/credits", tags=["credits"])
    def credits_balance(request: Request) -> dict[str, Any]:
        user = _user(request, require_auth=True)
        db = _db(request)
        return {
            **db.get_credit_balance(int(user["id"])),
            "ai_credit_cost": config.ai_credit_cost,
            "ledger": db.list_credit_ledger(int(user["id"]), limit=30),
        }

    @application.get("/api/credits/skus", tags=["credits"])
    def credit_skus(request: Request) -> dict[str, Any]:
        return _payments(request).list_skus()

    @application.post(
        "/api/orders", tags=["credits"], status_code=status.HTTP_201_CREATED
    )
    def create_order(payload: OrderCreateRequest, request: Request) -> dict[str, Any]:
        user = _user(request, require_auth=True)
        return _payments(request).create_order(int(user["id"]), payload.sku)

    @application.post("/api/orders/{order_id}/mock-pay", tags=["credits"])
    def mock_pay_order(order_id: str, request: Request) -> dict[str, Any]:
        user = _user(request, require_auth=True)
        return _payments(request).mock_pay(int(user["id"]), order_id)

    @application.get("/api/market/overview", tags=["market"])
    def market_overview(request: Request) -> dict[str, Any]:
        return _market(request).overview()

    @application.get("/api/market/mainline", tags=["market"])
    def market_mainline(request: Request) -> dict[str, Any]:
        return _market(request).mainline()

    @application.get("/api/market/preferred", tags=["market"])
    def preferred_stocks(
        request: Request,
        limit: int = Query(default=8, ge=1, le=20),
        candidates: int = Query(default=12, ge=1, le=30),
    ) -> dict[str, Any]:
        return _market(request).preferred_stocks(limit, max(limit, candidates))

    @application.get("/api/stocks/{code}", tags=["market"])
    @application.get("/api/market/stocks/{code}/daily", tags=["market"])
    def stock_daily(
        code: str,
        request: Request,
        days: int = Query(default=120, ge=60, le=500),
    ) -> dict[str, Any]:
        try:
            return _market(request).stock_daily(_valid_code(code), days)
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
        status_payload = _ai(request).status()
        status_payload["ai_credit_cost"] = config.ai_credit_cost
        return status_payload

    @application.post("/api/ai/interpret/{code}", tags=["ai"])
    def ai_interpret(
        code: str,
        request: Request,
        request_id: str | None = Query(default=None, max_length=64),
    ) -> dict[str, Any]:
        # Mini program should send Bearer token; local web falls back to local-web user.
        user = _user(request, require_auth=False)
        ai_service = _require_ai(request)
        try:
            analysis = _market(request).stock_daily(_valid_code(code), 120)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        if analysis["source"] == "sample":
            raise HTTPException(
                status_code=409, detail="行情为演示数据，AI 解读已禁用以免误导"
            )
        rid = request_id or uuid.uuid4().hex
        return _run_ai_with_credits(
            request,
            user=user,
            request_id=rid,
            reason=f"个股解读 {analysis.get('code')}",
            runner=lambda: ai_service.interpret_stock(analysis),
        )

    @application.post("/api/ai/review-trade", tags=["ai"])
    def ai_review_trade(payload: TradeReviewRequest, request: Request) -> dict[str, Any]:
        user = _user(request, require_auth=False)
        ai_service = _require_ai(request)
        code = _valid_code(payload.code)
        try:
            analysis = _market(request).stock_daily(code, 120)
            if analysis["source"] == "sample":
                analysis = None
        except Exception:
            analysis = None
        db = _db(request)
        user_id = int(user["id"])
        settings = db.get_settings(user_id)
        snapshot = db.portfolio_snapshot(user_id)
        portfolio = {
            "总资金": settings["total_capital"],
            "已用资金": snapshot["invested_cost"],
            "可用资金": snapshot["available_funds"],
        }
        trade = _dump(payload)
        trade["code"] = code
        request_id = payload.request_id or uuid.uuid4().hex
        return _run_ai_with_credits(
            request,
            user=user,
            request_id=request_id,
            reason=f"买入审查 {code}",
            runner=lambda: ai_service.review_trade(trade, analysis, portfolio),
        )

    @application.post("/api/ai/review-report", tags=["ai"])
    def ai_review_report(request: Request) -> dict[str, Any]:
        user = _user(request, require_auth=False)
        ai_service = _require_ai(request)
        db = _db(request)
        user_id = int(user["id"])
        trades = db.list_trades(limit=100000, user_id=user_id)
        stats = review_statistics(trades)
        request_id = request.headers.get("X-Request-Id") or uuid.uuid4().hex
        return _run_ai_with_credits(
            request,
            user=user,
            request_id=request_id,
            reason="复盘报告",
            runner=lambda: ai_service.review_report(stats, trades),
        )

    @application.get("/api/settings", tags=["settings"])
    def get_settings(request: Request) -> dict[str, Any]:
        user = _user(request)
        return _db(request).get_settings(int(user["id"]))

    @application.put("/api/settings", tags=["settings"])
    def update_settings(payload: SettingsUpdate, request: Request) -> dict[str, Any]:
        user = _user(request)
        db = _db(request)
        user_id = int(user["id"])
        values = _dump(payload, exclude_none=True)
        invested = db.portfolio_snapshot(user_id)["invested_cost"]
        if payload.total_capital < invested:
            raise HTTPException(
                status_code=409,
                detail="total capital cannot be below current invested cost",
            )
        return db.set_settings(values, user_id)

    @application.get("/api/positions", tags=["positions"])
    @application.get("/api/positions/status", tags=["positions"])
    def positions_status(request: Request) -> dict[str, Any]:
        user = _user(request)
        db = _db(request)
        market_service = _market(request)
        user_id = int(user["id"])
        positions = db.list_positions(user_id)
        quotes = market_service.quotes([row["code"] for row in positions])
        settings = db.get_settings(user_id)
        total_capital = float(settings["total_capital"])
        items = []
        total_market_value = 0.0
        total_unrealized = 0.0
        alerts = []
        for row in positions:
            quote = quotes[row["code"]]
            price = float(quote["price"])
            fx_rate = market_service.cny_rate(row["code"])
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
                "price_source": quote["source"],
                "market": quote.get("market", row.get("market", "A")),
                "currency": quote.get("currency", row.get("currency", "CNY")),
                "fx_rate": fx_rate,
                "change_pct": quote["change_pct"],
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
            "summary": {
                **db.portfolio_snapshot(user_id),
                "market_value": round(total_market_value, 2),
                "unrealized_pnl": round(total_unrealized, 2),
                "position_ratio": round(total_market_value / total_capital, 4),
            },
        }

    @application.post(
        "/api/positions", tags=["positions"], status_code=status.HTTP_201_CREATED
    )
    def create_position(payload: PositionCreate, request: Request) -> dict[str, Any]:
        user = _user(request)
        db = _db(request)
        user_id = int(user["id"])
        values = _dump(payload)
        values["code"] = _valid_code(payload.code)
        hk = is_hk_code(values["code"])
        values["market"] = "HK" if hk else "A"
        values["currency"] = "HKD" if hk else "CNY"
        values["fx_rate"] = _market(request).cny_rate(values["code"])
        if payload.stop_loss >= payload.avg_price:
            raise HTTPException(status_code=422, detail="stop loss must be below cost price")
        settings = db.get_settings(user_id)
        current = db.portfolio_snapshot(user_id)
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
        if float(current["invested_cost"]) + cost > invested_limit + 1e-6:
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
            return db.create_position(values, user_id)
        except sqlite3.IntegrityError as exc:
            raise HTTPException(status_code=409, detail="position already exists") from exc

    @application.put("/api/positions/{code}", tags=["positions"])
    @application.patch("/api/positions/{code}", tags=["positions"])
    def update_position(
        code: str, payload: PositionUpdate, request: Request
    ) -> dict[str, Any]:
        user = _user(request)
        db = _db(request)
        user_id = int(user["id"])
        code = _valid_code(code)
        current_position = db.get_position(code, user_id)
        if current_position is None:
            raise HTTPException(status_code=404, detail="position not found")
        quantity = payload.quantity or int(current_position["quantity"])
        avg_price = payload.avg_price or float(current_position["avg_price"])
        stop_loss = payload.stop_loss or float(current_position["stop_loss"])
        fx_rate = _market(request).cny_rate(code)
        if stop_loss >= avg_price:
            raise HTTPException(status_code=422, detail="stop loss must be below cost price")
        settings = db.get_settings(user_id)
        old_cost = (
            int(current_position["quantity"])
            * float(current_position["avg_price"])
            * float(current_position.get("fx_rate", 1.0))
        )
        proposed_cost = quantity * avg_price * fx_rate
        other_cost = float(db.portfolio_snapshot(user_id)["invested_cost"]) - old_cost
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
        spendable_funds = float(db.portfolio_snapshot(user_id)["available_funds"]) + old_cost
        if proposed_cost > spendable_funds + 1e-6:
            raise HTTPException(
                status_code=409,
                detail=f"持仓成本 ¥{proposed_cost:,.2f} 超过可用资金 ¥{spendable_funds:,.2f}",
            )
        updates = _dump(payload, exclude_unset=True)
        updates["fx_rate"] = fx_rate
        result = db.update_position(code, updates, user_id)
        if result is None:
            raise HTTPException(status_code=404, detail="position not found")
        return result

    @application.delete("/api/positions/{code}", tags=["positions"])
    def delete_position(code: str, request: Request) -> dict[str, bool]:
        user = _user(request)
        if not _db(request).delete_position(_valid_code(code), int(user["id"])):
            raise HTTPException(status_code=404, detail="position not found")
        return {"deleted": True}

    @application.get("/api/trades", tags=["trades"])
    def list_trades(
        request: Request, limit: int = Query(default=200, ge=1, le=1000)
    ) -> dict[str, Any]:
        user = _user(request)
        return {"items": _db(request).list_trades(limit, int(user["id"]))}

    @application.post(
        "/api/trades", tags=["trades"], status_code=status.HTTP_201_CREATED
    )
    def create_trade(payload: TradeCreate, request: Request) -> dict[str, Any]:
        user = _user(request)
        user_id = int(user["id"])
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
        try:
            trade = _db(request).execute_trade(values, user_id)
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        return {"trade": trade, "portfolio": _db(request).portfolio_snapshot(user_id)}

    @application.get("/api/journal", tags=["journal"])
    def list_journal(
        request: Request, limit: int = Query(default=200, ge=1, le=1000)
    ) -> dict[str, Any]:
        user = _user(request)
        return {"items": _db(request).list_journals(limit, int(user["id"]))}

    @application.get("/api/journal/{journal_id}", tags=["journal"])
    def get_journal(journal_id: int, request: Request) -> dict[str, Any]:
        user = _user(request)
        item = _db(request).get_journal(journal_id, int(user["id"]))
        if item is None:
            raise HTTPException(status_code=404, detail="journal entry not found")
        return item

    @application.post(
        "/api/journal", tags=["journal"], status_code=status.HTTP_201_CREATED
    )
    def create_journal(payload: JournalCreate, request: Request) -> dict[str, Any]:
        user = _user(request)
        try:
            return _db(request).create_journal(_dump(payload), int(user["id"]))
        except sqlite3.IntegrityError as exc:
            raise HTTPException(status_code=409, detail="linked trade does not exist") from exc

    @application.patch("/api/journal/{journal_id}", tags=["journal"])
    def update_journal(
        journal_id: int, payload: JournalUpdate, request: Request
    ) -> dict[str, Any]:
        user = _user(request)
        try:
            item = _db(request).update_journal(
                journal_id, _dump(payload, exclude_unset=True), int(user["id"])
            )
        except sqlite3.IntegrityError as exc:
            raise HTTPException(status_code=409, detail="linked trade does not exist") from exc
        if item is None:
            raise HTTPException(status_code=404, detail="journal entry not found")
        return item

    @application.delete("/api/journal/{journal_id}", tags=["journal"])
    def delete_journal(journal_id: int, request: Request) -> dict[str, bool]:
        user = _user(request)
        if not _db(request).delete_journal(journal_id, int(user["id"])):
            raise HTTPException(status_code=404, detail="journal entry not found")
        return {"deleted": True}

    @application.get("/api/review", tags=["review"])
    @application.get("/api/review/stats", tags=["review"])
    def review_stats(request: Request) -> dict[str, Any]:
        user = _user(request)
        return review_statistics(_db(request).list_trades(limit=100000, user_id=int(user["id"])))

    return application


def _db(request: Request) -> Database:
    return request.app.state.db


def _market(request: Request) -> MarketService:
    return request.app.state.market


def _ai(request: Request) -> AIService:
    return request.app.state.ai


def _auth(request: Request) -> AuthService:
    return request.app.state.auth


def _payments(request: Request) -> PaymentService:
    return request.app.state.payments


def _user(request: Request, *, require_auth: bool = False) -> dict[str, Any]:
    return _auth(request).resolve_user(request, require_auth=require_auth)


def _require_ai(request: Request) -> AIService:
    ai_service = _ai(request)
    if not ai_service.available:
        raise HTTPException(
            status_code=503,
            detail="AI 服务未启用：需要安装 cursor-sdk 并设置 CURSOR_API_KEY",
        )
    return ai_service


def _run_ai_with_credits(
    request: Request,
    *,
    user: dict[str, Any],
    request_id: str,
    reason: str,
    runner,
) -> dict[str, Any]:
    db = _db(request)
    config = request.app.state.config
    user_id = int(user["id"])
    # Local anonymous web user keeps free AI; WeChat / authenticated users pay credits.
    charge = user.get("openid") != LOCAL_OPENID
    cost = int(config.ai_credit_cost) if charge else 0
    ledger: dict[str, Any] | None = None
    if charge:
        try:
            ledger = db.reserve_credits(
                user_id,
                cost,
                reason=reason,
                ref_type="ai_debit",
                ref_id=request_id,
            )
        except ValueError as exc:
            if "insufficient credits" in str(exc):
                raise HTTPException(
                    status_code=402,
                    detail=f"AI 点数不足（每次消耗 {cost} 点），请先购买点数包",
                ) from exc
            raise HTTPException(status_code=409, detail=str(exc)) from exc
    try:
        result = runner()
    except RuntimeError as exc:
        if charge and cost:
            db.refund_credits(
                user_id,
                cost,
                reason=f"退款：{reason}",
                ref_type="ai_refund",
                ref_id=request_id,
            )
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    except Exception:
        if charge and cost:
            db.refund_credits(
                user_id,
                cost,
                reason=f"退款：{reason}",
                ref_type="ai_refund",
                ref_id=request_id,
            )
        raise
    result = dict(result)
    result["credits_charged"] = cost
    result["credits_balance"] = db.get_credit_balance(user_id)["balance"]
    result["request_id"] = request_id
    result["ledger_id"] = ledger.get("id") if ledger else None
    return result


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
