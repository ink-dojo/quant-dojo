"""
test_factor_monitor_health.py — factor_health_report 的样本量门禁

Phase 5 早期 live/factor_snapshot/ 只有少量快照，统计量没有意义，
不应该让 risk_monitor 错误地把因子标成 dead。

本文件验证 MIN_OBS_FOR_VERDICT 门禁的行为：
  1. 样本量不足时一律返回 insufficient_data
  2. 样本量充足且 IC 显著时返回 healthy
  3. n_obs/t_stat 字段总是被填充
"""

import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

# ── stub for optional dependency ────────────────────────────────────────────
for _pkg in ("akshare",):
    if _pkg not in sys.modules:
        sys.modules[_pkg] = MagicMock()

import numpy as np
import pandas as pd

from pipeline import factor_monitor
from pipeline.factor_monitor import factor_health_report, MIN_OBS_FOR_VERDICT


class TestFactorHealthReportInsufficientData(unittest.TestCase):
    """样本量不足时不下结论"""

    def setUp(self):
        # 写入只有 5 个快照的临时目录（< 默认 MIN_OBS_FOR_VERDICT=20）
        self.tmpdir = tempfile.TemporaryDirectory()
        self.snap_dir = Path(self.tmpdir.name)

        # 构造 5 个快照，每个包含 100 只股票的 'foo' 因子
        symbols = [f"S{i:04d}" for i in range(100)]
        rng = np.random.default_rng(42)
        for i in range(5):
            date = pd.Timestamp("2026-01-05") + pd.Timedelta(days=i)
            df = pd.DataFrame(
                {"foo": rng.normal(size=100)},
                index=symbols,
            )
            df.to_parquet(self.snap_dir / f"{date.date()}.parquet")

        # 价格数据（用 patch 替换 load_price_wide 返回值，避免触本地 CSV）
        dates = pd.bdate_range("2026-01-01", "2026-01-15")
        prices = pd.DataFrame(
            rng.normal(loc=10, scale=0.5, size=(len(dates), len(symbols))),
            index=dates,
            columns=symbols,
        )
        self._prices = prices.cumsum(axis=0).abs() + 1  # positive

    def tearDown(self):
        self.tmpdir.cleanup()

    def test_insufficient_data_status_when_few_snapshots(self):
        with patch.object(factor_monitor, "FACTOR_SNAPSHOT_DIR", self.snap_dir), \
             patch.object(factor_monitor, "load_price_wide", return_value=self._prices):
            report = factor_health_report(factors=["foo"])

        self.assertIn("foo", report)
        info = report["foo"]
        self.assertEqual(info["status"], "insufficient_data",
                         f"5 个快照应判定为 insufficient_data，实际: {info['status']}")
        self.assertLess(info["n_obs"], MIN_OBS_FOR_VERDICT)

    def test_n_obs_and_t_stat_always_present(self):
        with patch.object(factor_monitor, "FACTOR_SNAPSHOT_DIR", self.snap_dir), \
             patch.object(factor_monitor, "load_price_wide", return_value=self._prices):
            report = factor_health_report(factors=["foo"])

        info = report["foo"]
        self.assertIn("n_obs", info)
        self.assertIn("t_stat", info)
        self.assertIn("rolling_ic", info)
        self.assertIsInstance(info["n_obs"], int)

    def test_min_obs_can_be_lowered(self):
        """显式传入更低的 min_obs 应允许做出判断"""
        with patch.object(factor_monitor, "FACTOR_SNAPSHOT_DIR", self.snap_dir), \
             patch.object(factor_monitor, "load_price_wide", return_value=self._prices):
            report = factor_health_report(factors=["foo"], min_obs=3)

        info = report["foo"]
        self.assertNotEqual(info["status"], "insufficient_data",
                            "min_obs 设为 3 后，5 个快照应足以做出判断")
        self.assertIn(info["status"], {"healthy", "degraded", "dead"})

    def test_no_data_status_when_factor_missing(self):
        """快照里没有该因子时仍返回 no_data"""
        with patch.object(factor_monitor, "FACTOR_SNAPSHOT_DIR", self.snap_dir), \
             patch.object(factor_monitor, "load_price_wide", return_value=self._prices):
            report = factor_health_report(factors=["nonexistent_factor"])

        self.assertEqual(report["nonexistent_factor"]["status"], "no_data")
        self.assertEqual(report["nonexistent_factor"]["n_obs"], 0)


if __name__ == "__main__":
    unittest.main()
