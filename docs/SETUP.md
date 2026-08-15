# 安装与故障排查

## 前置条件

| 项目 | 要求 |
|---|---|
| Python | ≥3.12（DeepEar 要求）；其余引擎 ≥3.10 |
| uv | 强烈建议。能自动下载多版本解释器 |
| 磁盘 | 约 8–12 GB（五个独立 venv，DeepEar 含 torch） |
| git | 需支持 submodule |

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

## 安装

```bash
# 克隆时带上子模块
git clone --recursive <仓库地址>
cd Stock-analysis-for-the-future

# 已经克隆过但没带 --recursive：
git submodule update --init --recursive

# 全部安装
./scripts/bootstrap.sh

# 或只装某一个（省时间省磁盘）
./scripts/bootstrap.sh daily_stock_analysis

# 只装 hub 自己的依赖（够用 doctor / list / score）
./scripts/bootstrap.sh --hub-only
```

## 为什么每个引擎一个虚拟环境

它们的依赖互相打架：

| 引擎 | Python | 主要依赖 |
|---|---|---|
| DeepEar | ≥3.12 | torch, transformers, sentence-transformers, agno |
| TradingAgents-astock | ≥3.10 | langgraph, langchain 系 |
| daily_stock_analysis | ≥3.10 | sqlalchemy, litellm, fastapi |
| aiagents-stock | ≥3.10 | streamlit, peewee, playwright |

塞进同一个环境必然版本冲突。`engines/.venvs/<engine>/` 各自独立，
`hub/runner.py` 调用时会挑对应的解释器。

## 配置

只改根目录 `.env`。**不要**去改 `engines/*/.env` —— 那些值会被导通层覆盖。

```bash
cp .env.example .env
vim .env
```

具体填什么见 [REQUIRED_INPUTS.md](REQUIRED_INPUTS.md)。

验证配置是否正确到达引擎：

```bash
python -m hub envmap --engine daily_stock_analysis
```

## 日常使用

```bash
# 每天收盘后跑一轮
python -m hub run --engine all --horizon 5

# 每周回填一次，看命中率
python -m hub score

# 只跑某个引擎
python -m hub run --engine deepear --query "AI算力政策对相关标的的影响"
```

定时任务示例（每个交易日 18:00）：

```cron
0 18 * * 1-5 cd /path/to/Stock-analysis-for-the-future && \
  .venv/bin/python -m hub run --engine all >> data/cron.log 2>&1
0 20 * * 6   cd /path/to/Stock-analysis-for-the-future && \
  .venv/bin/python -m hub score >> data/cron.log 2>&1
```

---

## 故障排查

### `doctor` 显示"子模块未拉取"

```bash
git submodule update --init --recursive
```

### `doctor` 显示"缺虚拟环境"

```bash
./scripts/bootstrap.sh <engine>
```

### DeepEar 安装失败，提示 Python 版本

DeepEar 要求 ≥3.12。装 uv 后重跑 bootstrap，它会自动下载 3.12。

### 引擎跑起来了但报"未配置 API key"

导通层只注入**非空**值。检查：

```bash
python -m hub envmap --engine <engine>
```

如果目标变量没出现在输出里，说明对应的 `SAF_*` 键在 `.env` 里是空的。

### 引擎超时

默认单引擎超时 3600 秒。多 Agent 辩论（TradingAgents）很慢：

```bash
python -m hub run --engine tradingagents_astock --timeout 7200
```

### `hub score` 回填不出结果

按顺序排查：

1. **没装 akshare** —— `./scripts/bootstrap.sh --hub-only`
2. **窗口还没走完** —— T+20 需要等 20 个交易日，这是正常的
3. **预测不可证伪** —— `hub list` 看方向是不是空的。缺方向或缺证伪条件的
   记录不进统计队列，这是有意为之
4. **板块级预测** —— `symbol_kind != "stock"` 的记录会被跳过（已知限制）

### akshare 限流 / 取数失败

配 `SAF_TUSHARE_TOKEN` 换更稳定的数据源，或降低批量大小。

### 网络代理

国内访问 OpenAI/Gemini 通常需要代理。daily_stock_analysis 自带代理开关，
可通过 `.env` 传给它：

```ini
USE_PROXY=true
PROXY_HOST=127.0.0.1
PROXY_PORT=10809
```

（这两个键会原样透传，因为它们不在 `SAF_` 命名空间内。）

---

## 更新上游引擎

```bash
git submodule update --remote engines/daily_stock_analysis
./scripts/bootstrap.sh daily_stock_analysis   # 重装依赖
python -m pytest tests/                        # 确认适配器还能解析
git add engines/daily_stock_analysis && git commit -m "chore: 更新 DSA"
```

上游改了输出格式时，适配器的解析测试会先失败 —— 这正是那些测试存在的意义。
