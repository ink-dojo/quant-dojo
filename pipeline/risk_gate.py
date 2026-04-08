"""
pipeline/risk_gate.py — Phase 7 实验结果风险门

一个纯函数，拿回测 metrics 和一组阈值配置去问：
    "这条结果能不能被当作候选策略推到下一步评审？"

设计原则：
  - **纯函数**：不读盘不写盘，input metrics → output verdict
  - **规则硬编码在 DEFAULT_RULES**，单测可传自定义 rules 覆盖
  - **不拒绝、不执行**：只返回 {"passed": bool, "failures": [...], "warnings": [...]}，
    是否真的拦截由上游（experiment_summarizer / CLI / 人工评审）决定
  - 所有阈值用 **"最低要求"** 语义：指标 < 阈值视为失败
  - max_drawdown 比较时考虑它是负数（-0.20 差于 -0.15），比较绝对值

默认门槛来自 CLAUDE.md「策略评审门槛」：
  - annualized_return > 15%
  - sharpe > 0.8
  - abs(max_drawdown) < 30%
  - n_trading_days > 3 年 ≈ 700
  - win_rate > 45%
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


# ══════════════════════════════════════════════════════════════
# 默认规则 —— 单测/调用方可整份替换
# ══════════════════════════════════════════════════════════════

DEFAULT_RULES: dict = {
    # key: (最低值, 是否必填). 缺字段时 required=True 会计入 failure
    "sharpe": {"min": 0.8, "required": True, "label": "夏普比率"},
    "annualized_return": {"min": 0.15, "required": True, "label": "年化收益"},
    "total_return": {"min": 0.0, "required": False, "label": "累计收益"},
    # max_drawdown 是负数：-0.30 是门槛，|dd| > 0.30 → 失败
    "max_drawdown": {"max_abs": 0.30, "required": True, "label": "最大回撤"},
    "n_trading_days": {"min": 700, "required": False, "label": "回测天数"},
    # 警告级：不影响 passed，只放进 warnings
    "win_rate": {"min": 0.45, "required": False, "level": "warning", "label": "胜率"},
}


@dataclass
class GateResult:
    """
    风险门判定结果。

    字段：
        passed     — 有 failures 就是 False
        failures   — 硬失败条目列表：[{key, label, expected, actual, reason}]
        warnings   — 软警告条目列表（未达门槛但未被标为必填 + level=warning）
        metrics    — 原始 metrics 副本，便于上游记账
    """
    passed: bool
    failures: list[dict]
    warnings: list[dict]
    metrics: dict

    def to_dict(self) -> dict:
        return {
            "passed": self.passed,
            "failures": self.failures,
            "warnings": self.warnings,
            "metrics": self.metrics,
        }


def evaluate(
    metrics: Optional[dict],
    rules: Optional[dict] = None,
) -> GateResult:
    """
    检查回测 metrics 是否通过风险门。

    参数：
        metrics — 一般来自 RunRecord.metrics 或 ExperimentRecord.result_summary
        rules   — 阈值配置，默认 DEFAULT_RULES。单测可传自定义

    返回：GateResult
    """
    metrics = dict(metrics or {})
    rules = rules or DEFAULT_RULES
    failures: list[dict] = []
    warnings: list[dict] = []

    for key, cfg in rules.items():
        label = cfg.get("label", key)
        required = cfg.get("required", False)
        level = cfg.get("level", "failure")
        if key not in metrics or metrics[key] is None:
            if required:
                failures.append({
                    "key": key,
                    "label": label,
                    "expected": cfg,
                    "actual": None,
                    "reason": f"缺失指标 {key}",
                })
            continue

        try:
            actual = float(metrics[key])
        except (TypeError, ValueError):
            failures.append({
                "key": key,
                "label": label,
                "expected": cfg,
                "actual": metrics[key],
                "reason": f"{key} 不是数值",
            })
            continue

        ok, reason = _check_rule(key, actual, cfg)
        if ok:
            continue
        entry = {
            "key": key,
            "label": label,
            "expected": cfg,
            "actual": actual,
            "reason": reason,
        }
        if level == "warning":
            warnings.append(entry)
        else:
            failures.append(entry)

    return GateResult(
        passed=not failures,
        failures=failures,
        warnings=warnings,
        metrics=metrics,
    )


def _check_rule(key: str, actual: float, cfg: dict) -> tuple[bool, str]:
    """
    单条规则检查。返回 (是否通过, 失败原因)。
    """
    if "min" in cfg and actual < cfg["min"]:
        return False, f"{key}={actual:.4f} < 下限 {cfg['min']}"
    if "max" in cfg and actual > cfg["max"]:
        return False, f"{key}={actual:.4f} > 上限 {cfg['max']}"
    if "max_abs" in cfg and abs(actual) > cfg["max_abs"]:
        return False, f"|{key}|={abs(actual):.4f} > 绝对值上限 {cfg['max_abs']}"
    return True, ""


def render_gate_markdown(result: GateResult) -> str:
    """把 GateResult 渲染成 markdown 一块。"""
    lines: list[str] = ["## 风险门检查", ""]
    icon = "✅" if result.passed else "❌"
    lines.append(f"- **结论**: {icon} {'通过' if result.passed else '未通过'}")
    if result.failures:
        lines.append(f"- **硬失败 ({len(result.failures)})**:")
        for f in result.failures:
            lines.append(f"  - {f['label']}：{f['reason']}")
    if result.warnings:
        lines.append(f"- **警告 ({len(result.warnings)})**:")
        for w in result.warnings:
            lines.append(f"  - {w['label']}：{w['reason']}")
    if not result.failures and not result.warnings:
        lines.append("- 所有门槛均通过")
    return "\n".join(lines)


if __name__ == "__main__":
    passing = {
        "sharpe": 1.2,
        "annualized_return": 0.18,
        "total_return": 0.6,
        "max_drawdown": -0.22,
        "n_trading_days": 750,
        "win_rate": 0.48,
    }
    failing = {
        "sharpe": 0.5,
        "annualized_return": 0.05,
        "max_drawdown": -0.45,
        "n_trading_days": 200,
        "win_rate": 0.35,
    }
    print(render_gate_markdown(evaluate(passing)))
    print()
    print(render_gate_markdown(evaluate(failing)))
    print("✅ risk_gate import ok")
