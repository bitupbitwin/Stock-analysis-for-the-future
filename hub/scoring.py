"""回填真实结果 + 统计命中率。

这是把"看起来很专业的研报"和"可验证的预测"区分开的那一层。
没有这一层，前面四个引擎输出的都只是意见。
"""

from __future__ import annotations

import datetime as dt
from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass, field

from . import market
from .schema import Prediction, Realized, classify_return


@dataclass
class ScoreReport:
    engine: str
    horizon_days: int
    n_scored: int = 0
    n_hit: int = 0
    avg_ret_pct: float = 0.0
    avg_excess_vs_bench_pct: float = 0.0
    by_direction: dict[str, tuple[int, int]] = field(default_factory=dict)  # dir -> (hit, total)

    @property
    def hit_rate(self) -> float | None:
        return self.n_hit / self.n_scored if self.n_scored else None

    def render(self) -> str:
        hr = "n/a" if self.hit_rate is None else f"{self.hit_rate:.1%}"
        lines = [
            (
                f"[{self.engine}] T+{self.horizon_days}  样本={self.n_scored}  "
                f"方向命中率={hr}  平均收益={self.avg_ret_pct:+.2f}%  "
                f"平均超额(vs基准)={self.avg_excess_vs_bench_pct:+.2f}%"
            )
        ]
        for direction, (hit, total) in sorted(self.by_direction.items()):
            rate = f"{hit / total:.1%}" if total else "n/a"
            lines.append(f"    预测{direction:<5} {hit}/{total} = {rate}")
        return "\n".join(lines)


def score_prediction(
    pred: Prediction,
    horizon_days: int,
    *,
    benchmark: str = "000300",
    neutral_band_pct: float = 2.0,
) -> Realized | None:
    """给单条预测回填 T+N 结果。数据不足返回 None。"""
    if pred.symbol_kind != "stock":
        return None  # 板块/指数预测需要各自的指数代码，见 README 的"已知限制"
    asof = pred.asof_date or pred.created_at[:10]
    try:
        dt.date.fromisoformat(asof)
    except ValueError:
        return None

    start, end = market.window_for(asof, horizon_days)
    try:
        bars = market.stock_daily(pred.symbol, start, end)
    except market.MarketDataUnavailable:
        return None

    got = market.forward_return_pct(bars, asof, horizon_days)
    if got is None:
        return None  # 窗口还没走完
    ret_pct, end_date = got

    bench_ret = None
    try:
        bench_bars = market.index_daily(benchmark, start, end)
        bench_got = market.forward_return_pct(bench_bars, asof, horizon_days)
        if bench_got:
            bench_ret = bench_got[0]
    except market.MarketDataUnavailable:
        bench_ret = None

    realized_dir = classify_return(ret_pct, neutral_band_pct)
    predicted_dir = pred.infer_direction()

    return Realized(
        horizon_days=horizon_days,
        as_of=dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
        end_date=end_date,
        ret_pct=round(ret_pct, 4),
        bench_ret_pct=None if bench_ret is None else round(bench_ret, 4),
        excess_vs_bench_pct=None if bench_ret is None else round(ret_pct - bench_ret, 4),
        realized_direction=realized_dir,
        hit=None if predicted_dir is None else (predicted_dir == realized_dir),
    )


def aggregate(preds: Iterable[Prediction], horizon_days: int) -> list[ScoreReport]:
    """按引擎汇总命中率。只统计有 realized 且 hit 非空的记录。"""
    buckets: dict[str, list[tuple[Prediction, Realized]]] = defaultdict(list)
    for p in preds:
        for r in p.realized:
            if r.horizon_days == horizon_days and r.hit is not None:
                buckets[p.engine].append((p, r))

    reports = []
    for engine, items in sorted(buckets.items()):
        rep = ScoreReport(engine=engine, horizon_days=horizon_days, n_scored=len(items))
        rep.n_hit = sum(1 for _, r in items if r.hit)
        rets = [r.ret_pct for _, r in items if r.ret_pct is not None]
        rep.avg_ret_pct = sum(rets) / len(rets) if rets else 0.0
        exc = [r.excess_vs_bench_pct for _, r in items if r.excess_vs_bench_pct is not None]
        rep.avg_excess_vs_bench_pct = sum(exc) / len(exc) if exc else 0.0

        by_dir: dict[str, list[int]] = defaultdict(lambda: [0, 0])
        for p, r in items:
            d = p.infer_direction() or "unknown"
            by_dir[d][1] += 1
            if r.hit:
                by_dir[d][0] += 1
        rep.by_direction = {k: (v[0], v[1]) for k, v in by_dir.items()}
        reports.append(rep)
    return reports


def driver_hit_rates(preds: Iterable[Prediction], horizon_days: int) -> dict[str, tuple[int, int]]:
    """按驱动因素类别统计命中率 —— 回答"政策信号到底准不准"。"""
    stats: dict[str, list[int]] = defaultdict(lambda: [0, 0])
    for p in preds:
        realized = next(
            (r for r in p.realized if r.horizon_days == horizon_days and r.hit is not None),
            None,
        )
        if realized is None:
            continue
        for category in {d.category for d in p.drivers}:
            stats[category][1] += 1
            if realized.hit:
                stats[category][0] += 1
    return {k: (v[0], v[1]) for k, v in sorted(stats.items())}
