#!/usr/bin/env python3
"""在 TradingAgents-astock 的 venv 内运行一次分析，结果 dump 成 JSON。

由 hub/adapters/tradingagents.py 调起。cwd 由 runner 设为引擎根目录。
上游代码零修改 —— 这里只是 import 它的公开类。
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
from pathlib import Path


def _jsonable(obj, _depth: int = 0):
    """LangGraph 的 state 里混着各种对象，转成能落盘的形状。"""
    if _depth > 6:
        return str(obj)[:2000]
    if obj is None or isinstance(obj, (bool, int, float)):
        return obj
    if isinstance(obj, str):
        return obj[:20000]
    if isinstance(obj, dict):
        return {str(k): _jsonable(v, _depth + 1) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_jsonable(v, _depth + 1) for v in obj[:100]]
    for attr in ("model_dump", "dict"):
        fn = getattr(obj, attr, None)
        if callable(fn):
            try:
                return _jsonable(fn(), _depth + 1)
            except Exception:  # noqa: BLE001 - 尽力序列化，失败就退化成字符串
                break
    return str(obj)[:20000]


def main() -> int:
    parser = argparse.ArgumentParser(description="TradingAgents-astock JSON driver")
    parser.add_argument("--ticker", required=True)
    parser.add_argument("--date", default="", help="YYYY-MM-DD；留空用今天")
    parser.add_argument("--out", required=True)
    parser.add_argument("--max-debate-rounds", type=int, default=1)
    parser.add_argument("--deep-model", default=None)
    parser.add_argument("--quick-model", default=None)
    args = parser.parse_args()

    # 用北京时间取"今天"：容器通常跑在 UTC，直接 date.today() 会在
    # 北京时间早上 08:00 前取到前一个交易日。
    cn_today = dt.datetime.now(tz=dt.timezone(dt.timedelta(hours=8))).date()
    trade_date = args.date.strip() or cn_today.isoformat()

    sys.path.insert(0, str(Path.cwd()))
    from tradingagents.default_config import DEFAULT_CONFIG
    from tradingagents.graph.trading_graph import TradingAgentsGraph

    config = dict(DEFAULT_CONFIG)
    config["max_debate_rounds"] = args.max_debate_rounds
    if args.deep_model:
        config["deep_think_llm"] = args.deep_model
    if args.quick_model:
        config["quick_think_llm"] = args.quick_model

    graph = TradingAgentsGraph(debug=False, config=config)
    final_state, decision = graph.propagate(args.ticker, trade_date)

    payload = {
        "ticker": args.ticker,
        "trade_date": trade_date,
        "decision": _jsonable(decision),
        "final_state": _jsonable(final_state),
        "model_id": config.get("deep_think_llm"),
        "config_summary": {
            k: config.get(k)
            for k in ("deep_think_llm", "quick_think_llm", "max_debate_rounds", "data_vendors")
        },
    }

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[tradingagents_driver] wrote {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
