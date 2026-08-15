"""`hub doctor`：一眼看清哪些引擎能跑、缺什么。

这个命令就是"需要你提供哪些信息"的可执行版本 —— 文档会过期，它不会。
"""

from __future__ import annotations

from dataclasses import dataclass

from . import config, envmap, runner
from .adapters import ADAPTERS

# 每个引擎"最低可跑"所需的统一键（满足任意一组即可）
MINIMUM_REQUIREMENTS: dict[str, list[list[str]]] = {
    "deepear": [
        ["SAF_DEEPSEEK_API_KEY"],
        ["SAF_OPENROUTER_API_KEY"],
        ["SAF_OPENAI_API_KEY"],
        ["SAF_DASHSCOPE_API_KEY"],
    ],
    "daily_stock_analysis": [
        ["SAF_ANSPIRE_API_KEY"],
        ["SAF_GEMINI_API_KEY"],
        ["SAF_DEEPSEEK_API_KEY"],
        ["SAF_OPENAI_API_KEY"],
        ["SAF_ANTHROPIC_API_KEY"],
    ],
    "tradingagents_astock": [
        ["SAF_DEEPSEEK_API_KEY"],
        ["SAF_OPENAI_API_KEY"],
        ["SAF_DASHSCOPE_API_KEY"],
        ["SAF_ZHIPU_API_KEY"],
        ["SAF_OPENROUTER_API_KEY"],
    ],
    "aiagents_stock": [
        ["SAF_DEEPSEEK_API_KEY"],
    ],
    "stock_investment_advisor": [],  # 只靠 Claude 的 WebSearch，不需要任何 key
}

# 强烈建议但非必需
RECOMMENDED: dict[str, list[str]] = {
    "daily_stock_analysis": ["SAF_TUSHARE_TOKEN", "SAF_TAVILY_API_KEY", "SAF_WATCHLIST"],
    "aiagents_stock": ["SAF_TUSHARE_TOKEN"],
    "deepear": ["SAF_JINA_API_KEY"],
    "tradingagents_astock": [],
    "stock_investment_advisor": [],
}


@dataclass
class EngineStatus:
    engine: str
    installed: bool
    has_venv: bool
    headless: bool
    satisfied: bool
    missing_options: list[list[str]]
    recommended_missing: list[str]
    commit: str | None

    @property
    def needs_venv(self) -> bool:
        """Skill 类引擎（非 headless）没有 Python 依赖，不需要 venv。"""
        return self.headless

    @property
    def runnable(self) -> bool:
        if not (self.installed and self.satisfied):
            return False
        return self.has_venv if self.needs_venv else True

    def render(self) -> str:
        if not self.installed:
            mark, note = "✗", "子模块未拉取 → git submodule update --init --recursive"
        elif self.needs_venv and not self.has_venv:
            mark, note = "✗", f"缺虚拟环境 → ./scripts/bootstrap.sh {self.engine}"
        elif not self.satisfied:
            options = " 或 ".join("+".join(o) for o in self.missing_options)
            mark, note = "✗", f"缺 API Key → 在 .env 填 {options}"
        elif not self.headless:
            mark, note = "◐", "需在 Claude Code 中手动使用（Skill，非脚本）"
        else:
            mark, note = "✓", "可运行"

        line = f"  {mark} {self.engine:<26} {note}"
        if self.commit:
            line += f"  [{self.commit}]"
        if self.recommended_missing:
            line += f"\n      建议补充: {', '.join(self.recommended_missing)}"
        return line


def check_engine(engine: str, values: dict[str, str]) -> EngineStatus:
    options = MINIMUM_REQUIREMENTS.get(engine, [])
    satisfied = not options or any(
        all((values.get(k) or "").strip() for k in option) for option in options
    )
    rec_missing = [
        k for k in RECOMMENDED.get(engine, []) if not (values.get(k) or "").strip()
    ]
    return EngineStatus(
        engine=engine,
        installed=runner.is_installed(engine),
        has_venv=runner.has_venv(engine),
        headless=ADAPTERS[engine].headless,
        satisfied=satisfied,
        missing_options=[] if satisfied else options,
        recommended_missing=rec_missing,
        commit=runner.engine_commit(engine),
    )


def run_doctor(settings: config.Settings) -> tuple[str, bool]:
    """返回 (报告文本, 是否至少有一个引擎可跑)。"""
    lines = [
        "Stock Analysis for the Future — 环境体检",
        "=" * 60,
        f".env 位置: {settings.env_path}"
        + ("" if settings.env_path.exists() else "  ← 不存在！先 cp .env.example .env"),
        "",
        "引擎状态:",
    ]
    statuses = [check_engine(e, settings.values) for e in sorted(ADAPTERS)]
    lines.extend(s.render() for s in statuses)

    watchlist = settings.watchlist
    lines += [
        "",
        f"自选股 (SAF_WATCHLIST): {', '.join(watchlist) if watchlist else '未设置'}",
        f"基准指数 (SAF_BENCHMARK): {settings.benchmark}",
        f"中性带 (SAF_NEUTRAL_BAND_PCT): ±{settings.neutral_band_pct}%",
    ]

    try:
        import akshare  # noqa: F401

        lines.append("回填行情 (akshare): ✓ 已安装")
    except ImportError:
        lines.append("回填行情 (akshare): ✗ 未安装 → pip install -r requirements.txt")

    store_path = config.DB_PATH
    if store_path.exists():
        from .store import Store

        counts = Store(store_path).counts()
        lines.append(
            f"台账: {counts['predictions']} 条预测 "
            f"({counts['falsifiable']} 条可证伪), {counts['realized_rows']} 条已回填"
        )
    else:
        lines.append("台账: 尚未创建（首次 `hub run` 后生成）")

    configured = [k for k in envmap.unified_keys() if (settings.values.get(k) or "").strip()]
    lines += ["", f"已配置的统一键: {len(configured)}/{len(envmap.unified_keys())}"]

    runnable = [s for s in statuses if s.runnable and s.headless]
    lines += ["", f"可无人值守运行的引擎: {len(runnable)}"]
    if not runnable:
        lines.append("  → 至少配一个 LLM API Key，见 docs/REQUIRED_INPUTS.md")

    return "\n".join(lines), bool(runnable)
