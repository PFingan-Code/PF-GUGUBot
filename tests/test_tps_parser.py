# -*- coding: utf-8 -*-
import importlib.util
import sys
import unittest
from pathlib import Path

_PARSER_PATH = (
    Path(__file__).resolve().parents[1]
    / "GUGUbot"
    / "gugubot"
    / "utils"
    / "tick_query.py"
)
_spec = importlib.util.spec_from_file_location("tick_query", _PARSER_PATH)
_tick_query = importlib.util.module_from_spec(_spec)
sys.modules["tick_query"] = _tick_query
_spec.loader.exec_module(_tick_query)
parse_tick_query = _tick_query.parse_tick_query


class TestTickQueryParser(unittest.TestCase):
    def test_parse_english(self):
        raw = (
            "The game is running.\n"
            "Target tick rate: 20.0 per second.\n"
            "Average time per tick: 12.34ms\n"
            "Percentiles: P50: 11.2ms P95: 18.5ms P99: 25.1ms from 100 target"
        )
        stats = parse_tick_query(raw)
        self.assertIsNotNone(stats)
        self.assertEqual(stats.status, "running")
        self.assertEqual(stats.target, 20.0)
        self.assertEqual(stats.average, 12.34)
        self.assertEqual(stats.p50, 11.2)
        self.assertEqual(stats.p95, 18.5)
        self.assertEqual(stats.p99, 25.1)
        self.assertAlmostEqual(stats.tps, 20.0)
        self.assertAlmostEqual(stats.target_mspt, 50.0)

    def test_parse_chinese(self):
        raw = (
            "游戏正在运行。\n"
            "目标刻频率：每秒 20.0 刻。\n"
            "平均每刻耗时：12.34毫秒\n"
            "百分位数：P50：11.2毫秒 P95：18.5毫秒 P99：25.1毫秒，来自 100 个目标"
        )
        stats = parse_tick_query(raw)
        self.assertIsNotNone(stats)
        self.assertEqual(stats.status, "running")
        self.assertEqual(stats.target, 20.0)
        self.assertEqual(stats.average, 12.34)
        self.assertEqual(stats.p50, 11.2)
        self.assertEqual(stats.p95, 18.5)
        self.assertEqual(stats.p99, 25.1)

    def test_parse_lagging_by_status_and_mspt(self):
        raw = (
            "The game is running, but can't keep up with the target tick rate.\n"
            "Target tick rate: 20.0 per second.\n"
            "Average time per tick: 62.50ms\n"
            "Percentiles: P50: 60.0ms P95: 80.0ms P99: 90.0ms from 100 target"
        )
        stats = parse_tick_query(raw)
        self.assertIsNotNone(stats)
        self.assertEqual(stats.status, "lagging")
        self.assertAlmostEqual(stats.tps, 16.0)

    def test_parse_without_percentiles(self):
        raw = (
            "The game is running.\n"
            "Target tick rate: 20.0 per second.\n"
            "Average time per tick: 8.00ms"
        )
        stats = parse_tick_query(raw)
        self.assertIsNotNone(stats)
        self.assertEqual(stats.average, 8.0)
        self.assertIsNone(stats.p50)
        self.assertIsNone(stats.p95)
        self.assertIsNone(stats.p99)

    def test_parse_color_codes_and_decimal_comma(self):
        raw = (
            "§aThe game is running.§r\n"
            "Target tick rate: 20,0 per second.\n"
            "Average time per tick: 12,34ms\n"
            "Percentiles: P50: 11,2ms P95: 18,5ms P99: 25,1ms from 100 target"
        )
        stats = parse_tick_query(raw)
        self.assertIsNotNone(stats)
        self.assertEqual(stats.target, 20.0)
        self.assertEqual(stats.average, 12.34)
        self.assertEqual(stats.p50, 11.2)

    def test_parse_invalid(self):
        self.assertIsNone(parse_tick_query(""))
        self.assertIsNone(parse_tick_query("Unknown command"))
        self.assertIsNone(parse_tick_query("Incorrect argument"))


if __name__ == "__main__":
    unittest.main()
