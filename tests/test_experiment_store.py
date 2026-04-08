"""
test_experiment_store.py — Phase 7 实验记录存储单测

覆盖 pipeline/experiment_store.py：
  - ExperimentRecord CRUD
  - generate_experiment_id 唯一性
  - save/get/list/update/delete 完整生命周期
  - id 校验
  - status 校验
  - failed 自动补 error
  - JSON 序列化 NaN/numpy
"""
import json
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from pipeline import experiment_store
from pipeline.experiment_store import (
    ExperimentRecord,
    delete_experiment,
    generate_experiment_id,
    get_experiment,
    list_experiments,
    save_experiment,
    update_experiment,
)


@pytest.fixture
def tmp_store(tmp_path, monkeypatch):
    """每个测试独立的 EXPERIMENTS_DIR"""
    monkeypatch.setattr(experiment_store, "EXPERIMENTS_DIR", tmp_path / "experiments")
    return tmp_path / "experiments"


# ────────────────────────────────────────────────────────────
# generate_experiment_id
# ────────────────────────────────────────────────────────────

class TestGenerateId:
    def test_format(self):
        eid = generate_experiment_id("factor_decay_mom", {"drop_factor": "mom"})
        # exp_YYYYMMDD_XXXXXXXX
        assert eid.startswith("exp_")
        parts = eid.split("_")
        assert len(parts) == 3
        assert len(parts[1]) == 8  # date
        assert len(parts[2]) == 8  # hash

    def test_uniqueness(self):
        ids = {generate_experiment_id("q", {"x": i}) for i in range(20)}
        assert len(ids) == 20

    def test_none_params_ok(self):
        eid = generate_experiment_id("q")
        assert eid.startswith("exp_")


# ────────────────────────────────────────────────────────────
# save / get 基本功能
# ────────────────────────────────────────────────────────────

class TestSaveGet:
    def test_save_creates_file(self, tmp_store):
        rec = ExperimentRecord(
            experiment_id="exp_test_001",
            question_id="q1", question_type="factor_decay",
            question_text="q?", rationale="r", priority="high",
            command="backtest.run", params={"drop_factor": "mom"},
            status="proposed",
        )
        path = save_experiment(rec)
        assert path.exists()
        assert path.name == "exp_test_001.json"

    def test_save_fills_timestamps(self, tmp_store):
        rec = ExperimentRecord(
            experiment_id="exp_test_002", question_id="q",
            command="backtest.run", status="proposed",
        )
        save_experiment(rec)
        loaded = get_experiment("exp_test_002")
        assert loaded.created_at != ""
        assert loaded.updated_at != ""

    def test_save_preserves_created_at_on_resave(self, tmp_store):
        rec = ExperimentRecord(
            experiment_id="exp_test_003", question_id="q",
            command="backtest.run", status="proposed",
        )
        save_experiment(rec)
        first_created = get_experiment("exp_test_003").created_at
        # 重新保存
        rec2 = get_experiment("exp_test_003")
        rec2.status = "running"
        save_experiment(rec2)
        assert get_experiment("exp_test_003").created_at == first_created

    def test_get_missing_raises(self, tmp_store):
        with pytest.raises(FileNotFoundError):
            get_experiment("exp_not_exist")

    def test_roundtrip_preserves_fields(self, tmp_store):
        rec = ExperimentRecord(
            experiment_id="exp_rt_001",
            question_id="factor_decay_mom",
            question_type="factor_decay",
            question_text="因子 mom 是否降级？",
            rationale="ic=0.01",
            priority="high",
            command="backtest.run",
            params={"drop_factor": "mom", "n": 30},
            status="success",
            run_id="run_abc_123",
            result_summary={"sharpe_delta": 0.15, "max_dd_delta": -0.02},
            source={"factor": "mom", "status": "degraded"},
        )
        save_experiment(rec)
        loaded = get_experiment("exp_rt_001")
        assert loaded.question_type == "factor_decay"
        assert loaded.params["drop_factor"] == "mom"
        assert loaded.params["n"] == 30
        assert loaded.run_id == "run_abc_123"
        assert loaded.result_summary["sharpe_delta"] == 0.15
        assert loaded.source["factor"] == "mom"


# ────────────────────────────────────────────────────────────
# 校验
# ────────────────────────────────────────────────────────────

class TestValidation:
    def test_invalid_id_raises(self, tmp_store):
        rec = ExperimentRecord(
            experiment_id="../etc/passwd",
            command="backtest.run", status="proposed",
        )
        with pytest.raises(ValueError, match="非法 experiment_id"):
            save_experiment(rec)

    def test_empty_id_raises(self, tmp_store):
        rec = ExperimentRecord(experiment_id="", status="proposed")
        with pytest.raises(ValueError):
            save_experiment(rec)

    def test_invalid_status_raises(self, tmp_store):
        rec = ExperimentRecord(
            experiment_id="exp_bad_status",
            command="backtest.run",
            status="exploded",
        )
        with pytest.raises(ValueError, match="非法 status"):
            save_experiment(rec)

    def test_failed_auto_fills_error(self, tmp_store):
        rec = ExperimentRecord(
            experiment_id="exp_failed_001",
            command="backtest.run", status="failed",
        )
        save_experiment(rec)
        loaded = get_experiment("exp_failed_001")
        assert loaded.error is not None
        assert "未知" in loaded.error or loaded.error != ""


# ────────────────────────────────────────────────────────────
# list
# ────────────────────────────────────────────────────────────

class TestList:
    def test_empty_returns_empty(self, tmp_store):
        assert list_experiments() == []

    def test_returns_all_sorted_by_created_desc(self, tmp_store):
        # 依次创建三条，created_at 单调递增
        for i in range(3):
            rec = ExperimentRecord(
                experiment_id=f"exp_l_{i:03d}",
                question_id=f"q{i}",
                command="backtest.run",
                status="proposed",
            )
            save_experiment(rec)
        records = list_experiments()
        assert len(records) == 3
        # 倒序：最新创建的在最前
        assert records[0].experiment_id == "exp_l_002"
        assert records[-1].experiment_id == "exp_l_000"

    def test_filter_by_status(self, tmp_store):
        save_experiment(ExperimentRecord(
            experiment_id="exp_fs_01", command="backtest.run", status="proposed",
        ))
        save_experiment(ExperimentRecord(
            experiment_id="exp_fs_02", command="backtest.run", status="success",
            run_id="r1",
        ))
        save_experiment(ExperimentRecord(
            experiment_id="exp_fs_03", command="backtest.run", status="success",
            run_id="r2",
        ))
        assert len(list_experiments(status="success")) == 2
        assert len(list_experiments(status="proposed")) == 1

    def test_filter_by_question_type(self, tmp_store):
        save_experiment(ExperimentRecord(
            experiment_id="exp_qt_01", question_type="factor_decay",
            command="backtest.run", status="proposed",
        ))
        save_experiment(ExperimentRecord(
            experiment_id="exp_qt_02", question_type="drawdown_spike",
            command="backtest.run", status="proposed",
        ))
        assert len(list_experiments(question_type="factor_decay")) == 1
        assert len(list_experiments(question_type="drawdown_spike")) == 1

    def test_limit(self, tmp_store):
        for i in range(5):
            save_experiment(ExperimentRecord(
                experiment_id=f"exp_lim_{i}",
                command="backtest.run", status="proposed",
            ))
        assert len(list_experiments(limit=3)) == 3

    def test_skips_corrupted_json(self, tmp_store):
        save_experiment(ExperimentRecord(
            experiment_id="exp_good", command="backtest.run", status="proposed",
        ))
        # 手动写一个坏文件
        bad = tmp_store / "exp_bad.json"
        bad.write_text("{not valid json", encoding="utf-8")
        records = list_experiments()
        assert len(records) == 1
        assert records[0].experiment_id == "exp_good"


# ────────────────────────────────────────────────────────────
# update
# ────────────────────────────────────────────────────────────

class TestUpdate:
    def test_update_transitions_status(self, tmp_store):
        save_experiment(ExperimentRecord(
            experiment_id="exp_u_01", command="backtest.run", status="proposed",
        ))
        update_experiment("exp_u_01", status="running")
        assert get_experiment("exp_u_01").status == "running"

    def test_update_attaches_run_id_and_summary(self, tmp_store):
        save_experiment(ExperimentRecord(
            experiment_id="exp_u_02", command="backtest.run", status="running",
        ))
        update_experiment(
            "exp_u_02",
            status="success",
            run_id="run_xyz",
            result_summary={"sharpe": 1.2, "max_dd": -0.1},
        )
        loaded = get_experiment("exp_u_02")
        assert loaded.status == "success"
        assert loaded.run_id == "run_xyz"
        assert loaded.result_summary["sharpe"] == 1.2

    def test_update_unknown_field_raises(self, tmp_store):
        save_experiment(ExperimentRecord(
            experiment_id="exp_u_03", command="backtest.run", status="proposed",
        ))
        with pytest.raises(ValueError, match="没有字段"):
            update_experiment("exp_u_03", not_a_field=1)

    def test_update_bumps_updated_at(self, tmp_store):
        save_experiment(ExperimentRecord(
            experiment_id="exp_u_04", command="backtest.run", status="proposed",
        ))
        first = get_experiment("exp_u_04").updated_at
        import time
        time.sleep(0.01)
        update_experiment("exp_u_04", status="running")
        second = get_experiment("exp_u_04").updated_at
        assert second >= first


# ────────────────────────────────────────────────────────────
# delete
# ────────────────────────────────────────────────────────────

class TestDelete:
    def test_delete_existing(self, tmp_store):
        save_experiment(ExperimentRecord(
            experiment_id="exp_d_01", command="backtest.run", status="proposed",
        ))
        assert delete_experiment("exp_d_01") is True
        with pytest.raises(FileNotFoundError):
            get_experiment("exp_d_01")

    def test_delete_missing_returns_false(self, tmp_store):
        assert delete_experiment("exp_no_such") is False

    def test_delete_rejects_bad_id(self, tmp_store):
        with pytest.raises(ValueError):
            delete_experiment("../../etc/passwd")


# ────────────────────────────────────────────────────────────
# JSON 序列化保底
# ────────────────────────────────────────────────────────────

class TestJSONSerialization:
    def test_nan_becomes_none(self, tmp_store):
        rec = ExperimentRecord(
            experiment_id="exp_nan_01",
            command="backtest.run", status="success",
            run_id="x",
            result_summary={"sharpe": float("nan"), "ok": 1.2},
        )
        save_experiment(rec)
        raw = json.loads((tmp_store / "exp_nan_01.json").read_text())
        assert raw["result_summary"]["sharpe"] is None
        assert raw["result_summary"]["ok"] == 1.2
