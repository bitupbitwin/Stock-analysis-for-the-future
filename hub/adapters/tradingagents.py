"""TradingAgents-astock 适配器。

上游没有"输出 JSON"的入口，只有 TradingAgentsGraph.propagate(ticker, date)。
所以这里注入一个 driver 脚本（scripts/drivers/tradingagents_driver.py），
在引擎自己的 venv 里 import 上游包、跑图、把结果 dump 成 JSON。
上游代码本身一行不改。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from ..schema import Driver, Prediction
from .base import Adapter, AnalysisRequest, normalize_a_share_code, parse_direction

DRIVER_SCRIPT = Path("scripts") / "drivers" / "tradingagents_driver.py"

# 7 位分析师 -> 统一的驱动因素类别
_ANALYST_CATEGORY = {
    "market_report": "technical",
    "news_report": "news",
    "sentiment_report": "theme",
    "fundamentals_report": "fundamental",
    "policy_report": "policy",
    "hotmoney_report": "capital",
    "unlock_report": "capital",
}


class TradingAgentsAdapter(Adapter):
    name = "tradingagents_astock"

    def run(self, request: AnalysisRequest) -> list[Prediction]:
        from .. import config, runner

        if not request.symbols:
            raise ValueError("tradingagents_astock 需要至少一个标的：--symbols 600519")

        driver_abs = config.REPO_ROOT / DRIVER_SCRIPT
        if not driver_abs.exists():
            raise FileNotFoundError(f"缺少 driver 脚本: {driver_abs}")

        out_dir = self.reports_dir / self.name
        out_dir.mkdir(parents=True, exist_ok=True)

        preds: list[Prediction] = []
        for symbol in request.symbols:
            code = normalize_a_share_code(symbol)
            out_path = out_dir / f"{code}_{request.asof_date or 'latest'}.json"
            args = [
                str(driver_abs),
                "--ticker", code,
                "--date", request.asof_date or "",
                "--out", str(out_path),
                "--max-debate-rounds", str(request.extra.get("max_debate_rounds", 1)),
            ]
            result = runner.run(
                self.name, args, self.settings_values, timeout=request.timeout
            )
            if not out_path.exists():
                raise RuntimeError(
                    f"TradingAgents 未产出结果 (rc={result.returncode})。\n"
                    f"stderr 末尾:\n{result.stderr[-1500:]}"
                )
            preds.extend(self.parse_output(out_path, request))
        return preds

    # ------------------------------------------------------------------
    def parse_output(self, path: Path, request: AnalysisRequest) -> list[Prediction]:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return []

        code = normalize_a_share_code(str(data.get("ticker") or ""))
        if not code:
            return []

        decision = data.get("decision")
        decision_text = decision if isinstance(decision, str) else json.dumps(
            decision, ensure_ascii=False
        )
        direction = parse_direction(decision_text)

        state: dict[str, Any] = data.get("final_state") or {}
        drivers = []
        for key, category in _ANALYST_CATEGORY.items():
            report = state.get(key)
            if isinstance(report, str) and report.strip():
                drivers.append(
                    Driver(category=category, statement=report.strip()[:400], weight=1.0 / 7)
                )

        # 多空辩论本身就是最好的证伪材料
        falsifiers = ["窗口内跑输沪深300 视为本条判断无超额价值"]
        debate = state.get("investment_debate_state") or {}
        bear = debate.get("bear_history") or debate.get("bear_report")
        if isinstance(bear, str) and bear.strip():
            falsifiers.insert(0, f"空头论点若兑现即证伪：{bear.strip()[:300]}")
        risk = state.get("risk_debate_state") or {}
        if isinstance(risk.get("judge_decision"), str):
            falsifiers.append(f"风险委员会意见：{risk['judge_decision'][:300]}")

        pred = self._base_prediction(
            code, request,
            direction=direction,
            rationale=decision_text[:4000],
            falsifiers=falsifiers,
            raw_output_path=str(path),
            model_id=data.get("model_id"),
        )
        pred.drivers = drivers
        pred.inputs_snapshot = {
            "trade_date": data.get("trade_date"),
            "config": data.get("config_summary"),
            "analyst_reports_present": [k for k in _ANALYST_CATEGORY if state.get(k)],
            "bull_bear_rounds": debate.get("count"),
        }
        if pred.asof_date is None and data.get("trade_date"):
            pred.asof_date = str(data["trade_date"])[:10]
        # 上游只给方向不给概率 —— 就不编概率，留 None
        return [pred]
