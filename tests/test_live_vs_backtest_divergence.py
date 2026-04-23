"""Tests for pipeline/live_vs_backtest.py daily divergence (Issue #41)."""
from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Optional
from unittest.mock import patch

import numpy as np
import pandas as pd
import pytest

from pipeline.live_vs_backtest import (
    DivergenceAlert,
    check_and_alert,
    compute_divergence_zscore,
    daily_pnl_divergence,
    load_divergence_state,
)


# ══════════════════════════════════════════════════════════════
# compute_divergence_zscore — 纯函数, 无文件依赖
# ══════════════════════════════════════════════════════════════

def _dates(n: int) -> list[str]:
    return [d.strftime("%Y-%m-%d") for d in pd.bdate_range("2026-01-02", periods=n)]


def test_zscore_ok_when_within_one_sigma():
    """所有 daily_delta 在 1σ 内, alert_level=ok."""
    rng = np.random.default_rng(42)
    delta = list(rng.normal(0, 0.001, 50))
    delta[-1] = 0.0005  # 最新一日, 0.5σ
    alert = compute_divergence_zscore(delta, _dates(50))
    assert alert.alert_level == "ok"
    assert alert.zscore < 2.0


def test_zscore_warn_at_2sigma():
    """最新一日是 2.5σ → warn."""
    rng = np.random.default_rng(0)
    history = list(rng.normal(0, 0.001, 60))  # σ ≈ 0.001, 不是常数
    delta = history + [0.0025]  # 2.5σ from mean(0)
    alert = compute_divergence_zscore(delta, _dates(len(delta)))
    assert alert.alert_level == "warn", \
        f"期望 warn, 实际 {alert.alert_level} (z={alert.zscore:.2f})"
    assert 2.0 <= alert.zscore < 3.0


def test_zscore_critical_at_3sigma():
    """最新一日是 3.5σ → critical + 触发 kill."""
    rng = np.random.default_rng(0)
    history = list(rng.normal(0, 0.001, 60))
    delta = history + [0.0035]  # 3.5σ
    alert = compute_divergence_zscore(delta, _dates(len(delta)))
    assert alert.alert_level == "critical", \
        f"期望 critical, 实际 {alert.alert_level} (z={alert.zscore:.2f})"
    assert alert.zscore >= 3.0
    trigger = alert.to_kill_trigger()
    assert trigger is not None
    assert trigger["action"] == "halve"
    assert "tracking divergence" in trigger["reason"]


def test_zscore_insufficient_data_too_few_points():
    """样本不足 min_observations + 1 → insufficient_data."""
    delta = [0.001, 0.002, -0.001]  # 3 points
    alert = compute_divergence_zscore(delta, _dates(3), min_observations=10)
    assert alert.alert_level == "insufficient_data"
    assert alert.fallback_reason is not None


def test_zscore_insufficient_data_zero_history_std():
    """历史全平 (σ=0) → insufficient (防除零)."""
    delta = [0.0] * 30 + [0.005]
    alert = compute_divergence_zscore(delta, _dates(31))
    assert alert.alert_level == "insufficient_data"
    assert "σ ≈ 0" in alert.fallback_reason


def test_zscore_dates_mismatch_raises():
    with pytest.raises(ValueError):
        compute_divergence_zscore([0.001] * 5, _dates(3))


def test_zscore_custom_thresholds():
    """自定义阈值: warn=1.5, critical=2.5."""
    rng = np.random.default_rng(0)
    history = list(rng.normal(0, 0.001, 60))
    delta = history + [0.002]  # ≈ 2.0σ
    alert = compute_divergence_zscore(
        delta, _dates(len(delta)), warn_zscore=1.5, critical_zscore=2.5
    )
    assert alert.alert_level == "warn", \
        f"期望 warn (在 [1.5, 2.5)), 实际 {alert.alert_level} (z={alert.zscore:.2f})"


def test_zscore_lookback_excludes_latest():
    """lookback_days 用历史窗口, 不含最新一日 (避免污染 σ)."""
    # 历史小波动 + 最新大波动. 不含最新的 σ ≈ 0.001
    delta = [0.001, -0.001] * 15 + [0.005]  # 31 points
    alert = compute_divergence_zscore(delta, _dates(31), lookback_days=30)
    # σ_hist ≈ 0.001, latest = 0.005 → z ≈ 5
    assert alert.zscore > 4.0
    assert alert.alert_level == "critical"


def test_zscore_uses_recent_window_not_full_history():
    """最近 lookback_days 内 σ 大, 早期 σ 小. 应用最近的."""
    delta = [0.0001] * 100 + [0.005] * 30 + [0.005]  # 早 σ 极小, 晚 σ 大
    alert = compute_divergence_zscore(delta, _dates(131), lookback_days=30)
    # 最近 30 日 σ ≈ 0 (因为都是 0.005), 但应该被 0 检查截获 → insufficient
    # 实际由于 [0.005]*31, σ=0, 触发 insufficient
    assert alert.alert_level == "insufficient_data"


# ══════════════════════════════════════════════════════════════
# DivergenceAlert 数据类
# ══════════════════════════════════════════════════════════════

def test_alert_to_kill_trigger_only_critical():
    ok_alert = DivergenceAlert(0.5, "ok", 0.001, 0.001, 30, "2026-04-23")
    warn_alert = DivergenceAlert(2.5, "warn", 0.0025, 0.001, 30, "2026-04-23")
    crit_alert = DivergenceAlert(4.0, "critical", 0.004, 0.001, 30, "2026-04-23")

    assert ok_alert.to_kill_trigger() is None
    assert warn_alert.to_kill_trigger() is None
    trig = crit_alert.to_kill_trigger()
    assert trig is not None and trig["action"] == "halve"


def test_alert_is_helpers():
    crit = DivergenceAlert(4.0, "critical", 0.004, 0.001, 30, "2026-04-23")
    warn = DivergenceAlert(2.5, "warn", 0.0025, 0.001, 30, "2026-04-23")
    ok = DivergenceAlert(0.5, "ok", 0.0005, 0.001, 30, "2026-04-23")

    assert crit.is_critical() and not crit.is_warn()
    assert warn.is_warn() and not warn.is_critical()
    assert not ok.is_warn() and not ok.is_critical()


def test_alert_immutable():
    """frozen dataclass."""
    alert = DivergenceAlert(0.5, "ok", 0.0005, 0.001, 30, "2026-04-23")
    with pytest.raises((AttributeError, Exception)):
        alert.zscore = 999.0  # type: ignore[misc]


# ══════════════════════════════════════════════════════════════
# daily_pnl_divergence — 文件 IO 集成
# ══════════════════════════════════════════════════════════════

def _write_synthetic_live_nav(path: Path, n_days: int = 50, seed: int = 42) -> None:
    """生成合成 live nav.csv."""
    rng = np.random.default_rng(seed)
    rets = rng.normal(0.0003, 0.01, n_days)
    nav_vals = np.cumprod(1 + rets) * 1_000_000
    dates = pd.bdate_range("2026-01-02", periods=n_days)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["date", "nav"])
        for d, v in zip(dates, nav_vals):
            writer.writerow([d.strftime("%Y-%m-%d"), f"{v:.4f}"])


def _write_synthetic_backtest_run(
    base_dir: Path,
    n_days: int = 50,
    seed: int = 100,
    inject_outlier_at: Optional[int] = None,
    outlier_size: float = 0.0,
) -> Path:
    """
    生成合成 backtest run JSON + equity csv. 返回 run JSON 路径.

    Args:
        inject_outlier_at: 在第 N 个 return 上加 outlier_size. None = 不注入.
            支持负索引 (-1 = 最后一日).
    """
    base_dir.mkdir(parents=True, exist_ok=True)
    rng = np.random.default_rng(seed)
    rets = rng.normal(0.0003, 0.01, n_days)
    if inject_outlier_at is not None:
        rets[inject_outlier_at] += outlier_size
    cum = np.cumsum(rets)
    dates = pd.bdate_range("2026-01-02", periods=n_days)
    eq_path = base_dir / "equity.csv"
    with open(eq_path, "w", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["date", "cumulative_return"])
        for d, c in zip(dates, cum):
            writer.writerow([d.strftime("%Y-%m-%d"), f"{c:.6f}"])
    run_path = base_dir / "run.json"
    run = {
        "run_id": "test_run_001",
        "strategy_id": "synthetic",
        "artifacts": {"equity_csv": str(eq_path)},
    }
    with open(run_path, "w", encoding="utf-8") as f:
        json.dump(run, f)
    return run_path


def test_daily_pnl_divergence_normal_returns_ok(tmp_path):
    """live ≈ backtest, 偏差全是噪声 → ok."""
    live_nav = tmp_path / "live" / "nav.csv"
    _write_synthetic_live_nav(live_nav, n_days=50, seed=42)
    bt_run = _write_synthetic_backtest_run(tmp_path / "bt", n_days=50, seed=42)

    alert = daily_pnl_divergence(live_nav, bt_run)
    # 同 seed → live 与 bt 高度相关, daily_delta 接近 0
    assert alert.alert_level in ("ok", "insufficient_data")


def test_daily_pnl_divergence_outlier_triggers_critical(tmp_path):
    """live 有 outlier 但 backtest 没有 → 最新一日大偏差 → critical."""
    live_nav = tmp_path / "live" / "nav.csv"
    _write_synthetic_live_nav(live_nav, n_days=50, seed=42)
    # backtest 同 seed 但**最新一日**注入大 outlier (反向)
    bt_run = _write_synthetic_backtest_run(
        tmp_path / "bt", n_days=50, seed=42,
        inject_outlier_at=-1, outlier_size=-0.05,  # backtest 最后一日掉 5%
    )
    alert = daily_pnl_divergence(live_nav, bt_run)
    assert alert.alert_level == "critical", \
        f"期望 critical, 实际 {alert.alert_level} (z={alert.zscore:.2f})"


def test_daily_pnl_divergence_missing_files_returns_insufficient(tmp_path):
    alert = daily_pnl_divergence(
        tmp_path / "nonexistent.csv",
        tmp_path / "nonexistent.json",
    )
    assert alert.alert_level == "insufficient_data"
    assert alert.fallback_reason is not None


# ══════════════════════════════════════════════════════════════
# check_and_alert — state file + alert 触发
# ══════════════════════════════════════════════════════════════

def test_check_and_alert_writes_state_file(tmp_path):
    live_nav = tmp_path / "live" / "nav.csv"
    _write_synthetic_live_nav(live_nav, n_days=50, seed=42)
    bt_run = _write_synthetic_backtest_run(tmp_path / "bt", n_days=50, seed=42)
    state_file = tmp_path / "state" / "tracking_divergence_state.json"

    alert = check_and_alert(
        live_nav, bt_run,
        state_file=state_file,
        notify=False,  # 不发实际 alert
    )
    assert state_file.exists()
    state = json.loads(state_file.read_text())
    assert state["alert_level"] == alert.alert_level
    assert state["zscore"] == alert.zscore
    assert "updated_at" in state


def test_check_and_alert_no_state_file_when_none(tmp_path):
    live_nav = tmp_path / "live" / "nav.csv"
    _write_synthetic_live_nav(live_nav, n_days=50, seed=42)
    bt_run = _write_synthetic_backtest_run(tmp_path / "bt", n_days=50, seed=42)

    check_and_alert(live_nav, bt_run, state_file=None, notify=False)
    # 没异常即可


def test_check_and_alert_critical_calls_send_alert(tmp_path):
    live_nav = tmp_path / "live" / "nav.csv"
    _write_synthetic_live_nav(live_nav, n_days=50, seed=42)
    bt_run = _write_synthetic_backtest_run(
        tmp_path / "bt", n_days=50, seed=42,
        inject_outlier_at=-1, outlier_size=-0.05,
    )

    with patch("pipeline.alert_notifier.send_alert") as mock_send:
        alert = check_and_alert(
            live_nav, bt_run,
            state_file=tmp_path / "state.json",
            notify=True,
        )
        if alert.is_critical():
            mock_send.assert_called_once()
            kwargs = mock_send.call_args.kwargs
            assert "CRITICAL" in kwargs["title"]


def test_load_divergence_state_returns_none_when_missing(tmp_path):
    assert load_divergence_state(tmp_path / "nonexistent.json") is None


def test_load_divergence_state_roundtrip(tmp_path):
    live_nav = tmp_path / "live" / "nav.csv"
    _write_synthetic_live_nav(live_nav, n_days=50, seed=42)
    bt_run = _write_synthetic_backtest_run(tmp_path / "bt", n_days=50, seed=42)
    state_file = tmp_path / "state.json"

    written_alert = check_and_alert(live_nav, bt_run, state_file=state_file, notify=False)
    state = load_divergence_state(state_file)
    assert state is not None
    assert state["alert_level"] == written_alert.alert_level


# ══════════════════════════════════════════════════════════════
# event_kill_switch external_triggers 集成
# ══════════════════════════════════════════════════════════════

def test_external_trigger_halve_escalates_ok_to_halve():
    """无 NAV 触发, 但外部传 halve → 最终是 halve."""
    from live.event_kill_switch import KillAction, evaluate

    # 平稳 NAV, 单独 evaluate 应是 ok
    nav = pd.Series(
        [1_000_000 * (1 + 0.0005) ** i for i in range(40)],
        index=pd.bdate_range("2026-01-02", periods=40),
    )
    base = evaluate(nav)
    assert base.action == KillAction.OK

    # 加 external halve trigger
    with_ext = evaluate(
        nav,
        external_triggers=[
            {"action": "halve", "reason": "tracking divergence z=3.5σ"}
        ],
    )
    assert with_ext.action == KillAction.HALVE
    assert any("[external]" in r and "tracking" in r for r in with_ext.reasons)


def test_external_trigger_halt_overrides_halve():
    """NAV 触发 HALVE, 外部传 HALT → 取最严重的 HALT."""
    from live.event_kill_switch import KillAction, evaluate

    nav = pd.Series(
        [1_000_000 * (1 + 0.0005) ** i for i in range(40)],
        index=pd.bdate_range("2026-01-02", periods=40),
    )
    with_ext = evaluate(
        nav,
        external_triggers=[
            {"action": "halt", "reason": "manual override"},
            {"action": "halve", "reason": "tracking divergence"},
        ],
    )
    assert with_ext.action == KillAction.HALT


def test_external_trigger_invalid_action_recorded_as_warning():
    from live.event_kill_switch import KillAction, evaluate

    nav = pd.Series(
        [1_000_000 * (1 + 0.0005) ** i for i in range(40)],
        index=pd.bdate_range("2026-01-02", periods=40),
    )
    report = evaluate(
        nav,
        external_triggers=[{"action": "BOGUS", "reason": "test"}],
    )
    assert report.action == KillAction.WARN
    assert any("无效 action" in w for w in report.warnings)


def test_external_trigger_ok_action_ignored():
    """action='ok' 不应成为触发器."""
    from live.event_kill_switch import KillAction, evaluate

    nav = pd.Series(
        [1_000_000 * (1 + 0.0005) ** i for i in range(40)],
        index=pd.bdate_range("2026-01-02", periods=40),
    )
    report = evaluate(
        nav,
        external_triggers=[{"action": "ok", "reason": "no issue"}],
    )
    assert report.action == KillAction.OK
    assert not any("[external]" in r for r in report.reasons)


def test_external_trigger_none_unchanged():
    from live.event_kill_switch import KillAction, evaluate

    nav = pd.Series(
        [1_000_000 * (1 + 0.0005) ** i for i in range(40)],
        index=pd.bdate_range("2026-01-02", periods=40),
    )
    report = evaluate(nav, external_triggers=None)
    assert report.action == KillAction.OK


def test_divergence_alert_to_kill_trigger_integrates_with_evaluate():
    """端到端: critical alert → kill trigger → evaluate 触发 HALVE."""
    from live.event_kill_switch import KillAction, evaluate

    crit = DivergenceAlert(4.0, "critical", 0.004, 0.001, 30, "2026-04-23")
    trigger = crit.to_kill_trigger()
    assert trigger is not None

    nav = pd.Series(
        [1_000_000 * (1 + 0.0005) ** i for i in range(40)],
        index=pd.bdate_range("2026-01-02", periods=40),
    )
    report = evaluate(nav, external_triggers=[trigger])
    assert report.action == KillAction.HALVE
