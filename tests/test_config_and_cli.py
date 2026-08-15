"""配置解析 + CLI 冒烟测试。"""

from __future__ import annotations

import pytest

from hub import config
from hub.cli import build_parser, main


def test_parse_env_file_handles_quotes_comments_and_export(tmp_path):
    env = tmp_path / ".env"
    env.write_text(
        "# 注释行\n"
        "\n"
        "SAF_DEEPSEEK_API_KEY=sk-plain\n"
        "SAF_OPENAI_API_KEY='sk-quoted'\n"
        'SAF_TUSHARE_TOKEN="tok"\n'
        "export SAF_GEMINI_API_KEY=g-key\n"
        "SAF_BENCHMARK=000300  # 沪深300\n"
        "SAF_WATCHLIST=600519,300750\n",
        encoding="utf-8",
    )
    values = config.parse_env_file(env)
    assert values["SAF_DEEPSEEK_API_KEY"] == "sk-plain"
    assert values["SAF_OPENAI_API_KEY"] == "sk-quoted"
    assert values["SAF_TUSHARE_TOKEN"] == "tok"
    assert values["SAF_GEMINI_API_KEY"] == "g-key"
    assert values["SAF_BENCHMARK"] == "000300"


def test_env_vars_override_file(tmp_path, monkeypatch):
    env = tmp_path / ".env"
    env.write_text("SAF_DEEPSEEK_API_KEY=from-file\n", encoding="utf-8")
    monkeypatch.setenv("SAF_DEEPSEEK_API_KEY", "from-environ")
    settings = config.load_settings(env)
    assert settings.get("SAF_DEEPSEEK_API_KEY") == "from-environ"


def test_settings_watchlist_handles_fullwidth_comma(tmp_path):
    env = tmp_path / ".env"
    env.write_text("SAF_WATCHLIST=600519，300750, 002594\n", encoding="utf-8")
    assert config.load_settings(env).watchlist == ["600519", "300750", "002594"]


def test_settings_defaults_when_file_missing(tmp_path):
    settings = config.load_settings(tmp_path / "nope.env")
    assert settings.watchlist == []
    assert settings.benchmark == "000300"
    assert settings.neutral_band_pct == 2.0


def test_neutral_band_falls_back_on_garbage(tmp_path):
    env = tmp_path / ".env"
    env.write_text("SAF_NEUTRAL_BAND_PCT=abc\n", encoding="utf-8")
    assert config.load_settings(env).neutral_band_pct == 2.0


def test_every_engine_path_is_declared():
    from hub.adapters import ADAPTERS

    assert set(ADAPTERS) == set(config.ENGINE_PATHS)


def test_cli_parser_accepts_core_commands():
    parser = build_parser()
    for argv in (
        ["doctor"],
        ["engines"],
        ["envmap", "--engine", "deepear"],
        ["run", "--engine", "all", "--symbols", "600519", "--horizon", "5"],
        ["score", "--horizon", "20"],
        ["list", "--json"],
        ["ingest", "r.md", "--symbol", "600519"],
        ["install-skill", "--force"],
    ):
        assert parser.parse_args(argv) is not None


def test_cli_rejects_unknown_engine():
    with pytest.raises(SystemExit):
        build_parser().parse_args(["run", "--engine", "not-real"])


def test_envmap_command_runs(capsys, tmp_path):
    env = tmp_path / ".env"
    env.write_text("SAF_DEEPSEEK_API_KEY=sk-secret-value-123\n", encoding="utf-8")
    assert main(["--env", str(env), "envmap", "--engine", "deepear"]) == 0
    out = capsys.readouterr().out
    assert "DEEPSEEK_API_KEY" in out
    assert "sk-secret-value-123" not in out   # 必须脱敏


def test_engines_command_runs(capsys):
    assert main(["engines"]) == 0
    out = capsys.readouterr().out
    assert "deepear" in out and "stock_investment_advisor" in out
