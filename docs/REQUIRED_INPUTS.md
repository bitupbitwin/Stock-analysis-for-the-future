# 需要你提供的信息

**结论先给：几乎什么都不用提供。**

你原本的预期是「配置大模型 apikey 以后就能用」。这个项目不是这么工作的 ——
它压根不读任何 LLM API Key。下面解释清楚，以及真正需要你确认的少数几件事。

---

## 1. 为什么不需要大模型 API Key

我在源码里查过了：整个项目读取的环境变量只有这些，没有一个和大模型有关。

```
STOCK_ANALYSIS_CACHE_DIR         行情缓存目录
STOCK_ANALYSIS_RESEARCH_DIR      研究工作区
STOCK_ANALYSIS_THESIS_DIR        投资论文目录
STOCK_ANALYSIS_HOME              Agent 安装记录目录
STOCK_ANALYSIS_PROFILE           投资画像
STOCK_ANALYSIS_BROWSER_FALLBACK  浏览器兜底抓取开关
STOCK_ANALYSIS_DEBUG             调试输出
STOCK_ANALYSIS_LENSES_DIR        分析框架配置目录
CLAUDE_CONFIG_DIR / CODEX_HOME   宿主 Agent 的配置目录
```

原因是它的分工方式：

- **CLI 模式**：程序自己抓公开数据（东方财富、新浪、交易所公告等），
  按预先写死的报告契约填充章节。这一路完全是确定性代码，不涉及大模型。
- **Agent 模式**：Skill 装进 Claude Code / Codex 后，是**宿主 Agent 调用这个 CLI**
  取数，然后由宿主自己推理成自然语言报告。用的是你打开 Claude Code 时
  已经登录的那个账号，不需要在本项目里再配一次。

所以无论哪种模式，都没有「本项目的 API Key」这个东西。

---

## 2. 唯一真正必需的：网络

这个工具的数据来自境内财经站点：

```
push2his.eastmoney.com    历史行情
quote.eastmoney.com       行情快照
data.eastmoney.com        资金流、板块
hq.sinajs.cn              新浪行情
qt.gtimg.cn               腾讯行情
www.sse.com.cn            上交所公告
q.10jqka.com.cn           同花顺
```

访问不了的话，报告还是会生成，但里面**没有数据** —— 只剩章节标题和
「未发现可确认披露」这类占位说明。

自查：

```bash
./sa --doctor
```

会逐个测试数据源连通性并直接告诉你结果。

> 顺带一提：我在开发沙箱里跑过，这些域名全部被出口策略拦截，所以我**没能**
> 端到端验证真实数据下的报告质量。安装链路、参数传递、配置注入我都实测通过了，
> 但「报告内容好不好」需要你在本地网络正常的环境里自己看一眼。

---

## 3. 建议你确认的三件事（都不是必需）

### 3.1 要不要装 Agent 入口

`./setup.sh` 会问你。装了以后可以在 Claude Code 里说人话提问，
代价是会往 `~/.claude` 和 `~/.codex` 写入文件（只写本项目管理的文件，
可用 `stock-analysis-agent uninstall all` 干净撤销）。

只想用命令行就选 `n`，或者直接 `./setup.sh --cli-only`。

### 3.2 要不要打开浏览器兜底抓取

做历史复盘建议打开 —— 部分历史数据（如历史板块榜）默认只读本地缓存，
新装的机器没有缓存就取不到历史。

在 `.env` 里：

```ini
STOCK_ANALYSIS_BROWSER_FALLBACK=1
```

代价是慢。只做当日分析可以不开。

### 3.3 缓存目录放哪

默认 `~/.cache/stock-analysis`。这个缓存会随着你每天使用逐步积累历史数据，
**建议保持默认、不要定期清理** —— 清了历史复盘能力会变差。

想放到别处（比如大容量磁盘）：

```ini
STOCK_ANALYSIS_CACHE_DIR=/data/stock-analysis-cache
```

---

## 4. 环境要求

| 项目 | 要求 |
|---|---|
| Python | ≥3.9 |
| uv 或 pipx | 建议装 uv：`curl -LsSf https://astral.sh/uv/install.sh \| sh` |
| 磁盘 | 很小。依赖只有 pypdf / requests / xlrd，加上源码约 80 MB |
| 网络 | 能访问境内财经站点（见上） |

装完如果提示 `stock-analysis: command not found`，是 `~/.local/bin` 不在 PATH：

```bash
echo 'export PATH="$HOME/.local/bin:$PATH"' >> ~/.bashrc && source ~/.bashrc
```

---

## 5. 如果你确实想要「大模型 API Key」那种用法

那说明你要的是另一类工具 —— 自己带 LLM、自己调 API 的那种。
这个项目的设计取向正好相反：它把推理交给宿主 Agent，自己只负责
**确定性的取数和报告契约**。

这其实是它做历史归因比别的项目靠谱的原因：证据分级、拒绝用后发公告倒推
前期行情、区分「已确认原因」和「高相关解释」，这些都是写死在代码里的规则，
不依赖某次大模型输出的发挥。
