"""
test_control_plane.py — 控制面核心组件测试

测试覆盖：
  1. 策略注册表：注册/列出/获取/工厂函数
  2. 运行记录存储：保存/读取/列出/对比/删除
  3. CLI 编译和帮助输出
  4. 控制面契约：命令列表/只读命令执行

运行方式:
  python -m pytest tests/test_control_plane.py -v
"""
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock

# 注入缺失的第三方依赖 stub
for _pkg in ("akshare",):
    if _pkg not in sys.modules:
        sys.modules[_pkg] = MagicMock()

import numpy as np
import pandas as pd


# ─────────────────────────────────────────────────────────────────
# 1. TestStrategyRegistry
# ─────────────────────────────────────────────────────────────────

class TestStrategyRegistry(unittest.TestCase):
    """测试策略注册表的核心功能"""

    def test_builtin_strategies_registered(self):
        """内置策略（dual_ma, multi_factor）应在模块加载时自动注册"""
        from pipeline.strategy_registry import list_strategies
        entries = list_strategies()
        ids = [e.id for e in entries]
        self.assertIn("dual_ma", ids)
        self.assertIn("multi_factor", ids)

    def test_get_strategy_exists(self):
        """get_strategy 应返回已注册策略"""
        from pipeline.strategy_registry import get_strategy
        entry = get_strategy("dual_ma")
        self.assertEqual(entry.id, "dual_ma")
        self.assertEqual(entry.data_type, "single")
        self.assertTrue(len(entry.params) > 0)

    def test_get_strategy_not_found(self):
        """get_strategy 对未知 ID 应抛出 KeyError"""
        from pipeline.strategy_registry import get_strategy
        with self.assertRaises(KeyError):
            get_strategy("nonexistent_strategy")

    def test_strategy_entry_has_factory(self):
        """每个注册策略必须有 factory 函数"""
        from pipeline.strategy_registry import list_strategies
        for entry in list_strategies():
            self.assertIsNotNone(entry.factory, f"策略 {entry.id} 缺少 factory")

    def test_dual_ma_factory_creates_strategy(self):
        """dual_ma 工厂函数应能创建可运行的策略实例"""
        from pipeline.strategy_registry import get_strategy
        entry = get_strategy("dual_ma")
        strategy = entry.factory({"fast_period": 10, "slow_period": 30, "symbol": "000001"})
        self.assertIsNotNone(strategy)
        self.assertTrue(hasattr(strategy, "run"))

    def test_multi_factor_factory_creates_adapter(self):
        """multi_factor 工厂函数应能创建适配器实例"""
        from pipeline.strategy_registry import get_strategy
        entry = get_strategy("multi_factor")
        adapter = entry.factory({"n_stocks": 10})
        self.assertIsNotNone(adapter)
        self.assertTrue(hasattr(adapter, "run"))

    def test_strategy_params_have_defaults(self):
        """每个策略参数应有默认值"""
        from pipeline.strategy_registry import list_strategies
        for entry in list_strategies():
            for p in entry.params:
                self.assertIsNotNone(
                    p.default,
                    f"策略 {entry.id} 的参数 {p.name} 缺少默认值"
                )


# ─────────────────────────────────────────────────────────────────
# 2. TestRunStore
# ─────────────────────────────────────────────────────────────────

class TestRunStore(unittest.TestCase):
    """测试运行记录存储"""

    def setUp(self):
        """每个测试使用临时目录"""
        self.tmp = tempfile.TemporaryDirectory()
        self.tmp_path = Path(self.tmp.name) / "runs"
        # 替换模块级 RUNS_DIR
        import pipeline.run_store as rs
        self._orig_runs_dir = rs.RUNS_DIR
        rs.RUNS_DIR = self.tmp_path

    def tearDown(self):
        import pipeline.run_store as rs
        rs.RUNS_DIR = self._orig_runs_dir
        self.tmp.cleanup()

    def _make_record(self, run_id="test_001", strategy_id="dual_ma"):
        from pipeline.run_store import RunRecord
        return RunRecord(
            run_id=run_id,
            strategy_id=strategy_id,
            strategy_name="测试策略",
            params={"fast_period": 20},
            start_date="2023-01-01",
            end_date="2024-12-31",
            status="success",
            metrics={"sharpe": 1.23, "max_drawdown": -0.15},
            created_at="2026-03-23T12:00:00",
        )

    def test_generate_run_id_unique(self):
        """run_id 应包含策略名和日期"""
        from pipeline.run_store import generate_run_id
        rid = generate_run_id("dual_ma", "2023-01-01", "2024-12-31", {})
        self.assertTrue(rid.startswith("dual_ma_"))

    def test_save_and_get(self):
        """保存后应能读取"""
        from pipeline.run_store import save_run, get_run
        record = self._make_record()
        save_run(record)

        loaded = get_run("test_001")
        self.assertEqual(loaded.strategy_id, "dual_ma")
        self.assertEqual(loaded.metrics["sharpe"], 1.23)

    def test_get_nonexistent_raises(self):
        """读取不存在的记录应抛出 FileNotFoundError"""
        from pipeline.run_store import get_run
        with self.assertRaises(FileNotFoundError):
            get_run("nonexistent_run")

    def test_list_runs_empty(self):
        """空目录应返回空列表"""
        from pipeline.run_store import list_runs
        self.assertEqual(list_runs(), [])

    def test_list_runs_returns_saved(self):
        """保存的记录应出现在列表中"""
        from pipeline.run_store import save_run, list_runs
        save_run(self._make_record("run_a"))
        save_run(self._make_record("run_b", "multi_factor"))

        all_runs = list_runs()
        self.assertEqual(len(all_runs), 2)

        # 按策略过滤
        filtered = list_runs(strategy_id="multi_factor")
        self.assertEqual(len(filtered), 1)
        self.assertEqual(filtered[0].strategy_id, "multi_factor")

    def test_compare_runs(self):
        """对比应返回指标名和运行数据"""
        from pipeline.run_store import save_run, compare_runs
        save_run(self._make_record("run_x"))
        save_run(self._make_record("run_y"))

        result = compare_runs(["run_x", "run_y"])
        self.assertIn("runs", result)
        self.assertIn("metric_names", result)
        self.assertEqual(len(result["runs"]), 2)

    def test_delete_run(self):
        """删除后不应再能读取"""
        from pipeline.run_store import save_run, delete_run, get_run
        save_run(self._make_record())
        self.assertTrue(delete_run("test_001"))
        with self.assertRaises(FileNotFoundError):
            get_run("test_001")

    def test_save_with_equity(self):
        """保存时附带净值 DataFrame"""
        from pipeline.run_store import save_run, get_run
        record = self._make_record("run_eq")
        dates = pd.date_range("2023-01-01", periods=10, freq="B")
        equity = pd.DataFrame({"returns": np.random.randn(10) * 0.01}, index=dates)
        save_run(record, equity_df=equity)

        loaded = get_run("run_eq")
        self.assertIn("equity_csv", loaded.artifacts)

    def test_nan_metric_serialization(self):
        """NaN 指标应被序列化为 null"""
        from pipeline.run_store import save_run, get_run
        record = self._make_record("run_nan")
        record.metrics = {"sharpe": float("nan"), "return": 0.05}
        save_run(record)

        loaded = get_run("run_nan")
        self.assertIsNone(loaded.metrics["sharpe"])


# ─────────────────────────────────────────────────────────────────
# 3. TestCLI
# ─────────────────────────────────────────────────────────────────

class TestCLI(unittest.TestCase):
    """测试 CLI 编译和基本功能"""

    def _run_cli(self, args, timeout=30):
        """运行 CLI 子进程并保证超时后回收，防止子进程泄漏。"""
        import subprocess
        proc = subprocess.Popen(
            [sys.executable, "-m", "pipeline.cli"] + args,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
        )
        try:
            stdout, stderr = proc.communicate(timeout=timeout)
        except subprocess.TimeoutExpired:
            proc.kill()
            stdout, stderr = proc.communicate()
        # 返回一个类似 CompletedProcess 的对象
        return subprocess.CompletedProcess(proc.args, proc.returncode, stdout, stderr)

    def test_cli_compiles(self):
        """cli.py 应能正常编译"""
        import py_compile
        cli_path = str(Path(__file__).parent.parent / "pipeline" / "cli.py")
        py_compile.compile(cli_path, doraise=True)

    def test_cli_help_output(self):
        """--help 应成功退出且包含关键命令"""
        result = self._run_cli(["--help"])
        self.assertEqual(result.returncode, 0)
        self.assertIn("backtest", result.stdout)
        self.assertIn("signal", result.stdout)
        self.assertIn("strategies", result.stdout)
        self.assertIn("doctor", result.stdout)

    def test_backtest_list_works(self):
        """backtest list 应能运行（即使无记录）"""
        result = self._run_cli(["backtest", "list"])
        self.assertEqual(result.returncode, 0)

    def test_strategies_command(self):
        """strategies 命令应列出已注册策略"""
        result = self._run_cli(["strategies"])
        self.assertEqual(result.returncode, 0)
        self.assertIn("dual_ma", result.stdout)
        self.assertIn("multi_factor", result.stdout)

    def test_signal_date_legacy(self):
        """旧命令 signal --date 应正确分发（无 argparse 错误）"""
        result = self._run_cli(["signal", "--date", "2026-03-20"], timeout=60)
        # 允许底层管道因数据问题失败，但 CLI 本身不应出现 argparse 解析错误
        self.assertNotIn("unrecognized arguments", result.stderr)
        self.assertNotIn("error: the following arguments are required", result.stderr)

    def test_signal_run_new(self):
        """新命令 signal run --date 应正确分发（无 argparse 错误）"""
        result = self._run_cli(["signal", "run", "--date", "2026-03-20"], timeout=60)
        # 允许底层管道因数据问题失败，但 CLI 本身不应出现 argparse 解析错误
        self.assertNotIn("unrecognized arguments", result.stderr)
        self.assertNotIn("error: the following arguments are required", result.stderr)

    def test_risk_check_legacy(self):
        """旧命令 risk-check 应成功运行（returncode 0）"""
        result = self._run_cli(["risk-check"], timeout=60)
        self.assertEqual(result.returncode, 0)

    def test_weekly_report_legacy(self):
        """旧命令 weekly-report 应成功运行（returncode 0）"""
        result = self._run_cli(["weekly-report"], timeout=60)
        self.assertEqual(result.returncode, 0)

    def test_risk_check_new(self):
        """新命令 risk check 应成功运行（returncode 0）"""
        result = self._run_cli(["risk", "check"], timeout=60)
        self.assertEqual(result.returncode, 0)

    def test_report_weekly_new(self):
        """新命令 report weekly 应成功运行（returncode 0）"""
        result = self._run_cli(["report", "weekly"], timeout=60)
        self.assertEqual(result.returncode, 0)


# ─────────────────────────────────────────────────────────────────
# 4. TestControlSurface
# ─────────────────────────────────────────────────────────────────

class TestControlSurface(unittest.TestCase):
    """测试控制面契约"""

    def test_list_commands_returns_all(self):
        """list_commands 应返回所有定义的命令"""
        from pipeline.control_surface import list_commands
        commands = list_commands()
        names = [c["name"] for c in commands]
        self.assertIn("strategies.list", names)
        self.assertIn("backtest.run", names)
        self.assertIn("risk.check", names)
        self.assertIn("doctor", names)

    def test_command_has_mutates_flag(self):
        """每个命令应标注是否变更状态"""
        from pipeline.control_surface import list_commands
        for cmd in list_commands():
            self.assertIn("mutates", cmd)
            self.assertIsInstance(cmd["mutates"], bool)

    def test_readonly_commands_not_mutate(self):
        """只读命令 mutates 应为 False"""
        from pipeline.control_surface import list_commands
        readonly = ["strategies.list", "backtest.list", "positions.get",
                     "performance.get", "data.freshness", "doctor"]
        commands = {c["name"]: c for c in list_commands()}
        for name in readonly:
            self.assertFalse(commands[name]["mutates"], f"{name} 应为只读")

    def test_mutating_commands_flagged(self):
        """变更命令 mutates 应为 True"""
        from pipeline.control_surface import list_commands
        mutating = ["backtest.run", "signal.run", "rebalance.run", "report.weekly"]
        commands = {c["name"]: c for c in list_commands()}
        for name in mutating:
            self.assertTrue(commands[name]["mutates"], f"{name} 应标记为变更命令")

    def test_execute_strategies_list(self):
        """execute strategies.list 应返回策略列表"""
        from pipeline.control_surface import execute
        result = execute("strategies.list")
        self.assertEqual(result["status"], "success")
        data = result["data"]
        self.assertIsInstance(data, list)
        ids = [s["id"] for s in data]
        self.assertIn("dual_ma", ids)

    def test_execute_unknown_command(self):
        """execute 未知命令应返回错误"""
        from pipeline.control_surface import execute
        result = execute("nonexistent.command")
        self.assertEqual(result["status"], "error")
        self.assertIn("未知命令", result["error"])

    def test_execute_doctor(self):
        """execute doctor 应成功运行"""
        from pipeline.control_surface import execute
        result = execute("doctor")
        self.assertEqual(result["status"], "success")
        self.assertIsInstance(result["data"], dict)

    def test_mutating_command_requires_approval(self):
        """变更命令未 approved 时应返回 requires_approval"""
        from pipeline.control_surface import execute
        result = execute("backtest.run", strategy_id="dual_ma",
                         start="2023-01-01", end="2024-12-31")
        self.assertEqual(result["status"], "requires_approval")
        self.assertIn("command", result)
        self.assertIn("message", result)

    def test_mutating_command_with_approval(self):
        """变更命令 approved=True 时应正常执行（此处用 report.weekly 做轻量测试）"""
        from pipeline.control_surface import execute
        result = execute("report.weekly", approved=True)
        self.assertEqual(result["status"], "success")

    def test_readonly_command_no_approval_needed(self):
        """只读命令不需要 approved 即可执行"""
        from pipeline.control_surface import execute
        result = execute("strategies.list")
        self.assertEqual(result["status"], "success")

    def test_dry_run_returns_plan(self):
        """dry_run=True 时返回执行计划但不实际执行"""
        from pipeline.control_surface import execute
        result = execute("backtest.run", dry_run=True, approved=True,
                         strategy_id="dual_ma", start="2023-01-01", end="2024-12-31")
        self.assertEqual(result["status"], "dry_run")
        self.assertEqual(result["command"], "backtest.run")


if __name__ == "__main__":
    unittest.main()
