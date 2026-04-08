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

    def test_download_data_calls_run_update(self, tmp_path):
        """--download 应调用 pipeline.data_update.run_update"""
        from quant_dojo.commands.init import _download_data

        with patch("pipeline.data_update.run_update") as mock_update:
            mock_update.return_value = {"updated": ["000001", "600000"], "skipped": [], "failed": []}
            _download_data(tmp_path)
            mock_update.assert_called_once()

    def test_download_handles_missing_dep(self, tmp_path):
        """缺少依赖时应提示安装"""
        from quant_dojo.commands.init import _download_data

        with patch("pipeline.data_update.run_update", side_effect=ImportError("No module named 'baostock'")):
            _download_data(tmp_path)  # 不应崩溃


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

    def test_check_initialized_no_config_exits(self, tmp_path):
        """无 config.yaml 时应 exit(1)"""
        from quant_dojo.commands.run import _check_initialized

        with patch("quant_dojo.commands.run.PROJECT_ROOT", tmp_path):
            with pytest.raises(SystemExit) as exc_info:
                _check_initialized()
            assert exc_info.value.code == 1

    def test_check_initialized_with_config(self, tmp_path):
        """有 config.yaml 时不应退出"""
        from quant_dojo.commands.run import _check_initialized

        config_dir = tmp_path / "config"
        config_dir.mkdir()
        (config_dir / "config.yaml").write_text("pipeline:\n  default_strategy: v7\n")

        with patch("quant_dojo.commands.run.PROJECT_ROOT", tmp_path):
            _check_initialized()  # 不应崩溃

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

    @patch("quant_dojo.commands.run._check_initialized")
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

    @patch("quant_dojo.commands.run._check_initialized")
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

    def test_show_last_run(self, tmp_path):
        """有运行记录时应显示最近运行"""
        from quant_dojo.commands.status import _show_last_run

        log_dir = tmp_path / "logs"
        log_dir.mkdir()
        log = {
            "date": "2026-04-05",
            "timestamp": "2026-04-05T16:30:00",
            "elapsed_sec": 8.3,
            "steps": {"signal": {"status": "ok"}},
        }
        (log_dir / "quant_dojo_run_2026-04-05.json").write_text(json.dumps(log))

        with patch("quant_dojo.commands.status.PROJECT_ROOT", tmp_path):
            _show_last_run()  # 不应崩溃

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

    def test_show_backtest_divergence_with_success_run(self, tmp_path, capsys):
        """存在成功回测 run 时，status 应显示 live vs bt 摘要"""
        from quant_dojo.commands.status import _show_backtest_divergence

        # 构造最小 live/runs + live/portfolio
        runs_dir = tmp_path / "live" / "runs"
        portfolio_dir = tmp_path / "live" / "portfolio"
        runs_dir.mkdir(parents=True)
        portfolio_dir.mkdir(parents=True)

        eq_csv = runs_dir / "eq.csv"
        eq_csv.write_text(
            "date,cumulative_return\n2026-03-20,0.00\n2026-03-21,0.01\n"
        )
        run = runs_dir / "v7_fixture.json"
        run.write_text(json.dumps({
            "run_id": "v7_fixture",
            "strategy_id": "v7",
            "status": "success",
            "artifacts": {"equity_csv": str(eq_csv)},
        }))

        (portfolio_dir / "nav.csv").write_text(
            "date,nav\n2026-03-20,1000000\n2026-03-21,1020000\n"
        )

        with patch("quant_dojo.commands.status.PROJECT_ROOT", tmp_path):
            _show_backtest_divergence()

        out = capsys.readouterr().out
        assert "偏差 (live vs backtest)" in out
        assert "v7_fixture" in out
        assert "共同窗口" in out

    def test_show_backtest_divergence_no_success_run(self, tmp_path, capsys):
        """只有失败回测时，应提示无成功记录"""
        from quant_dojo.commands.status import _show_backtest_divergence

        runs_dir = tmp_path / "live" / "runs"
        portfolio_dir = tmp_path / "live" / "portfolio"
        runs_dir.mkdir(parents=True)
        portfolio_dir.mkdir(parents=True)

        (runs_dir / "v7_bad.json").write_text(json.dumps({
            "run_id": "v7_bad",
            "strategy_id": "v7",
            "status": "failed",
            "artifacts": {},
        }))
        (portfolio_dir / "nav.csv").write_text("date,nav\n2026-03-20,1000000\n")

        with patch("quant_dojo.commands.status.PROJECT_ROOT", tmp_path):
            _show_backtest_divergence()

        out = capsys.readouterr().out
        assert "无成功的回测记录" in out

    def test_show_backtest_divergence_missing_files(self, tmp_path, capsys):
        """runs 或 nav 缺失时应静默提示，不崩溃"""
        from quant_dojo.commands.status import _show_backtest_divergence

        with patch("quant_dojo.commands.status.PROJECT_ROOT", tmp_path):
            _show_backtest_divergence()

        out = capsys.readouterr().out
        assert "无可用数据" in out


# ═══════════════════════════════════════════════════════════
# compare command
# ═══════════════════════════════════════════════════════════

class TestCompareCommand:
    def test_compare_needs_two_strategies(self):
        """至少需要 2 个策略"""
        from quant_dojo.commands.compare import run_compare

        with pytest.raises(SystemExit) as exc_info:
            run_compare(strategies=["v7"])
        assert exc_info.value.code == 1

    def test_compare_two_strategies(self):
        """两个策略对比应成功"""
        from quant_dojo.commands.compare import run_compare

        mock_result = MagicMock()
        mock_result.status = "success"
        mock_result.metrics = {
            "total_return": 0.12,
            "annualized_return": 0.06,
            "sharpe": 1.1,
            "max_drawdown": -0.08,
        }
        mock_result.config = MagicMock()
        mock_result.config.strategy = "v7"

        mock_result2 = MagicMock()
        mock_result2.status = "success"
        mock_result2.metrics = {
            "total_return": 0.08,
            "annualized_return": 0.04,
            "sharpe": 0.7,
            "max_drawdown": -0.12,
        }
        mock_result2.config = MagicMock()
        mock_result2.config.strategy = "v8"

        with patch("utils.local_data_loader.get_all_symbols", return_value=["000001"]):
            with patch("backtest.standardized.run_backtest", side_effect=[mock_result, mock_result2]):
                with patch("backtest.comparison.generate_comparison_report", return_value="/tmp/report.html"):
                    run_compare(
                        strategies=["v7", "v8"],
                        start="2024-01-01",
                        end="2025-12-31",
                    )

    def test_compare_all_fail_exits(self):
        """所有回测都失败应 exit(1)"""
        from quant_dojo.commands.compare import run_compare

        mock_result = MagicMock()
        mock_result.status = "failed"
        mock_result.error = "no data"

        with patch("utils.local_data_loader.get_all_symbols", return_value=["000001"]):
            with patch("backtest.standardized.run_backtest", return_value=mock_result):
                with pytest.raises(SystemExit) as exc_info:
                    run_compare(strategies=["v7", "v8"])
                assert exc_info.value.code == 1

    def test_compare_all_strategies_default(self):
        """无参数时应对比所有策略"""
        from quant_dojo.__main__ import main

        with patch("sys.argv", ["quant_dojo", "compare"]):
            with patch("quant_dojo.commands.compare.run_compare") as mock:
                main()
                # 应传入所有已知策略
                call_strategies = mock.call_args[1]["strategies"]
                assert len(call_strategies) >= 2

    def test_compare_cli_dispatch(self):
        """CLI 应正确调度 compare 命令"""
        from quant_dojo.__main__ import main

        with patch("sys.argv", ["quant_dojo", "compare", "v7", "v8"]):
            with patch("quant_dojo.commands.compare.run_compare") as mock:
                main()
                mock.assert_called_once_with(
                    strategies=["v7", "v8"],
                    start=None,
                    end=None,
                    n_stocks=30,
                )


# ═══════════════════════════════════════════════════════════
# quickstart command
# ═══════════════════════════════════════════════════════════

class TestQuickstartCommand:
    def test_quickstart_no_data_skip_download_exits(self, tmp_path):
        """无数据+跳过下载应 exit(1)"""
        from quant_dojo.commands.quickstart import run_quickstart

        data_dir = tmp_path / "empty-data"
        data_dir.mkdir()

        with patch("quant_dojo.commands.init.PROJECT_ROOT", tmp_path):
            with patch("quant_dojo.commands.init.CONFIG_DIR", tmp_path / "config"):
                with patch("quant_dojo.commands.init.CONFIG_FILE", tmp_path / "config" / "config.yaml"):
                    with patch("quant_dojo.commands.init.CONFIG_EXAMPLE", tmp_path / "config" / "config.example.yaml"):
                        with pytest.raises(SystemExit) as exc_info:
                            run_quickstart(data_dir=str(data_dir), skip_download=True)
                        assert exc_info.value.code == 1

    def test_quickstart_with_existing_data(self, tmp_path):
        """有数据时应跳过下载并继续回测"""
        from quant_dojo.commands.quickstart import run_quickstart

        data_dir = tmp_path / "data"
        data_dir.mkdir()
        (data_dir / "sh.600000.csv").write_text("date,close\n2024-01-01,10.0\n")

        mock_result = MagicMock()
        mock_result.status = "success"
        mock_result.metrics = {"total_return": 0.1, "sharpe": 1.0, "max_drawdown": -0.05}
        mock_result.equity_curve = None
        mock_result.run_id = "qs_001"

        with patch("quant_dojo.commands.init.PROJECT_ROOT", tmp_path):
            with patch("quant_dojo.commands.init.CONFIG_DIR", tmp_path / "config"):
                with patch("quant_dojo.commands.init.CONFIG_FILE", tmp_path / "config" / "config.yaml"):
                    with patch("quant_dojo.commands.init.CONFIG_EXAMPLE", tmp_path / "config" / "config.example.yaml"):
                        with patch("utils.local_data_loader.get_all_symbols", return_value=["600000"]):
                            with patch("backtest.standardized.run_backtest", return_value=mock_result):
                                with patch("pipeline.active_strategy.get_active_strategy", return_value="v7"):
                                    with patch("quant_dojo.commands.schedule.setup_schedule"):
                                        with patch("quant_dojo.commands.quickstart._resolve_data_path", return_value=data_dir):
                                            run_quickstart(data_dir=str(data_dir), skip_download=True)

    def test_quickstart_cli_dispatch(self):
        """CLI 应正确调度 quickstart 命令"""
        from quant_dojo.__main__ import main

        with patch("sys.argv", ["quant_dojo", "quickstart", "--skip-download"]):
            with patch("quant_dojo.commands.quickstart.run_quickstart") as mock:
                main()
                mock.assert_called_once_with(data_dir=None, skip_download=True)


# ═══════════════════════════════════════════════════════════
# update command
# ═══════════════════════════════════════════════════════════

class TestUpdateCommand:
    def test_update_dry_run(self):
        """dry_run 应不实际下载"""
        from quant_dojo.commands.update import run_update

        with patch("utils.runtime_config.get_local_data_dir") as mock_dir:
            from pathlib import Path
            mock_dir.return_value = Path("/tmp/test-data")
            with patch("pathlib.Path.exists", return_value=True):
                with patch("pathlib.Path.glob", return_value=["a.csv"]):
                    with patch("pipeline.data_update.run_update") as mock_update:
                        mock_update.return_value = {"updated": [], "skipped": ["000001"], "failed": []}
                        run_update(dry_run=True)
                        mock_update.assert_called_once()

    def test_update_cli_dispatch(self):
        """CLI 应正确调度 update 命令"""
        from quant_dojo.__main__ import main

        with patch("sys.argv", ["quant_dojo", "update", "--dry-run"]):
            with patch("quant_dojo.commands.update.run_update") as mock:
                main()
                mock.assert_called_once_with(dry_run=True, full=False)


# ═══════════════════════════════════════════════════════════
# schedule command
# ═══════════════════════════════════════════════════════════

class TestScheduleCommand:
    def test_schedule_generates_cron_line(self):
        """schedule 应生成正确的 crontab 条目"""
        from quant_dojo.commands.schedule import setup_schedule

        with patch("quant_dojo.commands.schedule._get_current_crontab", return_value=""):
            with patch("quant_dojo.commands.schedule._add_cron") as mock_add:
                setup_schedule(time="17:00")
                cron_line = mock_add.call_args[0][0]
                assert "0 17" in cron_line
                assert "1-5" in cron_line  # weekdays only
                assert "quant_dojo run" in cron_line

    def test_schedule_replaces_existing(self):
        """已存在定时任务时应替换"""
        from quant_dojo.commands.schedule import setup_schedule

        existing = "30 16 * * 1-5 cd /old && python -m quant_dojo run # quant-dojo-auto"
        with patch("quant_dojo.commands.schedule._get_current_crontab", return_value=existing):
            with patch("quant_dojo.commands.schedule._remove_cron") as mock_rm:
                with patch("quant_dojo.commands.schedule._add_cron"):
                    setup_schedule(time="17:00")
                    mock_rm.assert_called_once()

    def test_schedule_remove(self):
        """--remove 应移除定时任务"""
        from quant_dojo.commands.schedule import setup_schedule

        with patch("quant_dojo.commands.schedule._remove_cron") as mock_rm:
            setup_schedule(remove=True)
            mock_rm.assert_called_once_with("# quant-dojo-auto")


# ═══════════════════════════════════════════════════════════
# notify command
# ═══════════════════════════════════════════════════════════

class TestNotifyCommand:
    def test_no_webhook_silently_skips(self):
        """未配置 webhook 应静默跳过"""
        from quant_dojo.commands.notify import send_run_notification

        with patch("utils.runtime_config.get_config", return_value={"alerts": {}}):
            # 不应抛异常
            send_run_notification("2026-04-03", {"signal": {"status": "ok"}}, 5.0)

    def test_feishu_format(self):
        """飞书 URL 应使用飞书格式"""
        from quant_dojo.commands.notify import _send_webhook
        import json

        with patch("urllib.request.urlopen") as mock_open:
            mock_resp = MagicMock()
            mock_resp.status = 200
            mock_resp.__enter__ = lambda s: s
            mock_resp.__exit__ = MagicMock(return_value=False)
            mock_open.return_value = mock_resp

            _send_webhook("https://open.feishu.cn/hook/xxx", "title", "body")

            req = mock_open.call_args[0][0]
            payload = json.loads(req.data)
            assert payload["msg_type"] == "text"
            assert "title" in payload["content"]["text"]

    def test_slack_format(self):
        """Slack URL 应使用 Slack 格式"""
        from quant_dojo.commands.notify import _send_webhook
        import json

        with patch("urllib.request.urlopen") as mock_open:
            mock_resp = MagicMock()
            mock_resp.status = 200
            mock_resp.__enter__ = lambda s: s
            mock_resp.__exit__ = MagicMock(return_value=False)
            mock_open.return_value = mock_resp

            _send_webhook("https://hooks.slack.com/xxx", "title", "body")

            req = mock_open.call_args[0][0]
            payload = json.loads(req.data)
            assert "text" in payload
            assert "*title*" in payload["text"]

    def test_dingtalk_format(self):
        """钉钉 URL 应使用钉钉格式"""
        from quant_dojo.commands.notify import _send_webhook
        import json

        with patch("urllib.request.urlopen") as mock_open:
            mock_resp = MagicMock()
            mock_resp.status = 200
            mock_resp.__enter__ = lambda s: s
            mock_resp.__exit__ = MagicMock(return_value=False)
            mock_open.return_value = mock_resp

            _send_webhook("https://oapi.dingtalk.com/robot/xxx", "title", "body")

            req = mock_open.call_args[0][0]
            payload = json.loads(req.data)
            assert payload["msgtype"] == "text"


# ═══════════════════════════════════════════════════════════
# report command
# ═══════════════════════════════════════════════════════════

class TestReportCommand:
    def test_weekly_report_auto_week(self):
        """无参数时应自动计算当前 ISO 周"""
        from quant_dojo.commands.report import generate_report

        with patch("pipeline.weekly_report.generate_weekly_report") as mock_gen:
            mock_gen.return_value = {"path": "/tmp/report.md"}
            generate_report()
            call_week = mock_gen.call_args[0][0]
            # 应是 YYYY-WNN 格式
            assert "-W" in call_week

    def test_weekly_report_explicit_week(self):
        """指定周应传递到报告生成"""
        from quant_dojo.commands.report import generate_report

        with patch("pipeline.weekly_report.generate_weekly_report") as mock_gen:
            mock_gen.return_value = {"path": "/tmp/report.md"}
            generate_report(week="2026-W14")
            mock_gen.assert_called_once_with("2026-W14")

    def test_backtest_report_no_runs_exits(self):
        """无回测记录时应 exit(1)"""
        from quant_dojo.commands.report import generate_report

        with patch("pipeline.run_store.list_runs", return_value=[]):
            with pytest.raises(SystemExit) as exc_info:
                generate_report(backtest=True)
            assert exc_info.value.code == 1

    def test_report_dispatch_from_cli(self):
        """CLI 应正确调度 report 命令"""
        from quant_dojo.__main__ import main

        with patch("sys.argv", ["quant_dojo", "report", "--week", "2026-W14"]):
            with patch("quant_dojo.commands.report.generate_report") as mock:
                main()
                mock.assert_called_once_with(week="2026-W14", backtest=False)


# ═══════════════════════════════════════════════════════════
# activate command
# ═══════════════════════════════════════════════════════════

class TestActivateCommand:
    def test_activate_show_mode(self):
        """--show 应显示当前策略"""
        from quant_dojo.commands.activate import run_activate

        with patch("pipeline.active_strategy.get_active_strategy", return_value="v7"):
            with patch("pipeline.active_strategy.get_strategy_history", return_value=[]):
                with patch("pipeline.active_strategy.VALID_STRATEGIES", {"v7", "v8", "ad_hoc"}):
                    run_activate(show=True)  # 不应崩溃

    def test_activate_invalid_strategy_exits(self):
        """无效策略应 exit(1)"""
        from quant_dojo.commands.activate import run_activate

        with patch("pipeline.active_strategy.get_active_strategy", return_value="v7"):
            with patch("pipeline.active_strategy.VALID_STRATEGIES", {"v7", "v8"}):
                with pytest.raises(SystemExit) as exc_info:
                    run_activate(strategy="nonexistent")
                assert exc_info.value.code == 1

    def test_activate_same_strategy_noop(self):
        """已是当前策略时应提示无需切换"""
        from quant_dojo.commands.activate import run_activate

        with patch("pipeline.active_strategy.get_active_strategy", return_value="v7"):
            with patch("pipeline.active_strategy.VALID_STRATEGIES", {"v7", "v8"}):
                with patch("pipeline.active_strategy.set_active_strategy") as mock_set:
                    run_activate(strategy="v7")
                    mock_set.assert_not_called()


# ═══════════════════════════════════════════════════════════
# signals command
# ═══════════════════════════════════════════════════════════

class TestSignalsCommand:
    def test_signals_no_dir(self, tmp_path):
        """无 signals 目录时不崩溃"""
        from quant_dojo.commands.signals import show_signals

        with patch("quant_dojo.commands.signals.PROJECT_ROOT", tmp_path):
            show_signals()

    def test_signals_with_data(self, tmp_path):
        """有信号文件时应显示"""
        from quant_dojo.commands.signals import show_signals

        signal_dir = tmp_path / "live" / "signals"
        signal_dir.mkdir(parents=True)
        sig = {
            "date": "2026-04-03",
            "strategy": "v7",
            "picks": ["000001", "600036", "000858"],
            "scores": {"000001": 0.85, "600036": 0.72, "000858": 0.65},
        }
        (signal_dir / "2026-04-03.json").write_text(json.dumps(sig))

        with patch("quant_dojo.commands.signals.PROJECT_ROOT", tmp_path):
            show_signals()

    def test_signals_specific_date(self, tmp_path):
        """指定日期应显示该天信号"""
        from quant_dojo.commands.signals import show_signals

        signal_dir = tmp_path / "live" / "signals"
        signal_dir.mkdir(parents=True)
        sig = {"date": "2026-04-03", "picks": ["000001"], "scores": {}}
        (signal_dir / "2026-04-03.json").write_text(json.dumps(sig))

        with patch("quant_dojo.commands.signals.PROJECT_ROOT", tmp_path):
            show_signals(date="2026-04-03")

    def test_signals_cli_dispatch(self):
        """CLI 应正确调度 signals 命令"""
        from quant_dojo.__main__ import main

        with patch("sys.argv", ["quant_dojo", "signals", "-n", "3"]):
            with patch("quant_dojo.commands.signals.show_signals") as mock:
                main()
                mock.assert_called_once_with(n=3, date=None)


# ═══════════════════════════════════════════════════════════
# logs command
# ═══════════════════════════════════════════════════════════

class TestLogsCommand:
    def test_logs_no_dir(self, tmp_path):
        """无 logs 目录时不崩溃"""
        from quant_dojo.commands.logs import show_logs

        with patch("quant_dojo.commands.logs.PROJECT_ROOT", tmp_path):
            show_logs()

    def test_logs_with_data(self, tmp_path):
        """有运行记录时应显示"""
        from quant_dojo.commands.logs import show_logs

        log_dir = tmp_path / "logs"
        log_dir.mkdir()
        log = {
            "date": "2026-04-03",
            "timestamp": "2026-04-03T16:30:00",
            "elapsed_sec": 12.5,
            "steps": {
                "data_update": {"status": "ok"},
                "signal": {"status": "ok"},
            },
        }
        (log_dir / "quant_dojo_run_2026-04-03.json").write_text(json.dumps(log))

        with patch("quant_dojo.commands.logs.PROJECT_ROOT", tmp_path):
            show_logs()  # 不应崩溃

    def test_logs_with_detail(self, tmp_path):
        """--detail 应显示步骤详情"""
        from quant_dojo.commands.logs import show_logs

        log_dir = tmp_path / "logs"
        log_dir.mkdir()
        log = {
            "date": "2026-04-03",
            "timestamp": "2026-04-03T16:30:00",
            "elapsed_sec": 5.0,
            "steps": {
                "signal": {"status": "failed", "error": "no data"},
            },
        }
        (log_dir / "quant_dojo_run_2026-04-03.json").write_text(json.dumps(log))

        with patch("quant_dojo.commands.logs.PROJECT_ROOT", tmp_path):
            show_logs(detail=True)  # 不应崩溃

    def test_logs_cli_dispatch(self):
        """CLI 应正确调度 logs 命令"""
        from quant_dojo.__main__ import main

        with patch("sys.argv", ["quant_dojo", "logs", "-n", "5"]):
            with patch("quant_dojo.commands.logs.show_logs") as mock:
                main()
                mock.assert_called_once_with(n=5, detail=False)


# ═══════════════════════════════════════════════════════════
# doctor command
# ═══════════════════════════════════════════════════════════

# ═══════════════════════════════════════════════════════════
# generate command
# ═══════════════════════════════════════════════════════════

class TestGenerateCommand:
    def _make_mock_data(self):
        """创建模拟数据"""
        dates = pd.date_range("2024-01-01", "2025-12-31", freq="B")
        symbols = [f"00000{i}" for i in range(1, 51)]
        np.random.seed(42)
        price = pd.DataFrame(
            np.random.randn(len(dates), len(symbols)).cumsum(axis=0) + 100,
            index=dates, columns=symbols,
        )
        return {"price": price}

    def test_generate_cli_dispatch(self):
        """CLI 应正确调度 generate 命令"""
        from quant_dojo.__main__ import main

        with patch("sys.argv", ["quant_dojo", "generate", "--top", "4", "--min-icir", "0.15"]):
            with patch("quant_dojo.commands.generate.run_generate") as mock:
                main()
                mock.assert_called_once_with(
                    top_n=4,
                    min_icir=0.15,
                    max_corr=0.6,
                    start=None,
                    end=None,
                    n_stocks=30,
                    activate=False,
                )

    def test_generate_cli_activate_flag(self):
        """--activate 标志应传递"""
        from quant_dojo.__main__ import main

        with patch("sys.argv", ["quant_dojo", "generate", "--activate"]):
            with patch("quant_dojo.commands.generate.run_generate") as mock:
                main()
                mock.assert_called_once_with(
                    top_n=6,
                    min_icir=0.2,
                    max_corr=0.6,
                    start=None,
                    end=None,
                    n_stocks=30,
                    activate=True,
                )

    def test_evaluate_factors(self):
        """因子评估应返回排序后的统计"""
        from quant_dojo.commands.generate import _evaluate_factors

        dates = pd.date_range("2024-01-01", periods=100, freq="B")
        symbols = [f"00000{i}" for i in range(1, 51)]
        np.random.seed(42)

        ret_wide = pd.DataFrame(
            np.random.randn(len(dates), len(symbols)) * 0.02,
            index=dates, columns=symbols,
        )

        # 创建一个有信号的因子和一个纯噪声因子
        good_factor = ret_wide.shift(1) * 3 + pd.DataFrame(
            np.random.randn(len(dates), len(symbols)) * 0.01,
            index=dates, columns=symbols,
        )
        noise_factor = pd.DataFrame(
            np.random.randn(len(dates), len(symbols)),
            index=dates, columns=symbols,
        )

        factors = {"good": good_factor, "noise": noise_factor}

        with patch("utils.factor_analysis.compute_ic_series") as mock_ic:
            # 模拟 IC 序列
            ic_good = pd.Series(np.random.normal(0.05, 0.03, 80), index=dates[:80])
            ic_noise = pd.Series(np.random.normal(0.0, 0.05, 80), index=dates[:80])
            mock_ic.side_effect = [ic_good, ic_noise]

            stats = _evaluate_factors(factors, ret_wide)

        assert len(stats) == 2
        # good 因子应排在前面（|ICIR| 更大）
        assert stats[0]["name"] == "good"

    def test_build_strategy_definition(self):
        """策略定义应包含正确字段"""
        from quant_dojo.commands.generate import _build_strategy_definition

        selected = [
            {"name": "low_vol_20d", "IC_mean": -0.03, "ICIR": -0.35, "pct_pos": 0.4, "IC_std": 0.08, "n_days": 100},
            {"name": "bp", "IC_mean": 0.02, "ICIR": 0.25, "pct_pos": 0.55, "IC_std": 0.08, "n_days": 100},
        ]

        strategy = _build_strategy_definition(selected)

        assert strategy["name"] == "auto_gen"
        assert len(strategy["factors"]) == 2
        assert strategy["factors"][0]["direction"] == -1  # low_vol IC 为负，反向
        assert strategy["factors"][1]["direction"] == 1   # bp IC 为正，正向
        assert strategy["weighting"] == "ic_weighted"
        assert strategy["neutralize"] is True

    def test_select_uncorrelated_removes_redundant(self):
        """去冗余应移除高相关因子"""
        from quant_dojo.commands.generate import _select_uncorrelated

        dates = pd.date_range("2024-01-01", periods=200, freq="B")
        symbols = [f"00000{i}" for i in range(1, 51)]
        np.random.seed(42)

        base = pd.DataFrame(
            np.random.randn(len(dates), len(symbols)),
            index=dates, columns=symbols,
        )
        # factor_b 几乎和 factor_a 完全一样（相关性 > 0.95）
        factor_a = base
        factor_b = base + pd.DataFrame(
            np.random.randn(len(dates), len(symbols)) * 0.05,
            index=dates, columns=symbols,
        )
        factor_c = pd.DataFrame(
            np.random.randn(len(dates), len(symbols)),
            index=dates, columns=symbols,
        )

        qualified = [
            {"name": "a", "IC_mean": 0.05, "ICIR": 0.5},
            {"name": "b", "IC_mean": 0.04, "ICIR": 0.4},
            {"name": "c", "IC_mean": 0.03, "ICIR": 0.3},
        ]
        factors = {"a": factor_a, "b": factor_b, "c": factor_c}

        selected = _select_uncorrelated(qualified, factors, max_corr=0.6, top_n=3)

        names = [s["name"] for s in selected]
        assert "a" in names
        # b 应被过滤掉（与 a 高度相关），c 应保留
        assert "b" not in names
        assert "c" in names

    def test_save_strategy(self, tmp_path):
        """策略保存应写入 JSON 文件"""
        from quant_dojo.commands.generate import _save_strategy

        strategy_def = {
            "name": "auto_gen",
            "factors": [{"name": "bp", "direction": 1, "icir": 0.3, "ic_mean": 0.02}],
            "weighting": "ic_weighted",
            "neutralize": True,
            "n_stocks": 30,
            "generated_at": "2026-04-06",
        }
        metrics = {"sharpe": 1.5, "total_return": 0.2, "max_drawdown": -0.1}
        selected = [{"name": "bp", "IC_mean": 0.02, "ICIR": 0.3}]

        with patch("quant_dojo.commands.generate.PROJECT_ROOT", tmp_path):
            path = _save_strategy(strategy_def, metrics, selected)

        assert path.exists()
        content = json.loads(path.read_text())
        assert content["strategy"]["name"] == "auto_gen"
        assert content["backtest_metrics"]["sharpe"] == 1.5

        # latest 也应存在
        latest = tmp_path / "strategies" / "generated" / "auto_gen_latest.json"
        assert latest.exists()


# ═══════════════════════════════════════════════════════════
# auto_gen loader / pipeline integration
# ═══════════════════════════════════════════════════════════

class TestAutoGenLoader:
    def _write_strategy(self, tmp_path, factors):
        """在 tmp_path 下写一个 auto_gen_latest.json"""
        gen_dir = tmp_path / "strategies" / "generated"
        gen_dir.mkdir(parents=True)
        latest = gen_dir / "auto_gen_latest.json"
        payload = {
            "strategy": {
                "name": "auto_gen",
                "factors": factors,
                "weighting": "ic_weighted",
                "neutralize": True,
                "n_stocks": 30,
                "generated_at": "2026-04-07T00:00:00",
            },
            "backtest_metrics": {"sharpe": 1.5},
            "factor_details": [],
        }
        latest.write_text(json.dumps(payload))
        return latest

    def test_load_definition(self, tmp_path):
        """正常加载策略定义"""
        from pipeline import auto_gen_loader

        latest = self._write_strategy(tmp_path, [
            {"name": "low_vol_20d", "direction": -1, "icir": 0.4, "ic_mean": -0.03},
            {"name": "bp", "direction": 1, "icir": 0.3, "ic_mean": 0.02},
        ])

        with patch.object(auto_gen_loader, "LATEST_FILE", latest):
            strategy = auto_gen_loader.load_auto_gen_definition()

        assert strategy["name"] == "auto_gen"
        assert len(strategy["factors"]) == 2
        assert strategy["factors"][0]["direction"] == -1

    def test_load_definition_missing(self, tmp_path):
        """缺少文件时抛 FileNotFoundError"""
        from pipeline import auto_gen_loader

        with patch.object(auto_gen_loader, "LATEST_FILE", tmp_path / "missing.json"):
            with pytest.raises(FileNotFoundError):
                auto_gen_loader.load_auto_gen_definition()

    def test_get_factor_names_empty(self, tmp_path):
        """缺少文件时返回空列表，不抛"""
        from pipeline import auto_gen_loader

        with patch.object(auto_gen_loader, "LATEST_FILE", tmp_path / "missing.json"):
            assert auto_gen_loader.get_auto_gen_factor_names() == []

    def test_get_factor_names_with_file(self, tmp_path):
        """有文件时返回名字列表"""
        from pipeline import auto_gen_loader

        latest = self._write_strategy(tmp_path, [
            {"name": "bp", "direction": 1},
            {"name": "low_vol_20d", "direction": -1},
        ])

        with patch.object(auto_gen_loader, "LATEST_FILE", latest):
            names = auto_gen_loader.get_auto_gen_factor_names()

        assert names == ["bp", "low_vol_20d"]

    def test_compute_auto_gen_factors_filters_unknown(self, tmp_path):
        """compute_auto_gen_factors 应跳过 build_fast_factors 不认识的因子"""
        from pipeline.auto_gen_loader import compute_auto_gen_factors

        dates = pd.date_range("2024-01-01", periods=120, freq="B")
        symbols = [f"00000{i}" for i in range(1, 21)]
        np.random.seed(7)
        price = pd.DataFrame(
            np.cumsum(np.random.randn(len(dates), len(symbols)) * 0.5, axis=0) + 100,
            index=dates, columns=symbols,
        )

        strategy_def = {
            "factors": [
                {"name": "low_vol_20d", "direction": -1},
                {"name": "team_coin", "direction": 1},
                {"name": "totally_made_up_factor", "direction": 1},
            ],
        }

        with patch("utils.local_data_loader.load_price_wide", return_value=pd.DataFrame()):
            with patch("utils.local_data_loader.load_factor_wide", return_value=pd.DataFrame()):
                result = compute_auto_gen_factors(
                    strategy_def, price, symbols, "2024-01-01", "2024-06-30",
                )

        assert "low_vol_20d" in result
        assert "team_coin" in result
        assert "totally_made_up_factor" not in result
        # 方向被保留
        assert result["low_vol_20d"][1] == -1


class TestActiveStrategyAutoGen:
    def test_auto_gen_in_valid_strategies(self):
        """auto_gen 应在合法策略集中"""
        from pipeline.active_strategy import VALID_STRATEGIES
        assert "auto_gen" in VALID_STRATEGIES

    def test_set_active_to_auto_gen(self, tmp_path):
        """可以激活 auto_gen 策略"""
        from pipeline import active_strategy

        state_file = tmp_path / "strategy_state.json"
        with patch.object(active_strategy, "STATE_FILE", state_file):
            result = active_strategy.set_active_strategy("auto_gen", reason="test")
            assert result["current"] == "auto_gen"
            assert active_strategy.get_active_strategy() == "auto_gen"


class TestDoctorCommand:
    def test_doctor_runs(self):
        """doctor 命令不应崩溃"""
        from quant_dojo.commands.doctor import run_doctor
        # doctor 会检查真实的依赖，不需要 mock
        run_doctor()
