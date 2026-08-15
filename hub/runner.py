"""子进程执行层：在各引擎自己的 venv 里跑它们自己的入口。"""

from __future__ import annotations

import os
import subprocess
import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from . import config, envmap


class EngineNotInstalled(RuntimeError):
    """引擎子模块没拉下来，或 venv 没建。"""


@dataclass
class RunResult:
    run_id: str
    engine: str
    argv: list[str]
    returncode: int
    stdout: str
    stderr: str
    started_at: str
    finished_at: str
    cwd: Path

    @property
    def ok(self) -> bool:
        return self.returncode == 0


def engine_dir(engine: str) -> Path:
    path = config.ENGINE_PATHS.get(engine)
    if path is None:
        raise KeyError(f"未知引擎: {engine}")
    return path


def is_installed(engine: str) -> bool:
    """子模块是否已 checkout（空目录 = 没 init）。"""
    d = engine_dir(engine)
    return d.is_dir() and any(d.iterdir())


def has_venv(engine: str) -> bool:
    return config.venv_python(engine).exists()


def engine_commit(engine: str) -> str | None:
    """引擎当前 commit，写进预测记录用于复现。"""
    d = engine_dir(engine)
    if not d.is_dir():
        return None
    try:
        out = subprocess.run(
            ["git", "-C", str(d), "rev-parse", "--short", "HEAD"],
            capture_output=True, text=True, timeout=15, check=False,
        )
        return out.stdout.strip() or None
    except (OSError, subprocess.SubprocessError):
        return None


def build_env(
    engine: str,
    settings_values: Mapping[str, str],
    *,
    allow_live_trading: bool = False,
    overrides: Mapping[str, str] | None = None,
) -> dict[str, str]:
    """继承当前环境 + 注入投射后的引擎变量。"""
    env = dict(os.environ)
    env.update(
        envmap.project_env(
            engine,
            settings_values,
            allow_live_trading=allow_live_trading,
            overrides=overrides,
        )
    )
    # 让引擎能 import 自己的包
    d = engine_dir(engine)
    existing = env.get("PYTHONPATH", "")
    env["PYTHONPATH"] = f"{d}{os.pathsep}{existing}" if existing else str(d)
    env.setdefault("PYTHONIOENCODING", "utf-8")
    env.setdefault("PYTHONUNBUFFERED", "1")
    return env


def run(
    engine: str,
    args: Sequence[str],
    settings_values: Mapping[str, str],
    *,
    timeout: int = 3600,
    allow_live_trading: bool = False,
    overrides: Mapping[str, str] | None = None,
    use_venv: bool = True,
) -> RunResult:
    """在引擎目录里执行 `python <args...>`。"""
    if not is_installed(engine):
        raise EngineNotInstalled(
            f"引擎 {engine} 未安装。先跑: git submodule update --init engines/{engine}"
        )

    python = config.venv_python(engine)
    if use_venv and not python.exists():
        raise EngineNotInstalled(
            f"引擎 {engine} 缺少虚拟环境 {python}。先跑: ./scripts/bootstrap.sh {engine}"
        )
    interpreter = str(python) if use_venv else "python3"

    argv = [interpreter, *args]
    env = build_env(
        engine, settings_values,
        allow_live_trading=allow_live_trading, overrides=overrides,
    )
    started = datetime.now(timezone.utc).isoformat(timespec="seconds")
    try:
        proc = subprocess.run(
            argv, cwd=str(engine_dir(engine)), env=env,
            capture_output=True, text=True, timeout=timeout, check=False,
        )
        rc, out, err = proc.returncode, proc.stdout, proc.stderr
    except subprocess.TimeoutExpired as exc:
        rc = 124
        out = exc.stdout.decode("utf-8", "replace") if isinstance(exc.stdout, bytes) else (exc.stdout or "")
        err = f"引擎 {engine} 超时 ({timeout}s)"
    finished = datetime.now(timezone.utc).isoformat(timespec="seconds")

    return RunResult(
        run_id=uuid.uuid4().hex[:12], engine=engine, argv=argv, returncode=rc,
        stdout=out, stderr=err, started_at=started, finished_at=finished,
        cwd=engine_dir(engine),
    )
