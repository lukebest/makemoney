"""Auth, credits, and mock payment coverage."""

from __future__ import annotations

import os

from fastapi.testclient import TestClient

from backend.main import create_app
from backend.tests.test_api import DummyAI, DummyMarket, make_client


def auth_headers(client: TestClient, label: str = "alice") -> dict[str, str]:
    token = client.post("/api/auth/dev", json={"label": label}).json()["token"]
    return {"Authorization": f"Bearer {token}"}


def test_dev_login_and_user_isolation(tmp_path):
    with make_client(tmp_path) as client:
        alice = auth_headers(client, "alice")
        bob = auth_headers(client, "bob")
        created = client.post(
            "/api/positions",
            headers=alice,
            json={
                "code": "600519",
                "name": "贵州茅台",
                "quantity": 100,
                "avg_price": 100,
                "stop_loss": 95,
            },
        )
        assert created.status_code == 201
        alice_items = client.get("/api/positions", headers=alice).json()["items"]
        bob_items = client.get("/api/positions", headers=bob).json()["items"]
        assert len(alice_items) == 1
        assert bob_items == []


def test_mock_wechat_code_login(tmp_path):
    with make_client(tmp_path) as client:
        response = client.post("/api/auth/wechat", json={"code": "mock:guest"})
        assert response.status_code == 200
        body = response.json()
        assert body["token"]
        assert body["user"]["mock"] is True
        me = client.get("/api/auth/me", headers={"Authorization": f"Bearer {body['token']}"})
        assert me.status_code == 200
        assert me.json()["credits"]["balance"] == 0


def test_credit_purchase_and_ai_debit_refund(tmp_path, monkeypatch):
    class FlakyAI(DummyAI):
        def __init__(self):
            super().__init__()
            self.fail_once = True

        def interpret_stock(self, analysis):
            if self.fail_once:
                self.fail_once = False
                raise RuntimeError("cursor down")
            return super().interpret_stock(analysis)

    ai = FlakyAI()
    with make_client(tmp_path, ai=ai) as client:
        headers = auth_headers(client, "payer")
        skus = client.get("/api/credits/skus").json()
        assert skus["mock_pay_allowed"] is True
        order = client.post(
            "/api/orders", headers=headers, json={"sku": "credits_5"}
        ).json()["order"]
        paid = client.post(f"/api/orders/{order['id']}/mock-pay", headers=headers)
        assert paid.status_code == 200
        assert paid.json()["credits"]["balance"] == 5

        failed = client.post("/api/ai/interpret/600519?request_id=req-1", headers=headers)
        assert failed.status_code == 502
        assert client.get("/api/credits", headers=headers).json()["balance"] == 5

        # Same request_id after a refunded failure must charge again (not free AI).
        ok = client.post("/api/ai/interpret/600519?request_id=req-1", headers=headers)
        assert ok.status_code == 200
        assert ok.json()["credits_charged"] == 1
        assert ok.json()["credits_balance"] == 4

        # Successful same request_id stays idempotent.
        again = client.post("/api/ai/interpret/600519?request_id=req-1", headers=headers)
        assert again.status_code == 200
        assert again.json()["credits_charged"] == 0
        assert client.get("/api/credits", headers=headers).json()["balance"] == 4


def test_idempotent_replay_failure_does_not_refund_prior_success(tmp_path):
    """Replaying a successful request_id during an outage must not reclaim credits."""

    class FlipAI(DummyAI):
        def __init__(self):
            super().__init__()
            self.mode = "ok"

        def interpret_stock(self, analysis):
            if self.mode == "fail":
                raise RuntimeError("cursor down")
            return super().interpret_stock(analysis)

    ai = FlipAI()
    with make_client(tmp_path, ai=ai) as client:
        headers = auth_headers(client, "replay")
        order = client.post(
            "/api/orders", headers=headers, json={"sku": "credits_5"}
        ).json()["order"]
        client.post(f"/api/orders/{order['id']}/mock-pay", headers=headers)

        ok = client.post("/api/ai/interpret/600519?request_id=stable-1", headers=headers)
        assert ok.status_code == 200
        assert ok.json()["credits_charged"] == 1
        assert client.get("/api/credits", headers=headers).json()["balance"] == 4

        ai.mode = "fail"
        replay = client.post(
            "/api/ai/interpret/600519?request_id=stable-1", headers=headers
        )
        assert replay.status_code == 502
        # Prior successful debit must remain consumed.
        assert client.get("/api/credits", headers=headers).json()["balance"] == 4


def test_insufficient_credits_returns_402(tmp_path):
    with make_client(tmp_path) as client:
        headers = auth_headers(client, "broke")
        response = client.post("/api/ai/interpret/600519", headers=headers)
        assert response.status_code == 402
        assert "点数不足" in response.json()["detail"]


def test_production_blocks_mock_pay(tmp_path, monkeypatch):
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("PAYMENT_PROVIDER", "mock")
    monkeypatch.delenv("ALLOW_MOCK_PAYMENTS", raising=False)
    # Recreate app after env change.
    app = create_app(tmp_path / "prod.db", DummyMarket(), ai_service=DummyAI())
    with TestClient(app) as client:
        token = client.post("/api/auth/wechat", json={"code": "mock:x"})
        assert token.status_code == 403
        # Without wechat secrets in production, login must fail rather than mock.
        monkeypatch.setenv("WECHAT_APP_ID", "wx_test")
        monkeypatch.setenv("WECHAT_APP_SECRET", "secret")
        # Still no real code2session — use create_app again for config reload.
        # Payment kill-switch: create PaymentService via health after forcing mock deny.
        from backend.config import load_config
        from backend.payments import PaymentService
        from backend.db import Database

        cfg = load_config()
        assert cfg.mock_pay_allowed is False
        db = Database(tmp_path / "prod2.db")
        db.initialize()
        user = db.upsert_user("prod-user", mock=False)
        service = PaymentService(db, cfg)
        try:
            service.create_order(int(user["id"]), "credits_5")
            assert False, "expected mock pay block"
        except Exception as exc:  # noqa: BLE001
            assert "禁用模拟支付" in str(exc.detail)


def test_local_web_ai_skips_credits(tmp_path):
    with make_client(tmp_path) as client:
        # No Authorization header → local-web free AI path.
        response = client.post("/api/ai/interpret/600519")
        assert response.status_code == 200
        assert response.json()["credits_charged"] == 0


def test_legacy_positions_migration_adds_columns_before_pk_rewrite(tmp_path):
    """Old DBs lack market/currency/fx_rate; migration must not SELECT them first."""
    import sqlite3

    from backend.db import Database, LOCAL_USER_ID

    path = tmp_path / "legacy.db"
    connection = sqlite3.connect(path)
    connection.executescript(
        """
        CREATE TABLE positions (
            code TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            quantity INTEGER NOT NULL,
            avg_price REAL NOT NULL,
            stop_loss REAL NOT NULL,
            thesis TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        INSERT INTO positions(code, name, quantity, avg_price, stop_loss, thesis, created_at, updated_at)
        VALUES ('600519', '贵州茅台', 100, 100, 95, '', '2020-01-01T00:00:00+00:00', '2020-01-01T00:00:00+00:00');
        """
    )
    connection.commit()
    connection.close()

    db = Database(path)
    db.initialize()
    rows = db.list_positions(LOCAL_USER_ID)
    assert len(rows) == 1
    assert rows[0]["code"] == "600519"
    assert rows[0]["user_id"] == LOCAL_USER_ID
    assert rows[0]["market"] == "A"
    assert rows[0]["currency"] == "CNY"


def test_mark_order_paid_rejects_non_pending_status(tmp_path):
    from backend.db import Database

    db = Database(tmp_path / "orders.db")
    db.initialize()
    user = db.upsert_user("order-user", mock=True)
    user_id = int(user["id"])
    order = db.create_order(
        user_id=user_id,
        sku="credits_5",
        title="体验包",
        credits=5,
        amount_fen=100,
        provider="mock",
    )
    with db.transaction() as connection:
        connection.execute(
            "UPDATE orders SET status = 'cancelled' WHERE id = ?",
            (order["id"],),
        )
    try:
        db.mark_order_paid(order["id"], provider_ref="should-fail")
        assert False, "expected non-pending order to be rejected"
    except ValueError as exc:
        assert "pending" in str(exc)
    assert db.get_credit_balance(user_id)["balance"] == 0
    assert db.get_order(order["id"])["status"] == "cancelled"
