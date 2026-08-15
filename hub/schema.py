"""统一预测记录 schema。

所有引擎的输出都会被归一化成 `Prediction`，这样才能跨引擎比较、
并在 T+N 之后用真实行情回填、计算命中率。

设计原则：预测必须是**可证伪**的。任何一条记录如果缺少
horizon_days / 概率分布 / 证伪条件，都视为不完整（`is_falsifiable()` 为 False），
在统计命中率时会被单独标记出来，而不是混进胜率里。
"""

from __future__ import annotations

import hashlib
import json
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any

# 统一方向标签
DIRECTION_UP = "up"
DIRECTION_FLAT = "flat"
DIRECTION_DOWN = "down"
DIRECTIONS = (DIRECTION_UP, DIRECTION_FLAT, DIRECTION_DOWN)

# 默认评估窗口（交易日）
DEFAULT_HORIZONS = (1, 5, 20)

# 中性带：涨跌幅绝对值小于该阈值算“震荡”，用于判定方向是否命中。
# 与 daily_stock_analysis 的 BACKTEST_NEUTRAL_BAND_PCT 默认值保持一致。
DEFAULT_NEUTRAL_BAND_PCT = 2.0


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


@dataclass
class Driver:
    """单条驱动因素（政策/新闻/技术突破/资金/技术面...）。"""

    category: str  # policy | news | tech_breakthrough | theme | capital | technical | fundamental | other
    statement: str
    weight: float = 0.0  # 0~1，引擎给出的相对重要性
    source_url: str | None = None
    source_published_at: str | None = None  # 用于检查未来数据泄漏

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class Realized:
    """回填的真实结果。"""

    horizon_days: int
    as_of: str | None = None          # 回填时间
    end_date: str | None = None       # T+N 对应的交易日
    ret_pct: float | None = None      # 个股收益率 %
    bench_ret_pct: float | None = None  # 沪深300 收益率 %
    industry_ret_pct: float | None = None  # 行业指数收益率 %
    excess_vs_bench_pct: float | None = None
    excess_vs_industry_pct: float | None = None
    realized_direction: str | None = None  # up/flat/down（按中性带判定）
    hit: bool | None = None            # 预测方向是否命中

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class Prediction:
    """一条可证伪的预测记录。"""

    # --- 身份 ---
    engine: str                       # deepear | daily_stock_analysis | ...
    symbol: str                       # 600519 / 沪深300 / AI算力 等
    prediction_id: str = field(default_factory=lambda: uuid.uuid4().hex)

    # --- 预测内容 ---
    created_at: str = field(default_factory=_utcnow)
    asof_date: str | None = None      # 预测所基于的交易日（回测时必须显式指定）
    horizon_days: int = 5
    direction: str | None = None      # up/flat/down
    p_up: float | None = None
    p_flat: float | None = None
    p_down: float | None = None
    confidence: float | None = None   # 引擎自评信心，**不等于**校准概率
    target_low: float | None = None
    target_high: float | None = None

    # --- 依据与证伪 ---
    drivers: list[Driver] = field(default_factory=list)
    falsifiers: list[str] = field(default_factory=list)  # 什么情况说明这条预测错了
    rationale: str = ""

    # --- 可复现性 ---
    inputs_snapshot: dict[str, Any] = field(default_factory=dict)  # 当时可获得的全部输入
    engine_version: str | None = None  # 引擎 git commit
    model_id: str | None = None
    raw_output_path: str | None = None  # 原始报告落盘位置

    # --- 结果回填 ---
    realized: list[Realized] = field(default_factory=list)

    symbol_kind: str = "stock"  # stock | sector | index | market

    # ------------------------------------------------------------------
    def normalize_probabilities(self) -> None:
        """把概率归一化到和为 1；若引擎只给了方向，则不臆造概率。"""
        parts = [self.p_up, self.p_flat, self.p_down]
        if any(p is None for p in parts):
            return
        total = sum(parts)  # type: ignore[arg-type]
        if total <= 0:
            return
        self.p_up, self.p_flat, self.p_down = (p / total for p in parts)  # type: ignore[misc]

    def infer_direction(self) -> str | None:
        """概率齐全时由概率推方向；否则沿用引擎给的方向。"""
        if self.direction:
            return self.direction
        parts = {
            DIRECTION_UP: self.p_up,
            DIRECTION_FLAT: self.p_flat,
            DIRECTION_DOWN: self.p_down,
        }
        if any(v is None for v in parts.values()):
            return None
        self.direction = max(parts, key=lambda k: parts[k])  # type: ignore[arg-type]
        return self.direction

    def is_falsifiable(self) -> bool:
        """判断这条预测是否够格进入命中率统计。"""
        return bool(
            self.symbol
            and self.horizon_days
            and self.infer_direction() in DIRECTIONS
            and self.falsifiers
        )

    def input_digest(self) -> str:
        """输入快照的指纹，用于判断两次预测是否基于同一批信息。"""
        blob = json.dumps(self.inputs_snapshot, sort_keys=True, ensure_ascii=False, default=str)
        return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:16]

    # ------------------------------------------------------------------
    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["input_digest"] = self.input_digest()
        d["falsifiable"] = self.is_falsifiable()
        return d

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> Prediction:
        d = dict(d)
        d.pop("input_digest", None)
        d.pop("falsifiable", None)
        drivers = [Driver(**x) if isinstance(x, dict) else x for x in d.pop("drivers", [])]
        realized = [Realized(**x) if isinstance(x, dict) else x for x in d.pop("realized", [])]
        known = {f for f in cls.__dataclass_fields__}  # type: ignore[attr-defined]
        d = {k: v for k, v in d.items() if k in known}
        obj = cls(**d)
        obj.drivers = drivers
        obj.realized = realized
        return obj


def classify_return(ret_pct: float, neutral_band_pct: float = DEFAULT_NEUTRAL_BAND_PCT) -> str:
    """按中性带把实际收益率归成 up/flat/down。"""
    if ret_pct > neutral_band_pct:
        return DIRECTION_UP
    if ret_pct < -neutral_band_pct:
        return DIRECTION_DOWN
    return DIRECTION_FLAT
