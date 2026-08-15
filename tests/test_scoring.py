"""回填与命中率统计测试（不联网，用构造好的 bar 序列）。"""

from __future__ import annotations

from hub import market, scoring
from hub.schema import DIRECTION_DOWN, DIRECTION_UP, Driver, Prediction, Realized


def _bars(closes, start_day=1):
    return [
        market.Bar(date=f"2026-08-{start_day + i:02d}", close=c)
        for i, c in enumerate(closes)
    ]


def test_forward_return_uses_nth_trading_day():
    bars = _bars([100.0, 101.0, 102.0, 105.0, 110.0])
    got = market.forward_return_pct(bars, "2026-08-01", 3)
    assert got is not None
    ret, end_date = got
    assert abs(ret - 5.0) < 1e-9        # 100 -> 105
    assert end_date == "2026-08-04"


def test_forward_return_none_when_window_incomplete():
    """窗口没走完就不打分 —— 宁可没样本，也不要假样本。"""
    bars = _bars([100.0, 101.0])
    assert market.forward_return_pct(bars, "2026-08-01", 5) is None


def test_forward_return_starts_at_first_bar_on_or_after_asof():
    """预测日停牌/非交易日时，从之后第一个交易日算起。"""
    bars = _bars([100.0, 110.0, 120.0], start_day=3)
    got = market.forward_return_pct(bars, "2026-08-01", 1)
    assert got is not None
    assert abs(got[0] - 10.0) < 1e-9


def test_window_for_covers_horizon_with_buffer():
    start, end = market.window_for("2020-08-14", 20)
    assert start < "2020-08-14" < end


def test_window_end_never_exceeds_today():
    """未来区间要截断到今天，否则数据源会报错。"""
    import datetime as dt

    future = (market.today_cn() + dt.timedelta(days=5)).isoformat()
    _, end = market.window_for(future, 20)
    assert end == market.today_cn().isoformat()


def test_today_cn_uses_beijing_time():
    """容器跑在 UTC 时，'今天'必须按北京时间算，否则窗口会少一天。"""
    import datetime as dt

    utc_now = dt.datetime.now(tz=dt.timezone.utc)
    assert market.today_cn() == (utc_now + dt.timedelta(hours=8)).date()


def _scored(engine, predicted, realized_dir, ret, excess):
    p = Prediction(
        engine=engine, symbol="600519", horizon_days=5,
        direction=predicted, falsifiers=["x"],
        drivers=[Driver(category="policy", statement="降准")],
    )
    p.realized = [Realized(
        horizon_days=5, ret_pct=ret, excess_vs_bench_pct=excess,
        realized_direction=realized_dir, hit=(predicted == realized_dir),
    )]
    return p


def test_aggregate_computes_hit_rate_per_engine():
    preds = [
        _scored("deepear", DIRECTION_UP, DIRECTION_UP, 5.0, 3.0),
        _scored("deepear", DIRECTION_UP, DIRECTION_DOWN, -4.0, -6.0),
        _scored("deepear", DIRECTION_UP, DIRECTION_UP, 3.0, 1.0),
        _scored("daily_stock_analysis", DIRECTION_DOWN, DIRECTION_DOWN, -3.0, -1.0),
    ]
    reports = {r.engine: r for r in scoring.aggregate(preds, 5)}

    de = reports["deepear"]
    assert de.n_scored == 3
    assert de.n_hit == 2
    assert abs(de.hit_rate - 2 / 3) < 1e-9
    assert abs(de.avg_ret_pct - (5.0 - 4.0 + 3.0) / 3) < 1e-9
    assert abs(de.avg_excess_vs_bench_pct - (3.0 - 6.0 + 1.0) / 3) < 1e-9
    assert de.by_direction[DIRECTION_UP] == (2, 3)

    assert reports["daily_stock_analysis"].hit_rate == 1.0


def test_aggregate_ignores_unscored_predictions():
    unscored = Prediction(engine="deepear", symbol="600519", direction=DIRECTION_UP)
    assert scoring.aggregate([unscored], 5) == []


def test_aggregate_ignores_other_horizons():
    p = _scored("deepear", DIRECTION_UP, DIRECTION_UP, 5.0, 3.0)
    assert scoring.aggregate([p], 20) == []


def test_driver_hit_rates_group_by_category():
    a = _scored("deepear", DIRECTION_UP, DIRECTION_UP, 5.0, 3.0)
    b = _scored("deepear", DIRECTION_UP, DIRECTION_DOWN, -5.0, -3.0)
    b.drivers = [Driver(category="policy", statement="x"), Driver(category="capital", statement="y")]

    rates = scoring.driver_hit_rates([a, b], 5)
    assert rates["policy"] == (1, 2)
    assert rates["capital"] == (0, 1)


def test_score_report_renders_without_crashing():
    reports = scoring.aggregate([_scored("deepear", DIRECTION_UP, DIRECTION_UP, 5.0, 3.0)], 5)
    text = reports[0].render()
    assert "deepear" in text and "T+5" in text


def test_sector_predictions_are_skipped_not_faked():
    """板块级预测暂不打分，但必须显式返回 None，而不是编个结果。"""
    p = Prediction(engine="aiagents_stock", symbol="算力", symbol_kind="sector",
                   direction=DIRECTION_UP, asof_date="2026-08-01")
    assert scoring.score_prediction(p, 5) is None
