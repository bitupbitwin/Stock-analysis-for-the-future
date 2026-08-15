# Stock Analysis for the Future

历史股价归因研究 —— 输入一只股票和一段时间，回答「这段涨跌到底是因为什么」。

内核是 [AdvancingTitans/stock-analysis](https://github.com/AdvancingTitans/stock-analysis) v5.0.0，
以 git submodule 固定在 `engines/stock-analysis`，**上游代码零修改**。
本仓库负责的是把它装好、配好、开箱可用。

---

## ⚠️ 先说一件事：这个工具不需要大模型 API Key

这和常见的 AI 选股项目不一样。它有两种用法，**都不用你填任何 key**：

| 模式 | 谁在做分析 | 要不要 API Key |
|---|---|---|
| **CLI 模式** | 程序本身。抓公开数据 → 按固定报告契约输出，全程不调用大模型 | 不需要 |
| **Agent 模式** | 你已经在用的 Claude Code / Codex。它调用本 CLI 取数，再自己推理 | 不需要（用你原本的 Claude 登录） |

`.env` 里全是可选项（缓存目录、抓取开关之类），一个都不填也能直接跑。

真正需要的只有一样：**能访问中国财经网站的网络**（东方财富、新浪财经、腾讯财经等）。

---

## 三步跑起来

```bash
git clone <你的仓库地址>
cd Stock-analysis-for-the-future
./setup.sh
```

`setup.sh` 会拉子模块、把 `stock-analysis` 装成全局命令、问你要不要装
Claude Code / Codex 入口、生成 `.env`。装完直接用：

```bash
# 复盘一次异动
./sa --market price-move --symbol 300750 --depth standard

# 复盘一段历史区间
./sa --market price-move --symbol 300750 \
     --window-type multi-session --start-date 20241111 --date 20241125

# 体检：装好没、配置读到没、数据源通不通
./sa --doctor
```

装了 Agent 入口的话，重启 Claude Code 后直接说人话：

```
复盘宁德时代 300750 在 2024 年 11 月那波大涨到底是因为什么
分析贵州茅台 600519
今天 A 股发生了什么
```

---

## 历史归因怎么用

三种分析边界，对应三类问题：

| `--window-type` | 适用场景 | 必需参数 |
|---|---|---|
| `single-session` | 「今天为什么突然大涨」 | `--date`（缺省为最新交易日） |
| `multi-session` | 「11月这半个月那波行情是怎么回事」 | `--start-date` + `--date` |
| `event-window` | 「财报发布前后股价怎么走的」 | `--event` 事件标签 |

深度用 `--depth quick / standard / deep` 控制。

报告固定包含这几节：

```
价格与成交异常 → 事件时间线 → 已确认原因 → 高相关解释
→ 市场结构因素 → 是否改变基本面 → 后续验证
```

**这个结构本身就是它最大的价值**：它把「已确认原因」和「高相关解释」分开，
并且在证据不足时明确写「未发现能确认因果的一手披露」，而不是硬凑一个理由。
它也不会用晚于异动的公告去倒推之前的行情。

历史复盘最容易犯的错就是把时间上的巧合当成因果 —— 这个工具在报告契约层面
就堵住了这条路。

---

## 目录

```
engines/stock-analysis/   上游源码（submodule，不改）
setup.sh                  一键安装
sa                        CLI 包装：自动加载 .env + --doctor 体检
.env.example              可选配置说明
docs/
├── REQUIRED_INPUTS.md    需要你提供什么（结论：几乎不需要）
└── USAGE.md              常用命令与排错
```

`sa` 只是个薄包装，省掉每次手动 export 环境变量。直接用 `stock-analysis` 完全等价。

---

## 已知限制

- **数据源在境内**。东方财富、新浪、腾讯等站点如果访问不了，报告会是一份
  只有骨架、没有内容的空壳。`./sa --doctor` 会直接告诉你通不通。
- **历史数据依赖缓存**。部分数据（如历史板块榜）默认只读本地缓存。做历史复盘
  建议在 `.env` 里打开 `STOCK_ANALYSIS_BROWSER_FALLBACK=1`，慢但能补历史。
- **它不预测未来，也不选股**。这是个复盘工具，输出的是「候选原因 + 证据等级」，
  不是买卖建议。
- **归因是研究判断，不是统计因果**。即使剔除了大盘和行业 Beta，事件研究本身
  也只能证明异常收益与事件在时间上相关。报告里的「高相关解释」就是这个意思，
  不要当成结论。

---

## 升级上游

```bash
./setup.sh --upgrade
```

会把子模块拉到上游最新版并重装。想固定在当前版本就不要跑这条。

---

## 许可证

本仓库自有内容（`setup.sh`、`sa`、`docs/`）采用 MIT。
`engines/stock-analysis` 为上游项目，MIT License，Copyright (c) 2026 yjw。
以 submodule 引用，本仓库不再分发其源码。

报告仅供研究，不构成投资建议。
