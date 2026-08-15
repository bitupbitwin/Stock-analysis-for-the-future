"""导通层测试 —— 这层错了，所有引擎都会拿到错的 key。"""

from __future__ import annotations

import pytest

from hub import envmap


def test_one_deepseek_key_reaches_all_four_engines():
    """核心承诺：填一个 DeepSeek key，四个代码引擎全部通电。"""
    source = {"SAF_DEEPSEEK_API_KEY": "sk-test-123"}
    for engine in ("deepear", "daily_stock_analysis", "tradingagents_astock", "aiagents_stock"):
        projected = envmap.project_env(engine, source)
        assert projected.get("DEEPSEEK_API_KEY") == "sk-test-123", engine


def test_dsa_gets_both_key_aliases():
    """daily_stock_analysis 同一个 key 有两个变量名，都要喂到。"""
    projected = envmap.project_env(
        "daily_stock_analysis", {"SAF_DEEPSEEK_API_KEY": "sk-abc"}
    )
    assert projected["DEEPSEEK_API_KEY"] == "sk-abc"
    assert projected["LLM_DEEPSEEK_API_KEY"] == "sk-abc"


def test_gemini_maps_to_google_api_key_for_tradingagents():
    """同一个 Google key 在两个引擎里叫不同名字。"""
    source = {"SAF_GEMINI_API_KEY": "g-key"}
    assert envmap.project_env("daily_stock_analysis", source)["GEMINI_API_KEY"] == "g-key"
    assert envmap.project_env("tradingagents_astock", source)["GOOGLE_API_KEY"] == "g-key"


def test_empty_values_are_not_injected():
    """空值不能注入，否则会用空字符串覆盖引擎自带 .env 里的真实值。"""
    projected = envmap.project_env(
        "deepear", {"SAF_DEEPSEEK_API_KEY": "", "SAF_OPENAI_API_KEY": "   "}
    )
    assert "DEEPSEEK_API_KEY" not in projected
    assert "OPENAI_API_KEY" not in projected


def test_static_env_forces_headless_mode_for_dsa():
    """hub 自己调度，不能让引擎内部再起定时器或 WebUI。"""
    projected = envmap.project_env("daily_stock_analysis", {})
    assert projected["SCHEDULE_ENABLED"] == "false"
    assert projected["WEBUI_ENABLED"] == "false"
    assert projected["SAVE_CONTEXT_SNAPSHOT"] == "true"


def test_live_trading_is_off_by_default():
    """默认必须关掉自动交易。"""
    projected = envmap.project_env(
        "aiagents_stock", {}, overrides={"MINIQMT_ENABLED": "true"}
    )
    assert projected["MINIQMT_ENABLED"] == "false"


def test_live_trading_can_be_explicitly_enabled():
    projected = envmap.project_env(
        "aiagents_stock", {},
        allow_live_trading=True, overrides={"MINIQMT_ENABLED": "true"},
    )
    assert projected["MINIQMT_ENABLED"] == "true"


def test_overrides_win_over_mapping():
    projected = envmap.project_env(
        "daily_stock_analysis",
        {"SAF_WATCHLIST": "600519"},
        overrides={"STOCK_LIST": "000001,000002"},
    )
    assert projected["STOCK_LIST"] == "000001,000002"


def test_unknown_engine_rejected():
    with pytest.raises(KeyError):
        envmap.project_env("nope", {})


def test_every_mapped_engine_is_a_real_engine():
    """映射表里不能出现拼错的引擎名。"""
    known = set(envmap.engines())
    for unified, targets in envmap.ENV_MAP.items():
        unknown = set(targets) - known
        assert not unknown, f"{unified} 指向了未知引擎 {unknown}"


def test_missing_for_engine_reports_unset_keys():
    missing = envmap.missing_for_engine("deepear", {"SAF_DEEPSEEK_API_KEY": "x"})
    assert "SAF_DEEPSEEK_API_KEY" not in missing
    assert "SAF_OPENAI_API_KEY" in missing
