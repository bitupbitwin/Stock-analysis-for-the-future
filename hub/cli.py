"""统一命令行：python -m hub <command>"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from . import config, doctor, envmap, scoring
from .adapters import ADAPTERS, HEADLESS_ENGINES, AnalysisRequest, get_adapter
from .schema import DEFAULT_HORIZONS
from .store import Store


def _settings(args) -> config.Settings:
    return config.load_settings(Path(args.env) if getattr(args, "env", None) else None)


def _store() -> Store:
    return Store(config.DB_PATH)


# ----------------------------------------------------------------------
def cmd_doctor(args) -> int:
    report, ok = doctor.run_doctor(_settings(args))
    print(report)
    return 0 if ok else 1


def cmd_envmap(args) -> int:
    if args.engine:
        settings = _settings(args)
        projected = envmap.project_env(args.engine, settings.values)
        print(f"# {args.engine} 将收到的环境变量（值已脱敏）")
        for key, value in sorted(projected.items()):
            shown = value if len(value) < 8 else f"{value[:4]}…{value[-2:]}"
            print(f"{key}={shown}")
        missing = envmap.missing_for_engine(args.engine, settings.values)
        if missing:
            print(f"\n# 该引擎相关但未配置: {', '.join(missing)}")
    else:
        print("# 统一键 -> 各引擎变量名")
        print(envmap.describe())
    return 0


def cmd_run(args) -> int:
    settings = _settings(args)
    store = _store()
    config.REPORTS_DIR.mkdir(parents=True, exist_ok=True)

    engines = HEADLESS_ENGINES if args.engine == "all" else [args.engine]
    symbols = [s.strip() for s in (args.symbols or "").split(",") if s.strip()]
    if not symbols:
        symbols = settings.watchlist

    request = AnalysisRequest(
        symbols=symbols,
        query=args.query or "",
        asof_date=args.asof_date,
        horizon_days=args.horizon,
        timeout=args.timeout,
    )

    total, failures = 0, []
    for engine in engines:
        adapter = get_adapter(engine, settings.values, config.REPORTS_DIR)
        if not adapter.headless:
            print(f"[skip] {engine}: 非无人值守引擎")
            continue
        print(f"[run ] {engine} …", flush=True)
        try:
            preds = adapter.run(request)
        except Exception as exc:  # noqa: BLE001 - 单引擎失败不该拖垮整轮
            print(f"[fail] {engine}: {exc}", file=sys.stderr)
            failures.append(engine)
            continue
        store.save_many(preds)
        total += len(preds)
        falsifiable = sum(1 for p in preds if p.is_falsifiable())
        print(f"[ok  ] {engine}: {len(preds)} 条预测（{falsifiable} 条可证伪）")

    print(f"\n合计写入 {total} 条预测 → {config.DB_PATH}")
    if failures:
        print(f"失败引擎: {', '.join(failures)}", file=sys.stderr)
    return 1 if failures and total == 0 else 0


def cmd_ingest(args) -> int:
    """把手工/Skill 产出的报告解析进台账。"""
    settings = _settings(args)
    path = Path(args.path)
    if not path.exists():
        print(f"文件不存在: {path}", file=sys.stderr)
        return 1

    adapter = get_adapter(args.engine, settings.values, config.REPORTS_DIR)
    request = AnalysisRequest(
        symbols=[args.symbol], asof_date=args.asof_date, horizon_days=args.horizon
    )

    parse = getattr(adapter, "parse_markdown", None)
    if parse is None:
        print(f"引擎 {args.engine} 不支持 ingest（只有 Skill 类引擎需要）", file=sys.stderr)
        return 1

    preds = parse(
        path.read_text(encoding="utf-8"), request,
        symbol=args.symbol, source_path=str(path),
    )
    _store().save_many(preds)
    for p in preds:
        print(
            f"已记录 {p.symbol} 方向={p.direction} "
            f"p_up={p.p_up} 可证伪={p.is_falsifiable()} id={p.prediction_id}"
        )
    return 0


def cmd_score(args) -> int:
    """回填真实行情并统计命中率。"""
    settings = _settings(args)
    store = _store()
    horizons = [args.horizon] if args.horizon else list(DEFAULT_HORIZONS)

    try:
        import akshare  # noqa: F401
    except ImportError:
        print(
            "无法回填：未安装 akshare。\n"
            "  pip install -r requirements.txt   （或 ./scripts/bootstrap.sh --hub-only）",
            file=sys.stderr,
        )
        return 1

    for horizon in horizons:
        pending = store.pending_scoring(horizon)
        filled = 0
        for pred in pending:
            realized = scoring.score_prediction(
                pred, horizon,
                benchmark=settings.benchmark,
                neutral_band_pct=settings.neutral_band_pct,
            )
            if realized is not None:
                store.save_realized(pred.prediction_id, realized)
                filled += 1
        print(f"T+{horizon}: 待回填 {len(pending)} 条，成功 {filled} 条")

    print("\n命中率统计（只含已回填、且可证伪的预测）")
    print("=" * 60)
    all_preds = store.list_predictions(limit=100000)
    any_report = False
    for horizon in horizons:
        for report in scoring.aggregate(all_preds, horizon):
            print(report.render())
            any_report = True
        rates = scoring.driver_hit_rates(all_preds, horizon)
        if rates:
            print(f"  -- T+{horizon} 按驱动因素分类 --")
            for category, (hit, total) in rates.items():
                print(f"     {category:<18} {hit}/{total} = {hit / total:.1%}")
    if not any_report:
        print("暂无可统计样本 —— 预测窗口还没走完，或行情未取到。")
    return 0


def cmd_list(args) -> int:
    preds = _store().list_predictions(engine=args.engine, symbol=args.symbol, limit=args.limit)
    if args.json:
        print(json.dumps([p.to_dict() for p in preds], ensure_ascii=False, indent=2, default=str))
        return 0
    if not preds:
        print("台账为空。")
        return 0
    print(f"{'时间':<12} {'引擎':<24} {'标的':<8} {'方向':<6} {'p_up':<7} {'窗口':<6} 命中")
    print("-" * 82)
    for p in preds:
        realized = next((r for r in p.realized if r.hit is not None), None)
        hit = "-" if realized is None else ("✓" if realized.hit else "✗")
        p_up = "-" if p.p_up is None else f"{p.p_up:.2f}"
        print(
            f"{p.created_at[:10]:<12} {p.engine:<24} {p.symbol:<8} "
            f"{p.direction or '-'!s:<6} {p_up:<7} T+{p.horizon_days:<4} {hit}"
        )
    return 0


def cmd_install_skill(args) -> int:
    """把 stock-investment-advisor 装进 ~/.claude/skills/。"""
    source = config.ENGINE_PATHS["stock_investment_advisor"]
    if not (source / "SKILL.md").exists():
        print(
            "子模块未拉取：git submodule update --init engines/stock_investment_advisor",
            file=sys.stderr,
        )
        return 1

    target_root = Path(args.target).expanduser() if args.target else Path.home() / ".claude" / "skills"
    target_root.mkdir(parents=True, exist_ok=True)
    target = target_root / "stock-investment-advisor"

    if target.is_symlink() or target.exists():
        if not args.force:
            print(f"已存在 {target}（用 --force 覆盖）")
            return 0
        if target.is_symlink() or target.is_file():
            target.unlink()
        else:
            import shutil

            shutil.rmtree(target)

    os.symlink(source.resolve(), target, target_is_directory=True)
    print(f"已链接 {target} -> {source.resolve()}")
    print("在 Claude Code 里即可使用该 Skill 做联网情景研判。")
    print("分析完把结论存成 .md，然后：")
    print("  python -m hub ingest --engine stock_investment_advisor --symbol 600519 报告.md")
    return 0


def cmd_engines(args) -> int:
    for name, cls in sorted(ADAPTERS.items()):
        mode = "无人值守" if cls.headless else "需 Claude 交互"
        print(f"{name:<28} {mode:<12} 相关配置: {', '.join(envmap.keys_for_engine(name)) or '无'}")
    return 0


# ----------------------------------------------------------------------
def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m hub",
        description="五引擎统一预测台账（Stock Analysis for the Future）",
    )
    parser.add_argument("--env", help="指定 .env 路径（默认仓库根目录 .env）")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("doctor", help="体检：哪些引擎能跑、缺什么")
    p.set_defaults(func=cmd_doctor)

    p = sub.add_parser("engines", help="列出所有引擎及其所需配置")
    p.set_defaults(func=cmd_engines)

    p = sub.add_parser("envmap", help="查看统一键到各引擎变量的映射")
    p.add_argument("--engine", choices=sorted(ADAPTERS), help="只看某个引擎实际会收到什么")
    p.set_defaults(func=cmd_envmap)

    p = sub.add_parser("run", help="跑引擎并把预测写进台账")
    p.add_argument("--engine", default="all", choices=[*sorted(ADAPTERS), "all"])
    p.add_argument("--symbols", help="逗号分隔，如 600519,300750；缺省用 SAF_WATCHLIST")
    p.add_argument("--query", help="自然语言问题（DeepEar 用）")
    p.add_argument("--asof-date", help="预测基准日 YYYY-MM-DD（回测时必填）")
    p.add_argument("--horizon", type=int, default=5, help="预测窗口交易日数，默认 5")
    p.add_argument("--timeout", type=int, default=3600)
    p.set_defaults(func=cmd_run)

    p = sub.add_parser("ingest", help="把 Skill/手工报告解析进台账")
    p.add_argument("path")
    p.add_argument("--engine", default="stock_investment_advisor", choices=sorted(ADAPTERS))
    p.add_argument("--symbol", required=True)
    p.add_argument("--asof-date")
    p.add_argument("--horizon", type=int, default=10)
    p.set_defaults(func=cmd_ingest)

    p = sub.add_parser("score", help="回填真实收益并统计命中率")
    p.add_argument("--horizon", type=int, help="只算某个窗口；缺省算 T+1/T+5/T+20")
    p.set_defaults(func=cmd_score)

    p = sub.add_parser("list", help="查看台账")
    p.add_argument("--engine", choices=sorted(ADAPTERS))
    p.add_argument("--symbol")
    p.add_argument("--limit", type=int, default=50)
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_list)

    p = sub.add_parser("install-skill", help="安装 stock-investment-advisor 到 Claude Code")
    p.add_argument("--target", help="skills 目录，默认 ~/.claude/skills")
    p.add_argument("--force", action="store_true")
    p.set_defaults(func=cmd_install_skill)

    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
