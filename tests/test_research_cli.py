"""
test_research_cli.py — Phase 7 research CLI 子命令冒烟测试

直接调用 pipeline.cli.cmd_research_* 函数，绕过 argparse 但保留分发逻辑。
用 tmp_path 隔离 experiment_store，避免污染真实 live/experiments/。
"""
import argparse
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from pipeline import cli as cli_mod
from pipeline import experiment_store
from pipeline.experiment_store import ExperimentRecord, save_experiment


@pytest.fixture
def tmp_store(tmp_path, monkeypatch):
    monkeypatch.setattr(experiment_store, "EXPERIMENTS_DIR", tmp_path / "experiments")
    return tmp_path / "experiments"


@pytest.fixture
def fake_system_state(monkeypatch):
    """给 _collect_system_state 返回固定的 degraded 因子和空告警。"""
    def fake():
        return (
            {"mom_20": {"status": "degraded", "rolling_ic": 0.01, "t_stat": 1.2, "n_obs": 80}},
            [],
            {},
        )
    monkeypatch.setattr(cli_mod, "_collect_system_state", fake)
    return fake


# ──────────────────────────────────────────────
# research propose
# ──────────────────────────────────────────────

class TestProposeCmd:
    def test_prints_markdown_plan(self, tmp_store, fake_system_state, capsys):
        args = argparse.Namespace()
        cli_mod.cmd_research_propose(args)
        out = capsys.readouterr().out
        assert "# 研究计划" in out
        assert "mom_20" in out

    def test_empty_state_prints_no_action(self, tmp_store, monkeypatch, capsys):
        monkeypatch.setattr(cli_mod, "_collect_system_state", lambda: ({}, [], {}))
        cli_mod.cmd_research_propose(argparse.Namespace())
        out = capsys.readouterr().out
        assert "no_action" in out


# ──────────────────────────────────────────────
# research run
# ──────────────────────────────────────────────

class TestRunCmd:
    def test_run_without_approved_only_proposes(self, tmp_store, fake_system_state, capsys):
        args = argparse.Namespace(approved=False, max_runs=None)
        cli_mod.cmd_research_run(args)
        out = capsys.readouterr().out
        assert "未 --approved" in out
        # 应该落 1 条 proposed
        from pipeline.experiment_store import list_experiments
        records = list_experiments()
        assert len(records) == 1
        assert records[0].status == "proposed"

    def test_run_with_approved_calls_executor(
        self, tmp_store, fake_system_state, capsys, monkeypatch,
    ):
        # 注入 fake executor 到 control_surface.execute，避免真跑回测
        calls = []
        def fake_execute(command, approved=False, **kwargs):
            calls.append(command)
            return {"status": "success", "data": {"run_id": "r_fake", "metrics": {"sharpe": 1.3}}}
        monkeypatch.setattr("pipeline.control_surface.execute", fake_execute)

        args = argparse.Namespace(approved=True, max_runs=None)
        cli_mod.cmd_research_run(args)
        out = capsys.readouterr().out
        assert "success" in out
        assert "r_fake" in out
        assert calls == ["backtest.run"]


# ──────────────────────────────────────────────
# research list
# ──────────────────────────────────────────────

class TestListCmd:
    def test_empty(self, tmp_store, capsys):
        args = argparse.Namespace(status=None, type=None, limit=20)
        cli_mod.cmd_research_list(args)
        out = capsys.readouterr().out
        assert "无 experiment" in out

    def test_prints_records(self, tmp_store, capsys):
        save_experiment(ExperimentRecord(
            experiment_id="exp_cli_1", question_id="q",
            question_type="factor_decay", command="backtest.run",
            status="success", run_id="r1", priority="high",
        ))
        args = argparse.Namespace(status=None, type=None, limit=20)
        cli_mod.cmd_research_list(args)
        out = capsys.readouterr().out
        assert "exp_cli_1" in out
        assert "factor_decay" in out
        assert "r1" in out

    def test_status_filter(self, tmp_store, capsys):
        save_experiment(ExperimentRecord(
            experiment_id="exp_fs_1", command="backtest.run", status="success", run_id="r"))
        save_experiment(ExperimentRecord(
            experiment_id="exp_fs_2", command="backtest.run", status="failed", error="x"))
        args = argparse.Namespace(status="failed", type=None, limit=20)
        cli_mod.cmd_research_list(args)
        out = capsys.readouterr().out
        assert "exp_fs_2" in out
        assert "exp_fs_1" not in out


# ──────────────────────────────────────────────
# research summarize
# ──────────────────────────────────────────────

class TestSummarizeCmd:
    def test_empty(self, tmp_store, capsys):
        args = argparse.Namespace(status="success", limit=20, baseline_run=None)
        cli_mod.cmd_research_summarize(args)
        out = capsys.readouterr().out
        assert "# 实验结果总结" in out
        assert "共 0 条" in out

    def test_with_record(self, tmp_store, capsys):
        save_experiment(ExperimentRecord(
            experiment_id="exp_s_1", question_type="factor_decay",
            question_text="?",
            command="backtest.run", status="success", run_id="r",
            result_summary={"sharpe": 1.5, "max_drawdown": -0.08, "total_return": 0.2},
        ))
        args = argparse.Namespace(status="success", limit=20, baseline_run=None)
        cli_mod.cmd_research_summarize(args)
        out = capsys.readouterr().out
        assert "exp_s_1" in out
        assert "sharpe" in out


# ──────────────────────────────────────────────
# argparse 入口冒烟
# ──────────────────────────────────────────────

class TestArgparseWiring:
    def test_parser_accepts_research_subcommands(self):
        """确认 research 子命令的 argparse 定义不挂。"""
        import subprocess
        result = subprocess.run(
            [sys.executable, "-m", "pipeline.cli", "research", "--help"],
            capture_output=True, text=True,
            cwd=str(PROJECT_ROOT),
            timeout=30,
        )
        assert result.returncode == 0
        assert "propose" in result.stdout
        assert "run" in result.stdout
        assert "list" in result.stdout
        assert "summarize" in result.stdout
