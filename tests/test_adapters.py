"""适配器解析测试 —— 全部离线，用伪造的上游产物驱动。

这些 fixture 的字段名来自各上游仓库的真实 schema：
  DeepEar   : src/schema/models.py 的 InvestmentSignal
  DSA       : src/storage.py 的 analysis_history 表
  TA-astock : TradingAgentsGraph.propagate 的返回
  aiagents  : longhubang_engine._extract_recommended_stocks 的输出
"""

from __future__ import annotations

import json
import sqlite3

from hub.adapters import AnalysisRequest
from hub.adapters.advisor import AdvisorAdapter
from hub.adapters.aiagents import AiAgentsAdapter
from hub.adapters.base import (
    normalize_a_share_code,
    parse_direction,
    score_to_probabilities,
)
from hub.adapters.daily_stock import DailyStockAdapter
from hub.adapters.deepear import DeepEarAdapter
from hub.adapters.tradingagents import TradingAgentsAdapter
from hub.schema import DIRECTION_DOWN, DIRECTION_FLAT, DIRECTION_UP

REQ = AnalysisRequest(symbols=["600519"], horizon_days=5, asof_date="2026-08-14")


# ---------------------------------------------------------------- 通用工具
def test_parse_direction_chinese():
    assert parse_direction("看多，建议买入") == DIRECTION_UP
    assert parse_direction("短期看空，破位") == DIRECTION_DOWN
    assert parse_direction("震荡观望") == DIRECTION_FLAT
    assert parse_direction("BUY") == DIRECTION_UP
    assert parse_direction("") is None
    assert parse_direction("无法判断") is None


def test_normalize_a_share_code():
    assert normalize_a_share_code("sh600519") == "600519"
    assert normalize_a_share_code("600519.SH") == "600519"
    assert normalize_a_share_code("600519") == "600519"


def test_score_to_probabilities_sums_to_one():
    for score in (0, 25, 50, 75, 100):
        probs = score_to_probabilities(score)
        assert abs(sum(probs) - 1.0) < 1e-9
    assert score_to_probabilities(90)[0] > score_to_probabilities(10)[0]


def test_score_to_probabilities_argmax_matches_score_side():
    """高分要真的判成看多，不能被震荡权重吃掉。"""
    p_up, p_flat, p_down = score_to_probabilities(78)
    assert p_up == max(p_up, p_flat, p_down)

    # 50 分是中性，应判震荡
    assert score_to_probabilities(50)[1] == max(score_to_probabilities(50))

    # 低分应判看跌
    assert score_to_probabilities(15)[2] == max(score_to_probabilities(15))


def test_sentiment_blend_keeps_argmax_across_confidence():
    """置信度只该收窄差距，不该翻转方向 —— 这是之前的 bug。"""
    from hub.adapters.base import sentiment_to_probabilities

    for conf in (0.3, 0.5, 0.7, 0.9):
        p_up, p_flat, p_down = sentiment_to_probabilities(-0.6, conf)
        assert p_down == max(p_up, p_flat, p_down), f"conf={conf} 时方向被压平了"


def test_sentiment_blend_shrinks_toward_uniform_at_low_confidence():
    from hub.adapters.base import sentiment_to_probabilities

    strong = sentiment_to_probabilities(0.9, 0.95)
    weak = sentiment_to_probabilities(0.9, 0.05)
    assert strong[0] > weak[0]                       # 高置信 -> 更极端
    assert max(weak) - min(weak) < max(strong) - min(strong)
    assert all(abs(p - 1 / 3) < 0.05 for p in weak)  # 低置信 -> 近似均匀


# ---------------------------------------------------------------- DeepEar
def test_deepear_parses_signal_into_prediction(tmp_path):
    ckpt = tmp_path / "run1"
    ckpt.mkdir()
    (ckpt / "analyzed_signals.json").write_text(json.dumps([{
        "signal_id": "sig_1",
        "title": "国常会部署算力基础设施建设",
        "summary": "政策利好算力板块",
        "reasoning": "财政支持落地，产业链受益",
        "sentiment_score": 0.8,
        "confidence": 0.9,
        "intensity": 5,
        "expectation_gap": 0.7,
        "expected_horizon": "T+3",
        "price_in_status": "部分定价",
        "industry_tags": ["算力", "AI"],
        "impact_tickers": [{"code": "600519", "weight": 0.8}],
        "transmission_chain": [
            {"node_name": "上游芯片", "impact_type": "利好", "logic": "订单增加"}
        ],
        "sources": [{"title": "新闻", "url": "https://example.com/a"}],
    }]), encoding="utf-8")
    (ckpt / "report_structured.json").write_text(
        json.dumps({"title": "算力专题"}), encoding="utf-8"
    )

    preds = DeepEarAdapter({}, tmp_path).parse_checkpoint(ckpt, REQ)
    assert len(preds) == 1
    p = preds[0]
    assert p.symbol == "600519"
    assert p.engine == "deepear"
    assert p.horizon_days == 3           # 来自 expected_horizon="T+3"
    assert p.direction == DIRECTION_UP   # sentiment 0.8 + confidence 0.9
    assert abs(p.p_up + p.p_flat + p.p_down - 1.0) < 1e-9
    assert p.p_up > p.p_down
    assert p.falsifiers                  # 必须有证伪条件
    assert p.is_falsifiable()
    assert any(d.category == "theme" for d in p.drivers)   # 传导链
    assert p.inputs_snapshot["sources"][0]["url"] == "https://example.com/a"


def test_deepear_low_confidence_pushes_toward_flat():
    """低置信度不该产出高上涨概率。"""
    from hub.adapters.deepear import _probabilities

    high = _probabilities(0.9, 0.95)
    low = _probabilities(0.9, 0.05)
    assert high[0] > low[0]
    assert low[1] > high[1]   # p_flat 更大


def test_deepear_missing_checkpoint_returns_empty(tmp_path):
    assert DeepEarAdapter({}, tmp_path).parse_checkpoint(tmp_path / "nope", REQ) == []


def test_deepear_falls_back_to_requested_symbols(tmp_path):
    """信号没带标的时，用请求里的自选股。"""
    ckpt = tmp_path / "run2"
    ckpt.mkdir()
    (ckpt / "analyzed_signals.json").write_text(json.dumps([{
        "title": "宏观信号", "sentiment_score": -0.6, "confidence": 0.7,
        "impact_tickers": [],
    }]), encoding="utf-8")
    preds = DeepEarAdapter({}, tmp_path).parse_checkpoint(ckpt, REQ)
    assert [p.symbol for p in preds] == ["600519"]
    assert preds[0].direction == DIRECTION_DOWN


# ---------------------------------------------------------------- DSA
def _make_dsa_db(path, rows):
    conn = sqlite3.connect(path)
    conn.execute("""CREATE TABLE analysis_history (
        id INTEGER PRIMARY KEY AUTOINCREMENT, query_id TEXT, code TEXT, name TEXT,
        report_type TEXT, sentiment_score INTEGER, operation_advice TEXT,
        trend_prediction TEXT, analysis_summary TEXT, raw_result TEXT,
        news_content TEXT, context_snapshot TEXT, ideal_buy REAL,
        secondary_buy REAL, stop_loss REAL, take_profit REAL, created_at TEXT)""")
    for r in rows:
        cols = ",".join(r)
        marks = ",".join("?" * len(r))
        conn.execute(f"INSERT INTO analysis_history ({cols}) VALUES ({marks})", tuple(r.values()))
    conn.commit()
    conn.close()


def test_dsa_parses_analysis_history(tmp_path):
    db = tmp_path / "stock_analysis.db"
    _make_dsa_db(db, [{
        "code": "600519", "name": "贵州茅台", "sentiment_score": 78,
        "operation_advice": "买入", "trend_prediction": "看多",
        "analysis_summary": "白酒板块资金回流",
        "context_snapshot": json.dumps({"news": ["消费政策"], "ma5": 1500}),
        "ideal_buy": 1480.0, "stop_loss": 1400.0, "take_profit": 1650.0,
        "created_at": "2026-08-14 18:00:00",
    }])

    preds = DailyStockAdapter({}, tmp_path).parse_db(db, REQ)
    assert len(preds) == 1
    p = preds[0]
    assert p.symbol == "600519"
    assert p.direction == DIRECTION_UP
    assert p.confidence == 0.78
    assert p.target_high == 1650.0
    assert p.asof_date == "2026-08-14"
    assert p.inputs_snapshot["context"]["ma5"] == 1500
    assert any("1400" in f for f in p.falsifiers)
    assert p.is_falsifiable()


def test_dsa_watermark_only_returns_new_rows(tmp_path):
    """跑一轮只应收本轮新增的记录，不能把历史全捞回来。"""
    db = tmp_path / "s.db"
    _make_dsa_db(db, [
        {"code": "600519", "sentiment_score": 60, "trend_prediction": "看多",
         "created_at": "2026-08-13 18:00:00"},
        {"code": "000001", "sentiment_score": 30, "trend_prediction": "看空",
         "created_at": "2026-08-14 18:00:00"},
    ])
    adapter = DailyStockAdapter({}, tmp_path)
    assert len(adapter.parse_db(db, REQ)) == 2
    assert [p.symbol for p in adapter.parse_db(db, REQ, after_id=1)] == ["000001"]


def test_dsa_missing_db_is_not_a_crash(tmp_path):
    assert DailyStockAdapter({}, tmp_path).parse_db(tmp_path / "none.db", REQ) == []


# ---------------------------------------------------------------- TradingAgents
def test_tradingagents_parses_driver_output(tmp_path):
    out = tmp_path / "ta.json"
    out.write_text(json.dumps({
        "ticker": "600519", "trade_date": "2026-08-14",
        "decision": "综合多空辩论后给出：买入",
        "model_id": "deepseek-chat",
        "final_state": {
            "market_report": "MA5>MA10>MA20 多头排列",
            "news_report": "消费刺激政策落地",
            "policy_report": "货币政策偏宽松",
            "hotmoney_report": "龙虎榜净买入",
            "unlock_report": "近期无解禁",
            "fundamentals_report": "业绩符合预期",
            "sentiment_report": "社交情绪偏暖",
            "investment_debate_state": {
                "bear_history": "估值已在历史高位，若批价回落逻辑破裂",
                "count": 1,
            },
            "risk_debate_state": {"judge_decision": "仓位控制在三成"},
        },
    }), encoding="utf-8")

    preds = TradingAgentsAdapter({}, tmp_path).parse_output(out, REQ)
    assert len(preds) == 1
    p = preds[0]
    assert p.direction == DIRECTION_UP
    assert p.model_id == "deepseek-chat"
    # 七个分析师应各自成为一条驱动因素
    assert len(p.drivers) == 7
    categories = {d.category for d in p.drivers}
    assert {"policy", "capital", "technical", "news"} <= categories
    # 空头论点必须进证伪条件
    assert any("估值已在历史高位" in f for f in p.falsifiers)
    assert p.is_falsifiable()
    # 上游不给概率，这里就不能凭空造
    assert p.p_up is None


def test_tradingagents_bad_json_returns_empty(tmp_path):
    bad = tmp_path / "bad.json"
    bad.write_text("{not json", encoding="utf-8")
    assert TradingAgentsAdapter({}, tmp_path).parse_output(bad, REQ) == []


# ---------------------------------------------------------------- aiagents
def test_aiagents_parses_recommendations(tmp_path):
    out = tmp_path / "lhb.json"
    out.write_text(json.dumps({
        "success": True, "timestamp": "2026-08-14 20:00:00",
        "final_report": {"summary": "游资活跃"},
        "recommended_stocks": [{
            "rank": 1, "code": "300750", "name": "宁德时代",
            "net_inflow": 123456789.0, "reason": "资金净流入 1.2 亿元",
            "confidence": "高", "buy_price": "待定",
            "target_price": "待定", "stop_loss": "待定", "hold_period": "短线",
        }],
    }), encoding="utf-8")

    preds = AiAgentsAdapter({}, tmp_path).parse_output(out, REQ)
    assert len(preds) == 1
    p = preds[0]
    assert p.symbol == "300750"
    assert p.direction == DIRECTION_UP     # 该引擎只出看多候选
    assert p.confidence == 0.75            # "高" -> 0.75
    assert p.target_high is None           # "待定" 不能变成 0
    assert p.asof_date == "2026-08-14"
    assert any("游资出货" in f for f in p.falsifiers)
    assert p.is_falsifiable()


def test_aiagents_placeholder_prices_become_none():
    from hub.adapters.aiagents import _to_float

    assert _to_float("待定") is None
    assert _to_float("") is None
    assert _to_float(None) is None
    assert _to_float("12.5") == 12.5
    assert _to_float(3) == 3.0


# ---------------------------------------------------------------- advisor
def test_advisor_parses_scenario_probabilities(tmp_path):
    md = """
# 贵州茅台 未来两周研判

## 政策面
消费刺激政策延续。

## 资金流向
北向资金连续三日净流入。

## 情景推演
- 乐观情景：概率 35%，价格区间 1600-1700
- 基准情景：概率 45%，价格区间 1500-1600
- 悲观情景：概率 20%，价格区间 1400-1500

## 证伪条件
- 批价跌破 2600 元
- 北向资金转为连续净流出
"""
    preds = AdvisorAdapter({}, tmp_path).parse_markdown(
        md, REQ, symbol="600519", source_path="r.md"
    )
    p = preds[0]
    assert abs(p.p_up - 0.35) < 1e-6
    assert abs(p.p_flat - 0.45) < 1e-6
    assert abs(p.p_down - 0.20) < 1e-6
    assert p.direction == DIRECTION_FLAT   # 基准情景概率最高
    assert any("批价跌破 2600" in f for f in p.falsifiers)
    assert {"policy", "capital"} <= {d.category for d in p.drivers}
    assert p.is_falsifiable()


def test_advisor_without_probabilities_still_records(tmp_path):
    """没抽到概率就留 None，不编造。"""
    preds = AdvisorAdapter({}, tmp_path).parse_markdown(
        "# 简单结论\n没有给出概率。\n", REQ, symbol="600519"
    )
    p = preds[0]
    assert p.p_up is None
    assert p.direction is None
    assert not p.is_falsifiable()   # 无方向 -> 不进命中率统计


def test_advisor_is_not_headless():
    assert AdvisorAdapter.headless is False
