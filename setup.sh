#!/usr/bin/env bash
# 一键安装 stock-analysis（历史股价归因研究工具）。
#
# 做四件事：
#   1. 拉取 engines/stock-analysis 子模块
#   2. 把它安装成全局命令 stock-analysis / stock-analysis-agent
#   3. 可选：把 Skill 装进 Claude Code / Codex，之后能用自然语言提问
#   4. 生成 .env 并体检
#
# 用法:
#   ./setup.sh                 # 安装 CLI + 询问是否装 Agent 入口
#   ./setup.sh --with-agent    # 安装 CLI 并直接装 Claude + Codex 入口
#   ./setup.sh --cli-only      # 只装 CLI，不碰 ~/.claude 和 ~/.codex
#   ./setup.sh --upgrade       # 子模块拉到上游最新版后重装

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ENGINE_DIR="$REPO_ROOT/engines/stock-analysis"
cd "$REPO_ROOT"

MODE="ask"
UPGRADE=0
for arg in "$@"; do
  case "$arg" in
    --with-agent) MODE="agent" ;;
    --cli-only)   MODE="cli" ;;
    --upgrade)    UPGRADE=1 ;;
    -h|--help)    sed -n '2,14p' "$0"; exit 0 ;;
    *) echo "未知参数: $arg（可用 --with-agent / --cli-only / --upgrade）" >&2; exit 2 ;;
  esac
done

info() { printf '\033[1;34m[setup]\033[0m %s\n' "$*"; }
warn() { printf '\033[1;33m[warn]\033[0m %s\n'  "$*"; }
fail() { printf '\033[1;31m[fail]\033[0m %s\n'  "$*" >&2; }

# ---------------------------------------------------------------- 1. 子模块
info "拉取 stock-analysis 源码"
git submodule update --init --recursive

if [ "$UPGRADE" = "1" ]; then
  info "升级到上游最新版"
  git submodule update --remote engines/stock-analysis
fi

if [ ! -f "$ENGINE_DIR/pyproject.toml" ]; then
  fail "子模块拉取失败，$ENGINE_DIR 是空的。请检查网络后重试。"
  exit 1
fi

VERSION="$(grep -m1 '^version' "$ENGINE_DIR/pyproject.toml" | cut -d'"' -f2)"
COMMIT="$(git -C "$ENGINE_DIR" rev-parse --short HEAD)"
info "版本 v$VERSION ($COMMIT)"

# ---------------------------------------------------------------- 2. 安装
# 用 uv tool / pipx 安装成**全局命令**，而不是本地 venv。
# 原因：Agent 模式下 Claude Code 需要在 PATH 上找到 stock-analysis 才能调用它。
install_tool() {
  if command -v uv >/dev/null 2>&1; then
    info "用 uv 安装（来源：本仓库固定的版本）"
    uv tool install --force "$ENGINE_DIR"
    return 0
  fi
  if command -v pipx >/dev/null 2>&1; then
    info "用 pipx 安装"
    pipx install --force "$ENGINE_DIR"
    return 0
  fi
  warn "没有 uv 也没有 pipx，回退到 pip --user"
  warn "强烈建议装 uv: curl -LsSf https://astral.sh/uv/install.sh | sh"
  python3 -m pip install --user --force-reinstall "$ENGINE_DIR"
}

install_tool

if ! command -v stock-analysis >/dev/null 2>&1; then
  warn "stock-analysis 不在 PATH 上。多半是 ~/.local/bin 没加进 PATH："
  warn '  echo '"'"'export PATH="$HOME/.local/bin:$PATH"'"'"' >> ~/.bashrc && source ~/.bashrc'
else
  info "命令就绪: $(command -v stock-analysis)"
fi

# ---------------------------------------------------------------- 3. Agent 入口
install_agent() {
  info "安装 Claude Code / Codex 入口"
  stock-analysis-agent install all
  info "重启 Claude Code 或 Codex 后即可用自然语言提问"
}

case "$MODE" in
  agent) install_agent ;;
  cli)   info "跳过 Agent 入口（--cli-only）" ;;
  ask)
    echo
    echo "是否把 Skill 装进 Claude Code / Codex？"
    echo "  装了以后可以直接说「复盘宁德时代 300750 2024 年的几次大涨」"
    echo "  会写入 ~/.claude 与 ~/.codex（只添加本项目管理的文件，可用 uninstall 撤销）"
    read -r -p "安装？[Y/n] " reply || reply="n"
    case "${reply:-Y}" in
      [Nn]*) info "跳过。以后可随时运行: stock-analysis-agent install all" ;;
      *)     install_agent ;;
    esac
    ;;
esac

# ---------------------------------------------------------------- 4. 配置
if [ ! -f "$REPO_ROOT/.env" ]; then
  cp "$REPO_ROOT/.env.example" "$REPO_ROOT/.env"
  info "已生成 .env（全部是可选项，不填也能直接用）"
fi

echo
info "安装完成。试一下："
echo "    ./sa --market price-move --symbol 300750 --depth standard"
echo
info "体检： ./sa --doctor"
