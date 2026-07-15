from fastapi.testclient import TestClient

from backend.main import create_app


class DummyCache:
    def clear(self):
        return None


class DummyMarket:
    cache = DummyCache()

    def overview(self):
        return {
            "indexes": [],
            "breadth": {"advance_ratio": 0.5},
            "phase": {"code": "spring", "name": "春播期"},
            "source": "sample",
        }

    def quotes(self, codes):
        return {
            code: {
                "code": code,
                "name": f"股票{code}",
                "price": 8.0,
                "change_pct": -1.0,
                "source": "test",
            }
            for code in codes
        }

    def stock_daily(self, code, days):
        return {"code": code, "klines": [], "source": "test", "days": days}

    def cny_rate(self, code):
        return 0.87 if len(code) == 5 else 1.0

    def preferred_stocks(self, limit, candidates):
        return {
            "items": [
                {
                    "code": "600519",
                    "name": "贵州茅台",
                    "score": 75,
                    "setup": "重点观察",
                }
            ][:limit],
            "source": "test",
            "analyzed_count": candidates,
        }


def make_client(tmp_path):
    app = create_app(tmp_path / "test.db", DummyMarket())
    return TestClient(app)


def test_health_settings_and_cors(tmp_path):
    with make_client(tmp_path) as client:
        assert client.get("/api/health").json()["status"] == "ok"
        settings = client.get("/api/settings").json()
        assert settings["total_capital"] == 100000.0
        response = client.put(
            "/api/settings",
            json={"total_capital": 200000, "max_position_ratio": 0.4},
        )
        assert response.status_code == 200
        assert response.json()["max_position_ratio"] == 0.4

        preflight = client.options(
            "/api/health",
            headers={
                "Origin": "http://localhost:5173",
                "Access-Control-Request-Method": "GET",
            },
        )
        assert preflight.headers["access-control-allow-origin"] == "http://localhost:5173"
        assert client.get("/api/stocks/600519").status_code == 200
        assert client.get("/api/stocks/00700").json()["code"] == "00700"
        preferred = client.get("/api/market/preferred?limit=1&candidates=3")
        assert preferred.status_code == 200
        assert preferred.json()["items"][0]["score"] == 75
        assert preferred.json()["analyzed_count"] == 3


def test_hong_kong_connect_buy_allows_non_a_share_lot(tmp_path):
    with make_client(tmp_path) as client:
        response = client.post(
            "/api/trades",
            json={
                "code": "00700",
                "name": "腾讯控股",
                "side": "buy",
                "quantity": 10,
                "price": 400,
                "logic": "港股通趋势验证",
                "funds_confirmed": True,
                "space_confirmed": True,
                "stop_loss": 380,
            },
        )
        assert response.status_code == 201
        trade = response.json()["trade"]
        assert trade["code"] == "00700"
        assert trade["currency"] == "HKD"
        assert trade["fx_rate"] == 0.87


def test_buy_requires_discipline_and_updates_review(tmp_path):
    with make_client(tmp_path) as client:
        rejected = client.post(
            "/api/trades",
            json={
                "code": "600519",
                "side": "buy",
                "quantity": 100,
                "price": 10,
                "stop_loss": 9,
            },
        )
        assert rejected.status_code == 409

        bought = client.post(
            "/api/trades",
            json={
                "code": "600519",
                "name": "贵州茅台",
                "side": "buy",
                "quantity": 100,
                "price": 10,
                "logic": "趋势向上且基本面在能力圈",
                "funds_confirmed": True,
                "space_confirmed": True,
                "stop_loss": 9,
            },
        )
        assert bought.status_code == 201
        status_response = client.get("/api/positions/status").json()
        assert status_response["items"][0]["quantity"] == 100
        assert status_response["items"][0]["stop_triggered"] is True
        assert len(status_response["alerts"]) == 1

        sold = client.post(
            "/api/trades",
            json={
                "code": "600519",
                "side": "sell",
                "quantity": 100,
                "price": 12,
                "note": "按计划止盈",
            },
        )
        assert sold.status_code == 201
        review = client.get("/api/review/stats").json()
        assert review["win_rate"] == 1.0
        assert review["realized_pnl"] == 200.0


def test_position_and_journal_crud(tmp_path):
    with make_client(tmp_path) as client:
        created_position = client.post(
            "/api/positions",
            json={
                "code": "000001",
                "name": "平安银行",
                "quantity": 100,
                "avg_price": 10,
                "stop_loss": 9,
                "thesis": "测试持仓",
            },
        )
        assert created_position.status_code == 201
        updated_position = client.put(
            "/api/positions/000001", json={"stop_loss": 9.5}
        )
        assert updated_position.json()["stop_loss"] == 9.5
        assert client.get("/api/review").status_code == 200

        created = client.post(
            "/api/journal",
            json={
                "title": "交易复盘",
                "content": "严格执行计划",
                "tags": ["纪律"],
            },
        )
        assert created.status_code == 201
        journal_id = created.json()["id"]
        updated = client.patch(
            f"/api/journal/{journal_id}", json={"mood": "冷静"}
        )
        assert updated.json()["mood"] == "冷静"
        assert client.delete(f"/api/journal/{journal_id}").json() == {"deleted": True}
        assert client.delete("/api/positions/000001").json() == {"deleted": True}
