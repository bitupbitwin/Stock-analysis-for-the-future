"""daily_stock_analysis (DSA) 适配器。

调用: python main.py         （STOCK_LIST 由导通层从 SAF_WATCHLIST 注入）
读取: <engine>/data/stock_analysis.db 的 analysis_history 表

DSA 把每次分析写进 analysis_history：
  code / name / sentiment_score / operation_advice / trend_prediction /
  analysis_summary / context_snapshot / ideal_buy / stop_loss / take_profit
context_snapshot 正好就是"当时可获得的全部输入"，直接进 inputs_snapshot。
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

from ..schema import Driver, Prediction
from .base import (
    Adapter,
    AnalysisRequest,
    normalize_a_share_code,
    parse_direction,
    score_to_probabilities,
)

DB_RELATIVE = Path("data") / "stock_analysis.db"


class DailyStockAdapter(Adapter):
    name = "daily_stock_analysis"

    def run(self, request: AnalysisRequest) -> list[Prediction]:
        from .. import runner

        watchlist = request.symbols or [
            s.strip() for s in (self.settings_values.get("SAF_WATCHLIST") or "").split(",") if s.strip()
        ]
        if not watchlist:
            raise ValueError("daily_stock_analysis 需要自选股：设置 SAF_WATCHLIST 或传 --symbols")

        db_path = runner.engine_dir(self.name) / DB_RELATIVE
        seen_before = self._max_id(db_path)

        result = runner.run(
            self.name, ["main.py"], self.settings_values,
            timeout=request.timeout,
            overrides={"STOCK_LIST": ",".join(watchlist)},
        )
        preds = self.parse_db(db_path, request, after_id=seen_before)
        if not preds and not result.ok:
            raise RuntimeError(
                f"daily_stock_analysis 运行失败 (rc={result.returncode})，且未写入新记录。\n"
                f"stderr 末尾:\n{result.stderr[-1500:]}"
            )
        return preds

    # ------------------------------------------------------------------
    @staticmethod
    def _max_id(db_path: Path) -> int:
        """跑之前记下水位线，之后只取新增记录。"""
        if not db_path.exists():
            return 0
        try:
            conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True, timeout=15)
            try:
                row = conn.execute("SELECT MAX(id) FROM analysis_history").fetchone()
                return int(row[0] or 0)
            finally:
                conn.close()
        except sqlite3.Error:
            return 0

    def parse_db(
        self, db_path: Path, request: AnalysisRequest, *, after_id: int = 0
    ) -> list[Prediction]:
        """读取 analysis_history 新增行并归一化。"""
        if not db_path.exists():
            return []
        try:
            conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True, timeout=15)
        except sqlite3.Error:
            return []
        conn.row_factory = sqlite3.Row
        try:
            rows = conn.execute(
                """SELECT * FROM analysis_history
                   WHERE id > ? ORDER BY id""",
                (after_id,),
            ).fetchall()
        except sqlite3.Error:
            return []
        finally:
            conn.close()

        return [p for row in rows if (p := self._row_to_prediction(dict(row), request, db_path))]

    def _row_to_prediction(
        self, row: dict[str, Any], request: AnalysisRequest, db_path: Path
    ) -> Prediction | None:
        code = row.get("code")
        if not code:
            return None

        direction = parse_direction(row.get("trend_prediction")) or parse_direction(
            row.get("operation_advice")
        )

        # DSA 的 sentiment_score 是 0~100 的整数
        score = row.get("sentiment_score")
        p_up = p_flat = p_down = None
        if score is not None:
            p_up, p_flat, p_down = score_to_probabilities(float(score))

        snapshot: dict[str, Any] = {
            "name": row.get("name"),
            "report_type": row.get("report_type"),
            "sentiment_score": score,
            "operation_advice": row.get("operation_advice"),
            "trend_prediction": row.get("trend_prediction"),
            "ideal_buy": row.get("ideal_buy"),
            "stop_loss": row.get("stop_loss"),
            "take_profit": row.get("take_profit"),
            "dsa_created_at": row.get("created_at"),
        }
        raw_snapshot = row.get("context_snapshot")
        if raw_snapshot:
            try:
                snapshot["context"] = json.loads(raw_snapshot)
            except (json.JSONDecodeError, TypeError):
                snapshot["context_raw"] = str(raw_snapshot)[:20000]

        drivers = [
            Driver(category="technical", statement=f"DSA 综合评分 {score}", weight=0.5)
        ]
        summary = row.get("analysis_summary")
        if summary:
            drivers.append(Driver(category="news", statement=str(summary)[:400], weight=0.5))

        falsifiers = []
        if row.get("stop_loss"):
            falsifiers.append(f"跌破止损位 {row['stop_loss']} 视为该判断失效")
        if row.get("take_profit"):
            falsifiers.append(f"未触及目标位 {row['take_profit']} 则上涨逻辑未兑现")
        falsifiers.append("窗口内跑输沪深300 视为本条判断无超额价值")

        pred = self._base_prediction(
            normalize_a_share_code(str(code)), request,
            direction=direction,
            p_up=p_up, p_flat=p_flat, p_down=p_down,
            confidence=None if score is None else round(float(score) / 100.0, 4),
            target_low=row.get("ideal_buy"),
            target_high=row.get("take_profit"),
            rationale=str(summary or "")[:4000],
            falsifiers=falsifiers,
            raw_output_path=str(db_path),
        )
        pred.drivers = drivers
        pred.inputs_snapshot = snapshot
        if pred.asof_date is None and row.get("created_at"):
            pred.asof_date = str(row["created_at"])[:10]
        pred.normalize_probabilities()
        pred.infer_direction()
        return pred
