"""Cursor SDK (grok-4.5 high fast) powered interpretation and discipline coaching.

The model never predicts prices. It only turns machine-computed signals into
plain-language narratives and audits the user's own trading discipline. All
prompts pin the model to the provided data and forbid tool use, so a run is a
single text completion on a scratch directory.
"""

from __future__ import annotations

import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .market import TTLCache

MODEL_ID = "grok-4.5"
MODEL_LABEL = "Cursor Grok 4.5 · high · fast"

_COMMON_RULES = """
你是一位克制、专业的 A 股交易纪律教练，信奉“顺势而为、仓位管理、严格止损”。
规则：
- 只依据下面提供的数据推理，绝不编造数据中没有的数字或消息面信息。
- 不要预测目标价，不要给出买卖指令，结尾用一句话提醒“以上不构成投资建议”。
- 用简体中文、平实的段落回答，不用 markdown 标题和表格，全文不超过 300 字。
- 不要使用任何工具，不要读写文件，直接给出回答。
"""


class AIService:
    """Thin wrapper around the Cursor SDK for one-shot text completions."""

    def __init__(self, cache: TTLCache | None = None) -> None:
        self.cache = cache or TTLCache()

    @property
    def available(self) -> bool:
        if not os.getenv("CURSOR_API_KEY"):
            return False
        try:
            import cursor_sdk  # noqa: F401
        except ImportError:
            return False
        return True

    def status(self) -> dict[str, Any]:
        return {"available": self.available, "model": MODEL_LABEL}

    def interpret_stock(self, analysis: dict[str, Any]) -> dict[str, Any]:
        """Narrate the diagnosis page's machine signals for one stock."""
        key = f"ai:interpret:{analysis.get('code')}:{analysis.get('updated_at', '')}"
        return self.cache.get_or_load(
            key, 900, lambda: self._interpret_stock(analysis)
        )

    def _interpret_stock(self, analysis: dict[str, Any]) -> dict[str, Any]:
        klines = analysis.get("klines") or []
        recent = klines[-20:]
        digest = {
            "代码": analysis.get("code"),
            "名称": analysis.get("name"),
            "市场": "港股" if analysis.get("market") == "HK" else "A股",
            "现价": analysis.get("price"),
            "今日涨跌幅%": analysis.get("change_pct"),
            "趋势判定": analysis.get("trend"),
            "近20日支撑": analysis.get("support"),
            "近20日压力": analysis.get("resistance"),
            "入场检查": [
                {"项": item.get("label"), "通过": bool(item.get("passed"))}
                for item in analysis.get("checklist") or []
            ],
            "缠论结构": analysis.get("chan"),
            "近20日收盘": [round(float(row["close"]), 2) for row in recent],
            "近20日成交量": [float(row.get("volume", 0)) for row in recent],
        }
        prompt = (
            f"{_COMMON_RULES}\n"
            "任务：为散户解读下面这只股票的机器信号。说明当前趋势结构意味着什么、"
            "哪些检查项没通过及其含义、缠论中枢/类三买（如有）该怎么理解，"
            "最后给出这只票当前“该做的事”（观察/等待/若持有注意什么），落脚在纪律而非预测。\n\n"
            f"数据：\n{json.dumps(digest, ensure_ascii=False)}"
        )
        return self._respond(prompt)

    def review_trade(
        self,
        trade: dict[str, Any],
        analysis: dict[str, Any] | None,
        portfolio: dict[str, Any],
    ) -> dict[str, Any]:
        """Audit the user's buy-gate answers before the order is recorded."""
        digest: dict[str, Any] = {
            "拟买入": {
                "代码": trade.get("code"),
                "价格": trade.get("price"),
                "数量": trade.get("quantity"),
                "预设止损价": trade.get("stop_loss"),
            },
            "买入三问回答": {
                "为什么涨": trade.get("logic"),
                "谁在买": trade.get("funds_answer"),
                "还能涨吗": trade.get("space_answer"),
            },
            "账户": portfolio,
        }
        if analysis:
            digest["该股机器信号"] = {
                "趋势判定": analysis.get("trend"),
                "现价": analysis.get("price"),
                "近20日支撑": analysis.get("support"),
                "近20日压力": analysis.get("resistance"),
                "入场检查": [
                    {"项": item.get("label"), "通过": bool(item.get("passed"))}
                    for item in analysis.get("checklist") or []
                ],
                "缠论结构": analysis.get("chan"),
            }
        prompt = (
            f"{_COMMON_RULES}\n"
            "任务：作为买入前的最后一道纪律关卡，审查这位散户的“买入三问”回答。逐问指出："
            "回答是否具体可验证，还是含糊、情绪化（如“感觉要涨”“别人都在买”）；"
            "止损价与仓位是否合理；回答是否与该股机器信号矛盾（如逆势抄底、追高）。"
            "最后给出明确结论：这次买入理由“扎实 / 勉强 / 不成立”，以及最需要补答的一个问题。\n\n"
            f"数据：\n{json.dumps(digest, ensure_ascii=False)}"
        )
        return self._respond(prompt)

    def review_report(
        self, stats: dict[str, Any], trades: list[dict[str, Any]]
    ) -> dict[str, Any]:
        """Turn review statistics and the recent ledger into a coaching report."""
        key = f"ai:report:{stats.get('total_trades')}:{stats.get('realized_pnl')}"
        recent = [
            {
                "日期": str(row.get("traded_at", ""))[:16],
                "代码": row.get("code"),
                "方向": row.get("side"),
                "价格": row.get("price"),
                "数量": row.get("quantity"),
                "已实现盈亏": row.get("realized_pnl"),
                "买入逻辑": (str(row.get("logic") or ""))[:80],
                "备注": (str(row.get("note") or ""))[:80],
                "违纪": bool(row.get("violated")),
            }
            for row in trades[:20]
        ]
        digest = {"统计": stats, "最近交易": recent}
        prompt = (
            f"{_COMMON_RULES}\n"
            "任务：根据统计和最近交易记录写一份复盘。指出：胜率与盈亏比说明了什么问题"
            "（比如拿不住盈利、止损不坚决）；从买入逻辑文本里找出重复出现的坏习惯；"
            "违纪记录意味着什么。最后给出下阶段最该改的一件事，要具体可执行。"
            "若交易样本太少，就直说样本不足，别过度解读。\n\n"
            f"数据：\n{json.dumps(digest, ensure_ascii=False)}"
        )
        return self.cache.get_or_load(key, 600, lambda: self._respond(prompt))

    def _respond(self, prompt: str) -> dict[str, Any]:
        text = self._complete(prompt)
        return {
            "text": text,
            "model": MODEL_LABEL,
            "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        }

    def _complete(self, prompt: str) -> str:
        from cursor_sdk import (
            Agent,
            AgentOptions,
            CursorAgentError,
            LocalAgentOptions,
            ModelParameterValue,
            ModelSelection,
            SandboxOptions,
        )

        scratch = Path(tempfile.gettempdir()) / "makemoney-ai-scratch"
        scratch.mkdir(exist_ok=True)
        try:
            result = Agent.prompt(
                prompt,
                AgentOptions(
                    model=ModelSelection(
                        id=MODEL_ID,
                        params=[
                            ModelParameterValue(id="effort", value="high"),
                            ModelParameterValue(id="fast", value="true"),
                        ],
                    ),
                    local=LocalAgentOptions(
                        cwd=str(scratch),
                        sandbox_options=SandboxOptions(enabled=False),
                    ),
                ),
            )
        except CursorAgentError as exc:
            raise RuntimeError(f"AI 服务调用失败：{str(exc)[:200]}") from exc
        if result.status != "finished" or not result.result:
            raise RuntimeError(f"AI 运行未完成（状态 {result.status}）")
        return str(result.result).strip()
