"""aiagents-stock（智瞰龙虎）适配器。

上游是 Streamlit 优先的项目，但 `LonghubangEngine.run_comprehensive_analysis()`
是可无头调用的。走 driver 脚本 -> JSON，同时也支持直接读它的 longhubang.db。

⚠️ 该引擎输出的是"次日大概率上涨"的**Agent 评分**，不是校准概率；
confidence 字段是"高/中/低"文字。这里如实映射，不做概率包装。
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

from ..schema import DIRECTION_UP, Driver, Prediction
from .base import Adapter, AnalysisRequest, normalize_a_share_code

DRIVER_SCRIPT = Path("scripts") / "drivers" / "aiagents_driver.py"
DB_RELATIVE = Path("longhubang.db")

_CONFIDENCE_MAP = {"高": 0.75, "中": 0.5, "低": 0.25}


def _to_float(value: Any) -> float | None:
    """'待定' / '' / None -> None；数字字符串 -> float。"""
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip()
    if not text or text in {"待定", "-", "N/A", "无"}:
        return None
    try:
        return float(text.replace(",", "").rstrip("元"))
    except ValueError:
        return None


class AiAgentsAdapter(Adapter):
    name = "aiagents_stock"

    def run(self, request: AnalysisRequest) -> list[Prediction]:
        from .. import config, runner

        driver_abs = config.REPO_ROOT / DRIVER_SCRIPT
        if not driver_abs.exists():
            raise FileNotFoundError(f"缺少 driver 脚本: {driver_abs}")

        out_dir = self.reports_dir / self.name
        out_dir.mkdir(parents=True, exist_ok=True)
        out_path = out_dir / f"longhubang_{request.asof_date or 'latest'}.json"

        args = [
            str(driver_abs),
            "--date", request.asof_date or "",
            "--days", str(request.extra.get("days", 1)),
            "--out", str(out_path),
        ]
        result = runner.run(self.name, args, self.settings_values, timeout=request.timeout)
        if not out_path.exists():
            raise RuntimeError(
                f"aiagents-stock 未产出结果 (rc={result.returncode})。\n"
                f"stderr 末尾:\n{result.stderr[-1500:]}"
            )
        return self.parse_output(out_path, request)

    # ------------------------------------------------------------------
    def parse_output(self, path: Path, request: AnalysisRequest) -> list[Prediction]:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return []
        return self._from_recommendations(
            data.get("recommended_stocks") or [], request, str(path),
            analysis_date=data.get("timestamp"),
            report=data.get("final_report") or {},
        )

    def parse_db(self, db_path: Path, request: AnalysisRequest, *, limit: int = 5) -> list[Prediction]:
        """从 longhubang.db 的 longhubang_analysis 表读最近的推荐。"""
        if not db_path.exists():
            return []
        try:
            conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True, timeout=15)
        except sqlite3.Error:
            return []
        conn.row_factory = sqlite3.Row
        try:
            rows = conn.execute(
                "SELECT * FROM longhubang_analysis ORDER BY id DESC LIMIT ?", (limit,)
            ).fetchall()
        except sqlite3.Error:
            return []
        finally:
            conn.close()

        out: list[Prediction] = []
        for row in rows:
            try:
                recs = json.loads(row["recommended_stocks"] or "[]")
            except (json.JSONDecodeError, TypeError):
                continue
            out.extend(
                self._from_recommendations(
                    recs, request, str(db_path),
                    analysis_date=row["analysis_date"],
                    report={"summary": row["summary"]},
                )
            )
        return out

    def _from_recommendations(
        self, recs: list[Any], request: AnalysisRequest, raw_path: str,
        *, analysis_date: str | None, report: dict[str, Any],
    ) -> list[Prediction]:
        out: list[Prediction] = []
        for rec in recs:
            if not isinstance(rec, dict):
                continue
            code = rec.get("code")
            if not code:
                continue

            confidence = _CONFIDENCE_MAP.get(str(rec.get("confidence", "")).strip())
            stop_loss = _to_float(rec.get("stop_loss"))
            target = _to_float(rec.get("target_price"))

            falsifiers = ["窗口内跑输沪深300 视为本条判断无超额价值"]
            if stop_loss is not None:
                falsifiers.insert(0, f"跌破止损位 {stop_loss} 视为该推荐失效")
            falsifiers.append("若龙虎榜席位次日净卖出，说明游资出货、推荐逻辑被证伪")

            pred = self._base_prediction(
                normalize_a_share_code(str(code)), request,
                # 该引擎只产出"看多候选"，从不给看空标的 —— 如实记录方向为 up，
                # 由 hub score 用实际收益去验证这个偏多倾向的真实胜率。
                direction=DIRECTION_UP,
                confidence=confidence,
                target_high=target,
                target_low=stop_loss,
                rationale=str(rec.get("reason") or "")[:4000],
                falsifiers=falsifiers,
                raw_output_path=raw_path,
            )
            pred.horizon_days = request.extra.get("horizon_days", request.horizon_days)
            pred.drivers = [
                Driver(
                    category="capital",
                    statement=str(rec.get("reason") or "龙虎榜资金净流入")[:400],
                    weight=1.0,
                )
            ]
            pred.inputs_snapshot = {
                "rank": rec.get("rank"),
                "name": rec.get("name"),
                "net_inflow": rec.get("net_inflow"),
                "confidence_label": rec.get("confidence"),
                "hold_period": rec.get("hold_period"),
                "analysis_date": analysis_date,
                "report_summary": report.get("summary"),
            }
            if pred.asof_date is None and analysis_date:
                pred.asof_date = str(analysis_date)[:10]
            out.append(pred)
        return out
