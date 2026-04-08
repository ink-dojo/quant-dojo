"""
test_experiment_runner.py — Phase 7 experiment_runner 单测

覆盖 pipeline/experiment_runner.py：
  - propose_experiment 落 proposed 记录
  - run_experiment 的 success / failed / skipped 分支
  - fake executor 注入，不触碰真实 backtest
  - run_experiments 批处理 + max_runs 预算
"""
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from pipeline import experiment_store, experiment_runner
from pipeline.experiment_runner import (
    propose_experiment,
    run_experiment,
    run_experiments,
)
from pipeline.experiment_store import get_experiment
from pipeline.research_planner import ResearchQuestion, plan_research


@pytest.fixture
def tmp_store(tmp_path, monkeypatch):
    monkeypatch.setattr(experiment_store, "EXPERIMENTS_DIR", tmp_path / "experiments")
    return tmp_path / "experiments"


# ──────────────────────────────────────────────
# Fake executor helpers
# ──────────────────────────────────────────────

def make_success_executor(run_id="fake_run_1", metrics=None):
    metrics = metrics or {"sharpe": 1.1, "max_drawdown": -0.08, "total_return": 0.25}
    calls = []
    def executor(command, approved=False, **kwargs):
        calls.append({"command": command, "approved": approved, "kwargs": kwargs})
        return {"status": "success", "data": {"run_id": run_id, "metrics": metrics}}
    return executor, calls


def make_error_executor(msg="boom"):
    def executor(command, approved=False, **kwargs):
        return {"status": "error", "error": msg}
    return executor


def make_raising_executor():
    def executor(command, approved=False, **kwargs):
        raise RuntimeError("explosion")
    return executor


# ──────────────────────────────────────────────
# propose_experiment
# ──────────────────────────────────────────────

class TestPropose:
    def test_basic_fields(self, tmp_store):
        q = ResearchQuestion(
            id="factor_decay_mom",
            type="factor_decay",
            priority="high",
            question="mom 是否失效？",
            rationale="r",
            proposed_experiment={
                "command": "backtest.run",
                "params": {"drop_factor": "mom"},
            },
            source={"factor": "mom"},
        )
        rec = propose_experiment(q)
        assert rec.status == "proposed"
        assert rec.question_id == "factor_decay_mom"
        assert rec.command == "backtest.run"
        # strategy_id / start / end 注入到 params 外层
        assert rec.params["strategy_id"] == "multi_factor"
        assert "start" in rec.params and "end" in rec.params
        # 原始 question 参数在内层 params
        assert rec.params["params"]["drop_factor"] == "mom"
        # source 被保留
        assert rec.source["factor"] == "mom"

    def test_custom_window_and_strategy(self, tmp_store):
        q = ResearchQuestion(
            id="q1", type="factor_decay", priority="medium",
            question="q?", rationale="r",
            proposed_experiment={"command": "backtest.run", "params": {}},
        )
        rec = propose_experiment(
            q, strategy_id="dual_ma", start="2021-01-01", end="2023-12-31"
        )
        assert rec.params["strategy_id"] == "dual_ma"
        assert rec.params["start"] == "2021-01-01"
        assert rec.params["end"] == "2023-12-31"

    def test_no_experiment_field_defaults_to_empty(self, tmp_store):
        q = ResearchQuestion(
            id="q_no_exp", type="factor_insufficient", priority="low",
            question="q?", rationale="r", proposed_experiment=None,
        )
        rec = propose_experiment(q)
        assert rec.command == ""
        assert rec.params["params"] == {}


# ──────────────────────────────────────────────
# run_experiment
# ──────────────────────────────────────────────

class TestRunSingle:
    def _make_record(self, tmp_store, qtype="factor_decay", command="backtest.run"):
        q = ResearchQuestion(
            id=f"q_{qtype}",
            type=qtype,
            priority="medium",
            question="q?", rationale="r",
            proposed_experiment={"command": command, "params": {"drop_factor": "x"}},
        )
        return propose_experiment(q)

    def test_success(self, tmp_store):
        rec = self._make_record(tmp_store)
        executor, calls = make_success_executor(run_id="r_ok", metrics={
            "sharpe": 1.5, "total_return": 0.3, "max_drawdown": -0.12,
            "junk_field": "ignored",
        })
        updated = run_experiment(rec, executor=executor)
        assert updated.status == "success"
        assert updated.run_id == "r_ok"
        assert updated.result_summary["sharpe"] == 1.5
        assert updated.result_summary["max_drawdown"] == -0.12
        # summary 不应该带 junk_field
        assert "junk_field" not in updated.result_summary
        # executor 被正确调用一次且 approved=True
        assert len(calls) == 1
        assert calls[0]["command"] == "backtest.run"
        assert calls[0]["approved"] is True

    def test_executor_returns_error(self, tmp_store):
        rec = self._make_record(tmp_store)
        updated = run_experiment(rec, executor=make_error_executor("bt-failed"))
        assert updated.status == "failed"
        assert "bt-failed" in updated.error

    def test_executor_raises(self, tmp_store):
        rec = self._make_record(tmp_store)
        updated = run_experiment(rec, executor=make_raising_executor())
        assert updated.status == "failed"
        assert "explosion" in updated.error

    def test_skip_no_action(self, tmp_store):
        rec = self._make_record(tmp_store, qtype="no_action", command="")
        executor, calls = make_success_executor()
        updated = run_experiment(rec, executor=executor)
        assert updated.status == "skipped"
        # 跳过的不该触发 executor
        assert calls == []

    def test_skip_factor_insufficient(self, tmp_store):
        rec = self._make_record(tmp_store, qtype="factor_insufficient", command="")
        updated = run_experiment(rec, executor=make_success_executor()[0])
        assert updated.status == "skipped"

    def test_skip_unknown_command(self, tmp_store):
        rec = self._make_record(tmp_store, qtype="factor_decay", command="signal.run")
        executor, calls = make_success_executor()
        updated = run_experiment(rec, executor=executor)
        assert updated.status == "skipped"
        assert "signal.run" in updated.error
        assert calls == []

    def test_running_state_is_persisted_before_execute(self, tmp_store):
        rec = self._make_record(tmp_store)
        seen_status = {}
        def peeking_executor(command, approved=False, **kwargs):
            seen_status["before"] = get_experiment(rec.experiment_id).status
            return {"status": "success", "data": {"run_id": "r", "metrics": {}}}
        run_experiment(rec, executor=peeking_executor)
        assert seen_status["before"] == "running"

    def test_non_dict_result_is_failed(self, tmp_store):
        rec = self._make_record(tmp_store)
        def weird(command, approved=False, **kwargs):
            return "not a dict"
        updated = run_experiment(rec, executor=weird)
        assert updated.status == "failed"
        assert "非 dict" in updated.error


# ──────────────────────────────────────────────
# run_experiments 批处理
# ──────────────────────────────────────────────

class TestRunBatch:
    def test_runs_all_by_default(self, tmp_store):
        health = {
            "bp": {"status": "dead", "rolling_ic": 0.0, "t_stat": 0.1, "n_obs": 100},
            "mom": {"status": "degraded", "rolling_ic": 0.01, "t_stat": 1.2, "n_obs": 80},
        }
        qs = plan_research(factor_health=health)
        executor, calls = make_success_executor()
        results = run_experiments(qs, executor=executor)
        assert len(results) == 2
        assert all(r.status == "success" for r in results)
        assert len(calls) == 2

    def test_max_runs_budget(self, tmp_store):
        health = {
            "bp": {"status": "dead", "rolling_ic": 0.0, "t_stat": 0.1, "n_obs": 100},
            "mom": {"status": "degraded", "rolling_ic": 0.01, "t_stat": 1.2, "n_obs": 80},
            "vol": {"status": "dead", "rolling_ic": 0.0, "t_stat": 0.1, "n_obs": 100},
        }
        qs = plan_research(factor_health=health)
        assert len(qs) == 3
        executor, calls = make_success_executor()
        results = run_experiments(qs, max_runs=2, executor=executor)
        assert len(results) == 3
        statuses = [r.status for r in results]
        assert statuses.count("success") == 2
        assert statuses.count("proposed") == 1
        assert len(calls) == 2

    def test_no_action_batch_all_skipped(self, tmp_store):
        qs = plan_research()  # 空输入 → 只有 no_action
        executor, calls = make_success_executor()
        results = run_experiments(qs, executor=executor)
        assert len(results) == 1
        assert results[0].status == "skipped"
        assert calls == []

    def test_experiment_id_is_passed_to_executor(self, tmp_store):
        """experiment_runner 应把 experiment_id 注入到 executor kwargs 里，
        这样 control_surface 的 _backtest_run 才能 tag RunRecord。"""
        q = ResearchQuestion(
            id="q_pass", type="factor_decay", priority="high",
            question="?", rationale="r",
            proposed_experiment={"command": "backtest.run", "params": {"drop_factor": "x"}},
        )
        seen_kwargs = {}
        def capture(command, approved=False, **kwargs):
            seen_kwargs.update(kwargs)
            return {"status": "success", "data": {"run_id": "r1", "metrics": {}}}
        from pipeline.experiment_runner import propose_experiment
        rec = propose_experiment(q)
        run_experiment(rec, executor=capture)
        assert seen_kwargs.get("experiment_id") == rec.experiment_id

    def test_mixed_with_insufficient(self, tmp_store):
        health = {
            "bp": {"status": "dead", "rolling_ic": 0.0, "t_stat": 0.1, "n_obs": 100},
            "tov": {"status": "insufficient_data", "n_obs": 5},
        }
        qs = plan_research(factor_health=health)
        executor, calls = make_success_executor()
        results = run_experiments(qs, executor=executor)
        # dead → success，insufficient → skipped
        by_type = {r.question_type: r for r in results}
        assert by_type["factor_decay"].status == "success"
        assert by_type["factor_insufficient"].status == "skipped"
        assert len(calls) == 1  # 只有 dead 那条触发 executor
