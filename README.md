# Stock Analysis for the Future

把五个开源 A 股 AI 预测项目接进**同一套配置、同一个预测台账、同一把标尺**。

核心主张很简单：单个引擎输出"上涨概率 78%"没有意义，因为无法验证。
本项目把五个引擎的输出统一成**可证伪的预测记录**，在 T+1 / T+5 / T+20
之后用真实行情回填，算出每个引擎、每类信号的**真实历史命中率**。

```
                     根目录 .env（唯一事实来源）
                              │
                    hub/envmap.py 导通层
              （一个 key 翻译成各引擎认识的变量名）
                              │
   ┌──────────┬───────────────┼───────────────┬──────────────┐
   ▼          ▼               ▼               ▼              ▼
 DeepEar    daily_stock   TradingAgents   aiagents-stock   advisor
 新闻→时序    每日全景        7Agent辩论      龙虎榜/板块      Claude Skill
   │          │               │               │              │
   └──────────┴───────────────┼───────────────┴──────────────┘
                              ▼
                  统一预测记录 Prediction
        （时间/输入快照/窗口/概率/驱动因素/证伪条件）
                              │
                       SQLite 台账
                              │
                    hub score（回填真实行情）
                              ▼
        方向命中率 · 相对沪深300超额 · 按信号类别的胜率
```

---

## 五个引擎

| 引擎 | 上游 | 擅长 | 运行方式 | 许可证 |
|---|---|---|---|---|
| `deepear` | [HKUSTDial/DeepEar](https://github.com/HKUSTDial/DeepEar) | 新闻语义注入时序模型（Kronos），政策与技术突破发现 | 无人值守 | MIT |
| `daily_stock_analysis` | [ZhuLinsen/daily_stock_analysis](https://github.com/ZhuLinsen/daily_stock_analysis) | 每日全景分析，数据源最丰富，自动化最成熟 | 无人值守 | MIT |
| `tradingagents_astock` | [simonlin1212/TradingAgents-astock](https://github.com/simonlin1212/TradingAgents-astock) | 7 位分析师多空辩论，政策/游资/解禁独立成 Agent | 无人值守 | Apache-2.0 |
| `aiagents_stock` | [oficcejo/aiagents-stock](https://github.com/oficcejo/aiagents-stock) | 龙虎榜、游资追踪、板块轮动、次日选股 | 无人值守 | MIT(README声明) |
| `stock_investment_advisor` | [wind1096471134/stock-investment-advisor](https://github.com/wind1096471134/stock-investment-advisor) | 纯联网搜索的情景概率研判，零 API key | Claude Skill，需交互 | MIT |

上游代码以 **git submodule** 引入，**一行未改**。所有适配都在 `hub/` 里完成。

---

## 快速开始

```bash
git clone --recursive <你的仓库地址>
cd Stock-analysis-for-the-future

# 1. 装环境（每个引擎独立 venv —— 它们的依赖互相冲突）
./scripts/bootstrap.sh

# 2. 填配置：至少一个 LLM key + 你的自选股
cp .env.example .env && vim .env

# 3. 体检：哪些引擎能跑、还缺什么
python -m hub doctor

# 4. 跑一轮，预测进台账
python -m hub run --engine all --symbols 600519,300750 --horizon 5

# 5. 过几天回填真实行情，看命中率
python -m hub score
```

只想先试最轻的那个（不需要任何 API key）：

```bash
python -m hub install-skill          # 装进 ~/.claude/skills/
# 在 Claude Code 里让它分析一只股票，把结论存成 report.md，然后：
python -m hub ingest --engine stock_investment_advisor --symbol 600519 report.md
```

---

## 命令

| 命令 | 作用 |
|---|---|
| `hub doctor` | 体检：引擎装没装、key 缺不缺、台账多少条 |
| `hub engines` | 列出所有引擎及其所需配置 |
| `hub envmap --engine X` | 查看某引擎实际会收到哪些环境变量（值已脱敏） |
| `hub run` | 跑引擎，预测写进台账 |
| `hub ingest` | 把 Skill/手工报告解析进台账 |
| `hub score` | 回填真实收益，统计命中率 |
| `hub list` | 查看台账 |
| `hub install-skill` | 安装 Claude Skill |

---

## 导通层做了什么

五个上游对同一个东西起了五个名字。你只在根目录 `.env` 填一次：

```ini
SAF_DEEPSEEK_API_KEY=sk-xxx
```

`hub/envmap.py` 自动翻译：

| 引擎 | 实际收到 |
|---|---|
| DeepEar | `DEEPSEEK_API_KEY` |
| daily_stock_analysis | `DEEPSEEK_API_KEY` + `LLM_DEEPSEEK_API_KEY` |
| TradingAgents-astock | `DEEPSEEK_API_KEY` |
| aiagents-stock | `DEEPSEEK_API_KEY` |

同时强制注入若干安全默认值：关掉引擎内置定时器和 WebUI（由 hub 统一调度）、
**强制 `MINIQMT_ENABLED=false`**（禁止自动交易）。空值永远不注入，
以免用空字符串覆盖引擎自带的配置。

---

## 预测记录长什么样

每条预测都必须能被证伪，否则不进命中率统计：

```python
Prediction(
    engine="deepear", symbol="600519",
    created_at="2026-08-15T09:30:00+00:00",   # 预测生成时间
    asof_date="2026-08-15",                    # 基准交易日
    horizon_days=5,                            # 预测窗口
    p_up=0.62, p_flat=0.25, p_down=0.13,       # 三分类概率
    direction="up",
    drivers=[Driver(category="policy", statement="国常会部署算力基建", ...)],
    falsifiers=["若市场已充分定价，事件驱动的超额收益不成立", ...],
    inputs_snapshot={...},                     # 当时可获得的全部输入
    engine_version="579b7d4",                  # 引擎 commit，可复现
    realized=[Realized(horizon_days=5, ret_pct=4.2,
                       excess_vs_bench_pct=3.2, hit=True)],
)
```

`hub score` 输出：

```
[deepear] T+5  样本=38  方向命中率=57.9%  平均收益=+1.24%  平均超额(vs基准)=+0.41%
    预测up    18/29 = 62.1%
    预测down   4/9  = 44.4%
  -- T+5 按驱动因素分类 --
     policy             12/19 = 63.2%
     capital             9/17 = 52.9%
```

---

## 请先读这一段

**这五个项目都没有公开可信的长期样本外业绩证明。** 本项目不改变这个事实，
它只是让你**能够自己验证**。在你自己积累出足够样本之前，请把所有输出
当作研究材料，而不是投资建议。

具体的已知问题：

- **概率不是校准概率。** 引擎给的"信心分"是 LLM 自评。`hub` 把它们统一
  映射成三分类概率只是为了可比较，不代表统计意义上的概率。真实可信度只能
  由 `hub score` 用实际收益回填得出。
- **回测有未来数据泄漏风险。** 即使固定 `--asof-date`，联网搜索仍可能返回
  当时尚未发布的信息。TradingAgents 上游明确警告过这一点。因此
  **前视回测的结果不可信**，只有向前推进的实盘记录（今天预测、几天后回填）才算数。
- **样本量。** 几十条预测算出来的胜率没有统计意义。至少积累几百条、
  跨越不同市场环境后再看。
- **板块/指数级预测暂不打分**（`symbol_kind != "stock"` 会被跳过），
  因为需要各板块对应的指数代码映射，尚未实现。
- **aiagents-stock 只产出看多候选**，从不给看空标的。它的方向一律记为 `up`，
  由实际收益去检验这个偏多倾向的真实胜率。
- **不要开自动交易。** 系统默认强制关闭。

---

## 文档

- [需要你提供的信息](docs/REQUIRED_INPUTS.md) ← **先看这个**
- [安装与故障排查](docs/SETUP.md)
- [架构说明](docs/ARCHITECTURE.md)
- [许可证与归属](docs/LICENSES.md)

---

## 许可证

本仓库自有代码（`hub/`、`scripts/`、`tests/`）采用 MIT。
`engines/` 下为各上游项目，各自遵循其原许可证，详见 [docs/LICENSES.md](docs/LICENSES.md)。
