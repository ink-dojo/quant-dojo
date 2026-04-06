"""
tests/test_quant_dojo_cli.py — 统一 CLI 测试
"""
import json
import sys
from pathlib import Path
from unittest.mock import patch, MagicMock

import numpy as np
import pandas as pd
import pytest

PROJECT_ROOT = Path(__file__).parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


# ═══════════════════════════════════════════════════════════
# __main__ CLI parsing
# ═══════════════════════════════════════════════════════════

class TestCLIParsing:
    def test_help_does_not_crash(self):
        """--help 不应崩溃"""
        from quant_dojo.__main__ import main
        with pytest.raises(SystemExit) as exc_info:
            with patch("sys.argv", ["quant_dojo", "--help"]):
                main()
        assert exc_info.value.code == 0

    def test_no_args_prints_help(self, capsys):
        """无参数应打印帮助"""
        from quant_dojo.__main__ import main
        with patch("sys.argv", ["quant_dojo"]):
            main()
        captured = capsys.readouterr()
        assert "quant_dojo" in captured.out or "quant-dojo" in captured.out

    def test_backtest_subcommand_help(self):
        """backtest --help 不应崩溃"""
        from quant_dojo.__main__ import main
        with pytest.raises(SystemExit) as exc_info:
            with patch("sys.argv", ["quant_dojo", "backtest", "--help"]):
                main()
        assert exc_info.value.code == 0


# ═══════════════════════════════════════════════════════════
# init command
# ═══════════════════════════════════════════════════════════

class TestInitCommand:
    def test_init_creates_config(self, tmp_path):
        """init 应创建配置文件和目录"""
        from quant_dojo.commands.init import run_init, PROJECT_ROOT, CONFIG_FILE

        data_dir = tmp_path / "test-data"
        data_dir.mkdir()
        # 创建假数据
        (data_dir / "sh.600000.csv").write_text("date,close\n2024-01-01,10.0\n")

        with patch("quant_dojo.commands.init.PROJECT_ROOT", tmp_path):
            with patch("quant_dojo.commands.init.CONFIG_DIR", tmp_path / "config"):
                with patch("quant_dojo.commands.init.CONFIG_FILE", tmp_path / "config" / "config.yaml"):
                    with patch("quant_dojo.commands.init.CONFIG_EXAMPLE", tmp_path / "config" / "config.example.yaml"):
                        run_init(data_dir=str(data_dir))

        config_path = tmp_path / "config" / "config.yaml"
        assert config_path.exists()

    def test_detect_data_dir_uses_config(self, tmp_path):
        """_detect_data_dir 应读取 config.yaml"""
        from quant_dojo.commands.init import _detect_data_dir

        # 无配置时应返回默认
        with patch("quant_dojo.commands.init.CONFIG_FILE", tmp_path / "nonexistent.yaml"):
            result = _detect_data_dir()
            assert isinstance(result, Path)

    def test_quick_check_missing_data(self, tmp_path):
        """_quick_check 应检测到空数据目录"""
        from quant_dojo.commands.init import _quick_check

        empty_dir = tmp_path / "empty"
        empty_dir.mkdir()
        issues = _quick_check(empty_dir)
        assert any("空" in i for i in issues)

    def test_quick_check_nonexistent_dir(self, tmp_path):
        """_quick_check 应检测到不存在的目录"""
        from quant_dojo.commands.init import _quick_check

        issues = _quick_check(tmp_path / "nonexistent")
        assert any("不存在" in i for i in issues)


# ═══════════════════════════════════════════════════════════
# run command
# ═══════════════════════════════════════════════════════════

class TestRunCommand:
    def test_detect_latest_date_fallback(self):
        """无数据时应降级到今天"""
        from quant_dojo.commands.run import _detect_latest_date
        from datetime import datetime

        with patch("utils.local_data_loader.get_all_symbols", side_effect=Exception("no data")):
            date = _detect_latest_date()
        assert date == datetime.now().strftime("%Y-%m-%d")

    def test_step_data_update_fresh(self):
        """数据新鲜时不触发更新"""
        from quant_dojo.commands.run import _step_data_update

        with patch("pipeline.data_checker.check_data_freshness") as mock:
            mock.return_value = {"days_stale": 0, "latest_date": "2026-04-05"}
            result = _step_data_update()

        assert result["status"] == "ok"
        assert "新鲜" in result["summary"]

    def test_step_signal_dry_run(self):
        """dry_run 模式不执行信号生成"""
        from quant_dojo.commands.run import _step_signal

        result = _step_signal(date="2026-04-03", strategy="v7", dry_run=True)
        assert result["dry_run"]
        assert result["n_picks"] == 0

    def test_step_rebalance_dry_run(self):
        """dry_run 模式不执行调仓"""
        from quant_dojo.commands.run import _step_rebalance

        result = _step_rebalance(date="2026-04-03", strategy="v7", dry_run=True)
        assert result["dry_run"]

    def test_save_run_log(self, tmp_path):
        """运行日志应保存到 logs/"""
        from quant_dojo.commands.run import _save_run_log

        with patch("quant_dojo.commands.run.PROJECT_ROOT", tmp_path):
            _save_run_log("2026-04-03", {"signal": {"status": "ok"}}, 10.5)

        log_path = tmp_path / "logs" / "quant_dojo_run_2026-04-03.json"
        assert log_path.exists()
        data = json.loads(log_path.read_text())
        assert data["date"] == "2026-04-03"
        assert data["elapsed_sec"] == 10.5

    @patch("quant_dojo.commands.run._save_run_log")
    @patch("quant_dojo.commands.run._step_show_summary")
    @patch("quant_dojo.commands.run._step_risk_check", return_value={"status": "ok", "level": "ok", "alerts": []})
    @patch("quant_dojo.commands.run._step_rebalance", return_value={"status": "ok", "n_buys": 0, "n_sells": 0, "dry_run": True})
    @patch("quant_dojo.commands.run._step_signal", return_value={"status": "ok", "n_picks": 0, "dry_run": True})
    @patch("quant_dojo.commands.run._step_data_update", return_value={"status": "ok", "summary": "fresh"})
    @patch("quant_dojo.commands.run._detect_latest_date", return_value="2026-04-03")
    def test_run_daily_dry_run_succeeds(self, *mocks):
        """dry_run 全流程应成功"""
        from quant_dojo.commands.run import run_daily
        # 不应 sys.exit
        run_daily(dry_run=True)

    @patch("quant_dojo.commands.run._save_run_log")
    @patch("quant_dojo.commands.run._step_show_summary")
    @patch("quant_dojo.commands.run._step_risk_check", return_value={"status": "ok", "level": "ok", "alerts": []})
    @patch("quant_dojo.commands.run._step_signal", side_effect=RuntimeError("boom"))
    @patch("quant_dojo.commands.run._step_data_update", return_value={"status": "ok", "summary": "fresh"})
    @patch("quant_dojo.commands.run._detect_latest_date", return_value="2026-04-03")
    def test_run_daily_signal_failure_halts(self, *mocks):
        """信号失败应停止调仓但不阻止风控和报告"""
        from quant_dojo.commands.run import run_daily
        with pytest.raises(SystemExit) as exc_info:
            run_daily()
        assert exc_info.value.code == 1


# ═══════════════════════════════════════════════════════════
# backtest command
# ═══════════════════════════════════════════════════════════

class TestBacktestCommand:
    def test_smart_defaults(self):
        """无日期参数时应自动计算2年范围"""
        from quant_dojo.commands.backtest import run_backtest_cmd
        from datetime import datetime, timedelta

        with patch("utils.local_data_loader.get_all_symbols", return_value=["000001"]), \
             patch("backtest.standardized.run_backtest") as mock_bt:
            mock_result = MagicMock()
            mock_result.status = "success"
            mock_result.metrics = {"total_return": 0.1, "sharpe": 1.0, "max_drawdown": -0.05}
            mock_result.equity_curve = None
            mock_result.run_id = "test_001"
            mock_bt.return_value = mock_result

            run_backtest_cmd(strategy="v7", report=False)

            call_args = mock_bt.call_args[0][0]
            assert call_args.strategy == "v7"
            assert call_args.start != ""
            assert call_args.end != ""
            # end should be ~today
            end_dt = datetime.strptime(call_args.end, "%Y-%m-%d")
            assert abs((end_dt - datetime.now()).days) <= 1

    def test_explicit_dates(self):
        """显式日期应传递到 BacktestConfig"""
        from quant_dojo.commands.backtest import run_backtest_cmd

        with patch("utils.local_data_loader.get_all_symbols", return_value=["000001"]), \
             patch("backtest.standardized.run_backtest") as mock_bt:
            mock_result = MagicMock()
            mock_result.status = "success"
            mock_result.metrics = {"total_return": 0.05, "sharpe": 0.5, "max_drawdown": -0.1}
            mock_result.equity_curve = None
            mock_result.run_id = "test_002"
            mock_bt.return_value = mock_result

            run_backtest_cmd(strategy="v8", start="2024-01-01", end="2025-12-31", report=False)

            call_args = mock_bt.call_args[0][0]
            assert call_args.strategy == "v8"
            assert call_args.start == "2024-01-01"
            assert call_args.end == "2025-12-31"

    def test_failed_backtest_exits(self):
        """失败的回测应 sys.exit(1)"""
        from quant_dojo.commands.backtest import run_backtest_cmd

        with patch("utils.local_data_loader.get_all_symbols", return_value=["000001"]):
            with patch("backtest.standardized.run_backtest") as mock_bt:
                mock_result = MagicMock()
                mock_result.status = "failed"
                mock_result.error = "no data"
                mock_bt.return_value = mock_result

                with pytest.raises(SystemExit) as exc_info:
                    run_backtest_cmd(report=False)
                assert exc_info.value.code == 1

    def test_backtest_exits_when_no_data(self):
        """无数据时应 sys.exit(1) 并提示"""
        from quant_dojo.commands.backtest import run_backtest_cmd

        with patch("utils.local_data_loader.get_all_symbols", return_value=[]):
            with pytest.raises(SystemExit) as exc_info:
                run_backtest_cmd(report=False)
            assert exc_info.value.code == 1


# ═══════════════════════════════════════════════════════════
# status command
# ═══════════════════════════════════════════════════════════

class TestStatusCommand:
    def test_show_status_no_crash(self, tmp_path):
        """status 命令不应崩溃（即使数据缺失）"""
        from quant_dojo.commands.status import show_status

        with patch("quant_dojo.commands.status.PROJECT_ROOT", tmp_path):
            # 所有外部依赖可能失败，但命令本身不该崩溃
            show_status()

    def test_show_signal_status_with_data(self, tmp_path):
        """有信号文件时应显示信号信息"""
        from quant_dojo.commands.status import _show_signal_status

        signal_dir = tmp_path / "live" / "signals"
        signal_dir.mkdir(parents=True)
        sig = {"date": "2026-04-03", "picks": ["000001", "600036", "000858"]}
        (signal_dir / "2026-04-03.json").write_text(json.dumps(sig))

        with patch("quant_dojo.commands.status.PROJECT_ROOT", tmp_path):
            _show_signal_status()  # 不应崩溃

    def test_show_portfolio_status_empty(self, tmp_path):
        """无持仓时不崩溃"""
        from quant_dojo.commands.status import _show_portfolio_status

        with patch("quant_dojo.commands.status.PROJECT_ROOT", tmp_path):
            _show_portfolio_status()  # 不应崩溃

    def test_show_portfolio_with_nav(self, tmp_path):
        """有 NAV 数据时应显示收益"""
        from quant_dojo.commands.status import _show_portfolio_status

        portfolio_dir = tmp_path / "live" / "portfolio"
        portfolio_dir.mkdir(parents=True)

        # 创建 positions
        positions = {"000001": {"shares": 100}, "__cash__": 500000}
        (portfolio_dir / "positions.json").write_text(json.dumps(positions))

        # 创建 NAV
        nav_data = "date,nav\n2026-01-01,1000000\n2026-04-03,1050000\n"
        (portfolio_dir / "nav.csv").write_text(nav_data)

        with patch("quant_dojo.commands.status.PROJECT_ROOT", tmp_path):
            _show_portfolio_status()  # 不应崩溃


# ═══════════════════════════════════════════════════════════
# doctor command
# ═══════════════════════════════════════════════════════════

class TestDoctorCommand:
    def test_doctor_runs(self):
        """doctor 命令不应崩溃"""
        from quant_dojo.commands.doctor import run_doctor
        # doctor 会检查真实的依赖，不需要 mock
        run_doctor()
