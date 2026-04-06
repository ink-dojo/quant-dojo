"""
test_phase5_regression.py — Phase 5 回归测试（真实文件 IO）

测试三个核心场景，全部使用 tempfile.TemporaryDirectory 真实文件 IO，不依赖 mocks：
  1. signal → rebalance → risk → weekly_report 端到端链路
  2. PaperTrader 重启后从相同文件恢复状态
  3. 同日重复 rebalance 不产生重复交易

补充 test_phase5_smoke.py（基于 mocks 的冒烟测试）：
  - 本文件验证真实文件持久化和读写正确性
  - test_phase5_smoke.py 验证接口结构和返回值格式

运行方式:
  python -m pytest tests/test_phase5_regression.py -v
  python -m unittest tests.test_phase5_regression
"""

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

# ── stub for optional dependency ─────────────────────────────────────────────
for _pkg in ("akshare",):
    if _pkg not in sys.modules:
        sys.modules[_pkg] = MagicMock()
# ──────────────────────────────────────────────────────────────────────────────

import numpy as np
import pandas as pd


# ─────────────────────────────────────────────────────────────────────────────
# Test 1: End-to-end chain — signal → rebalance → risk → weekly report
# ─────────────────────────────────────────────────────────────────────────────

class TestE2ERechain(unittest.TestCase):
    """
    端到端链路测试：信号生成 → 模拟交易 → 风险检查 → 周报生成。

    使用真实文件 IO：
      - signal JSON / nav.csv / positions.json / trades.json 均写入 tempdir
      - 周报写入 tempdir/journal/weekly/
      - 数据加载通过 patch 模拟（与 test_phase5_smoke.py 一致）
    """

    SYMBOLS = ["000001.SZ", "000002.SZ", "000003.SZ"]

    def _fake_price_df(self) -> pd.DataFrame:
        """构造足够历史数据的 mock 价格 DataFrame（固定随机种子）。"""
        dates = pd.date_range("2025-01-02", "2026-03-20", freq="B")
        rng = np.random.default_rng(42)
        data = rng.uniform(5.0, 50.0, (len(dates), len(self.SYMBOLS)))
        return pd.DataFrame(data, index=dates, columns=self.SYMBOLS)

    def test_signal_rebalance_risk_report_chain(self):
        """全链路：signal JSON → PaperTrader rebalance → risk alerts → weekly report Markdown。"""
        from pipeline.daily_signal import run_daily_pipeline
        from live.paper_trader import PaperTrader
        from live.risk_monitor import check_risk_alerts
        from pipeline.weekly_report import generate_weekly_report

        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            price_df = self._fake_price_df()
            test_date = "2026-03-20"

            # ── 1. 信号生成（mock 数据加载，真实 signal JSON 文件写入） ─────
            signal_dir = tmp_path / "signals"
            snapshot_dir = tmp_path / "snapshots"
            portfolio_dir = tmp_path / "portfolio"

            def _noop_parquet(path, **kwargs):
                Path(path).touch()

            with patch("pipeline.daily_signal.get_all_symbols", return_value=self.SYMBOLS), \
                 patch("pipeline.daily_signal.load_price_wide", return_value=price_df), \
                 patch("pipeline.daily_signal.load_factor_wide", side_effect=Exception("无数据")), \
                 patch("pipeline.daily_signal.SIGNAL_DIR", signal_dir), \
                 patch("pipeline.daily_signal.SNAPSHOT_DIR", snapshot_dir), \
                 patch("pandas.DataFrame.to_parquet", side_effect=_noop_parquet):
                signal_result = run_daily_pipeline(date=test_date, n_stocks=2)

            # 信号文件必须已写入
            signal_file = signal_dir / "2026-03-20.json"
            self.assertTrue(signal_file.exists(), f"信号文件未生成: {signal_file}")
            with open(signal_file, encoding="utf-8") as f:
                saved_signal = json.load(f)
            self.assertEqual(saved_signal["date"], "2026-03-20")
            self.assertIn("picks", saved_signal)

            # ── 3. PaperTrader rebalance（真实文件 IO） ──────────────────
            with patch("live.paper_trader.PORTFOLIO_DIR", portfolio_dir), \
                 patch("live.paper_trader.POSITIONS_FILE", portfolio_dir / "positions.json"), \
                 patch("live.paper_trader.TRADES_FILE", portfolio_dir / "trades.json"), \
                 patch("live.paper_trader.NAV_FILE", portfolio_dir / "nav.csv"):
                trader = PaperTrader(initial_capital=100_000)

                # 从信号中获取 picks 和模拟价格
                picks = saved_signal["picks"]
                prices = {sym: 10.0 + i * 2.0 for i, sym in enumerate(picks)}

                rebal_result = trader.rebalance(
                    new_picks=picks,
                    prices=prices,
                    date="2026-03-20",
                )

            # 验证 rebalance 写出了文件
            positions_file = portfolio_dir / "positions.json"
            trades_file = portfolio_dir / "trades.json"
            nav_file = portfolio_dir / "nav.csv"
            self.assertTrue(positions_file.exists(), "positions.json 未生成")
            self.assertTrue(trades_file.exists(), "trades.json 未生成")
            self.assertTrue(nav_file.exists(), "nav.csv 未生成")

            # 验证 rebalance 返回结构
            self.assertIn("n_buys", rebal_result)
            self.assertIn("nav_after", rebal_result)
            self.assertGreater(rebal_result["nav_after"], 0)

            # ── 4. 风险检查 ───────────────────────────────────────────────
            with patch("live.risk_monitor.NAV_FILE", nav_file), \
                 patch("live.risk_monitor._log_decision"):
                alerts = check_risk_alerts(trader)

            self.assertIsInstance(alerts, list)

            # ── 5. 周报生成 ───────────────────────────────────────────────
            # patch base_dir 使 generate_weekly_report 指向 tmp_path
            with patch("pipeline.weekly_report.Path") as mock_path_cls:
                mock_file_path = MagicMock()
                mock_file_path.parent.parent = tmp_path
                mock_path_cls.return_value = mock_file_path

                original_path = Path
                def _path_side_effect(*args, **kwargs):
                    if not args:
                        return mock_file_path
                    return original_path(*args, **kwargs)
                mock_path_cls.side_effect = _path_side_effect

                report = generate_weekly_report(week="2026-W12")

            self.assertIsInstance(report, str)
            self.assertGreater(len(report), 0)
            self.assertIn("2026-W12", report)


# ─────────────────────────────────────────────────────────────────────────────
# Test 2: PaperTrader restart-safe — new instance reads same files
# ─────────────────────────────────────────────────────────────────────────────

class TestPaperTraderRestartSafe(unittest.TestCase):
    """
    验证 PaperTrader 重启后从相同文件恢复状态。

    流程：
      1. 创建 PaperTrader，执行 rebalance
      2. 新实例化 PaperTrader（指向相同目录）
      3. 断言：持仓键、现金、NAV、交易记录数 完全一致
    """

    def test_restart_reads_same_positions_and_nav(self):
        from live.paper_trader import PaperTrader

        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp)
            portfolio_dir = d
            positions_file = d / "positions.json"
            trades_file = d / "trades.json"
            nav_file = d / "nav.csv"

            with patch("live.paper_trader.PORTFOLIO_DIR", portfolio_dir), \
                 patch("live.paper_trader.POSITIONS_FILE", positions_file), \
                 patch("live.paper_trader.TRADES_FILE", trades_file), \
                 patch("live.paper_trader.NAV_FILE", nav_file):

                # ── 第一次：创建并执行 rebalance ─────────────────────────
                t1 = PaperTrader(initial_capital=200_000)
                rebal1 = t1.rebalance(
                    new_picks=["000001.SZ", "600000.SH"],
                    prices={"000001.SZ": 15.0, "600000.SH": 8.0},
                    date="2026-03-20",
                )
                pos1 = dict(t1.positions)
                cash1 = t1._get_cash()
                nav1 = rebal1["nav_after"]
                trades_count1 = len(t1.trades)

                # ── 第二次：新实例，指向相同文件 ─────────────────────────
                t2 = PaperTrader(initial_capital=200_000)
                pos2 = dict(t2.positions)
                cash2 = t2._get_cash()
                nav2 = t2._portfolio_value({"000001.SZ": 15.0, "600000.SH": 8.0})
                trades_count2 = len(t2.trades)

            # ── 断言 ────────────────────────────────────────────────────
            self.assertEqual(
                set(pos1.keys()), set(pos2.keys()),
                "重启后持仓键集合应一致",
            )
            self.assertAlmostEqual(cash1, cash2, places=2, msg="重启后现金应一致")
            self.assertAlmostEqual(nav1, nav2, places=2, msg="重启后 NAV 应一致")
            self.assertEqual(trades_count1, trades_count2, "重启后交易记录数应一致")

            for sym in pos1:
                if sym == "__cash__":
                    continue
                self.assertEqual(
                    pos1[sym]["shares"], pos2[sym]["shares"],
                    f"重启后 {sym} shares 应一致",
                )

    def test_restart_after_multiple_days(self):
        """跨两天的重启：Day1 rebalance → Day2 rebalance → 重启验证。"""
        from live.paper_trader import PaperTrader

        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp)

            with patch("live.paper_trader.PORTFOLIO_DIR", d), \
                 patch("live.paper_trader.POSITIONS_FILE", d / "positions.json"), \
                 patch("live.paper_trader.TRADES_FILE", d / "trades.json"), \
                 patch("live.paper_trader.NAV_FILE", d / "nav.csv"):

                # Day 1
                t1 = PaperTrader(initial_capital=100_000)
                t1.rebalance(["000001.SZ"], {"000001.SZ": 10.0}, "2026-03-20")

                # Day 2 — 部分调仓
                t1.rebalance(["000002.SZ"], {"000002.SZ": 20.0}, "2026-03-23")

                trades_day2_count = len(t1.trades)

            # 重启，新实例
            with patch("live.paper_trader.PORTFOLIO_DIR", d), \
                 patch("live.paper_trader.POSITIONS_FILE", d / "positions.json"), \
                 patch("live.paper_trader.TRADES_FILE", d / "trades.json"), \
                 patch("live.paper_trader.NAV_FILE", d / "nav.csv"):

                t2 = PaperTrader(initial_capital=100_000)

            self.assertEqual(len(t2.trades), trades_day2_count)
            # 000001.SZ 应已卖出（不在持仓中）
            self.assertNotIn("000001.SZ", t2.positions)
            # 000002.SZ 应在持仓中
            self.assertIn("000002.SZ", t2.positions)


# ─────────────────────────────────────────────────────────────────────────────
# Test 3: Same-day duplicate rebalance — no duplicate trades, same NAV
# ─────────────────────────────────────────────────────────────────────────────

class TestDuplicateRebalanceProtection(unittest.TestCase):
    """
    验证同日重复调用 rebalance 不会产生重复交易，NAV 结果一致。

    场景：同一交易日的 rebalance 调用（相同 picks + prices），只应执行一次。
    """

    def test_same_day_duplicate_returns_same_nav(self):
        """同日两次 rebalance 调用，第二次应跳过，NAV 与第一次完全一致。"""
        from live.paper_trader import PaperTrader

        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp)

            with patch("live.paper_trader.PORTFOLIO_DIR", d), \
                 patch("live.paper_trader.POSITIONS_FILE", d / "positions.json"), \
                 patch("live.paper_trader.TRADES_FILE", d / "trades.json"), \
                 patch("live.paper_trader.NAV_FILE", d / "nav.csv"):

                trader = PaperTrader(initial_capital=100_000)
                picks = ["000001.SZ", "000002.SZ"]
                prices = {"000001.SZ": 10.0, "000002.SZ": 20.0}
                date_str = "2026-03-20"

                # 第一次
                result1 = trader.rebalance(new_picks=picks, prices=prices, date=date_str)
                trades_after_first = len(trader.trades)

                # 第二次（同日、同参数）
                result2 = trader.rebalance(new_picks=picks, prices=prices, date=date_str)
                trades_after_second = len(trader.trades)

            # 不应产生新交易
            self.assertEqual(
                trades_after_first, trades_after_second,
                f"同日重复调仓产生了新交易——第一次 {trades_after_first} 笔，"
                f"第二次 {trades_after_second} 笔",
            )
            # NAV 应一致
            self.assertAlmostEqual(
                result1["nav_after"], result2["nav_after"], places=2,
                msg="同日重复调仓 NAV 应保持一致",
            )
            # 第一次调用已执行了真实交易（n_buys=2）
            self.assertGreater(trades_after_first, 0)

    def test_different_day_allows_rebalance(self):
        """不同日期的 rebalance 应正常执行，产生新交易。"""
        from live.paper_trader import PaperTrader

        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp)

            with patch("live.paper_trader.PORTFOLIO_DIR", d), \
                 patch("live.paper_trader.POSITIONS_FILE", d / "positions.json"), \
                 patch("live.paper_trader.TRADES_FILE", d / "trades.json"), \
                 patch("live.paper_trader.NAV_FILE", d / "nav.csv"):

                trader = PaperTrader(initial_capital=100_000)
                picks = ["000001.SZ"]
                price = {"000001.SZ": 10.0}

                # Day 1
                trader.rebalance(new_picks=picks, prices=price, date="2026-03-20")
                trades_day1 = len(trader.trades)

                # Day 2 — 更换标的
                trader.rebalance(new_picks=["000002.SZ"], prices={"000002.SZ": 20.0}, date="2026-03-23")
                trades_day2 = len(trader.trades)

            self.assertGreater(trades_day2, trades_day1, "新交易日的 rebalance 应增加交易记录")


# ─────────────────────────────────────────────────────────────────────────────
# Test 4: Weekly report reads real portfolio files
# ─────────────────────────────────────────────────────────────────────────────

class TestWeeklyReportWithRealFiles(unittest.TestCase):
    """
    验证 weekly_report 的文件加载函数能从真实文件读取正确数据。
    generate_weekly_report 的完整测试依赖 Path 重定向（复杂），
    因此聚焦于加载函数 + 基本返回值验证。
    """

    def test_load_functions_with_real_files(self):
        """_load_trades / _load_positions / _load_nav 从真实 JSON/CSV 文件正确读取。"""
        from pipeline.weekly_report import (
            _load_trades,
            _load_positions,
            _load_nav,
            _get_week_dates,
        )

        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)

            # 构造 portfolio 文件（写入真实文件路径）
            trades_file = tmp_path / "trades.json"
            positions_file = tmp_path / "positions.json"
            nav_file = tmp_path / "nav.csv"

            positions = {
                "__cash__": 80000.0,
                "000001.SZ": {"shares": 1000, "cost_price": 10.0, "current_price": 12.0},
            }
            # W13 Mon~Thu: 2026-03-23 ~ 2026-03-26
            trades = [
                {"date": "2026-03-23", "symbol": "000001.SZ", "action": "buy",
                 "shares": 1000, "price": 10.0, "cost": 30.0},
            ]
            nav_rows = [
                {"date": "2026-03-23", "nav": 100000.0},
                {"date": "2026-03-24", "nav": 102000.0},
                {"date": "2026-03-25", "nav": 101500.0},
                {"date": "2026-03-26", "nav": 103000.0},
            ]

            with open(trades_file, "w", encoding="utf-8") as f:
                json.dump(trades, f)
            with open(positions_file, "w", encoding="utf-8") as f:
                json.dump(positions, f)
            pd.DataFrame(nav_rows).to_csv(nav_file, index=False)

            # 测试加载函数（直接使用真实文件路径）
            dates = _get_week_dates("2026-W13")
            loaded_trades = _load_trades(str(trades_file), dates)
            loaded_positions = _load_positions(str(positions_file))
            loaded_nav = _load_nav(str(nav_file), dates)

            self.assertEqual(len(loaded_trades), 1)
            self.assertEqual(loaded_trades[0]["symbol"], "000001.SZ")
            self.assertEqual(loaded_positions["__cash__"], 80000.0)
            self.assertEqual(loaded_positions["000001.SZ"]["shares"], 1000)
            self.assertEqual(len(loaded_nav), 4)
            self.assertAlmostEqual(loaded_nav[0]["nav"], 100000.0)
            self.assertAlmostEqual(loaded_nav[-1]["nav"], 103000.0)


# ─────────────────────────────────────────────────────────────────────────────
# Test 5: 连续多日运行 + 重启恢复 — 端到端 loop 测试
# ─────────────────────────────────────────────────────────────────────────────

class TestContinuousMultiDayLoop(unittest.TestCase):
    """
    验证 Day1 signal → rebalance → Day2 signal → rebalance → ... → weekly report
    的完整连续循环，以及中途重启后状态恢复的正确性。
    """

    SYMBOLS = ["000001.SZ", "000002.SZ", "000003.SZ", "000004.SZ"]
    DATES = ["2026-03-23", "2026-03-24", "2026-03-25", "2026-03-26", "2026-03-27"]

    def _fake_price_df(self) -> pd.DataFrame:
        """构造多日价格数据。"""
        dates = pd.date_range("2025-01-02", "2026-03-28", freq="B")
        rng = np.random.default_rng(123)
        data = rng.uniform(5.0, 50.0, (len(dates), len(self.SYMBOLS)))
        return pd.DataFrame(data, index=dates, columns=self.SYMBOLS)

    def test_multi_day_signal_rebalance_loop(self):
        """连续 5 个交易日的 signal → rebalance 循环，验证 NAV 单调记录。"""
        from live.paper_trader import PaperTrader

        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp)
            price_df = self._fake_price_df()

            with patch("live.paper_trader.PORTFOLIO_DIR", d), \
                 patch("live.paper_trader.POSITIONS_FILE", d / "positions.json"), \
                 patch("live.paper_trader.TRADES_FILE", d / "trades.json"), \
                 patch("live.paper_trader.NAV_FILE", d / "nav.csv"):

                trader = PaperTrader(initial_capital=500_000)

                nav_records = []
                for i, date_str in enumerate(self.DATES):
                    # 模拟每天选不同的股票
                    picks = self.SYMBOLS[i % 3:(i % 3) + 2]
                    prices = {
                        sym: float(price_df.loc[price_df.index <= date_str].iloc[-1][sym])
                        for sym in self.SYMBOLS
                        if sym in price_df.columns
                    }

                    result = trader.rebalance(new_picks=picks, prices=prices, date=date_str)
                    nav_records.append(result["nav_after"])

                    # 验证每次 rebalance 后 NAV > 0
                    self.assertGreater(result["nav_after"], 0, f"Day {date_str} NAV <= 0")

                # 验证 nav.csv 有 5 行记录（每天一行）
                nav_df = pd.read_csv(d / "nav.csv")
                self.assertEqual(len(nav_df), 5, f"nav.csv 应有 5 行，实际 {len(nav_df)}")

                # 验证交易记录累积增长
                self.assertGreater(len(trader.trades), 0)

    def test_restart_mid_week_preserves_state(self):
        """运行 3 天后重启，新实例应恢复持仓、继续第 4 天调仓。"""
        from live.paper_trader import PaperTrader

        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp)

            with patch("live.paper_trader.PORTFOLIO_DIR", d), \
                 patch("live.paper_trader.POSITIONS_FILE", d / "positions.json"), \
                 patch("live.paper_trader.TRADES_FILE", d / "trades.json"), \
                 patch("live.paper_trader.NAV_FILE", d / "nav.csv"):

                # 前 3 天
                t1 = PaperTrader(initial_capital=300_000)
                for date_str in self.DATES[:3]:
                    t1.rebalance(
                        new_picks=["000001.SZ", "000002.SZ"],
                        prices={"000001.SZ": 15.0, "000002.SZ": 25.0},
                        date=date_str,
                    )
                trades_before = len(t1.trades)
                cash_before = t1._get_cash()

                # 重启
                t2 = PaperTrader(initial_capital=300_000)
                self.assertEqual(len(t2.trades), trades_before, "重启后交易记录数不一致")
                self.assertAlmostEqual(t2._get_cash(), cash_before, places=2, msg="重启后现金不一致")

                # 第 4 天 — 新实例继续调仓
                result = t2.rebalance(
                    new_picks=["000003.SZ"],
                    prices={"000003.SZ": 10.0, "000001.SZ": 15.0, "000002.SZ": 25.0},
                    date=self.DATES[3],
                )
                self.assertGreater(len(t2.trades), trades_before, "第4天应产生新交易")
                self.assertGreater(result["nav_after"], 0)

    def test_weekly_report_after_continuous_run(self):
        """连续运行后生成的周报应包含交易记录和 NAV 数据。"""
        from live.paper_trader import PaperTrader
        from pipeline.weekly_report import (
            _load_trades, _load_nav, _get_week_dates,
        )

        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp)

            with patch("live.paper_trader.PORTFOLIO_DIR", d), \
                 patch("live.paper_trader.POSITIONS_FILE", d / "positions.json"), \
                 patch("live.paper_trader.TRADES_FILE", d / "trades.json"), \
                 patch("live.paper_trader.NAV_FILE", d / "nav.csv"):

                trader = PaperTrader(initial_capital=100_000)
                for date_str in self.DATES:
                    trader.rebalance(
                        new_picks=["000001.SZ"],
                        prices={"000001.SZ": 10.0},
                        date=date_str,
                    )

            # 验证周报数据加载
            dates = _get_week_dates("2026-W13")
            trades = _load_trades(str(d / "trades.json"), dates)
            nav_rows = _load_nav(str(d / "nav.csv"), dates)

            self.assertGreater(len(trades), 0, "应有交易记录")
            self.assertGreater(len(nav_rows), 0, "应有 NAV 数据")


if __name__ == "__main__":
    unittest.main()
