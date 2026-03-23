"""
test_phase5_smoke.py — Phase 5 主链路冒烟测试

测试三个核心模块的接口和返回结构:
  1. pipeline.daily_signal.run_daily_pipeline  — 信号生成
  2. live.paper_trader.PaperTrader             — 模拟盘追踪
  3. live.risk_monitor.check_risk_alerts       — 风险监控

所有外部 IO（文件读写、数据加载）均通过 unittest.mock.patch 隔离，
无需真实数据即可运行。

运行方式:
  python -m pytest tests/ -v
  python -m unittest tests.test_phase5_smoke
"""

import contextlib
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

# ── 提前注入缺失的第三方依赖 stub ─────────────────────────────────────────
# utils/__init__.py 传递性地 import akshare（通过 data_loader / universe /
# fundamental_loader），但测试环境可能未安装。将其预先注入 sys.modules
# 以便 utils 包及其子模块能够成功导入。
for _pkg in ("akshare",):
    if _pkg not in sys.modules:
        sys.modules[_pkg] = MagicMock()
# ──────────────────────────────────────────────────────────────────────────

import numpy as np
import pandas as pd


# ─────────────────────────────────────────────────────────────────────────────
# 1. TestSignalStructure
# ─────────────────────────────────────────────────────────────────────────────

class TestSignalStructure(unittest.TestCase):
    """测试 run_daily_pipeline() 返回结构的正确性。"""

    SYMBOLS = ["000001.SZ", "000002.SZ", "600000.SH"]

    def _fake_price_df(self) -> pd.DataFrame:
        """构造 100 行 × 3 列的假价格 DataFrame（随机种子固定）。"""
        dates = pd.date_range("2025-01-01", periods=100, freq="B")
        rng = np.random.default_rng(42)
        data = rng.uniform(5.0, 50.0, (100, len(self.SYMBOLS)))
        return pd.DataFrame(data, index=dates, columns=self.SYMBOLS)

    def test_success_returns_required_keys(self):
        """成功路径：返回 dict 必须包含 date, picks, scores, factor_values, excluded。"""
        from pipeline.daily_signal import run_daily_pipeline

        price_df = self._fake_price_df()
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            with (
                patch("pipeline.daily_signal.get_all_symbols", return_value=self.SYMBOLS),
                patch("pipeline.daily_signal.load_price_wide", return_value=price_df),
                # 因子数据不可用时函数会 warn 并跳过，仍应正常返回
                patch("pipeline.daily_signal.load_factor_wide", side_effect=Exception("无数据")),
                patch("pipeline.daily_signal.SIGNAL_DIR", tmp_path / "signals"),
                patch("pipeline.daily_signal.SNAPSHOT_DIR", tmp_path / "snapshots"),
            ):
                result = run_daily_pipeline(date="2026-03-20", n_stocks=2)

        required_keys = {"date", "picks", "scores", "factor_values", "excluded"}
        for key in required_keys:
            self.assertIn(key, result, f"返回字典缺少 key: {key}")

    def test_error_path_returns_error_key(self):
        """load_price_wide 抛 FileNotFoundError 时，返回 dict 应含 error key 且 picks 为空。

        注: 因已使用 from-import，需 mock pipeline.daily_signal.load_price_wide
        而非 utils.local_data_loader.load_price_wide（后者 mock 无效）。
        """
        from pipeline.daily_signal import run_daily_pipeline

        with (
            patch("pipeline.daily_signal.get_all_symbols", return_value=self.SYMBOLS),
            patch(
                "pipeline.daily_signal.load_price_wide",
                side_effect=FileNotFoundError("parquet 文件不存在"),
            ),
        ):
            result = run_daily_pipeline(date="2026-03-20")

        self.assertIn("error", result, "数据加载失败时应返回 error key")
        self.assertEqual(result.get("picks"), [], "失败时 picks 应为空列表")

    def test_error_does_not_write_file(self):
        """数据加载失败时，不应在 SIGNAL_DIR 写入任何文件。"""
        from pipeline.daily_signal import run_daily_pipeline

        with tempfile.TemporaryDirectory() as tmp:
            signal_dir = Path(tmp) / "signals"
            with (
                patch("pipeline.daily_signal.get_all_symbols", return_value=self.SYMBOLS),
                patch(
                    "pipeline.daily_signal.load_price_wide",
                    side_effect=FileNotFoundError("无数据"),
                ),
                patch("pipeline.daily_signal.SIGNAL_DIR", signal_dir),
            ):
                run_daily_pipeline(date="2026-03-20")

            # 目录不存在，或存在但为空 → 均视为未写入
            no_files = (
                not signal_dir.exists()
                or not any(signal_dir.iterdir())
            )
            self.assertTrue(no_files, "加载失败时不应写入信号文件到 SIGNAL_DIR")


# ─────────────────────────────────────────────────────────────────────────────
# 2. TestPaperTraderInit
# ─────────────────────────────────────────────────────────────────────────────

class TestPaperTraderInit(unittest.TestCase):
    """测试 PaperTrader 初始化和基本查询接口。

    通过 patch live.paper_trader.PORTFOLIO_DIR 等模块级变量，
    将所有文件 IO 重定向到 tempfile.TemporaryDirectory，
    避免污染真实的 live/portfolio/ 目录。
    """

    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self._d = Path(self._tmpdir.name)

    def tearDown(self):
        self._tmpdir.cleanup()

    @contextlib.contextmanager
    def _patch_portfolio_dir(self):
        """将 paper_trader 模块的文件路径全部重定向到临时目录。"""
        d = self._d
        with (
            patch("live.paper_trader.PORTFOLIO_DIR", d),
            patch("live.paper_trader.POSITIONS_FILE", d / "positions.json"),
            patch("live.paper_trader.TRADES_FILE", d / "trades.json"),
            patch("live.paper_trader.NAV_FILE", d / "nav.csv"),
        ):
            yield d

    def test_cash_key_in_positions(self):
        """初始化后 positions 中应含 __cash__ 键，值等于初始资金。"""
        from live.paper_trader import PaperTrader

        with self._patch_portfolio_dir():
            trader = PaperTrader(initial_capital=500_000)

        self.assertIn("__cash__", trader.positions)
        self.assertAlmostEqual(trader.positions["__cash__"], 500_000)

    def test_get_performance_returns_dict(self):
        """get_performance() 应返回 dict；空投组合时返回空 dict 亦可。"""
        from live.paper_trader import PaperTrader

        with self._patch_portfolio_dir():
            trader = PaperTrader(initial_capital=100_000)
            perf = trader.get_performance()

        self.assertIsInstance(perf, dict)

    def test_get_current_positions_columns(self):
        """get_current_positions() 应返回 DataFrame，且包含所有必要列。"""
        from live.paper_trader import PaperTrader

        with self._patch_portfolio_dir():
            trader = PaperTrader(initial_capital=100_000)
            df = trader.get_current_positions()

        self.assertIsInstance(df, pd.DataFrame)
        expected_cols = {"symbol", "shares", "cost_price", "current_price", "pnl_pct"}
        missing = expected_cols - set(df.columns)
        self.assertFalse(missing, f"get_current_positions() 返回 DataFrame 缺少列: {missing}")


# ─────────────────────────────────────────────────────────────────────────────
# 3. TestRiskMonitorInterface
# ─────────────────────────────────────────────────────────────────────────────

class TestRiskMonitorInterface(unittest.TestCase):
    """测试 check_risk_alerts() 的接口和返回值格式。"""

    def _make_portfolio(self, positions=None) -> MagicMock:
        """构造最小 mock portfolio 对象（仅含现金，无股票持仓）。"""
        p = MagicMock()
        p.positions = positions or {"__cash__": 100_000}
        p._portfolio_value.return_value = 100_000
        return p

    def test_returns_list_when_nav_missing(self):
        """NAV 文件不存在时，check_risk_alerts() 应返回 list 而非抛异常。"""
        from live.risk_monitor import check_risk_alerts

        with tempfile.TemporaryDirectory() as tmp:
            nav_file = Path(tmp) / "nav.csv"  # 故意不创建
            with (
                patch("live.risk_monitor.NAV_FILE", nav_file),
                patch("live.risk_monitor._log_decision"),  # 避免写 .claude/decisions.md
            ):
                result = check_risk_alerts(self._make_portfolio())

        self.assertIsInstance(result, list)

    def test_alert_items_have_level_and_msg(self):
        """预警触发时，每条预警必须含 level 和 msg 字段。

        写入一段大幅回撤净值（从高点 110_000 跌至 85_000，跌幅约 22.7%），
        保证触发 critical 回撤预警。
        """
        from live.risk_monitor import check_risk_alerts

        with tempfile.TemporaryDirectory() as tmp:
            nav_file = Path(tmp) / "nav.csv"
            pd.DataFrame({
                "date": ["2026-01-01", "2026-02-01", "2026-03-01"],
                "nav":  [100_000,      110_000,      85_000],
            }).to_csv(nav_file, index=False)

            with (
                patch("live.risk_monitor.NAV_FILE", nav_file),
                patch("live.risk_monitor._log_decision"),
            ):
                alerts = check_risk_alerts(self._make_portfolio())

        self.assertIsInstance(alerts, list)
        self.assertGreater(len(alerts), 0, "回撤超 10% 时应至少有一条 critical 预警")
        for alert in alerts:
            self.assertIn("level", alert, f"预警缺少 level 字段: {alert}")
            self.assertIn("msg", alert, f"预警缺少 msg 字段: {alert}")

    def test_alert_level_values_are_valid(self):
        """所有预警的 level 字段只能是 'warning' 或 'critical'。"""
        from live.risk_monitor import check_risk_alerts

        with tempfile.TemporaryDirectory() as tmp:
            nav_file = Path(tmp) / "nav.csv"
            pd.DataFrame({
                "date": ["2026-01-01", "2026-02-01", "2026-03-01"],
                "nav":  [100_000,      110_000,      85_000],
            }).to_csv(nav_file, index=False)

            with (
                patch("live.risk_monitor.NAV_FILE", nav_file),
                patch("live.risk_monitor._log_decision"),
            ):
                alerts = check_risk_alerts(self._make_portfolio())

        valid_levels = {"warning", "critical"}
        for alert in alerts:
            self.assertIn(
                alert.get("level"),
                valid_levels,
                f"非法 level 值: {alert.get('level')}，期望 {valid_levels}",
            )


if __name__ == "__main__":
    unittest.main()
