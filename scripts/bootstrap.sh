#!/usr/bin/env bash
# 一键安装：拉子模块 + 为每个引擎建独立虚拟环境。
#
# 为什么每个引擎一个 venv：它们的依赖互相打架。
#   DeepEar              requires-python >=3.12，torch / transformers / sentence-transformers
#   TradingAgents-astock requires-python >=3.10，langgraph 系
#   daily_stock_analysis sqlalchemy / litellm 系
#   aiagents-stock       streamlit 系
# 塞进同一个环境必然版本冲突，所以物理隔离。
#
# 用法:
#   ./scripts/bootstrap.sh              # 全部引擎
#   ./scripts/bootstrap.sh deepear      # 只装某一个
#   ./scripts/bootstrap.sh --hub-only   # 只装 hub 自己的依赖（回填行情用）

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VENV_ROOT="$REPO_ROOT/engines/.venvs"
cd "$REPO_ROOT"

ALL_ENGINES=(deepear daily_stock_analysis tradingagents_astock aiagents_stock)
# stock_investment_advisor 是 Claude Skill，没有 Python 依赖，不建 venv。

# 每个引擎的最低 Python 版本（uv 会按需自动下载对应解释器）
py_version_for() {
  case "$1" in
    deepear) echo "3.12" ;;
    *)       echo "3.11" ;;
  esac
}

info()  { printf '\033[1;34m[bootstrap]\033[0m %s\n' "$*"; }
warn()  { printf '\033[1;33m[warn]\033[0m %s\n' "$*"; }
fail()  { printf '\033[1;31m[fail]\033[0m %s\n' "$*" >&2; }

have_uv() { command -v uv >/dev/null 2>&1; }

if ! have_uv; then
  warn "未检测到 uv。强烈建议安装（能自动管理多版本 Python）："
  warn "  curl -LsSf https://astral.sh/uv/install.sh | sh"
  warn "现在回退到 python3 -m venv，DeepEar 可能因 Python 版本不足而失败。"
fi

# ---------------------------------------------------------------- hub 自身
bootstrap_hub() {
  info "安装 hub 依赖（回填行情用的 akshare 等）"
  local venv="$REPO_ROOT/.venv"
  if have_uv; then
    uv venv --python 3.11 "$venv" >/dev/null
    uv pip install --python "$venv/bin/python" -r "$REPO_ROOT/requirements.txt"
  else
    python3 -m venv "$venv"
    "$venv/bin/pip" install --quiet --upgrade pip
    "$venv/bin/pip" install -r "$REPO_ROOT/requirements.txt"
  fi
  info "hub 环境就绪: $venv"
}

# ---------------------------------------------------------------- 单个引擎
bootstrap_engine() {
  local engine="$1"
  local src="$REPO_ROOT/engines/$engine"
  local venv="$VENV_ROOT/$engine"
  local pyver
  pyver="$(py_version_for "$engine")"

  if [ ! -d "$src" ] || [ -z "$(ls -A "$src" 2>/dev/null)" ]; then
    fail "$engine 子模块为空，跳过。先跑: git submodule update --init --recursive"
    return 1
  fi

  info "[$engine] 创建虚拟环境 (Python $pyver)"
  mkdir -p "$VENV_ROOT"
  if have_uv; then
    uv venv --python "$pyver" "$venv" >/dev/null
  else
    python3 -m venv "$venv"
  fi

  local py="$venv/bin/python"
  info "[$engine] 安装依赖（可能需要几分钟）"

  if [ -f "$src/requirements.txt" ]; then
    if have_uv; then
      uv pip install --python "$py" -r "$src/requirements.txt"
    else
      "$py" -m pip install --quiet --upgrade pip && "$py" -m pip install -r "$src/requirements.txt"
    fi
  elif [ -f "$src/pyproject.toml" ]; then
    if have_uv; then
      uv pip install --python "$py" -r "$src/pyproject.toml"
    else
      "$py" -m pip install --quiet --upgrade pip && "$py" -m pip install "$src"
    fi
  else
    warn "[$engine] 既无 requirements.txt 也无 pyproject.toml，跳过依赖安装"
  fi

  # 引擎自己的 .env：复制一份模板，实际值由 hub 的导通层在运行时注入
  for candidate in .env.example env_example.txt; do
    if [ -f "$src/$candidate" ] && [ ! -f "$src/.env" ]; then
      cp "$src/$candidate" "$src/.env"
      info "[$engine] 已生成 $src/.env（值由根目录 .env 覆盖注入，一般无需手改）"
      break
    fi
  done

  info "[$engine] 完成 → $py"
}

# ---------------------------------------------------------------- main
main() {
  if [ "${1:-}" = "--hub-only" ]; then
    bootstrap_hub
    return 0
  fi

  info "同步子模块"
  git submodule update --init --recursive

  bootstrap_hub

  local targets=("${ALL_ENGINES[@]}")
  if [ $# -gt 0 ]; then
    targets=("$@")
  fi

  local failed=()
  for engine in "${targets[@]}"; do
    bootstrap_engine "$engine" || failed+=("$engine")
  done

  if [ ! -f "$REPO_ROOT/.env" ]; then
    cp "$REPO_ROOT/.env.example" "$REPO_ROOT/.env"
    info "已生成 .env —— 现在去填 API Key（见 docs/REQUIRED_INPUTS.md）"
  fi

  echo
  if [ ${#failed[@]} -gt 0 ]; then
    fail "以下引擎安装失败: ${failed[*]}"
  fi
  info "下一步: 编辑 .env 后运行  python -m hub doctor"
}

main "$@"
