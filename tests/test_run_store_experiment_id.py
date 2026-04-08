"""
test_run_store_experiment_id.py — Phase 7 RunRecord.experiment_id 往返

确认 RunRecord 新增的 experiment_id 字段在 save → list → get 之间能完整
持久化，默认值是 None（向后兼容老数据）。
"""
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from pipeline import run_store
from pipeline.run_store import RunRecord, get_run, list_runs, save_run


@pytest.fixture
def tmp_runs_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(run_store, "RUNS_DIR", tmp_path / "runs")
    return tmp_path / "runs"


def _make(run_id: str, experiment_id=None) -> RunRecord:
    return RunRecord(
        run_id=run_id,
        strategy_id="test_s",
        strategy_name="test",
        params={"n": 30},
        start_date="2023-01-01",
        end_date="2024-12-31",
        status="success",
        metrics={"sharpe": 1.2, "max_drawdown": -0.1},
        created_at="2026-04-08T10:00:00",
        experiment_id=experiment_id,
    )


class TestExperimentIdRoundTrip:
    def test_save_and_get(self, tmp_runs_dir):
        save_run(_make("run_abc_1", experiment_id="exp_20260408_abc123"))
        loaded = get_run("run_abc_1")
        assert loaded.experiment_id == "exp_20260408_abc123"

    def test_default_none(self, tmp_runs_dir):
        save_run(_make("run_abc_2"))
        loaded = get_run("run_abc_2")
        assert loaded.experiment_id is None

    def test_list_preserves_field(self, tmp_runs_dir):
        save_run(_make("run_l_1", experiment_id="exp_a"))
        save_run(_make("run_l_2", experiment_id=None))
        runs = list_runs()
        by_id = {r.run_id: r for r in runs}
        assert by_id["run_l_1"].experiment_id == "exp_a"
        assert by_id["run_l_2"].experiment_id is None

    def test_legacy_record_without_field(self, tmp_runs_dir):
        """老 JSON 里没有 experiment_id 字段，应正常加载为 None。"""
        import json
        tmp_runs_dir.mkdir(parents=True, exist_ok=True)
        legacy = {
            "run_id": "run_legacy_1",
            "strategy_id": "s",
            "strategy_name": "s",
            "params": {},
            "start_date": "2023-01-01",
            "end_date": "2024-12-31",
            "status": "success",
            "metrics": {"sharpe": 1.0},
            "created_at": "2026-01-01T00:00:00",
            "artifacts": {},
        }
        (tmp_runs_dir / "run_legacy_1.json").write_text(
            json.dumps(legacy), encoding="utf-8"
        )
        loaded = get_run("run_legacy_1")
        assert loaded.experiment_id is None
