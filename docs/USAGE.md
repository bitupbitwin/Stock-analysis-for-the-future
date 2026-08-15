# 使用与排错

## 历史归因（主要用途）

```bash
# 单日异动：今天/某天为什么大涨
./sa --market price-move --symbol 300750 --window-type single-session --date 20241111

# 多日区间：某一段行情是怎么回事
./sa --market price-move --symbol 300750 \
     --window-type multi-session --start-date 20241111 --date 20241125 \
     --depth deep

# 事件窗口：围绕某个事件前后
./sa --market price-move --symbol 600519 \
     --window-type event-window --event "2024年报发布" --depth standard
```

日期格式一律 `YYYYMMDD`。

`--depth` 三档：

| 档位 | 用途 |
|---|---|
| `quick` | 快速看一眼 |
| `standard` | 默认，完整报告契约 |
| `deep` | 跨来源核验、多期与同业对照、反方审查 |

## 其他场景

```bash
./sa --market stock    --symbol 600519              # 个股研究
./sa --market a        --depth standard             # A股大盘复盘
./sa --market earnings --symbol 600519              # 财报复核
./sa --market fund     --symbol 512480              # 基金/ETF
./sa --market research --symbol 600519 --asset-type company --depth deep
```

全部参数：`./sa --help`

## Agent 模式

```bash
stock-analysis-agent install all      # 装入 Claude Code + Codex
stock-analysis-agent doctor all       # 查看安装状态
stock-analysis-agent uninstall all    # 干净卸载（只删本项目管理的文件）
```

重启宿主后直接说人话。规范入口是 `/move`（`/price-move` 已弃用，仅做兼容转发）。

```
复盘宁德时代 300750 在 2024 年 11 月那波大涨
贵州茅台 600519 最近为什么跌
用巴菲特和索罗斯对抗分析贵州茅台
```

---

## 排错

### 报告有章节但没有内容

数据源没取到。先跑 `./sa --doctor` 看连通性。国内直连一般没问题；
如果你在境外或公司网络，需要配代理。

### `stock-analysis: command not found`

`~/.local/bin` 不在 PATH：

```bash
echo 'export PATH="$HOME/.local/bin:$PATH"' >> ~/.bashrc && source ~/.bashrc
```

### 历史板块数据取不到

提示会写「历史板块榜无缓存」。在 `.env` 打开：

```ini
STOCK_ANALYSIS_BROWSER_FALLBACK=1
```

### 想看详细报错

```ini
STOCK_ANALYSIS_DEBUG=1
```

否则异常会被收敛成简短提示。

### 子模块是空的

```bash
git submodule update --init --recursive
```

或直接重跑 `./setup.sh`。

### .env 改了没生效

`sa` 只导出 `STOCK_ANALYSIS_*` 开头的变量，且**跳过空值**（空值会让上游用默认值，
而不是被空字符串覆盖）。确认你的行没有被 `#` 注释掉。

用 `stock-analysis` 而不是 `./sa` 时不会自动加载 `.env`，需要自己 export。

---

## 升级与固定版本

```bash
./setup.sh --upgrade     # 拉上游最新版并重装
```

不跑这条就一直固定在仓库记录的 commit 上。查看当前版本：

```bash
./sa --doctor            # 会打印源码 commit
git -C engines/stock-analysis log --oneline -1
```

升级后如果行为有变，可以回退：

```bash
git -C engines/stock-analysis checkout <旧commit>
./setup.sh --cli-only
```
