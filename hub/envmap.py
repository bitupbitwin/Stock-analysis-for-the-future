"""导通层：把一份统一 .env 投射成每个引擎各自认识的环境变量名。

这是整个项目"完全导通"的核心。五个上游项目对同一个东西起了五个名字：

    DeepSeek key ->  DEEPSEEK_API_KEY (DeepEar) / LLM_DEEPSEEK_API_KEY (DSA)
                     DEEPSEEK_API_KEY (TradingAgents) / DEEPSEEK_API_KEY (aiagents)

用户只需要在根目录 .env 里填 **一次**，这里负责翻译。

约定：
  * 统一键一律以 `SAF_` 开头（Stock Analysis for the Future）。
  * 值为空字符串的键不会被注入，避免用空值覆盖引擎自己的 .env。
  * 引擎自带的 .env 仍然生效，本层注入的值优先级更高（进程环境覆盖）。
"""

from __future__ import annotations

from collections.abc import Callable, Mapping

# 统一键 -> 各引擎的键名列表
# 一个统一键可以喂给多个引擎的多个变量名。
ENV_MAP: dict[str, dict[str, tuple[str, ...]]] = {
    # ---------------- LLM 供应商 ----------------
    "SAF_DEEPSEEK_API_KEY": {
        "deepear": ("DEEPSEEK_API_KEY",),
        "daily_stock_analysis": ("DEEPSEEK_API_KEY", "LLM_DEEPSEEK_API_KEY"),
        "tradingagents_astock": ("DEEPSEEK_API_KEY",),
        "aiagents_stock": ("DEEPSEEK_API_KEY",),
    },
    "SAF_DEEPSEEK_BASE_URL": {
        "aiagents_stock": ("DEEPSEEK_BASE_URL",),
    },
    "SAF_OPENAI_API_KEY": {
        "deepear": ("OPENAI_API_KEY",),
        "daily_stock_analysis": ("OPENAI_API_KEY",),
        "tradingagents_astock": ("OPENAI_API_KEY",),
    },
    "SAF_OPENROUTER_API_KEY": {
        "deepear": ("OPENROUTER_API_KEY",),
        "tradingagents_astock": ("OPENROUTER_API_KEY",),
    },
    "SAF_DASHSCOPE_API_KEY": {
        "deepear": ("DASHSCOPE_API_KEY",),
        "tradingagents_astock": ("DASHSCOPE_API_KEY",),
    },
    "SAF_GEMINI_API_KEY": {
        "daily_stock_analysis": ("GEMINI_API_KEY",),
        "tradingagents_astock": ("GOOGLE_API_KEY",),
    },
    "SAF_ANTHROPIC_API_KEY": {
        "daily_stock_analysis": ("ANTHROPIC_API_KEY",),
        "tradingagents_astock": ("ANTHROPIC_API_KEY",),
    },
    "SAF_ZHIPU_API_KEY": {
        "tradingagents_astock": ("ZHIPU_API_KEY",),
    },
    "SAF_MINIMAX_API_KEY": {
        "tradingagents_astock": ("MINIMAX_API_KEY",),
    },
    "SAF_ANSPIRE_API_KEY": {
        # DSA 支持多 key 逗号分隔
        "daily_stock_analysis": ("ANSPIRE_API_KEYS",),
    },
    "SAF_AIHUBMIX_KEY": {
        "daily_stock_analysis": ("AIHUBMIX_KEY",),
    },

    # ---------------- 搜索 / 新闻 ----------------
    "SAF_TAVILY_API_KEY": {
        "daily_stock_analysis": ("TAVILY_API_KEYS",),
    },
    "SAF_SERPAPI_API_KEY": {
        "daily_stock_analysis": ("SERPAPI_API_KEYS",),
    },
    "SAF_BRAVE_API_KEY": {
        "daily_stock_analysis": ("BRAVE_API_KEYS",),
    },
    "SAF_SEARXNG_BASE_URL": {
        "daily_stock_analysis": ("SEARXNG_BASE_URLS",),
    },
    "SAF_JINA_API_KEY": {
        "deepear": ("JINA_API_KEY",),
    },

    # ---------------- 行情数据 ----------------
    "SAF_TUSHARE_TOKEN": {
        "daily_stock_analysis": ("TUSHARE_TOKEN",),
        "aiagents_stock": ("TUSHARE_TOKEN",),
    },
    "SAF_FINNHUB_API_KEY": {
        "daily_stock_analysis": ("FINNHUB_API_KEY",),
        "tradingagents_astock": ("FINNHUB_API_KEY",),
    },
    "SAF_ALPHAVANTAGE_API_KEY": {
        "daily_stock_analysis": ("ALPHAVANTAGE_API_KEY",),
    },

    # ---------------- 推送 ----------------
    "SAF_WECOM_WEBHOOK": {
        "aiagents_stock": ("WECOM_WEBHOOK",),
    },
    "SAF_DINGTALK_WEBHOOK": {
        "daily_stock_analysis": ("DINGTALK_WEBHOOK_URL",),
        "aiagents_stock": ("DINGTALK_WEBHOOK",),
    },
    "SAF_FEISHU_WEBHOOK": {
        "daily_stock_analysis": ("FEISHU_WEBHOOK_URL",),
        "aiagents_stock": ("FEISHU_WEBHOOK",),
    },

    # ---------------- 自选股 ----------------
    "SAF_WATCHLIST": {
        "daily_stock_analysis": ("STOCK_LIST",),
    },
}

# 每个引擎固定注入的常量（保证非交互、可脚本化运行）
ENGINE_STATIC_ENV: dict[str, dict[str, str]] = {
    "daily_stock_analysis": {
        # hub 自己负责调度，禁止引擎内部再起定时器/WebUI
        "SCHEDULE_ENABLED": "false",
        "WEBUI_ENABLED": "false",
        "RUN_IMMEDIATELY": "true",
        # 保留上下文快照，hub 需要它来记录"当时可获得的输入"
        "SAVE_CONTEXT_SNAPSHOT": "true",
    },
    "aiagents_stock": {
        # 安全默认：未经严格回测前绝不打开自动交易
        "MINIQMT_ENABLED": "false",
    },
    "deepear": {},
    "tradingagents_astock": {},
    "stock_investment_advisor": {},
}

# 绝不允许 hub 自动打开的开关（即使用户在 .env 里写了也要拦下来，
# 只有显式传 --allow-live-trading 才放行）。
DANGEROUS_KEYS: tuple[str, ...] = (
    "MINIQMT_ENABLED",
    "MINIQMT_ACCOUNT_ID",
)


def unified_keys() -> list[str]:
    """所有支持的统一键。"""
    return sorted(ENV_MAP)


def engines() -> list[str]:
    return sorted(ENGINE_STATIC_ENV)


def keys_for_engine(engine: str) -> list[str]:
    """某个引擎会用到哪些统一键。"""
    return sorted(k for k, targets in ENV_MAP.items() if engine in targets)


def project_env(
    engine: str,
    source: Mapping[str, str],
    *,
    allow_live_trading: bool = False,
    overrides: Mapping[str, str] | None = None,
) -> dict[str, str]:
    """把统一配置投射成 `engine` 认识的环境变量。

    只返回**需要注入的增量**，不含继承的 os.environ。
    """
    if engine not in ENGINE_STATIC_ENV:
        raise KeyError(f"未知引擎: {engine}")

    out: dict[str, str] = dict(ENGINE_STATIC_ENV[engine])

    for unified, targets in ENV_MAP.items():
        names = targets.get(engine)
        if not names:
            continue
        value = (source.get(unified) or "").strip()
        if not value:
            continue  # 空值不注入，避免覆盖引擎自带 .env
        for name in names:
            out[name] = value

    if overrides:
        out.update({k: v for k, v in overrides.items() if v is not None})

    if not allow_live_trading:
        for key in DANGEROUS_KEYS:
            if key in out and key in ENGINE_STATIC_ENV.get(engine, {}):
                continue  # 静态默认值（false）保留
            out.pop(key, None)
        # 强制关闭
        if engine == "aiagents_stock":
            out["MINIQMT_ENABLED"] = "false"

    return out


def missing_for_engine(engine: str, source: Mapping[str, str]) -> list[str]:
    """该引擎相关、但用户还没填的统一键。"""
    return [k for k in keys_for_engine(engine) if not (source.get(k) or "").strip()]


def describe(fmt: Callable[[str], str] = str) -> str:
    """人类可读的映射表，供 `doctor` / 文档使用。"""
    lines = []
    for unified in unified_keys():
        targets = ENV_MAP[unified]
        rendered = "; ".join(
            f"{eng}:{'/'.join(names)}" for eng, names in sorted(targets.items())
        )
        lines.append(f"{fmt(unified):<28} -> {rendered}")
    return "\n".join(lines)
