"""stock-investment-advisor 适配器。

这个上游**不是程序**，是一个 Claude Skill（只有 SKILL.md + references/）。
它靠 Claude 的 WebSearch 联网检索，产出"乐观/基准/悲观 + 概率"的情景研判。

所以导通方式和别的引擎不同：
  1. `hub install-skill` 把它软链到 ~/.claude/skills/，Claude Code 里就能直接用；
  2. 分析完把 Markdown 结论存成文件，用 `hub ingest --engine advisor <file>`
     解析成统一预测记录，一起进台账受同样的命中率检验。

不假装它能无人值守跑 —— headless=False。
"""

from __future__ import annotations

import re
from pathlib import Path

from ..schema import DIRECTION_DOWN, DIRECTION_FLAT, DIRECTION_UP, Driver, Prediction
from .base import Adapter, AnalysisRequest, normalize_a_share_code, parse_percent

# 情景关键词 -> 方向
_SCENARIO_KEYWORDS = {
    DIRECTION_UP: ("乐观情景", "乐观", "bull case", "optimistic"),
    DIRECTION_FLAT: ("基准情景", "基准", "base case", "neutral"),
    DIRECTION_DOWN: ("悲观情景", "悲观", "bear case", "pessimistic"),
}

_DRIVER_SECTION_HINTS = {
    "policy": ("政策", "监管", "policy"),
    "news": ("新闻", "公告", "事件", "news"),
    "capital": ("资金", "北向", "主力", "fund flow"),
    "technical": ("技术", "均线", "rsi", "technical"),
    "fundamental": ("财报", "估值", "业绩", "fundamental", "valuation"),
    "theme": ("题材", "板块", "概念", "sector"),
}


class AdvisorAdapter(Adapter):
    name = "stock_investment_advisor"
    headless = False  # 需要 Claude 的 WebSearch，不能纯脚本跑

    def run(self, request: AnalysisRequest) -> list[Prediction]:
        raise NotImplementedError(
            "stock-investment-advisor 是 Claude Skill，不能由 hub 直接执行。\n"
            "用法：\n"
            "  1) python -m hub install-skill      # 安装到 ~/.claude/skills/\n"
            "  2) 在 Claude Code 里让它分析某只股票\n"
            "  3) 把结论存成 .md 后：python -m hub ingest --engine "
            "stock_investment_advisor --symbol 600519 report.md"
        )

    # ------------------------------------------------------------------
    def parse_markdown(
        self, text: str, request: AnalysisRequest, *, symbol: str, source_path: str | None = None
    ) -> list[Prediction]:
        """解析 Skill 输出的 Markdown 研判。"""
        p_up = self._scenario_prob(text, DIRECTION_UP)
        p_flat = self._scenario_prob(text, DIRECTION_FLAT)
        p_down = self._scenario_prob(text, DIRECTION_DOWN)

        drivers = []
        for category, hints in _DRIVER_SECTION_HINTS.items():
            for hint in hints:
                m = re.search(
                    rf"^#{{1,6}}\s*.*{re.escape(hint)}.*$\n((?:(?!^#{{1,6}}\s).*\n?)*)",
                    text, re.MULTILINE | re.IGNORECASE,
                )
                if m and m.group(1).strip():
                    drivers.append(
                        Driver(category=category, statement=m.group(1).strip()[:400], weight=0.0)
                    )
                    break

        falsifiers = self._extract_falsifiers(text)
        falsifiers.append("窗口内跑输沪深300 视为本条判断无超额价值")

        pred = self._base_prediction(
            normalize_a_share_code(symbol), request,
            p_up=p_up, p_flat=p_flat, p_down=p_down,
            rationale=text[:8000],
            falsifiers=falsifiers,
            raw_output_path=source_path,
        )
        pred.drivers = drivers
        pred.inputs_snapshot = {
            "source": "claude_websearch",
            "markdown_chars": len(text),
            "scenario_probs_found": [
                d for d, p in
                ((DIRECTION_UP, p_up), (DIRECTION_FLAT, p_flat), (DIRECTION_DOWN, p_down))
                if p is not None
            ],
        }
        pred.normalize_probabilities()
        pred.infer_direction()
        return [pred]

    @staticmethod
    def _scenario_prob(text: str, direction: str) -> float | None:
        for keyword in _SCENARIO_KEYWORDS[direction]:
            value = parse_percent(text, (keyword,))
            if value is not None:
                return value
        return None

    @staticmethod
    def _extract_falsifiers(text: str) -> list[str]:
        out: list[str] = []
        for hint in ("证伪", "风险", "falsif", "invalidat"):
            m = re.search(
                rf"^#{{1,6}}\s*.*{hint}.*$\n((?:(?!^#{{1,6}}\s).*\n?)*)",
                text, re.MULTILINE | re.IGNORECASE,
            )
            if m:
                for line in m.group(1).splitlines():
                    stripped = line.strip().lstrip("-*0123456789. ").strip()
                    if len(stripped) > 4:
                        out.append(stripped[:300])
        return out[:10]


def skill_source_dir() -> Path:
    from .. import config

    return config.ENGINE_PATHS["stock_investment_advisor"]
