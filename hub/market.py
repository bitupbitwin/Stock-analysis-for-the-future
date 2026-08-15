"""行情取数：只为回填真实结果服务（T+N 收益、基准超额）。

刻意保持很薄：akshare 是可选依赖，没装也不影响 hub 其余部分。
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Sequence
from dataclasses import dataclass


class MarketDataUnavailable(RuntimeError):
    pass


def _require_akshare():
    try:
        import akshare as ak
    except ImportError as exc:  # pragma: no cover - 取决于环境
        raise MarketDataUnavailable(
            "需要 akshare 才能回填真实行情：pip install -r requirements.txt"
        ) from exc
    return ak


@dataclass
class Bar:
    date: str
    close: float


def _normalize(rows: Sequence[dict]) -> list[Bar]:
    out: list[Bar] = []
    for r in rows:
        date = str(r.get("日期") or r.get("date") or "")[:10]
        close = r.get("收盘") if "收盘" in r else r.get("close")
        if date and close is not None:
            out.append(Bar(date=date, close=float(close)))
    out.sort(key=lambda b: b.date)
    return out


def stock_daily(symbol: str, start: str, end: str, adjust: str = "qfq") -> list[Bar]:
    """A股个股前复权日线。symbol 为 6 位代码，如 600519。"""
    ak = _require_akshare()
    df = ak.stock_zh_a_hist(
        symbol=symbol, period="daily",
        start_date=start.replace("-", ""), end_date=end.replace("-", ""),
        adjust=adjust,
    )
    if df is None or df.empty:
        raise MarketDataUnavailable(f"未取到 {symbol} 在 {start}~{end} 的行情")
    return _normalize(df.to_dict("records"))


def index_daily(symbol: str, start: str, end: str) -> list[Bar]:
    """指数日线。默认沪深300 = 000300。"""
    ak = _require_akshare()
    df = ak.index_zh_a_hist(
        symbol=symbol, period="daily",
        start_date=start.replace("-", ""), end_date=end.replace("-", ""),
    )
    if df is None or df.empty:
        raise MarketDataUnavailable(f"未取到指数 {symbol} 在 {start}~{end} 的行情")
    return _normalize(df.to_dict("records"))


def forward_return_pct(bars: Sequence[Bar], asof_date: str, horizon_days: int) -> tuple[float, str] | None:
    """从 asof_date（含）之后第 horizon_days 个交易日的收益率。

    返回 (收益率%, 结束交易日)。数据不足则返回 None —— 宁可不打分，
    也不用不完整的数据凑一个胜率出来。
    """
    idx = next((i for i, b in enumerate(bars) if b.date >= asof_date), None)
    if idx is None:
        return None
    end_idx = idx + horizon_days
    if end_idx >= len(bars):
        return None
    start_close = bars[idx].close
    end_close = bars[end_idx].close
    if start_close <= 0:
        return None
    return (end_close / start_close - 1.0) * 100.0, bars[end_idx].date


#: A股交易日历所在时区。容器通常跑在 UTC，直接用 date.today() 会在
#: UTC 日界（北京时间 08:00 前）取到前一天，导致窗口少算一天。
CN_TZ = dt.timezone(dt.timedelta(hours=8))


def today_cn() -> dt.date:
    """北京时间的今天。"""
    return dt.datetime.now(tz=CN_TZ).date()


def window_for(asof_date: str, horizon_days: int) -> tuple[str, str]:
    """给定预测日和窗口，算出需要拉取的行情区间（含足够缓冲应对停牌/假期）。"""
    start = dt.date.fromisoformat(asof_date) - dt.timedelta(days=10)
    end = dt.date.fromisoformat(asof_date) + dt.timedelta(days=horizon_days * 2 + 30)
    return start.isoformat(), min(end, today_cn()).isoformat()
