"""统一 schema + 台账测试。"""

from __future__ import annotations

from hub.schema import (
    DIRECTION_DOWN,
    DIRECTION_FLAT,
    DIRECTION_UP,
    Driver,
    Prediction,
    Realized,
    classify_return,
)
from hub.store import Store


def _pred(**kwargs) -> Prediction:
    base = {
        "engine": "deepear", "symbol": "600519", "horizon_days": 5,
        "p_up": 0.6, "p_flat": 0.3, "p_down": 0.1,
        "falsifiers": ["跌破 1500 视为失效"],
    }
    base.update(kwargs)
    return Prediction(**base)


def test_probabilities_normalize_to_one():
    p = _pred(p_up=6, p_flat=3, p_down=1)
    p.normalize_probabilities()
    assert abs(p.p_up + p.p_flat + p.p_down - 1.0) < 1e-9
    assert abs(p.p_up - 0.6) < 1e-9


def test_direction_inferred_from_probabilities():
    assert _pred().infer_direction() == DIRECTION_UP
    assert _pred(p_up=0.1, p_flat=0.2, p_down=0.7).infer_direction() == DIRECTION_DOWN
    assert _pred(p_up=0.2, p_flat=0.6, p_down=0.2).infer_direction() == DIRECTION_FLAT


def test_no_probabilities_means_no_invented_direction():
    """引擎没给概率就不能凭空造一个方向出来。"""
    p = _pred(p_up=None, p_flat=None, p_down=None)
    assert p.infer_direction() is None


def test_falsifiability_requires_falsifiers():
    assert _pred().is_falsifiable()
    assert not _pred(falsifiers=[]).is_falsifiable()


def test_falsifiability_requires_a_direction():
    p = _pred(p_up=None, p_flat=None, p_down=None)
    assert not p.is_falsifiable()


def test_input_digest_is_stable_and_sensitive():
    a = _pred(inputs_snapshot={"news": ["a", "b"], "score": 1})
    b = _pred(inputs_snapshot={"score": 1, "news": ["a", "b"]})  # 顺序不同
    c = _pred(inputs_snapshot={"news": ["a", "c"], "score": 1})
    assert a.input_digest() == b.input_digest()
    assert a.input_digest() != c.input_digest()


def test_classify_return_respects_neutral_band():
    assert classify_return(3.0, 2.0) == DIRECTION_UP
    assert classify_return(1.5, 2.0) == DIRECTION_FLAT
    assert classify_return(-5.0, 2.0) == DIRECTION_DOWN
    # 调宽中性带后同一个收益会被判成震荡
    assert classify_return(3.0, 5.0) == DIRECTION_FLAT


def test_roundtrip_through_dict():
    p = _pred(drivers=[Driver(category="policy", statement="降准", weight=0.8)])
    restored = Prediction.from_dict(p.to_dict())
    assert restored.symbol == p.symbol
    assert restored.drivers[0].category == "policy"
    assert restored.p_up == p.p_up


def test_store_saves_and_reads_back(tmp_path):
    store = Store(tmp_path / "t.db")
    p = _pred(drivers=[Driver(category="news", statement="利好")])
    store.save(p)

    got = store.get(p.prediction_id)
    assert got is not None
    assert got.symbol == "600519"
    assert got.drivers[0].statement == "利好"
    assert store.counts()["predictions"] == 1
    assert store.counts()["falsifiable"] == 1


def test_store_is_idempotent(tmp_path):
    """同一条预测重复保存不应产生第二行 —— 台账只写不改。"""
    store = Store(tmp_path / "t.db")
    p = _pred()
    store.save(p)
    store.save(p)
    assert store.counts()["predictions"] == 1


def test_realized_backfill_and_pending_query(tmp_path):
    store = Store(tmp_path / "t.db")
    p = _pred()
    store.save(p)

    assert [x.prediction_id for x in store.pending_scoring(5)] == [p.prediction_id]

    store.save_realized(
        p.prediction_id,
        Realized(horizon_days=5, ret_pct=4.2, bench_ret_pct=1.0,
                 excess_vs_bench_pct=3.2, realized_direction=DIRECTION_UP, hit=True),
    )
    assert store.pending_scoring(5) == []
    got = store.get(p.prediction_id)
    assert got.realized[0].hit is True
    assert got.realized[0].excess_vs_bench_pct == 3.2


def test_non_falsifiable_predictions_excluded_from_scoring_queue(tmp_path):
    """不可证伪的记录不该进命中率统计队列。"""
    store = Store(tmp_path / "t.db")
    store.save(_pred(falsifiers=[]))
    assert store.pending_scoring(5) == []


def test_list_filters_by_engine(tmp_path):
    store = Store(tmp_path / "t.db")
    store.save(_pred(engine="deepear"))
    store.save(_pred(engine="daily_stock_analysis", symbol="000001"))
    assert len(store.list_predictions(engine="deepear")) == 1
    assert len(store.list_predictions()) == 2
