"""适配器基类 + 中文方向/概率解析工具。"""

from __future__ import annotations

import re
from abc import ABC, abstractmethod
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ..schema import DIRECTION_DOWN, DIRECTION_FLAT, DIRECTION_UP, Prediction


@dataclass
class AnalysisRequest:
    """跨引擎统一的请求。各适配器按需取用自己支持的字段。"""

    symbols: list[str] = field(default_factory=list)
    query: str = ""                      # 自然语言问题（DeepEar / advisor 用）
    asof_date: str | None = None         # 回测时固定的"当时"
    horizon_days: int = 5
    timeout: int = 3600
    extra: dict[str, Any] = field(default_factory=dict)


# 中文方向词 -> 统一标签。顺序有意义：先匹配更长更具体的词。
_DIRECTION_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"强烈看多|坚定看多|极度看多"), DIRECTION_UP),
    (re.compile(r"看多|偏多|多头|上涨|买入|增持|走强|突破"), DIRECTION_UP),
    (re.compile(r"看空|偏空|空头|下跌|卖出|减持|走弱|破位"), DIRECTION_DOWN),
    (re.compile(r"震荡|观望|中性|横盘|持有|盘整"), DIRECTION_FLAT),
]

_EN_DIRECTION = {
    "buy": DIRECTION_UP, "strong_buy": DIRECTION_UP, "bullish": DIRECTION_UP,
    "long": DIRECTION_UP, "up": DIRECTION_UP,
    "sell": DIRECTION_DOWN, "strong_sell": DIRECTION_DOWN, "bearish": DIRECTION_DOWN,
    "short": DIRECTION_DOWN, "down": DIRECTION_DOWN,
    "hold": DIRECTION_FLAT, "neutral": DIRECTION_FLAT, "flat": DIRECTION_FLAT,
}


def parse_direction(text: str | None) -> str | None:
    """从中英文结论文本里提取方向。提取不到返回 None —— 不猜。"""
    if not text:
        return None
    lowered = text.strip().lower()
    if lowered in _EN_DIRECTION:
        return _EN_DIRECTION[lowered]
    for token, direction in _EN_DIRECTION.items():
        if re.search(rf"\b{re.escape(token)}\b", lowered):
            return direction
    for pattern, direction in _DIRECTION_PATTERNS:
        if pattern.search(text):
            return direction
    return None


def parse_percent(text: str | None, keywords: tuple[str, ...]) -> float | None:
    """从 '乐观情景 概率 45%' 这类文本里抽概率。"""
    if not text:
        return None
    for kw in keywords:
        m = re.search(rf"{re.escape(kw)}[^0-9%]{{0,20}}?(\d{{1,3}}(?:\.\d+)?)\s*%", text)
        if m:
            value = float(m.group(1))
            if 0 <= value <= 100:
                return value / 100.0
    return None


def sentiment_to_probabilities(
    sentiment: float, confidence: float = 0.8
) -> tuple[float, float, float]:
    """把 (情绪 -1~1, 置信度 0~1) 映射成 (p_up, p_flat, p_down)。

    做法是把"信号隐含分布"和"无信息先验(1/3,1/3,1/3)"按 confidence 线性混合：

        raw   = (max(s,0), 1-|s|, max(-s,0))     # 信号本身隐含的分布
        p     = c * raw + (1-c) * (1/3,1/3,1/3)  # 置信度越低越靠回先验

    这样低置信度会把质量拉向均匀分布（p_flat 上升、多空差距收窄），
    但**不会翻转 argmax** —— 一个中等强度的看空信号仍然判为看空，
    而不是因为置信度不满分就被压成"震荡"。

    **这是启发式映射，不是校准概率。** 它只是让不同引擎的输出能落进同一张
    表里比较；真正的可信度只能由 `hub score` 用实际收益回填统计出来。
    """
    s = max(-1.0, min(1.0, float(sentiment)))
    c = max(0.0, min(1.0, float(confidence)))
    prior = 1.0 / 3.0
    raw = (max(s, 0.0), 1.0 - abs(s), max(-s, 0.0))
    return tuple(c * r + (1.0 - c) * prior for r in raw)  # type: ignore[return-value]


def score_to_probabilities(
    score: float, *, lo: float = 0.0, hi: float = 100.0, confidence: float = 0.8
) -> tuple[float, float, float]:
    """把引擎的 0~100 情绪分映射成三分类概率。

    注意：概率是**分数**的忠实变换，而引擎自己的方向标签（如"看多"）单独保留。
    两者偶尔会不一致（比如评分 30 但标签写"看空"，概率仍偏震荡）——
    这时以引擎标签为准，不去粉饰这个分歧。
    """
    span = hi - lo or 1.0
    norm = max(0.0, min(1.0, (score - lo) / span))  # 0~1
    return sentiment_to_probabilities(2.0 * norm - 1.0, confidence)


def normalize_a_share_code(symbol: str) -> str:
    """把 sh600519 / 600519.SH / 600519 统一成 600519。"""
    s = symbol.strip().upper()
    s = re.sub(r"^(SH|SZ|BJ)", "", s)
    s = re.sub(r"\.(SH|SZ|BJ)$", "", s)
    m = re.search(r"\d{6}", s)
    return m.group(0) if m else symbol.strip()


class Adapter(ABC):
    """每个引擎一个适配器。

    职责边界：适配器**只负责调用和翻译**，绝不修改上游代码，
    也绝不替上游编造它没输出的东西（缺失就是缺失，落库为 None）。
    """

    name: str
    #: 该引擎能否在无人值守下跑完整流程
    headless: bool = True

    def __init__(self, settings_values: Mapping[str, str], reports_dir: Path):
        self.settings_values = settings_values
        self.reports_dir = reports_dir

    @abstractmethod
    def run(self, request: AnalysisRequest) -> list[Prediction]:
        """执行一次分析，返回归一化后的预测列表。"""

    # 供子类复用
    def _base_prediction(self, symbol: str, request: AnalysisRequest, **kwargs: Any) -> Prediction:
        from .. import runner  # 局部导入避免循环

        return Prediction(
            engine=self.name,
            symbol=symbol,
            asof_date=request.asof_date,
            horizon_days=request.horizon_days,
            engine_version=runner.engine_commit(self.name),
            **kwargs,
        )
