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
        test_date = price_df.index[-1].strftime("%Y-%m-%d")
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            # to_parquet 需要 pyarrow（测试环境可能未安装），用 side_effect 创建空文件以使后续 rename 成功
            def _fake_to_parquet(path, **kwargs):
                Path(path).touch()

            with patch("pipeline.daily_signal.get_all_symbols", return_value=self.SYMBOLS), \
                 patch("pipeline.daily_signal.load_price_wide", return_value=price_df), \
                 patch("pipeline.daily_signal.load_factor_wide", side_effect=Exception("无数据")), \
                 patch("pipeline.daily_signal.SIGNAL_DIR", tmp_path / "signals"), \
                 patch("pipeline.daily_signal.SNAPSHOT_DIR", tmp_path / "snapshots"), \
                 patch("pandas.DataFrame.to_parquet", side_effect=_fake_to_parquet):
                result = run_daily_pipeline(date=test_date, n_stocks=2)

        required_keys = {"date", "picks", "scores", "factor_values", "excluded"}
        for key in required_keys:
            self.assertIn(key, result, f"返回字典缺少 key: {key}")

    def test_error_path_returns_error_key(self):
        """load_price_wide 抛 FileNotFoundError 时，返回 dict 应含 error key 且 picks 为空。

        注: 因已使用 from-import，需 mock pipeline.daily_signal.load_price_wide
        而非 utils.local_data_loader.load_price_wide（后者 mock 无效）。
        """
        from pipeline.daily_signal import run_daily_pipeline

        with patch("pipeline.daily_signal.get_all_symbols", return_value=self.SYMBOLS), \
             patch("pipeline.daily_signal.load_price_wide",
                   side_effect=FileNotFoundError("parquet 文件不存在")):
            result = run_daily_pipeline(date="2026-03-20")

        self.assertIn("error", result, "数据加载失败时应返回 error key")
        self.assertEqual(result.get("picks"), [], "失败时 picks 应为空列表")

    def test_error_does_not_write_file(self):
        """数据加载失败时，不应在 SIGNAL_DIR 写入任何文件。"""
        from pipeline.daily_signal import run_daily_pipeline

        with tempfile.TemporaryDirectory() as tmp:
            signal_dir = Path(tmp) / "signals"
            with patch("pipeline.daily_signal.get_all_symbols", return_value=self.SYMBOLS), \
                 patch("pipeline.daily_signal.load_price_wide",
                       side_effect=FileNotFoundError("无数据")), \
                 patch("pipeline.daily_signal.SIGNAL_DIR", signal_dir):
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
        with patch("live.paper_trader.PORTFOLIO_DIR", d), \
             patch("live.paper_trader.POSITIONS_FILE", d / "positions.json"), \
             patch("live.paper_trader.TRADES_FILE", d / "trades.json"), \
             patch("live.paper_trader.NAV_FILE", d / "nav.csv"):
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
            with patch("live.risk_monitor.NAV_FILE", nav_file), \
                 patch("live.risk_monitor._log_decision"):
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

            with patch("live.risk_monitor.NAV_FILE", nav_file), \
                 patch("live.risk_monitor._log_decision"):
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

            with patch("live.risk_monitor.NAV_FILE", nav_file), \
                 patch("live.risk_monitor._log_decision"):
                alerts = check_risk_alerts(self._make_portfolio())

        valid_levels = {"warning", "critical"}
        for alert in alerts:
            self.assertIn(
                alert.get("level"),
                valid_levels,
                f"非法 level 值: {alert.get('level')}，期望 {valid_levels}",
            )


# ─────────────────────────────────────────────────────────────────────────────
# 4. TestWeeklyReport
# ─────────────────────────────────────────────────────────────────────────────

class TestWeeklyReport(unittest.TestCase):
    """测试 pipeline.weekly_report.generate_weekly_report() 的返回值和基本功能。"""

    def test_generate_returns_string(self):
        """调用 generate_weekly_report("2026-W12") 应返回非空字符串，包含 '周报' 或 '2026-W12'。"""
        from pipeline.weekly_report import generate_weekly_report

        with tempfile.TemporaryDirectory() as tmp:
            journal_dir = Path(tmp) / "journal" / "weekly"
            with patch("pipeline.weekly_report.Path") as mock_path:
                # 让 Path(__file__).parent.parent 返回 tmp 所在的上级目录
                mock_path.return_value.parent.parent = Path(tmp)
                # 直接调用，会在 tmp 中创建 journal/weekly 目录
                result = generate_weekly_report(week="2026-W12")

        self.assertIsInstance(result, str)
        self.assertGreater(len(result), 0, "返回的周报字符串应非空")
        # 验证包含周报标识
        self.assertTrue(
            "周报" in result or "2026-W12" in result,
            f"返回的周报应包含 '周报' 或 '2026-W12'，实际内容：{result[:200]}"
        )

    def test_generate_empty_state_still_returns(self):
        """调用 generate_weekly_report() 时若无数据，应返回占位报告（非空字符串），不抛异常。"""
        from pipeline.weekly_report import generate_weekly_report

        with tempfile.TemporaryDirectory() as tmp:
            # 创建空的数据目录结构，确保 generate_weekly_report 不会因为目录缺失而崩溃
            signals_dir = Path(tmp) / "live" / "signals"
            signals_dir.mkdir(parents=True, exist_ok=True)
            snapshot_dir = Path(tmp) / "live" / "factor_snapshot"
            snapshot_dir.mkdir(parents=True, exist_ok=True)
            journal_dir = Path(tmp) / "journal" / "weekly"

            with patch("pipeline.weekly_report.Path") as mock_path_class:
                # 构造 mock 的 Path 对象
                mock_path_instance = MagicMock()
                mock_path_instance.parent.parent = Path(tmp)
                mock_path_class.return_value = mock_path_instance

                # 也要 patch 直接创建 Path 对象时的行为
                def _path_side_effect(p):
                    if isinstance(p, str) and "factor_snapshot" in p:
                        return snapshot_dir
                    elif isinstance(p, str) and "signals" in p:
                        return signals_dir
                    elif isinstance(p, str) and "journal" in p:
                        return journal_dir
                    return Path(p)

                mock_path_class.side_effect = _path_side_effect

                # 调用应不抛异常
                try:
                    result = generate_weekly_report(week="2026-W13")
                except Exception as e:
                    self.fail(f"generate_weekly_report 无数据时不应抛异常，但得到: {e}")

        self.assertIsInstance(result, str, "即使无数据，也应返回字符串")
        self.assertGreater(len(result), 0, "返回的占位报告应非空")


# ─────────────────────────────────────────────────────────────────────────────
# 5. TestPaperTraderRebalance
# ─────────────────────────────────────────────────────────────────────────────

class TestPaperTraderRebalance(unittest.TestCase):
    """测试 PaperTrader.rebalance() 的调用和返回值。"""

    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self._d = Path(self._tmpdir.name)

    def tearDown(self):
        self._tmpdir.cleanup()

    @contextlib.contextmanager
    def _patch_portfolio_dir(self):
        """将 paper_trader 模块的文件路径全部重定向到临时目录。"""
        d = self._d
        with patch("live.paper_trader.PORTFOLIO_DIR", d), \
             patch("live.paper_trader.POSITIONS_FILE", d / "positions.json"), \
             patch("live.paper_trader.TRADES_FILE", d / "trades.json"), \
             patch("live.paper_trader.NAV_FILE", d / "nav.csv"):
            yield d

    def test_rebalance_returns_summary_keys(self):
        """调用 rebalance() 后，返回字典应包含 n_buys, n_sells, cash_after, nav_after 等关键字段。"""
        from live.paper_trader import PaperTrader

        with self._patch_portfolio_dir():
            trader = PaperTrader(initial_capital=100000)

            # 执行再平衡：新增两只股票，各分配 50000
            result = trader.rebalance(
                new_picks=["000001.SZ", "000002.SZ"],
                prices={"000001.SZ": 10.0, "000002.SZ": 20.0},
                date="2026-03-20"
            )

        # 验证返回值结构
        self.assertIsInstance(result, dict, "rebalance() 应返回字典")

        required_keys = {"n_buys", "n_sells", "cash_after", "nav_after"}
        for key in required_keys:
            self.assertIn(
                key, result,
                f"rebalance() 返回字典应包含键 '{key}'，实际键：{set(result.keys())}"
            )

        # 验证返回值的合理性（基本健全性检查）
        self.assertIsInstance(result["n_buys"], int, "n_buys 应为整数")
        self.assertIsInstance(result["n_sells"], int, "n_sells 应为整数")
        self.assertGreaterEqual(result["cash_after"], 0, "调仓后现金不应为负")
        self.assertGreater(result["nav_after"], 0, "调仓后净值应大于 0")

    def test_rebalance_with_empty_picks(self):
        """调用 rebalance(new_picks=[]) 应成功返回，早期返回不执行买卖，n_buys=0, n_sells=0。"""
        from live.paper_trader import PaperTrader

        with self._patch_portfolio_dir():
            trader = PaperTrader(initial_capital=100000)

            # 执行空持仓列表的调仓
            result = trader.rebalance(
                new_picks=[],
                prices={"000001.SZ": 10.0, "000002.SZ": 20.0},
                date="2026-03-21"
            )

        # 空持仓列表时，返回早期不执行任何买卖操作
        self.assertEqual(result["n_buys"], 0, "空持仓时 n_buys 应为 0")
        self.assertEqual(result["n_sells"], 0, "空持仓时 n_sells 应为 0")
        # 净值应等于初始现金（无交易成本）
        self.assertAlmostEqual(result["nav_after"], 100000, places=0)


# ─────────────────────────────────────────────────────────────────────────────
# 6. TestMainChainIntegration
# ─────────────────────────────────────────────────────────────────────────────

class TestMainChainIntegration(unittest.TestCase):
    """全链路集成测试：signal → rebalance → risk-check，使用临时目录真实文件 IO。

    不依赖网络、不依赖真实数据目录；通过 patch 将数据路径重定向到 tempdir，
    并向其中写入最小合法 CSV 数据（OHLCV 格式）。
    """

    SYMBOLS = ["000001", "000002", "000003"]

    def _write_mock_csvs(self, tmp_path: Path) -> None:
        """在 tmp_path 写入最小 mock CSV 文件（英文列名，load_local_stock 可直接解析）。

        文件命名约定：sz.{symbol}.csv，列：date, open, high, low, close, volume。
        日期范围覆盖 2025-01-01 ~ 2026-03-20，含足够历史数据供因子计算使用。
        """
        rng = np.random.default_rng(42)
        dates = pd.date_range("2025-01-01", "2026-03-20", freq="B")
        for sym in self.SYMBOLS:
            prices = rng.uniform(5.0, 50.0, len(dates))
            df = pd.DataFrame({
                "date": dates.strftime("%Y-%m-%d"),
                "open": prices,
                "high": prices * 1.02,
                "low": prices * 0.98,
                "close": prices,
                "volume": rng.integers(100_000, 1_000_000, len(dates)).astype(float),
            })
            csv_file = tmp_path / f"sz.{sym}.csv"
            df.to_csv(csv_file, index=False)

    def test_signal_rebalance_risk_chain(self):
        """全链路冒烟：信号生成 → 模拟交易再平衡 → 风险检查，均不依赖网络或真实数据目录。"""
        from pipeline.daily_signal import run_daily_pipeline
        from live.paper_trader import PaperTrader
        from live.risk_monitor import run_risk_check

        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            self._write_mock_csvs(tmp_path)

            # ── 1. 信号生成 ─────────────────────────────────────────────────
            def _noop_parquet(path, **kwargs):
                Path(path).touch()

            with patch("utils.local_data_loader._get_local_data_dir", return_value=tmp_path), \
                 patch("utils.local_data_loader._CACHE_DIR", tmp_path / "cache"), \
                 patch("pipeline.daily_signal.SIGNAL_DIR", tmp_path / "signals"), \
                 patch("pipeline.daily_signal.SNAPSHOT_DIR", tmp_path / "snapshots"), \
                 patch("pandas.DataFrame.to_parquet", side_effect=_noop_parquet):
                signal_result = run_daily_pipeline(date="2026-03-20")

            self.assertIsInstance(signal_result, dict, "run_daily_pipeline 应返回 dict")
            self.assertTrue(
                "date" in signal_result or "error" in signal_result,
                f"返回 dict 应含 'date' 或 'error' 键，实际: {set(signal_result.keys())}",
            )

            # ── 2. 模拟交易再平衡 ────────────────────────────────────────────
            pt_dir = tmp_path / "portfolio"
            with patch("live.paper_trader.PORTFOLIO_DIR", pt_dir), \
                 patch("live.paper_trader.POSITIONS_FILE", pt_dir / "positions.json"), \
                 patch("live.paper_trader.TRADES_FILE", pt_dir / "trades.json"), \
                 patch("live.paper_trader.NAV_FILE", pt_dir / "nav.csv"):
                trader = PaperTrader(initial_capital=100_000)
                rebal = trader.rebalance(
                    new_picks=["000001", "000002"],
                    prices={"000001": 10.0, "000002": 20.0},
                    date="2026-03-20",
                )

            for key in ("n_buys", "n_sells", "cash_after", "nav_after"):
                self.assertIn(
                    key, rebal,
                    f"rebalance() 返回 dict 缺少键 '{key}'，实际: {set(rebal.keys())}",
                )

            # ── 3. 风险检查 ──────────────────────────────────────────────────
            risk_result = run_risk_check(nav_history=None, positions={})
            self.assertIsInstance(risk_result, list, "run_risk_check 应返回 list")


if __name__ == "__main__":
    unittest.main()
