"""
test_weekly_report_audit.py — 周报审计字段单元测试

验证 weekly_report 的两段审计增强：
  1. _render_audit_footer 输出包含 git commit / strategy / sha256 指纹
  2. _render_factor_health_section 正确处理 insufficient_data 状态、
     展示 n_obs 与 t_stat
  3. _render_nav_section 输出每日变化、最大回撤、最佳/最差单日
"""

import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

# stub for optional dependency
for _pkg in ("akshare",):
    if _pkg not in sys.modules:
        sys.modules[_pkg] = MagicMock()

from pipeline.weekly_report import (
    _render_audit_footer,
    _render_factor_health_section,
    _render_nav_section,
    _file_fingerprint,
)


class TestAuditFooter(unittest.TestCase):
    def test_footer_contains_strategy_and_commit_labels(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            (tmp_path / "trades.json").write_text("[]")
            (tmp_path / "positions.json").write_text("{}")
            (tmp_path / "nav.csv").write_text("date,nav\n2026-04-03,1000000\n")

            output = _render_audit_footer(
                tmp_path / "trades.json",
                tmp_path / "positions.json",
                tmp_path / "nav.csv",
            )

        self.assertIn("重现条件", output)
        self.assertIn("活跃策略", output)
        self.assertIn("代码版本", output)
        self.assertIn("数据指纹", output)
        self.assertIn("trades.json", output)
        self.assertIn("positions.json", output)
        self.assertIn("nav.csv", output)

    def test_footer_marks_missing_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            # 不创建任何文件
            output = _render_audit_footer(
                tmp_path / "trades.json",
                tmp_path / "positions.json",
                tmp_path / "nav.csv",
            )
        self.assertIn("_missing_", output)


class TestFileFingerprint(unittest.TestCase):
    def test_fingerprint_returns_sha256_short_for_existing_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "x.txt"
            p.write_text("hello")
            fp = _file_fingerprint(p)
        self.assertTrue(fp["exists"])
        self.assertEqual(fp["size_bytes"], 5)
        self.assertEqual(len(fp["sha256_short"]), 12)

    def test_fingerprint_marks_missing(self):
        fp = _file_fingerprint(Path("/nonexistent/path/x.json"))
        self.assertFalse(fp["exists"])


class TestFactorHealthRendering(unittest.TestCase):
    def test_insufficient_data_status_rendered(self):
        health = {
            "team_coin": {
                "rolling_ic": 0.0124,
                "n_obs": 6,
                "t_stat": 0.5,
                "status": "insufficient_data",
            }
        }
        out = _render_factor_health_section(health)
        self.assertIn("team_coin", out)
        self.assertIn("样本不足", out)
        # n_obs 与 t_stat 必须在表里
        self.assertIn("| 6 |", out)
        self.assertIn("+0.50", out)

    def test_healthy_factor_rendered_with_t_stat(self):
        health = {
            "low_vol_20d": {
                "rolling_ic": 0.0448,
                "n_obs": 480,
                "t_stat": 4.49,
                "status": "healthy",
            }
        }
        out = _render_factor_health_section(health)
        self.assertIn("low_vol_20d", out)
        self.assertIn("健康", out)
        self.assertIn("+0.0448", out)
        self.assertIn("+4.49", out)


class TestNavSectionEnhanced(unittest.TestCase):
    def test_nav_section_includes_max_dd_and_extremes(self):
        nav_rows = [
            {"date": "2026-04-01", "nav": 1_000_000.0},
            {"date": "2026-04-02", "nav": 1_005_000.0},
            {"date": "2026-04-03", "nav": 990_000.0},
        ]
        out = _render_nav_section(nav_rows, all_nav=nav_rows, week_start="2026-04-01")
        self.assertIn("最大回撤", out)
        self.assertIn("最佳单日", out)
        self.assertIn("最差单日", out)
        self.assertIn("日变化", out)


if __name__ == "__main__":
    unittest.main()
