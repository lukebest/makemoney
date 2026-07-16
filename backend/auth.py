"""WeChat login and Bearer session helpers."""

from __future__ import annotations

import hashlib
import secrets
from typing import Any

import httpx
from fastapi import HTTPException, Request

from .config import AppConfig, load_config
from .db import LOCAL_OPENID, Database

MOCK_CODE_PREFIX = "mock:"


class AuthService:
    def __init__(self, db: Database, config: AppConfig | None = None) -> None:
        self.db = db
        self.config = config or load_config()

    def login_with_wechat_code(self, code: str) -> dict[str, Any]:
        code = (code or "").strip()
        if not code:
            raise HTTPException(status_code=422, detail="缺少微信登录 code")
        openid, session_key, mock = self._resolve_openid(code)
        user = self.db.upsert_user(openid, session_key=session_key, mock=mock)
        token = secrets.token_urlsafe(32)
        self.db.create_session(
            user["id"],
            token_hash=hash_token(token),
            ttl_seconds=self.config.session_ttl_seconds,
        )
        return {
            "token": token,
            "user": {
                "id": user["id"],
                "openid": user["openid"],
                "mock": bool(user.get("mock")),
                "created_at": user.get("created_at"),
            },
            "expires_in": self.config.session_ttl_seconds,
            "credits": self.db.get_credit_balance(user["id"]),
        }

    def login_dev(self, label: str = "dev") -> dict[str, Any]:
        if not self.config.mock_login_allowed:
            raise HTTPException(status_code=403, detail="生产环境禁用开发登录")
        openid = f"dev:{label.strip() or 'user'}"
        user = self.db.upsert_user(openid, session_key="", mock=True)
        token = secrets.token_urlsafe(32)
        self.db.create_session(
            user["id"],
            token_hash=hash_token(token),
            ttl_seconds=self.config.session_ttl_seconds,
        )
        return {
            "token": token,
            "user": {
                "id": user["id"],
                "openid": user["openid"],
                "mock": True,
                "created_at": user.get("created_at"),
            },
            "expires_in": self.config.session_ttl_seconds,
            "credits": self.db.get_credit_balance(user["id"]),
        }

    def resolve_user(self, request: Request, *, require_auth: bool = False) -> dict[str, Any]:
        header = request.headers.get("Authorization") or ""
        token = ""
        if header.lower().startswith("bearer "):
            token = header[7:].strip()
        if not token:
            if require_auth:
                raise HTTPException(status_code=401, detail="需要登录")
            return self.db.get_or_create_local_user()
        user = self.db.get_user_by_token(hash_token(token))
        if user is None:
            raise HTTPException(status_code=401, detail="登录已失效，请重新登录")
        return user

    def _resolve_openid(self, code: str) -> tuple[str, str, bool]:
        if code.startswith(MOCK_CODE_PREFIX):
            if not self.config.mock_login_allowed:
                raise HTTPException(status_code=403, detail="生产环境禁用模拟登录")
            suffix = code[len(MOCK_CODE_PREFIX) :].strip() or "guest"
            return f"mock:{suffix}", "", True
        if not self.config.wechat_configured:
            if self.config.mock_login_allowed:
                # Local/dev without credentials: treat raw code as mock openid seed.
                return f"mock:{code}", "", True
            raise HTTPException(
                status_code=503,
                detail="未配置 WECHAT_APP_ID / WECHAT_APP_SECRET，无法完成微信登录",
            )
        payload = self._code2session(code)
        openid = str(payload.get("openid") or "")
        if not openid:
            err = payload.get("errmsg") or payload.get("errcode") or "unknown"
            raise HTTPException(status_code=401, detail=f"微信登录失败：{err}")
        return openid, str(payload.get("session_key") or ""), False

    def _code2session(self, code: str) -> dict[str, Any]:
        url = "https://api.weixin.qq.com/sns/jscode2session"
        params = {
            "appid": self.config.wechat_app_id,
            "secret": self.config.wechat_app_secret,
            "js_code": code,
            "grant_type": "authorization_code",
        }
        try:
            response = httpx.get(url, params=params, timeout=10.0)
            response.raise_for_status()
            data = response.json()
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(status_code=502, detail=f"微信登录接口不可用：{exc}") from exc
        return data if isinstance(data, dict) else {}


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def ensure_local_openid() -> str:
    return LOCAL_OPENID
