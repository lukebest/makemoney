from backend.ai import AIService


class StubAI(AIService):
    def _complete(self, prompt: str) -> str:
        return "纪律审查完成。以上不构成投资建议。"


def test_trade_review_adds_deterministic_non_uptrend_warning():
    service = StubAI()
    result = service.review_trade(
        {
            "code": "600000",
            "price": 10,
            "quantity": 100,
            "stop_loss": 9,
            "logic": "测试",
            "funds_answer": "测试",
            "space_answer": "测试",
        },
        {
            "trend": "sideways",
            "structure": {"phase": "watch"},
            "checklist": [],
        },
        {"总资金": 100000, "已用资金": 0, "可用资金": 100000},
    )
    assert result["gate_passed"] is False
    assert "非上升趋势" in result["hard_warnings"][0]


def test_trade_review_warns_on_distribution_even_in_uptrend():
    service = StubAI()
    result = service.review_trade(
        {"code": "600000"},
        {
            "trend": "up",
            "structure": {"phase": "distribution"},
            "checklist": [],
        },
        {"总资金": 100000, "已用资金": 0, "可用资金": 100000},
    )
    assert result["gate_passed"] is False
    assert any("疑似出货" in warning for warning in result["hard_warnings"])


def test_trade_review_passes_deterministic_gate_in_markup():
    service = StubAI()
    result = service.review_trade(
        {"code": "600000"},
        {
            "trend": "up",
            "structure": {"phase": "markup"},
            "checklist": [],
        },
        {"总资金": 100000, "已用资金": 0, "可用资金": 100000},
    )
    assert result["gate_passed"] is True
    assert result["hard_warnings"] == []
