"""预测台账：SQLite 持久化。

只写不改。每条预测一旦落库，其预测内容字段不再修改；
后续只允许追加 realized 回填结果。这是防止"事后改预测"的最低要求。
"""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from .schema import Prediction, Realized

SCHEMA = """
CREATE TABLE IF NOT EXISTS predictions (
    prediction_id   TEXT PRIMARY KEY,
    engine          TEXT NOT NULL,
    symbol          TEXT NOT NULL,
    symbol_kind     TEXT NOT NULL DEFAULT 'stock',
    created_at      TEXT NOT NULL,
    asof_date       TEXT,
    horizon_days    INTEGER NOT NULL,
    direction       TEXT,
    p_up            REAL,
    p_flat          REAL,
    p_down          REAL,
    confidence      REAL,
    target_low      REAL,
    target_high     REAL,
    falsifiable     INTEGER NOT NULL DEFAULT 0,
    input_digest    TEXT,
    engine_version  TEXT,
    model_id        TEXT,
    raw_output_path TEXT,
    payload         TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_pred_engine  ON predictions(engine);
CREATE INDEX IF NOT EXISTS idx_pred_symbol  ON predictions(symbol);
CREATE INDEX IF NOT EXISTS idx_pred_created ON predictions(created_at);

CREATE TABLE IF NOT EXISTS realized (
    prediction_id        TEXT NOT NULL,
    horizon_days         INTEGER NOT NULL,
    as_of                TEXT,
    end_date             TEXT,
    ret_pct              REAL,
    bench_ret_pct        REAL,
    industry_ret_pct     REAL,
    excess_vs_bench_pct  REAL,
    excess_vs_industry_pct REAL,
    realized_direction   TEXT,
    hit                  INTEGER,
    PRIMARY KEY (prediction_id, horizon_days),
    FOREIGN KEY (prediction_id) REFERENCES predictions(prediction_id)
);

CREATE TABLE IF NOT EXISTS runs (
    run_id      TEXT PRIMARY KEY,
    engine      TEXT NOT NULL,
    started_at  TEXT NOT NULL,
    finished_at TEXT,
    status      TEXT NOT NULL,
    request     TEXT,
    stderr_tail TEXT
);
"""


class Store:
    def __init__(self, db_path: Path):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with self._conn() as conn:
            conn.executescript(SCHEMA)

    @contextmanager
    def _conn(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self.db_path, timeout=30)
        conn.row_factory = sqlite3.Row
        try:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA foreign_keys=ON")
            yield conn
            conn.commit()
        finally:
            conn.close()

    # ------------------------------------------------------------------
    def save(self, pred: Prediction) -> str:
        d = pred.to_dict()
        with self._conn() as conn:
            conn.execute(
                """INSERT OR IGNORE INTO predictions (
                    prediction_id, engine, symbol, symbol_kind, created_at, asof_date,
                    horizon_days, direction, p_up, p_flat, p_down, confidence,
                    target_low, target_high, falsifiable, input_digest,
                    engine_version, model_id, raw_output_path, payload
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    d["prediction_id"], d["engine"], d["symbol"], d["symbol_kind"],
                    d["created_at"], d["asof_date"], d["horizon_days"], d["direction"],
                    d["p_up"], d["p_flat"], d["p_down"], d["confidence"],
                    d["target_low"], d["target_high"], int(d["falsifiable"]),
                    d["input_digest"], d["engine_version"], d["model_id"],
                    d["raw_output_path"],
                    json.dumps(d, ensure_ascii=False, default=str),
                ),
            )
        for r in pred.realized:
            self.save_realized(pred.prediction_id, r)
        return pred.prediction_id

    def save_many(self, preds: list[Prediction]) -> int:
        for p in preds:
            self.save(p)
        return len(preds)

    def save_realized(self, prediction_id: str, r: Realized) -> None:
        with self._conn() as conn:
            conn.execute(
                """INSERT OR REPLACE INTO realized (
                    prediction_id, horizon_days, as_of, end_date, ret_pct,
                    bench_ret_pct, industry_ret_pct, excess_vs_bench_pct,
                    excess_vs_industry_pct, realized_direction, hit
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    prediction_id, r.horizon_days, r.as_of, r.end_date, r.ret_pct,
                    r.bench_ret_pct, r.industry_ret_pct, r.excess_vs_bench_pct,
                    r.excess_vs_industry_pct, r.realized_direction,
                    None if r.hit is None else int(r.hit),
                ),
            )

    # ------------------------------------------------------------------
    def get(self, prediction_id: str) -> Prediction | None:
        with self._conn() as conn:
            row = conn.execute(
                "SELECT payload FROM predictions WHERE prediction_id=?", (prediction_id,)
            ).fetchone()
        if not row:
            return None
        pred = Prediction.from_dict(json.loads(row["payload"]))
        pred.realized = self.realized_for(prediction_id)
        return pred

    def realized_for(self, prediction_id: str) -> list[Realized]:
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT * FROM realized WHERE prediction_id=? ORDER BY horizon_days",
                (prediction_id,),
            ).fetchall()
        out = []
        for row in rows:
            out.append(
                Realized(
                    horizon_days=row["horizon_days"], as_of=row["as_of"],
                    end_date=row["end_date"], ret_pct=row["ret_pct"],
                    bench_ret_pct=row["bench_ret_pct"],
                    industry_ret_pct=row["industry_ret_pct"],
                    excess_vs_bench_pct=row["excess_vs_bench_pct"],
                    excess_vs_industry_pct=row["excess_vs_industry_pct"],
                    realized_direction=row["realized_direction"],
                    hit=None if row["hit"] is None else bool(row["hit"]),
                )
            )
        return out

    def list_predictions(
        self, *, engine: str | None = None, symbol: str | None = None, limit: int = 200
    ) -> list[Prediction]:
        sql = "SELECT payload, prediction_id FROM predictions WHERE 1=1"
        args: list = []
        if engine:
            sql += " AND engine=?"
            args.append(engine)
        if symbol:
            sql += " AND symbol=?"
            args.append(symbol)
        sql += " ORDER BY created_at DESC LIMIT ?"
        args.append(limit)
        with self._conn() as conn:
            rows = conn.execute(sql, args).fetchall()
        out = []
        for row in rows:
            p = Prediction.from_dict(json.loads(row["payload"]))
            p.realized = self.realized_for(row["prediction_id"])
            out.append(p)
        return out

    def pending_scoring(self, horizon_days: int) -> list[Prediction]:
        """还没回填该窗口结果的预测。"""
        with self._conn() as conn:
            rows = conn.execute(
                """SELECT p.payload, p.prediction_id FROM predictions p
                   LEFT JOIN realized r
                     ON r.prediction_id = p.prediction_id AND r.horizon_days = ?
                   WHERE r.prediction_id IS NULL AND p.falsifiable = 1
                   ORDER BY p.created_at""",
                (horizon_days,),
            ).fetchall()
        return [Prediction.from_dict(json.loads(r["payload"])) for r in rows]

    def record_run(
        self, run_id: str, engine: str, started_at: str, finished_at: str | None,
        status: str, request: str, stderr_tail: str = "",
    ) -> None:
        with self._conn() as conn:
            conn.execute(
                """INSERT OR REPLACE INTO runs
                   (run_id, engine, started_at, finished_at, status, request, stderr_tail)
                   VALUES (?,?,?,?,?,?,?)""",
                (run_id, engine, started_at, finished_at, status, request, stderr_tail[-4000:]),
            )

    def counts(self) -> dict[str, int]:
        with self._conn() as conn:
            total = conn.execute("SELECT COUNT(*) c FROM predictions").fetchone()["c"]
            fals = conn.execute(
                "SELECT COUNT(*) c FROM predictions WHERE falsifiable=1"
            ).fetchone()["c"]
            scored = conn.execute("SELECT COUNT(*) c FROM realized").fetchone()["c"]
        return {"predictions": total, "falsifiable": fals, "realized_rows": scored}
