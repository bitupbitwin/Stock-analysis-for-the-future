#!/usr/bin/env python3
"""在 aiagents-stock 的 venv 内跑一次"智瞰龙虎"综合分析，dump 成 JSON。

由 hub/adapters/aiagents.py 调起。cwd 由 runner 设为引擎根目录。
上游代码零修改。

注意：该引擎默认预留了 MiniQMT 自动交易接口。runner 的导通层会强制
注入 MINIQMT_ENABLED=false，除非显式 --allow-live-trading。
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser(description="aiagents-stock 龙虎榜 JSON driver")
    parser.add_argument("--date", default="", help="YYYY-MM-DD；留空用上游默认（昨日）")
    parser.add_argument("--days", type=int, default=1)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()

    if os.getenv("MINIQMT_ENABLED", "false").lower() == "true":
        print(
            "[aiagents_driver] 拒绝执行：检测到 MINIQMT_ENABLED=true。"
            "自动交易必须在完成严格回测后手动开启。",
            file=sys.stderr,
        )
        return 2

    sys.path.insert(0, str(Path.cwd()))
    from longhubang_engine import LonghubangEngine

    engine = LonghubangEngine()
    results = engine.run_comprehensive_analysis(
        date=args.date.strip() or None, days=args.days
    )

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(
        json.dumps(results, ensure_ascii=False, indent=2, default=str), encoding="utf-8"
    )
    print(f"[aiagents_driver] wrote {out_path}")
    return 0 if results.get("success") else 1


if __name__ == "__main__":
    raise SystemExit(main())
