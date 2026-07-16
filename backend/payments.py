"""Credit packs and order/payment scaffolding with production mock kill-switch."""

from __future__ import annotations

from typing import Any

from fastapi import HTTPException

from .config import AppConfig, load_config
from .db import Database

CREDIT_SKUS: list[dict[str, Any]] = [
    {
        "sku": "credits_5",
        "title": "体验包",
        "credits": 5,
        "amount_fen": 100,
        "description": "5 次 AI 教练解读",
    },
    {
        "sku": "credits_20",
        "title": "常用包",
        "credits": 20,
        "amount_fen": 300,
        "description": "20 次 AI 教练解读",
        "popular": True,
    },
    {
        "sku": "credits_60",
        "title": "进阶包",
        "credits": 60,
        "amount_fen": 680,
        "description": "60 次 AI 教练解读",
    },
]


class PaymentService:
    def __init__(self, db: Database, config: AppConfig | None = None) -> None:
        self.db = db
        self.config = config or load_config()

    def list_skus(self) -> dict[str, Any]:
        return {
            "items": CREDIT_SKUS,
            "provider": self.config.payment_provider,
            "mock_pay_allowed": self.config.mock_pay_allowed,
            "ai_credit_cost": self.config.ai_credit_cost,
        }

    def create_order(self, user_id: int, sku: str) -> dict[str, Any]:
        pack = next((item for item in CREDIT_SKUS if item["sku"] == sku), None)
        if pack is None:
            raise HTTPException(status_code=422, detail="未知点数包")
        if self.config.payment_provider == "wechat" and self.config.is_production:
            raise HTTPException(
                status_code=503,
                detail="真实微信支付尚未配置商户号与 API v3 密钥，暂不可下单",
            )
        if self.config.payment_provider == "mock" and not self.config.mock_pay_allowed:
            raise HTTPException(
                status_code=403,
                detail="生产环境已禁用模拟支付；请配置真实微信支付或设置 ALLOW_MOCK_PAYMENTS=1",
            )
        order = self.db.create_order(
            user_id=user_id,
            sku=pack["sku"],
            title=pack["title"],
            credits=int(pack["credits"]),
            amount_fen=int(pack["amount_fen"]),
            provider=self.config.payment_provider,
        )
        return {"order": order, "mock_pay_allowed": self.config.mock_pay_allowed}

    def mock_pay(self, user_id: int, order_id: str) -> dict[str, Any]:
        if not self.config.mock_pay_allowed:
            raise HTTPException(
                status_code=403,
                detail="当前环境禁止模拟支付成功（生产环境默认熔断）",
            )
        order = self.db.get_order(order_id)
        if order is None or int(order["user_id"]) != user_id:
            raise HTTPException(status_code=404, detail="订单不存在")
        if order["status"] == "paid":
            return {
                "order": order,
                "credits": self.db.get_credit_balance(user_id),
                "already_paid": True,
            }
        if order["status"] != "pending":
            raise HTTPException(status_code=409, detail=f"订单状态不可支付：{order['status']}")
        paid = self.db.mark_order_paid(order_id, provider_ref=f"mock-{order_id}")
        return {
            "order": paid,
            "credits": self.db.get_credit_balance(user_id),
            "already_paid": False,
        }
