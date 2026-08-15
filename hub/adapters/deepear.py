"""DeepEar 适配器。

调用: python src/main_flow.py --query ... --sources all --depth auto --run-id <id>
读取: reports/checkpoints/<run_id>/report_structured.json
      reports/checkpoints/<run_id>/analyzed_signals.json

DeepEar 的 InvestmentSignal 自带 sentiment_score(-1~1) / confidence(0~1) /
intensity(1~5) / expected_horizon / impact_tickers，是五个引擎里最接近
"可结构化预测"的一个，所以这里做完整字段映射。
"""

from __future__ import annotations

import json
import uuid
from pathlib import Path
from typing import Any

from ..schema import Driver, Prediction
from .base import (
    Adapter,
    AnalysisRequest,
    normalize_a_share_code,
    sentiment_to_probabilities,
)

# DeepEar 的 expected_horizon 形如 "T+0" / "T+3" / "Long-term"
_HORIZON_FALLBACK = {"t+0": 1, "t+1": 1, "t+3": 3, "t+5": 5, "long-term": 20, "t+n": 5}


def _horizon_days(raw: str | None, default: int) -> int:
    if not raw:
        return default
    key = str(raw).strip().lower()
    if key in _HORIZON_FALLBACK:
        return _HORIZON_FALLBACK[key]
    if key.startswith("t+") and key[2:].isdigit():
        return max(1, int(key[2:]))
    return default


def _probabilities(sentiment: float, confidence: float) -> tuple[float, float, float]:
    """DeepEar 的 sentiment_score(-1~1) + confidence(0~1) -> 三分类概率。

    confidence 低时把质量拉回无信息先验，避免"低置信度却给出 90% 上涨"。
    """
    return sentiment_to_probabilities(sentiment, confidence)


class DeepEarAdapter(Adapter):
    name = "deepear"

    def run(self, request: AnalysisRequest) -> list[Prediction]:
        from .. import runner

        run_id = f"saf_{uuid.uuid4().hex[:10]}"
        query = request.query or self._default_query(request)
        args = [
            "src/main_flow.py",
            "--query", query,
            "--sources", str(request.extra.get("sources", "all")),
            "--depth", str(request.extra.get("depth", "auto")),
            "--wide", str(request.extra.get("wide", 10)),
            "--run-id", run_id,
        ]
        result = runner.run(
            self.name, args, self.settings_values, timeout=request.timeout
        )
        ckpt = runner.engine_dir(self.name) / "reports" / "checkpoints" / run_id
        preds = self.parse_checkpoint(ckpt, request)
        if not preds and not result.ok:
            raise RuntimeError(
                f"DeepEar 运行失败 (rc={result.returncode})，且未产出结构化报告。\n"
                f"stderr 末尾:\n{result.stderr[-1500:]}"
            )
        return preds

    def _default_query(self, request: AnalysisRequest) -> str:
        symbols = "、".join(request.symbols) if request.symbols else "A股市场"
        return (
            f"分析近期政策、行业新闻与技术突破对 {symbols} 未来"
            f"{request.horizon_days} 个交易日走势的影响"
        )

    # ------------------------------------------------------------------
    def parse_checkpoint(self, ckpt_dir: Path, request: AnalysisRequest) -> list[Prediction]:
        """从 checkpoint 目录解析预测。抽成独立方法便于离线测试。"""
        signals_path = ckpt_dir / "analyzed_signals.json"
        if not signals_path.exists():
            return []
        try:
            signals = json.loads(signals_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return []
        if isinstance(signals, dict):
            signals = signals.get("items", [])

        structured_path = ckpt_dir / "report_structured.json"
        structured: dict[str, Any] = {}
        if structured_path.exists():
            try:
                structured = json.loads(structured_path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                structured = {}

        out: list[Prediction] = []
        for sig in signals:
            if not isinstance(sig, dict):
                continue
            out.extend(self._signal_to_predictions(sig, request, ckpt_dir, structured))
        return out

    def _signal_to_predictions(
        self, sig: dict[str, Any], request: AnalysisRequest,
        ckpt_dir: Path, structured: dict[str, Any],
    ) -> list[Prediction]:
        sentiment = float(sig.get("sentiment_score") or 0.0)
        confidence = float(sig.get("confidence") or 0.5)
        p_up, p_flat, p_down = _probabilities(sentiment, confidence)
        horizon = _horizon_days(sig.get("expected_horizon"), request.horizon_days)

        drivers = [
            Driver(
                category="news",
                statement=str(sig.get("title") or "")[:400],
                weight=min(1.0, float(sig.get("intensity") or 3) / 5.0),
                source_url=(sig.get("sources") or [{}])[0].get("url")
                if isinstance(sig.get("sources"), list) and sig.get("sources") else None,
            )
        ]
        for node in sig.get("transmission_chain") or []:
            if isinstance(node, dict):
                drivers.append(
                    Driver(
                        category="theme",
                        statement=f"{node.get('node_name', '')}: {node.get('logic', '')}"[:400],
                        weight=0.3,
                    )
                )

        falsifiers: list[str] = []
        price_in = sig.get("price_in_status")
        if price_in and price_in != "未知":
            falsifiers.append(f"若市场已{price_in}，事件驱动的超额收益不成立")
        gap = sig.get("expectation_gap")
        if gap is not None:
            falsifiers.append(f"若预期差({gap})被后续公告证伪，该信号失效")
        falsifiers.append("若该信号相关标的在窗口内跑输沪深300，则本条逻辑不成立")

        tickers = sig.get("impact_tickers") or []
        symbols: list[tuple[str, float]] = []
        for t in tickers:
            if isinstance(t, dict):
                code = t.get("code") or t.get("ticker") or t.get("symbol")
                if code:
                    symbols.append((normalize_a_share_code(str(code)), float(t.get("weight") or 1.0)))
            elif isinstance(t, str):
                symbols.append((normalize_a_share_code(t), 1.0))

        if not symbols and request.symbols:
            symbols = [(normalize_a_share_code(s), 1.0) for s in request.symbols]
        if not symbols:
            return []

        preds = []
        for code, weight in symbols:
            pred = self._base_prediction(
                code, request,
                p_up=round(p_up, 4), p_flat=round(p_flat, 4), p_down=round(p_down, 4),
                confidence=confidence,
                rationale=str(sig.get("reasoning") or sig.get("summary") or "")[:4000],
                falsifiers=falsifiers,
                raw_output_path=str(ckpt_dir),
            )
            pred.horizon_days = horizon
            pred.drivers = drivers
            pred.inputs_snapshot = {
                "signal_id": sig.get("signal_id"),
                "title": sig.get("title"),
                "industry_tags": sig.get("industry_tags"),
                "sources": sig.get("sources"),
                "sentiment_score": sentiment,
                "intensity": sig.get("intensity"),
                "expectation_gap": gap,
                "timeliness": sig.get("timeliness"),
                "price_in_status": price_in,
                "ticker_weight": weight,
                "report_title": structured.get("title"),
            }
            pred.normalize_probabilities()
            pred.infer_direction()
            preds.append(pred)
        return preds
