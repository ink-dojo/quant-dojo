"""
test_experiment_summarizer.py — Phase 7 experiment_summarizer 单测

覆盖 pipeline/experiment_summarizer.py：
  - compare_to_baseline 的 success/failed/skipped/proposed 分支
  - verdict 判定（better/worse/neutral/n/a）
  - summarize_experiments 汇总统计
  - render_summary_markdown 输出
"""
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from pipeline.experiment_store import ExperimentRecord
from pipeline.experiment_summarizer import (
    compare_to_baseline,
    render_summary_markdown,
    summarize_experiments,
)


def _record(**overrides) -> ExperimentRecord:
    defaults = dict(
        experiment_id="exp_x", question_id="q", question_type="factor_decay",
        question_text="q?", priority="medium", command="backtest.run",
        status="success", run_id="r1",
        result_summary={"sharpe": 1.4, "max_drawdown": -0.10, "total_return": 0.3},
    )
    defaults.update(overrides)
    return ExperimentRecord(**defaults)


BASELINE = {"sharpe": 1.2, "max_drawdown": -0.15, "total_return": 0.2}


# ────────────────────────────────────────────
# compare_to_baseline
# ────────────────────────────────────────────

class TestCompareToBaseline:
    def test_success_better(self):
        # sharpe +0.2 && max_dd 改善 +0.05 → better
        row = compare_to_baseline(_record(), baseline=BASELINE)
        assert row["status"] == "success"
        assert row["verdict"] == "better"
        assert row["delta"]["sharpe"] == pytest_approx(0.2)
        assert row["delta"]["max_drawdown"] == pytest_approx(0.05)

    def test_success_worse(self):
        row = compare_to_baseline(
            _record(result_summary={"sharpe": 1.0, "max_drawdown": -0.20, "total_return": 0.1}),
            baseline=BASELINE,
        )
        # sharpe -0.2 且 max_dd 恶化 -0.05 → worse
        assert row["verdict"] == "worse"

    def test_success_neutral(self):
        # 两个都低于门槛
        row = compare_to_baseline(
            _record(result_summary={"sharpe": 1.22, "max_drawdown": -0.14, "total_return": 0.2}),
            baseline=BASELINE,
        )
        assert row["verdict"] == "neutral"

    def test_success_without_baseline(self):
        row = compare_to_baseline(_record(), baseline=None)
        assert row["verdict"] == "n/a"
        assert "baseline" in row["note"]

    def test_failed(self):
        r = _record(status="failed", error="bt exploded", result_summary=None)
        row = compare_to_baseline(r, baseline=BASELINE)
        assert row["verdict"] == "n/a"
        assert "失败" in row["note"]
        assert "bt exploded" in row["note"]

    def test_skipped(self):
        r = _record(status="skipped", error="no_action", result_summary=None)
        row = compare_to_baseline(r, baseline=BASELINE)
        assert row["verdict"] == "n/a"
        assert "跳过" in row["note"]

    def test_proposed_is_n_a(self):
        r = _record(status="proposed", run_id=None, result_summary=None)
        row = compare_to_baseline(r, baseline=BASELINE)
        assert row["verdict"] == "n/a"
        assert "未执行" in row["note"]

    def test_missing_metric_key_ignored(self):
        r = _record(result_summary={"sharpe": 1.35})  # 没 max_drawdown
        row = compare_to_baseline(r, baseline=BASELINE)
        assert "sharpe" in row["delta"]
        assert "max_drawdown" not in row["delta"]

    def test_nonnumeric_metric_tolerated(self):
        r = _record(result_summary={"sharpe": "not a number", "max_drawdown": -0.10})
        row = compare_to_baseline(r, baseline=BASELINE)
        assert "sharpe" not in row["delta"]
        assert "max_drawdown" in row["delta"]


# ────────────────────────────────────────────
# summarize_experiments
# ────────────────────────────────────────────

class TestSummarize:
    def test_counts(self):
        recs = [
            _record(experiment_id="e1", status="success",
                    result_summary={"sharpe": 1.5, "max_drawdown": -0.08, "total_return": 0.32}),  # better
            _record(experiment_id="e2", status="success",
                    result_summary={"sharpe": 0.8, "max_drawdown": -0.22, "total_return": 0.05}),  # worse
            _record(experiment_id="e3", status="skipped", error="x", result_summary=None),
            _record(experiment_id="e4", status="failed", error="boom", result_summary=None),
        ]
        s = summarize_experiments(recs, baseline=BASELINE)
        assert s["total"] == 4
        assert s["by_status"]["success"] == 2
        assert s["by_status"]["skipped"] == 1
        assert s["by_status"]["failed"] == 1
        assert s["improved"] == 1
        assert s["worsened"] == 1
        assert len(s["rows"]) == 4

    def test_empty(self):
        s = summarize_experiments([])
        assert s["total"] == 0
        assert s["rows"] == []
        assert s["improved"] == 0


# ────────────────────────────────────────────
# render_summary_markdown
# ────────────────────────────────────────────

class TestRenderMarkdown:
    def test_empty_renders(self):
        md = render_summary_markdown(summarize_experiments([]))
        assert "# 实验结果总结" in md
        assert "共 0 条" in md
        assert "_无实验记录_" in md

    def test_success_renders_delta(self):
        md = render_summary_markdown(summarize_experiments([_record()], baseline=BASELINE))
        assert "✅" in md
        assert "delta" in md
        assert "sharpe" in md

    def test_failed_shows_note(self):
        r = _record(status="failed", error="engine error", result_summary=None)
        md = render_summary_markdown(summarize_experiments([r], baseline=BASELINE))
        assert "engine error" in md
        assert "❔" in md or "note" in md

    def test_skipped_shows_note(self):
        r = _record(status="skipped", error="no_action", result_summary=None)
        md = render_summary_markdown(summarize_experiments([r], baseline=BASELINE))
        assert "no_action" in md

    def test_by_status_counts_rendered(self):
        recs = [
            _record(experiment_id="e1", status="success"),
            _record(experiment_id="e2", status="failed", error="x", result_summary=None),
        ]
        md = render_summary_markdown(summarize_experiments(recs, baseline=BASELINE))
        assert "success=1" in md
        assert "failed=1" in md


# ────────────────────────────────────────────
# 小工具
# ────────────────────────────────────────────

def pytest_approx(val, tol=1e-6):
    """极简 approx，避免引入 pytest.approx 依赖。"""
    class _A:
        def __eq__(self, other):
            return abs(float(other) - float(val)) < tol
        def __repr__(self):
            return f"approx({val})"
    return _A()
