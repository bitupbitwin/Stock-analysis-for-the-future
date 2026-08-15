# 许可证与归属

## 本仓库自有代码

`hub/`、`scripts/`、`tests/`、`docs/` 采用 **MIT License**（见根目录 `LICENSE`）。

## 上游项目

`engines/` 下全部为 **git submodule**，即本仓库**不包含也不再分发**它们的源码，
只记录了指向各自仓库的引用和 commit。克隆时才会从上游拉取。
这样每个项目的许可证归属保持清晰，升级也不会产生冲突。

| 目录 | 上游 | 许可证 | 版权 |
|---|---|---|---|
| `engines/deepear` | HKUSTDial/DeepEar | MIT | Copyright (c) 2026 Runke Ruan |
| `engines/daily_stock_analysis` | ZhuLinsen/daily_stock_analysis | MIT | Copyright (c) 2026 ZhuLinsen |
| `engines/tradingagents_astock` | simonlin1212/TradingAgents-astock | Apache-2.0 | 见其 `NOTICE` |
| `engines/aiagents_stock` | oficcejo/aiagents-stock | ⚠️ 见下方说明 | — |
| `engines/stock_investment_advisor` | wind1096471134/stock-investment-advisor | MIT | — |

### ⚠️ aiagents-stock 的许可证情况

该项目的 `README.md` 中声明 "MIT License"，但**仓库里没有 LICENSE 文件**。

这意味着严格来说其授权状态不够明确。对本项目影响有限，因为：

- 我们用 submodule 引用，**不再分发**它的代码；
- 适配器（`hub/adapters/aiagents.py`）是我们自己写的，没有复制上游代码。

但如果你打算把本项目商用或再分发，建议先向上游作者确认许可证，
或直接停用该引擎（`hub run --engine` 指定其他引擎即可，不影响其余四个）。

### TradingAgents-astock 的 Apache-2.0 义务

Apache-2.0 要求保留 `NOTICE` 文件并标注修改。本项目**未修改**其源码，
`NOTICE` 随 submodule 一并保留在 `engines/tradingagents_astock/NOTICE`。

## 数据源

各引擎使用的行情/新闻数据（akshare、tushare、东方财富、新浪、同花顺等）
各有自己的使用条款和频率限制。**本项目不对数据的准确性、可用性或商用许可作任何保证。**
批量抓取前请自行确认对应数据源的条款。

## 免责声明

本项目及其集成的所有引擎输出仅供研究与技术学习，**不构成投资建议**。
据此进行的任何投资决策及其后果由使用者自行承担。
