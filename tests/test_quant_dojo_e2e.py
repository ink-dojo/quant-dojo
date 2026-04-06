"""
tests/test_quant_dojo_e2e.py — 端到端集成测试

验证 quant_dojo 统一入口的完整链路：
  init → status → backtest → activate → run(dry) → status
"""
import json
import sys
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

PROJECT_ROOT = Path(__file__).parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


class TestEndToEnd:
    """完整用户旅程测试"""

    def test_full_journey_dry_run(self, tmp_path):
        """模拟完整用户旅程：init → status → backtest → activate → run(dry) → status"""

        # ── Step 1: init ──
        from quant_dojo.commands.init import run_init

        data_dir = tmp_path / "data"
        data_dir.mkdir()
        (data_dir / "sh.600000.csv").write_text("date,close\n2024-01-01,10.0\n")
        config_dir = tmp_path / "config"
        config_dir.mkdir()

        with patch("quant_dojo.commands.init.PROJECT_ROOT", tmp_path):
            with patch("quant_dojo.commands.init.CONFIG_DIR", config_dir):
                with patch("quant_dojo.commands.init.CONFIG_FILE", config_dir / "config.yaml"):
                    with patch("quant_dojo.commands.init.CONFIG_EXAMPLE", PROJECT_ROOT / "config" / "config.example.yaml"):
                        run_init(data_dir=str(data_dir))

        assert (tmp_path / "config" / "config.yaml").exists()

        # ── Step 2: status (should not crash with minimal setup) ──
        from quant_dojo.commands.status import show_status

        with patch("quant_dojo.commands.status.PROJECT_ROOT", tmp_path):
            show_status()

        # ── Step 3: backtest (mocked) ──
        from quant_dojo.commands.backtest import run_backtest_cmd

        mock_result = MagicMock()
        mock_result.status = "success"
        mock_result.metrics = {
            "total_return": 0.15,
            "sharpe": 1.2,
            "max_drawdown": -0.08,
        }
        mock_result.equity_curve = None
        mock_result.run_id = "test_e2e_001"

        with patch("backtest.standardized.run_backtest", return_value=mock_result):
            result = run_backtest_cmd(strategy="v7", start="2024-01-01", end="2025-12-31", report=False)

        assert result.status == "success"

        # ── Step 4: activate ──
        from quant_dojo.commands.activate import run_activate

        state_file = tmp_path / "live" / "strategy_state.json"
        state_file.parent.mkdir(parents=True, exist_ok=True)

        with patch("pipeline.active_strategy.STATE_FILE", state_file):
            run_activate(strategy="v8", reason="回测验证通过")

        assert state_file.exists()
        state = json.loads(state_file.read_text())
        assert state["active_strategy"] == "v8"

        # ── Step 5: run (dry) ──
        from quant_dojo.commands.run import run_daily

        with patch("quant_dojo.commands.run._check_initialized"):
            with patch("quant_dojo.commands.run._detect_latest_date", return_value="2026-04-03"):
                with patch("quant_dojo.commands.run._step_data_update", return_value={"status": "ok", "summary": "fresh"}):
                    with patch("quant_dojo.commands.run._step_signal", return_value={"status": "ok", "n_picks": 0, "dry_run": True}):
                        with patch("quant_dojo.commands.run._step_rebalance", return_value={"status": "ok", "n_buys": 0, "n_sells": 0, "dry_run": True}):
                            with patch("quant_dojo.commands.run._step_risk_check", return_value={"status": "ok", "level": "ok", "alerts": []}):
                                with patch("quant_dojo.commands.run._step_export_dashboard"):
                                    with patch("quant_dojo.commands.run._step_show_summary"):
                                        with patch("quant_dojo.commands.run._save_run_log"):
                                            run_daily(dry_run=True)

        # ── Step 6: status again ──
        with patch("quant_dojo.commands.status.PROJECT_ROOT", tmp_path):
            show_status()

    def test_doctor_detects_issues(self):
        """doctor 应检测到真实环境的状态"""
        from quant_dojo.commands.doctor import run_doctor
        # 不应崩溃
        run_doctor()


class TestCLIEntryPoint:
    """CLI 入口点测试"""

    def test_main_dispatches_init(self):
        """main 应正确调度 init 命令"""
        from quant_dojo.__main__ import main

        with patch("sys.argv", ["quant_dojo", "init", "--data-dir", "/tmp/test"]):
            with patch("quant_dojo.commands.init.run_init") as mock:
                main()
                mock.assert_called_once_with(data_dir="/tmp/test", download=False)

    def test_main_dispatches_status(self):
        """main 应正确调度 status 命令"""
        from quant_dojo.__main__ import main

        with patch("sys.argv", ["quant_dojo", "status"]):
            with patch("quant_dojo.commands.status.show_status") as mock:
                main()
                mock.assert_called_once()

    def test_main_dispatches_run_dry(self):
        """main 应正确调度 run --dry-run"""
        from quant_dojo.__main__ import main

        with patch("sys.argv", ["quant_dojo", "run", "--dry-run"]):
            with patch("quant_dojo.commands.run.run_daily") as mock:
                main()
                mock.assert_called_once_with(date=None, strategy=None, dry_run=True)

    def test_main_dispatches_backtest(self):
        """main 应正确调度 backtest"""
        from quant_dojo.__main__ import main

        with patch("sys.argv", ["quant_dojo", "backtest", "--strategy", "v8", "--start", "2024-01-01", "--end", "2025-12-31"]):
            with patch("quant_dojo.commands.backtest.run_backtest_cmd") as mock:
                main()
                mock.assert_called_once_with(
                    strategy="v8",
                    start="2024-01-01",
                    end="2025-12-31",
                    n_stocks=30,
                    report=True,
                )

    def test_main_dispatches_activate(self):
        """main 应正确调度 activate"""
        from quant_dojo.__main__ import main

        with patch("sys.argv", ["quant_dojo", "activate", "v8", "--reason", "test"]):
            with patch("quant_dojo.commands.activate.run_activate") as mock:
                main()
                mock.assert_called_once_with(strategy="v8", reason="test", show=False)
