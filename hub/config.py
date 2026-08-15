"""配置加载：根目录 .env 是唯一事实来源。"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
ENGINES_DIR = REPO_ROOT / "engines"
DATA_DIR = REPO_ROOT / "data"
REPORTS_DIR = REPO_ROOT / "data" / "reports"
DB_PATH = DATA_DIR / "predictions.db"

ENGINE_PATHS: dict[str, Path] = {
    "deepear": ENGINES_DIR / "deepear",
    "daily_stock_analysis": ENGINES_DIR / "daily_stock_analysis",
    "tradingagents_astock": ENGINES_DIR / "tradingagents_astock",
    "aiagents_stock": ENGINES_DIR / "aiagents_stock",
    "stock_investment_advisor": ENGINES_DIR / "stock_investment_advisor",
}

# 每个引擎独立 venv —— 它们的依赖互相冲突（DeepEar 要 py>=3.12 + torch，
# TradingAgents 要 py>=3.10），绝不能共用一个环境。
def venv_python(engine: str) -> Path:
    return ENGINES_DIR / ".venvs" / engine / "bin" / "python"


def parse_env_file(path: Path) -> dict[str, str]:
    """极简 .env 解析（不依赖 python-dotenv，hub 本身零依赖可跑）。"""
    out: dict[str, str] = {}
    if not path.exists():
        return out
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[len("export "):].strip()
        if "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip()
        # 去掉包裹引号；行尾注释只在无引号时剥离
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        elif " #" in value:
            value = value.split(" #", 1)[0].strip()
        out[key] = value
    return out


@dataclass
class Settings:
    values: dict[str, str]
    env_path: Path

    def get(self, key: str, default: str = "") -> str:
        return self.values.get(key, default)

    @property
    def watchlist(self) -> list[str]:
        raw = self.get("SAF_WATCHLIST", "")
        return [s.strip() for s in raw.replace("，", ",").split(",") if s.strip()]

    @property
    def neutral_band_pct(self) -> float:
        try:
            return float(self.get("SAF_NEUTRAL_BAND_PCT", "2.0"))
        except ValueError:
            return 2.0

    @property
    def benchmark(self) -> str:
        return self.get("SAF_BENCHMARK", "000300") or "000300"


def load_settings(env_path: Path | None = None) -> Settings:
    """读取 .env，再让真实环境变量覆盖它（CI / docker secrets 友好）。"""
    path = env_path or (REPO_ROOT / ".env")
    values = parse_env_file(path)
    for key, value in os.environ.items():
        if key.startswith("SAF_") and value.strip():
            values[key] = value
    return Settings(values=values, env_path=path)
