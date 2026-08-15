# 需要你提供的信息

按优先级排列。**只有第 1 项是必需的**，其余都能让系统跑得更好，但不填也能启动。

随时可以用可执行版本代替本文档（文档会过期，它不会）：

```bash
python -m hub doctor
```

---

## 第 0 步：你必须先做的一个决定

**你打算用哪家大模型？** 五个引擎里有四个是 LLM 驱动的，没有 LLM key 它们一行都跑不了。

| 选择 | 成本 | 覆盖引擎 | 建议 |
|---|---|---|---|
| **DeepSeek** | 最低 | 4/4 全覆盖 | ⭐ 推荐起步，一个 key 全线通电 |
| OpenAI | 高 | 3/4 | 效果好但贵，A股中文语料未必占优 |
| Gemini | 有免费额度 | 2/4 | 免费额度适合先试水 |
| 阿里百炼 DashScope | 中 | 2/4 | 国内网络访问稳定 |
| OpenRouter | 中 | 2/4 | 一个 key 转发多家模型 |

> 只填 `SAF_DEEPSEEK_API_KEY` 一项，四个代码引擎就都能跑。这是最省事的路径。

---

## 1. 必需 —— 至少一个 LLM API Key

在 `.env` 里填**至少一个**：

| 键 | 去哪申请 | 影响哪些引擎 |
|---|---|---|
| `SAF_DEEPSEEK_API_KEY` | platform.deepseek.com | DeepEar、DSA、TradingAgents、aiagents ✅全部 |
| `SAF_OPENAI_API_KEY` | platform.openai.com | DeepEar、DSA、TradingAgents |
| `SAF_GEMINI_API_KEY` | aistudio.google.com | DSA、TradingAgents |
| `SAF_DASHSCOPE_API_KEY` | bailian.console.aliyun.com | DeepEar、TradingAgents |
| `SAF_OPENROUTER_API_KEY` | openrouter.ai | DeepEar、TradingAgents |
| `SAF_ANTHROPIC_API_KEY` | console.anthropic.com | DSA、TradingAgents |
| `SAF_ANSPIRE_API_KEY` | Anspire Open | DSA（模型+搜索一站式） |
| `SAF_ZHIPU_API_KEY` / `SAF_MINIMAX_API_KEY` | 各自官网 | TradingAgents |

**不填任何一个的后果**：只有 `stock_investment_advisor`（Claude Skill）能用，
因为它走 Claude 自己的 WebSearch，不需要额外 key。

---

## 2. 强烈建议 —— 新闻与搜索源

这直接决定"能不能自动发现政策转向和技术突破"。全空时 DSA 会退回免费的
SearXNG 公共实例，能跑，但**会限流、结果不稳定**。

| 键 | 说明 |
|---|---|
| `SAF_TAVILY_API_KEY` | 有免费额度，专为 LLM 检索设计，性价比最高 ⭐ |
| `SAF_SERPAPI_API_KEY` | Google 结果质量最好，免费额度少 |
| `SAF_BRAVE_API_KEY` | 有免费额度 |
| `SAF_SEARXNG_BASE_URL` | 自建 SearXNG 实例地址，完全免费但要自己部署 |
| `SAF_JINA_API_KEY` | DeepEar 抓正文用（r.jina.ai）；不填会退化到内置抓取 |

---

## 3. 建议 —— 行情数据源

| 键 | 说明 |
|---|---|
| `SAF_TUSHARE_TOKEN` | tushare.pro，免费注册。不填则全靠 akshare 免费源，**有频率限制、偶发失败** |
| `SAF_FINNHUB_API_KEY` | 只在分析美股时需要 |
| `SAF_ALPHAVANTAGE_API_KEY` | 同上，可选 |

**不填的后果**：能跑，但批量分析时容易被限流。个人小批量自选股一般够用。

---

## 4. 你的投资参数 —— 这些只有你能决定

| 键 | 默认值 | 说明 |
|---|---|---|
| `SAF_WATCHLIST` | `600519,300750,002594` | **你的自选股**，6 位代码逗号分隔。请务必改成你自己的 |
| `SAF_BENCHMARK` | `000300` | 算超额收益的基准。沪深300=000300，中证500=000905 |
| `SAF_NEUTRAL_BAND_PCT` | `2.0` | 涨跌幅在 ±2% 内算"震荡"。调大 = 命中判定更严格 |

关于 `SAF_NEUTRAL_BAND_PCT`：这个值直接决定命中率数字好不好看。
调到 0 会让几乎所有预测都被判成涨或跌（胜率虚高接近抛硬币）；
调到 5 会让大部分判成震荡。**先定死再统计，不要看到结果不满意再回头调** ——
那是自欺欺人。

---

## 5. 可选 —— 结果推送

| 键 | 说明 |
|---|---|
| `SAF_WECOM_WEBHOOK` | 企业微信机器人 |
| `SAF_DINGTALK_WEBHOOK` | 钉钉机器人 |
| `SAF_FEISHU_WEBHOOK` | 飞书机器人 |

---

## 6. 环境层面需要你确认的事

1. **Python 版本**：DeepEar 要求 ≥3.12，其余 ≥3.10。
   装了 `uv` 的话会自动下载对应解释器，不用你操心；没装 uv 则需要本机已有 3.12。
   ```bash
   curl -LsSf https://astral.sh/uv/install.sh | sh
   ```

2. **磁盘空间**：五个引擎各自独立 venv，DeepEar 带 torch，**合计约 8–12 GB**。

3. **网络**：需要能访问各 LLM 厂商 API 和财经数据站点。
   国内访问 OpenAI/Gemini 通常需要代理；DeepSeek/DashScope/akshare 直连即可。

4. **是否开启自动交易**：aiagents-stock 预留了 MiniQMT 实盘接口。
   **系统默认强制关闭**（`MINIQMT_ENABLED=false`，见 `hub/envmap.py`）。
   在你自己积累足够长的样本外验证之前，请不要打开。

---

## 我需要你回答的问题（如果希望我继续配置）

1. 你打算用哪家 LLM？（推荐 DeepSeek）
2. 你的自选股是哪些？（给我 6 位代码）
3. 你的关注周期是短线（T+1~T+5）还是中线（T+20）？
4. 需不需要每天定时自动跑 + 推送到微信/钉钉/飞书？
5. 有没有 tushare token 和任一搜索 API key？

> **不要把真实 key 直接发给我或粘进对话**。自己写进 `.env` 即可 ——
> 该文件已在 `.gitignore` 中，不会进仓库。
