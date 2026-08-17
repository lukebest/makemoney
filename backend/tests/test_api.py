import time

from fastapi.testclient import TestClient

from backend.main import create_app


class DummyCache:
    def clear(self):
        return None

    def peek(self, key):
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

    def close_screen(self, max_candidates=None, on_progress=None):
        result = {
            "items": [
                {
                    "code": "600519",
                    "name": "贵州茅台",
                    "score": 100,
                    "setup": "重点观察",
                    "change_pct": 3.2,
                    "amount": 1e9,
                    "checks": [
                        {"key": "volume_pile", "label": "主力入场有量", "status": "passed", "detail": ""},
                        {"key": "controlled_washout", "label": "洗盘短而可控", "status": "passed", "detail": ""},
                        {"key": "price_volume_shift", "label": "洗盘后价量重心上移", "status": "passed", "detail": ""},
                        {"key": "startup_signal", "label": "强势启动信号", "status": "passed", "detail": ""},
                        {"key": "active_sector", "label": "处在活跃板块", "status": "passed", "detail": ""},
                    ],
                }
            ],
            "source": "akshare",
            "analyzed_count": max_candidates or 240,
            "universe_count": 320,
            "match_count": 1,
            "rejected_by": {"volume_pile": 180, "liquidity": 20},
            "active_sectors": ["医疗器械"],
            "as_of_date": "2026-07-16",
            "for_date": "2026-07-17",
            "after_close": True,
            "session_kind": "today_close",
            "updated_at": "2026-07-16T15:05:00+00:00",
        }
        if on_progress:
            on_progress(
                {
                    "total": result["analyzed_count"],
                    "checked": result["analyzed_count"],
                    "matches": result["match_count"],
                }
            )
        return result

    def mainline(self):
        return {
            "source": "test",
            "main_sector": "医疗器械",
            "active_sectors": ["医疗器械"],
            "sectors": [],
            "ladders": [],
            "leaders": [],
        }


class DummyAI:
    available = True

    def __init__(self):
        self.calls = []

    def status(self):
        return {"available": self.available, "model": "dummy"}

    def interpret_stock(self, analysis):
        self.calls.append(("interpret", analysis["code"]))
        return {"text": f"解读 {analysis['code']}", "model": "dummy"}

    def review_trade(self, trade, analysis, portfolio):
        self.calls.append(("review_trade", trade["code"]))
        assert "总资金" in portfolio
        return {"text": "买入理由勉强", "model": "dummy"}

    def review_report(self, stats, trades):
        self.calls.append(("report", stats["total_trades"]))
        return {"text": "复盘报告", "model": "dummy"}


class UnavailableAI(DummyAI):
    available = False


def make_client(tmp_path, ai=None):
    app = create_app(tmp_path / "test.db", DummyMarket(), ai_service=ai or DummyAI())
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
        assert client.get("/api/market/mainline").json()["main_sector"] == "医疗器械"
        empty = client.get("/api/market/preferred/close-screen")
        assert empty.status_code == 200
        assert empty.json()["items"] == []
        screened = client.post("/api/market/preferred/close-screen")
        assert screened.status_code == 200
        payload = screened.json()
        for _ in range(40):
            if payload.get("job", {}).get("status") != "running":
                break
            time.sleep(0.05)
            payload = client.get("/api/market/preferred/close-screen").json()
        assert payload["job"]["status"] == "done"
        assert payload["job"]["checked"] == payload["analyzed_count"]
        assert payload["job"]["matches"] == 1
        saved = client.get("/api/market/preferred/close-screen?for_date=2026-07-17")
        assert saved.status_code == 200
        assert saved.json()["items"][0]["code"] == "600519"
        assert saved.json()["match_count"] == 1
        assert saved.json()["universe_count"] == 320
        assert saved.json()["for_date"] == "2026-07-17"
        assert saved.json()["session_kind"] == "today_close"
        briefing = client.get("/api/today")
        assert briefing.status_code == 200
        assert "session" in briefing.json()
        assert "action" in briefing.json()["session"]
        assert "needs_run" in briefing.json()["close_screen"]


def test_stock_serves_snapshot_when_cache_cold(tmp_path):
    with make_client(tmp_path) as client:
        client.app.state.db.save_snapshot(
            "stock:600519:120",
            {
                "code": "600519",
                "name": "贵州茅台",
                "klines": [{"date": "2026-07-16", "open": 1, "close": 2, "high": 3, "low": 1, "volume": 10}],
                "source": "akshare",
            },
        )
        payload = client.get("/api/stocks/600519").json()
        assert payload["stale"] is True
        assert payload["klines"][0]["date"] == "2026-07-16"


def test_preferred_serves_snapshot_when_cache_cold(tmp_path):
    with make_client(tmp_path) as client:
        client.app.state.db.save_snapshot(
            "preferred",
            {
                "items": [{"code": "000001", "name": "平安银行", "score": 60, "setup": "继续跟踪"}],
                "source": "akshare",
                "analyzed_count": 12,
            },
        )
        payload = client.get("/api/market/preferred?limit=1&candidates=3").json()
        assert payload["stale"] is True
        assert payload["items"][0]["code"] == "000001"


def test_today_flags_buy_off_the_close_screen_list(tmp_path):
    with make_client(tmp_path) as client:
        session = client.get("/api/today").json()["session"]
        plan_date = (
            session["as_of_date"]
            if session["code"] in ("after_close", "weekend")
            else session["for_date"]
        )
        client.app.state.db.save_close_screen(
            {
                "items": [{"code": "600519", "name": "贵州茅台", "score": 100}],
                "as_of_date": "2020-01-01",
                "for_date": plan_date,
                "match_count": 1,
            }
        )
        bought = client.post(
            "/api/trades",
            json={
                "code": "000001",
                "name": "平安银行",
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
        discipline = client.get("/api/today").json()["discipline"]
        assert discipline["has_plan"] is True
        assert "600519" in discipline["plan_codes"]
        assert discipline["off_list"][0]["code"] == "000001"
        review = client.get("/api/review").json()
        assert review["violations"] == 1
        assert review["violation_items"][0]["code"] == "000001"


def test_close_screen_needs_run_when_saved_as_of_is_stale(tmp_path):
    with make_client(tmp_path) as client:
        client.app.state.db.save_close_screen(
            {
                "items": [],
                "as_of_date": "2020-01-02",
                "for_date": "2020-01-03",
                "match_count": 0,
            }
        )
        briefing = client.get("/api/today").json()
        saved = client.get("/api/market/preferred/close-screen").json()
        assert saved["needs_run"] == briefing["close_screen"]["needs_run"]
        if briefing["session"]["code"] in ("after_close", "weekend"):
            assert briefing["close_screen"]["needs_run"] is True


def test_today_attaches_live_change_when_spot_is_warm(tmp_path):
    class WarmCache(DummyCache):
        def peek(self, key):
            if key == "market:spot":
                return {"source": "akshare", "items": []}
            return None

    class WarmMarket(DummyMarket):
        cache = WarmCache()

    app = create_app(tmp_path / "test.db", WarmMarket(), ai_service=DummyAI())
    with TestClient(app) as client:
        client.app.state.db.save_close_screen(
            {
                "items": [
                    {"code": "600519", "name": "贵州茅台", "score": 100, "change_pct": 3.2}
                ],
                "as_of_date": "2026-07-16",
                "for_date": "2026-07-17",
                "match_count": 1,
            }
        )
        pick = client.get("/api/today").json()["close_screen"]["items"][0]
        assert pick["code"] == "600519"
        assert pick["live_price"] == 8.0
        assert pick["live_change_pct"] == -1.0


def test_positions_status_uses_saved_quotes_when_spot_cold(tmp_path):
    with make_client(tmp_path) as client:
        created = client.post(
            "/api/positions",
            json={
                "code": "000001",
                "name": "平安银行",
                "quantity": 100,
                "avg_price": 10,
                "stop_loss": 9,
            },
        )
        assert created.status_code == 201
        client.app.state.db.save_snapshot(
            "position-quotes",
            {"000001": {"price": 8.0, "change_pct": -2.0, "source": "akshare"}},
        )
        payload = client.get("/api/positions/status").json()
        assert payload["stale"] is True
        assert payload["items"][0]["live_price"] == 8.0
        assert payload["items"][0]["stop_triggered"] is True


def test_today_reads_stop_alerts_from_saved_quotes(tmp_path):
    with make_client(tmp_path) as client:
        created = client.post(
            "/api/positions",
            json={
                "code": "000001",
                "name": "平安银行",
                "quantity": 100,
                "avg_price": 10,
                "stop_loss": 9,
            },
        )
        assert created.status_code == 201
        client.app.state.db.save_snapshot(
            "position-quotes",
            {"000001": {"price": 8.0, "change_pct": -2.0, "source": "test"}},
        )
        briefing = client.get("/api/today").json()
        assert briefing["position_count"] == 1
        assert briefing["stops"][0]["code"] == "000001"


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


def test_position_limit_error_explains_cost_and_limit(tmp_path):
    with make_client(tmp_path) as client:
        response = client.post(
            "/api/positions",
            json={
                "code": "600519",
                "name": "贵州茅台",
                "quantity": 100,
                "avg_price": 1240,
                "stop_loss": 1178,
            },
        )
        assert response.status_code == 409
        detail = response.json()["detail"]
        assert "持仓成本 ¥124,000.00" in detail
        assert "单股仓位上限 ¥30,000.00" in detail


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


def test_ai_endpoints(tmp_path):
    ai = DummyAI()
    with make_client(tmp_path, ai) as client:
        assert client.get("/api/ai/status").json()["available"] is True
        interpret = client.post("/api/ai/interpret/600519")
        assert interpret.status_code == 200
        assert "600519" in interpret.json()["text"]

        review = client.post(
            "/api/ai/review-trade",
            json={
                "code": "600519",
                "price": 10,
                "quantity": 100,
                "stop_loss": 9,
                "logic": "趋势向上",
                "funds_answer": "放量",
                "space_answer": "空间足够",
            },
        )
        assert review.status_code == 200
        report = client.post("/api/ai/review-report")
        assert report.status_code == 200
        assert [name for name, _ in ai.calls] == ["interpret", "review_trade", "report"]


def test_ai_unavailable_returns_503(tmp_path):
    with make_client(tmp_path, UnavailableAI()) as client:
        assert client.get("/api/ai/status").json()["available"] is False
        assert client.post("/api/ai/interpret/600519").status_code == 503
        assert client.post("/api/ai/review-trade", json={"code": "600519"}).status_code == 503
        assert client.post("/api/ai/review-report").status_code == 503


def test_ai_interpret_refuses_sample_data(tmp_path):
    class SampleMarket(DummyMarket):
        def stock_daily(self, code, days):
            return {"code": code, "klines": [], "source": "sample", "days": days}

    app = create_app(tmp_path / "sample.db", SampleMarket(), ai_service=DummyAI())
    with TestClient(app) as client:
        assert client.post("/api/ai/interpret/600519").status_code == 409


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
        assert client.get("/api/today").json()["has_journal"] is True
        updated = client.patch(
            f"/api/journal/{journal_id}", json={"mood": "冷静"}
        )
        assert updated.json()["mood"] == "冷静"
        assert client.delete(f"/api/journal/{journal_id}").json() == {"deleted": True}
        assert client.delete("/api/positions/000001").json() == {"deleted": True}
