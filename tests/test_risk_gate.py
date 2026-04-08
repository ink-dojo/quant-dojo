"""
test_risk_gate.py — Phase 7 risk_gate 单测

覆盖 pipeline/risk_gate.py：
  - DEFAULT_RULES 的 pass/fail/warning 分支
  - 缺失指标（required 与否）
  - 非数值 metric 被标为 failure
  - max_drawdown 的绝对值比较
  - 自定义 rules 替换
  - render_gate_markdown 输出
"""
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from pipeline.risk_gate import DEFAULT_RULES, evaluate, render_gate_markdown


def _passing_metrics() -> dict:
    return {
        "sharpe": 1.2,
        "annualized_return": 0.18,
        "total_return": 0.6,
        "max_drawdown": -0.22,
        "n_trading_days": 750,
        "win_rate": 0.48,
    }


# ──────────────────────────────────────────────
# 基础 pass / fail
# ──────────────────────────────────────────────

class TestEvaluateBasic:
    def test_full_passing_metrics(self):
        r = evaluate(_passing_metrics())
        assert r.passed is True
        assert r.failures == []
        assert r.warnings == []

    def test_all_failing_metrics(self):
        metrics = {
            "sharpe": 0.3,
            "annualized_return": 0.05,
            "max_drawdown": -0.45,
            "n_trading_days": 100,
            "win_rate": 0.3,
        }
        r = evaluate(metrics)
        assert r.passed is False
        failed_keys = {f["key"] for f in r.failures}
        # sharpe / annualized_return / max_drawdown 都是硬失败
        assert "sharpe" in failed_keys
        assert "annualized_return" in failed_keys
        assert "max_drawdown" in failed_keys
        # win_rate 是 warning 级，不应在 failures
        assert "win_rate" not in failed_keys
        warn_keys = {w["key"] for w in r.warnings}
        assert "win_rate" in warn_keys


# ──────────────────────────────────────────────
# 缺失指标
# ──────────────────────────────────────────────

class TestMissingMetrics:
    def test_missing_required_is_failure(self):
        metrics = _passing_metrics()
        del metrics["sharpe"]
        r = evaluate(metrics)
        assert r.passed is False
        assert any(f["key"] == "sharpe" and "缺失" in f["reason"] for f in r.failures)

    def test_missing_optional_is_ignored(self):
        metrics = _passing_metrics()
        del metrics["total_return"]
        r = evaluate(metrics)
        # total_return 非必填 → 不影响
        assert r.passed is True

    def test_none_value_treated_as_missing(self):
        metrics = _passing_metrics()
        metrics["sharpe"] = None
        r = evaluate(metrics)
        assert any(f["key"] == "sharpe" for f in r.failures)

    def test_empty_metrics_required_all_fail(self):
        r = evaluate({})
        assert r.passed is False
        required_keys = {k for k, c in DEFAULT_RULES.items() if c.get("required")}
        failed = {f["key"] for f in r.failures}
        assert required_keys.issubset(failed)


# ──────────────────────────────────────────────
# 特殊类型 / 边界
# ──────────────────────────────────────────────

class TestTypeEdgeCases:
    def test_nonnumeric_is_failure(self):
        r = evaluate({**_passing_metrics(), "sharpe": "n/a"})
        assert r.passed is False
        assert any(f["key"] == "sharpe" and "不是数值" in f["reason"] for f in r.failures)

    def test_max_drawdown_exact_boundary_passes(self):
        # |−0.30| == 0.30 恰好等于门槛 → 允许（> 才挂）
        r = evaluate({**_passing_metrics(), "max_drawdown": -0.30})
        assert r.passed is True

    def test_max_drawdown_just_over_boundary_fails(self):
        r = evaluate({**_passing_metrics(), "max_drawdown": -0.3001})
        assert r.passed is False
        assert any(f["key"] == "max_drawdown" for f in r.failures)

    def test_max_drawdown_positive_also_bounded(self):
        """正数 max_drawdown（不该发生但容错）同样按绝对值算。"""
        r = evaluate({**_passing_metrics(), "max_drawdown": 0.40})
        assert r.passed is False

    def test_none_metrics_all_required_fail(self):
        r = evaluate(None)
        assert r.passed is False
        assert len(r.failures) >= 1


# ──────────────────────────────────────────────
# 自定义规则
# ──────────────────────────────────────────────

class TestCustomRules:
    def test_custom_rules_replace_default(self):
        rules = {
            "sharpe": {"min": 2.0, "required": True, "label": "夏普"},
        }
        # passing_metrics 里 sharpe=1.2 不达 2.0 → fail
        r = evaluate(_passing_metrics(), rules=rules)
        assert r.passed is False
        assert r.failures[0]["key"] == "sharpe"

    def test_custom_warning_level(self):
        rules = {
            "sharpe": {"min": 2.0, "required": False, "level": "warning", "label": "夏普"},
        }
        r = evaluate(_passing_metrics(), rules=rules)
        assert r.passed is True
        assert len(r.warnings) == 1

    def test_max_rule(self):
        rules = {"volatility": {"max": 0.3, "required": True, "label": "波动率"}}
        r = evaluate({"volatility": 0.5}, rules=rules)
        assert r.passed is False
        assert "上限" in r.failures[0]["reason"]


# ──────────────────────────────────────────────
# render_gate_markdown
# ──────────────────────────────────────────────

class TestRenderMarkdown:
    def test_passing_markdown(self):
        md = render_gate_markdown(evaluate(_passing_metrics()))
        assert "通过" in md
        assert "✅" in md

    def test_failing_markdown_lists_all_failures(self):
        metrics = {"sharpe": 0.1, "annualized_return": 0.01, "max_drawdown": -0.5}
        md = render_gate_markdown(evaluate(metrics))
        assert "未通过" in md
        assert "❌" in md
        assert "夏普比率" in md or "sharpe" in md
        assert "最大回撤" in md or "max_drawdown" in md

    def test_warning_only_still_passes(self):
        metrics = _passing_metrics()
        metrics["win_rate"] = 0.30  # 低于 warning 门槛
        result = evaluate(metrics)
        assert result.passed is True
        assert len(result.warnings) == 1
        md = render_gate_markdown(result)
        assert "警告" in md
        assert "胜率" in md or "win_rate" in md

    def test_to_dict_roundtrip(self):
        r = evaluate(_passing_metrics())
        d = r.to_dict()
        assert d["passed"] is True
        assert "metrics" in d
        assert "failures" in d
        assert "warnings" in d
