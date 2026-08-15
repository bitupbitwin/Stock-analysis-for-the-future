"""适配器注册表。"""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path

from .advisor import AdvisorAdapter
from .aiagents import AiAgentsAdapter
from .base import Adapter, AnalysisRequest
from .daily_stock import DailyStockAdapter
from .deepear import DeepEarAdapter
from .tradingagents import TradingAgentsAdapter

ADAPTERS: dict[str, type[Adapter]] = {
    DeepEarAdapter.name: DeepEarAdapter,
    DailyStockAdapter.name: DailyStockAdapter,
    TradingAgentsAdapter.name: TradingAgentsAdapter,
    AiAgentsAdapter.name: AiAgentsAdapter,
    AdvisorAdapter.name: AdvisorAdapter,
}

#: 可以无人值守跑的引擎（`hub run --engine all` 只跑这些）
HEADLESS_ENGINES = [name for name, cls in ADAPTERS.items() if cls.headless]


def get_adapter(name: str, settings_values: Mapping[str, str], reports_dir: Path) -> Adapter:
    try:
        cls = ADAPTERS[name]
    except KeyError as exc:
        raise KeyError(
            f"未知引擎 {name!r}，可选: {', '.join(sorted(ADAPTERS))}"
        ) from exc
    return cls(settings_values, reports_dir)


__all__ = [
    "ADAPTERS", "HEADLESS_ENGINES", "Adapter", "AnalysisRequest", "get_adapter",
]
