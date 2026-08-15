# -*- coding: utf-8 -*-
"""原版 ``/tick query`` 输出解析。

不依赖 MCDR，便于单独测试。
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

COLOR_CODE_RE = re.compile(r"§[0-9a-fk-or]", re.IGNORECASE)
DECIMAL_COMMA_RE = re.compile(r"(\d),(\d)")
NUMBER_RE = r"(\d+(?:\.\d+)?)"

TARGET_PATTERNS = [
    re.compile(rf"Target tick rate:\s*{NUMBER_RE}\s*per second", re.IGNORECASE),
    re.compile(rf"目标刻频率[：:]\s*每秒\s*{NUMBER_RE}\s*刻"),
    re.compile(rf"running at\s*{NUMBER_RE}\s*ticks per second", re.IGNORECASE),
    re.compile(rf"正以\s*{NUMBER_RE}\s*刻每秒"),
    re.compile(rf"\(target:\s*{NUMBER_RE}\)", re.IGNORECASE),
]
AVERAGE_PATTERNS = [
    re.compile(rf"Average time per tick:\s*{NUMBER_RE}\s*m?s", re.IGNORECASE),
    re.compile(rf"Average time:\s*{NUMBER_RE}\s*m?s", re.IGNORECASE),
    re.compile(rf"average time of\s*{NUMBER_RE}\s*m?s", re.IGNORECASE),
    re.compile(rf"平均每刻耗时[：:]\s*{NUMBER_RE}\s*毫秒"),
    re.compile(rf"平均每刻耗时\s*{NUMBER_RE}\s*毫秒"),
]
PERCENTILE_RE = re.compile(
    rf"P50[:：]\s*{NUMBER_RE}\s*(?:ms|毫秒)\s*"
    rf"P95[:：]\s*{NUMBER_RE}\s*(?:ms|毫秒)\s*"
    rf"P99[:：]\s*{NUMBER_RE}\s*(?:ms|毫秒)",
    re.IGNORECASE,
)


@dataclass
class TickStats:
    """``/tick query`` 解析结果。"""

    target: float
    average: float
    p50: Optional[float] = None
    p95: Optional[float] = None
    p99: Optional[float] = None
    status: str = "running"

    @property
    def tps(self) -> float:
        if self.average <= 0:
            return self.target
        return min(self.target, 1000.0 / self.average)

    @property
    def target_mspt(self) -> float:
        if self.target <= 0:
            return 50.0
        return 1000.0 / self.target

    def to_dict(self) -> Dict[str, Any]:
        return {
            "tps": self.tps,
            "target": self.target,
            "mspt": self.average,
            "p50": self.p50,
            "p95": self.p95,
            "p99": self.p99,
            "status": self.status,
            "error": False,
        }


def normalize_tick_query_text(raw: str) -> str:
    """去掉颜色码，并把欧式小数逗号规范为点。"""
    text = COLOR_CODE_RE.sub("", raw or "")
    return DECIMAL_COMMA_RE.sub(r"\1.\2", text)


def _first_float(patterns: List[re.Pattern], text: str) -> Optional[float]:
    for pattern in patterns:
        match = pattern.search(text)
        if match:
            return float(match.group(1))
    return None


def _detect_status(text: str, average: Optional[float], target: Optional[float]) -> str:
    lowered = text.lower()
    if (
        "can't keep up" in lowered
        or "cannot keep up" in lowered
        or "无法跟上" in text
        or "跟不上" in text
    ):
        status = "lagging"
    elif "sprint" in lowered or "冲刺" in text:
        status = "sprinting"
    elif "frozen" in lowered or "冻结" in text:
        status = "frozen"
    elif "running" in lowered or "运行" in text:
        status = "running"
    else:
        status = "unknown"

    if (
        status in {"running", "unknown"}
        and average is not None
        and target is not None
        and target > 0
        and average >= 1000.0 / target
    ):
        return "lagging"
    return status


def parse_tick_query(raw: str) -> Optional[TickStats]:
    """解析原版 ``/tick query`` 的中英文输出。

    Parameters
    ----------
    raw : str
        RCON 返回的原始文本。

    Returns
    -------
    TickStats or None
        解析成功返回统计数据；无法识别时返回 None。
    """
    text = normalize_tick_query_text(raw)
    if not text.strip():
        return None

    target = _first_float(TARGET_PATTERNS, text)
    average = _first_float(AVERAGE_PATTERNS, text)
    if target is None or average is None:
        return None

    p50 = p95 = p99 = None
    percentile_match = PERCENTILE_RE.search(text)
    if percentile_match:
        p50 = float(percentile_match.group(1))
        p95 = float(percentile_match.group(2))
        p99 = float(percentile_match.group(3))

    return TickStats(
        target=target,
        average=average,
        p50=p50,
        p95=p95,
        p99=p99,
        status=_detect_status(text, average, target),
    )
