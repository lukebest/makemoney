"""Runtime configuration for auth, credits, and payments."""

from __future__ import annotations

import os
from dataclasses import dataclass


def _env(name: str, default: str = "") -> str:
    return (os.getenv(name) or default).strip()


def _bool(name: str, default: bool = False) -> bool:
    raw = _env(name)
    if not raw:
        return default
    return raw.lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class AppConfig:
    app_env: str
    wechat_app_id: str
    wechat_app_secret: str
    payment_provider: str
    allow_mock_payments: bool
    ai_credit_cost: int
    session_ttl_seconds: int

    @property
    def is_production(self) -> bool:
        return self.app_env.lower() in {"production", "prod"}

    @property
    def wechat_configured(self) -> bool:
        return bool(self.wechat_app_id and self.wechat_app_secret)

    @property
    def mock_login_allowed(self) -> bool:
        return not self.is_production

    @property
    def mock_pay_allowed(self) -> bool:
        if self.payment_provider != "mock":
            return False
        if self.is_production and not self.allow_mock_payments:
            return False
        return True


def load_config() -> AppConfig:
    return AppConfig(
        app_env=_env("APP_ENV", "development"),
        wechat_app_id=_env("WECHAT_APP_ID"),
        wechat_app_secret=_env("WECHAT_APP_SECRET"),
        payment_provider=_env("PAYMENT_PROVIDER", "mock").lower(),
        allow_mock_payments=_bool("ALLOW_MOCK_PAYMENTS", False),
        ai_credit_cost=max(1, int(_env("AI_CREDIT_COST", "1") or "1")),
        session_ttl_seconds=max(3600, int(_env("SESSION_TTL_SECONDS", "2592000") or "2592000")),
    )
