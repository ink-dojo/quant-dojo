"""
test_e2e_control_plane.py — 控制面端到端集成测试

证明完整链路：
  control_surface.execute → strategy_registry → run_store → dashboard.services

测试覆盖：
  1. 成功回测：execute → 持久化 RunRecord → Dashboard 服务可读取
  2. 失败回测：run_strategy 抛异常，error 被捕获
  3. 审批门：未 approved 返回 requires_approval
  4. dry_run：不持久化，返回 dry_run 状态

运行方式:
  python -m pytest tests/test_e2e_control_plane.py -v
"""
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

import pandas as pd

# 注入缺失的第三方依赖 stub（与 test_control_plane.py 保持一致）
for _pkg in ("akshare",):
    if _pkg not in sys.modules:
        sys.modules[_pkg] = MagicMock()

# ─── 预定义测试用的固定返回值 ───────────────────────────────────

_DATES = pd.date_range("2023-01-01", periods=250, freq="B")
_CANNED_DF = pd.DataFrame({"returns": [0.001] * 250}, index=_DATES)

_CANNED_METRICS = {
    "total_return": 0.28,
    "annualized_return": 0.13,
    "volatility": 0.15,
    "sharpe": 0.87,
    "max_drawdown": -0.09,
    "win_rate": 0.56,
    "n_trading_days": 250,
}

_CANNED_PARAMS = {"symbol": "000001", "fast_period": 20, "slow_period": 60}

_CANNED_RESULT = {
    "strategy_id": "dual_ma",
    "params": _CANNED_PARAMS,
    "start": "2023-01-01",
    "end": "2024-12-31",
    "status": "success",
    "results_df": _CANNED_DF,
    "metrics": _CANNED_METRICS,
    "error": None,
}


class TestE2EControlPlane(unittest.TestCase):
    """端到端集成测试：控制面 → 存储 → Dashboard 完整链路"""

    def setUp(self):
        """每个测试使用独立的临时 RUNS_DIR，与生产数据隔离"""
        self.tmp = tempfile.TemporaryDirectory()
        self.tmp_path = Path(self.tmp.name) / "runs"
        import pipeline.run_store as rs
        self._orig_runs_dir = rs.RUNS_DIR
        rs.RUNS_DIR = self.tmp_path

    def tearDown(self):
        import pipeline.run_store as rs
        rs.RUNS_DIR = self._orig_runs_dir
        self.tmp.cleanup()

    # ──────────────────────────────────────────────────────────────
    # 测试 1：成功回测 — 完整链路验证
    # ──────────────────────────────────────────────────────────────

    @patch("pipeline.strategy_registry.run_strategy", return_value=_CANNED_RESULT)
    def test_successful_run_full_chain(self, _mock_run):
        """成功回测：execute → run_id + metrics → RunRecord 持久化 → Dashboard 可读"""
        from pipeline.control_surface import execute

        result = execute(
            "backtest.run",
            approved=True,
            strategy_id="dual_ma",
            start="2023-01-01",
            end="2024-12-31",
        )

        # 1. execute 返回 success 且携带 run_id
        self.assertEqual(result["status"], "success")
        self.assertIn("run_id", result["data"])
        run_id = result["data"]["run_id"]
        self.assertTrue(run_id.startswith("dual_ma_"), f"run_id 格式异常: {run_id}")

        # 2. RunRecord 持久化字段与入参一致
        from pipeline.run_store import get_run
        record = get_run(run_id)
        self.assertEqual(record.strategy_id, "dual_ma")
        self.assertEqual(record.params, _CANNED_PARAMS)
        self.assertEqual(record.start_date, "2023-01-01")
        self.assertEqual(record.end_date, "2024-12-31")
        self.assertEqual(record.status, "success")
        self.assertEqual(record.metrics, _CANNED_METRICS)

        # 3. get_run(run_id) 能复现同一条记录
        record2 = get_run(run_id)
        self.assertEqual(record2.run_id, run_id)
        self.assertEqual(record2.metrics, _CANNED_METRICS)

        # 4. equity_csv artifact 文件实际存在于磁盘
        self.assertIn("equity_csv", record.artifacts)
        equity_path = Path(record.artifacts["equity_csv"])
        self.assertTrue(equity_path.exists(), f"equity CSV 文件不存在: {equity_path}")

        # 5. Dashboard.get_run_detail 返回相同指标和溯源字段
        from dashboard.services.backtest_service import get_run_detail
        detail = get_run_detail(run_id)
        self.assertEqual(detail["metrics"], _CANNED_METRICS)
        self.assertEqual(detail["strategy_id"], "dual_ma")
        self.assertEqual(detail["params"], _CANNED_PARAMS)
        self.assertEqual(detail["start_date"], "2023-01-01")
        self.assertEqual(detail["end_date"], "2024-12-31")
        self.assertIn("created_at", detail)
        self.assertTrue(detail["created_at"], "created_at 不应为空")

        # 6. Dashboard.get_runs 包含此 run
        from dashboard.services.backtest_service import get_runs
        runs = get_runs()
        run_ids_in_list = [r["run_id"] for r in runs]
        self.assertIn(run_id, run_ids_in_list)

        # 7. Dashboard.compare_runs 正常工作
        from dashboard.services.backtest_service import compare_runs
        comparison = compare_runs([run_id])
        self.assertIn("runs", comparison)
        self.assertIn("metric_names", comparison)
        self.assertEqual(len(comparison["runs"]), 1)
        self.assertEqual(comparison["runs"][0]["run_id"], run_id)

    # ──────────────────────────────────────────────────────────────
    # 测试 2：失败回测 — 异常捕获
    # ──────────────────────────────────────────────────────────────

    @patch("pipeline.strategy_registry.run_strategy")
    def test_failed_run_error_captured(self, mock_run):
        """run_strategy 抛异常时，execute 应捕获并返回 error 状态，不留持久化记录"""
        mock_run.side_effect = RuntimeError("数据加载失败：无法连接数据源")

        from pipeline.control_surface import execute
        result = execute(
            "backtest.run",
            approved=True,
            strategy_id="dual_ma",
            start="2023-01-01",
            end="2024-12-31",
        )

        self.assertEqual(result["status"], "error")
        self.assertIn("数据加载失败", result["error"])

        # 异常发生在 save_run 之前，不应有持久化记录
        from pipeline.run_store import list_runs
        self.assertEqual(list_runs(), [])

    # ──────────────────────────────────────────────────────────────
    # 测试 3：审批门 — 未 approved 拒绝执行
    # ──────────────────────────────────────────────────────────────

    def test_approval_gate_without_approved(self):
        """backtest.run 未传 approved=True 时应返回 requires_approval，不执行任何副作用"""
        from pipeline.control_surface import execute

        result = execute(
            "backtest.run",
            strategy_id="dual_ma",
            start="2023-01-01",
            end="2024-12-31",
            # approved 默认 False
        )

        self.assertEqual(result["status"], "requires_approval")
        self.assertEqual(result["command"], "backtest.run")
        self.assertIn("message", result)
        self.assertIn("approved=True", result["message"])

        # 确认没有持久化任何记录
        from pipeline.run_store import list_runs
        self.assertEqual(list_runs(), [])

    # ──────────────────────────────────────────────────────────────
    # 测试 4：dry_run — 不持久化
    # ──────────────────────────────────────────────────────────────

    def test_dry_run_no_persist(self):
        """dry_run=True 时返回 dry_run 状态，不调用 run_strategy，不写磁盘"""
        from pipeline.control_surface import execute

        result = execute(
            "backtest.run",
            dry_run=True,
            approved=True,
            strategy_id="dual_ma",
            start="2023-01-01",
            end="2024-12-31",
        )

        self.assertEqual(result["status"], "dry_run")
        self.assertEqual(result["command"], "backtest.run")

        # dry_run 不持久化
        from pipeline.run_store import list_runs
        self.assertEqual(list_runs(), [])


if __name__ == "__main__":
    unittest.main()
