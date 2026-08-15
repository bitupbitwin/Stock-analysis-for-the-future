# 架构说明

## 设计约束

1. **上游代码一行不改。** 全部通过 submodule 引用。上游更新时 `git submodule update`
   即可，不存在合并冲突。所有适配逻辑集中在 `hub/`。
2. **一份配置，五处翻译。** 用户只填根目录 `.env`，导通层负责映射。
3. **每个引擎独立 venv。** 依赖冲突用物理隔离解决，不试图调和。
4. **不替引擎编造它没输出的东西。** 缺失就是缺失，落库为 `None`。
5. **台账只写不改。** 预测一旦落库不再修改，只允许追加回填结果。

## 目录

```
hub/                    集成层（本仓库自有代码，零第三方依赖）
├── config.py           .env 加载、路径常量
├── envmap.py           ★ 导通层：统一键 → 各引擎变量名
├── schema.py           ★ 统一预测记录 Prediction / Driver / Realized
├── store.py            SQLite 台账
├── runner.py           子进程执行（选对 venv、注入环境、设 cwd）
├── market.py           akshare 取数（仅回填用）
├── scoring.py          ★ 回填真实收益 + 命中率统计
├── doctor.py           环境体检
├── cli.py              命令行
└── adapters/           每个引擎一个适配器
    ├── base.py         基类 + 中文方向解析 + 概率映射
    ├── deepear.py
    ├── daily_stock.py
    ├── tradingagents.py
    ├── aiagents.py
    └── advisor.py

engines/                上游项目（submodule，不改）
├── .venvs/             各引擎独立虚拟环境（gitignore）
└── <5 个子模块>

scripts/
├── bootstrap.sh        一键装环境
└── drivers/            注入到引擎 venv 内运行的驱动脚本
    ├── tradingagents_driver.py
    └── aiagents_driver.py
```

## 数据流

```
.env
 └─► config.load_settings()
      └─► envmap.project_env(engine, values)      # 翻译成引擎变量名
           └─► runner.run(engine, args, env)      # 引擎自己的 venv + cwd
                └─► 引擎产出（JSON / SQLite / Markdown）
                     └─► adapters.<engine>.parse_*()
                          └─► Prediction（统一记录）
                               └─► store.save()   # SQLite 台账
                                    └─► scoring.score_prediction()
                                         └─► Realized（T+N 真实收益）
                                              └─► scoring.aggregate()
                                                   └─► 命中率
```

## 各引擎的接入方式

不同引擎的"出口"不一样，适配方式也不同：

| 引擎 | 调用入口 | 结果来源 | 适配难点 |
|---|---|---|---|
| DeepEar | `src/main_flow.py --run-id X` | `reports/checkpoints/X/analyzed_signals.json` | 一条信号可能影响多只股票，需展开成多条预测 |
| daily_stock_analysis | `main.py` | `data/stock_analysis.db` 的 `analysis_history` 表 | 需记录跑前水位线（`MAX(id)`），只取本轮新增 |
| TradingAgents-astock | 注入 driver 脚本 | driver 输出的 JSON | 上游只有 `propagate()` API，没有 JSON 出口，需自己写 driver |
| aiagents-stock | 注入 driver 脚本 | driver JSON 或 `longhubang.db` | Streamlit 优先，需绕到 `LonghubangEngine` |
| stock_investment_advisor | 不可脚本化 | 用户提供的 Markdown | 是 Claude Skill，靠 WebSearch，只能 `hub ingest` |

**driver 脚本**（`scripts/drivers/`）是为了给没有 JSON 出口的引擎补一个出口。
它们在引擎自己的 venv 内运行、cwd 设为引擎目录，只 import 上游的公开类，
不修改上游任何文件。

## 概率映射

不同引擎给的"信心"口径完全不同：

| 引擎 | 原始输出 |
|---|---|
| DeepEar | `sentiment_score` (-1~1) + `confidence` (0~1) |
| daily_stock_analysis | `sentiment_score` (0~100) + 中文标签"看多/震荡/看空" |
| TradingAgents | 只有一段中文决策文本 |
| aiagents-stock | "高/中/低" |
| advisor | 明确的情景概率（"乐观 40%"） |

统一成三分类概率的方法（`adapters/base.py:sentiment_to_probabilities`）：

```
raw = (max(s,0), 1-|s|, max(-s,0))          # 信号隐含分布
p   = c * raw + (1-c) * (1/3, 1/3, 1/3)     # 按置信度混合无信息先验
```

置信度低时把质量拉回均匀分布，但**不翻转 argmax** —— 中等强度的看空信号
仍判为看空，不会因为置信度不满分就被压成"震荡"。

**这是启发式映射，不是校准概率。** 它的唯一作用是让五个引擎的输出能落进
同一张表里比较。真正的可信度只能由 `hub score` 用实际收益回填统计出来。

TradingAgents 只给方向不给概率 —— 那就留 `None`，不编。

## 命中率判定

```
实际收益 > +neutral_band  →  up
实际收益 < -neutral_band  →  down
其余                      →  flat
命中 = (预测方向 == 实际方向)
```

`neutral_band` 默认 ±2%，由 `SAF_NEUTRAL_BAND_PCT` 控制。

**只有可证伪的预测才进统计**（`Prediction.is_falsifiable()`）：必须同时有
标的、窗口、方向、证伪条件。缺任何一项的记录会被单独标记，不混进胜率。

窗口没走完时 `forward_return_pct` 返回 `None` —— 宁可没样本，也不用不完整
数据凑一个胜率。

## 安全默认值

`envmap.ENGINE_STATIC_ENV` 强制注入：

- `SCHEDULE_ENABLED=false` / `WEBUI_ENABLED=false` —— 由 hub 统一调度，
  不让引擎内部再起定时器
- `SAVE_CONTEXT_SNAPSHOT=true` —— hub 需要它来记录"当时可获得的输入"
- **`MINIQMT_ENABLED=false`** —— 禁止自动交易。即使用户在 `.env` 里写了
  `true` 也会被 `envmap.project_env()` 拦下，除非显式传 `allow_live_trading=True`

## 测试策略

全部离线，不依赖网络和 API key：

| 文件 | 覆盖 |
|---|---|
| `test_envmap.py` | 导通层 —— 这层错了所有引擎都拿到错的 key |
| `test_schema_and_store.py` | 预测记录语义、台账幂等、可证伪判定 |
| `test_adapters.py` | 五个适配器的解析，fixture 字段名取自上游真实 schema |
| `test_scoring.py` | 收益计算、命中率聚合、窗口不足时的行为 |
| `test_config_and_cli.py` | .env 解析、CLI 参数、脱敏 |

适配器测试用伪造的上游产物驱动。**上游改了输出格式时，这些测试会先失败** ——
这正是它们存在的意义。
