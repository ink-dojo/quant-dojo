"""DSR #30 paper-trade kill switches (spec v2 §5).

从 NAV 曲线评估是否触发硬/软边界, 返回一份结构化报告.

硬边界:
  1. 30 日滚动 SR < 0.5         → HALVE (仓位减半)
  2. 30 日滚动 SR < 0 连续 10 日 → HALT (全减, 下线)
  3. 累计 DD > 20% (v1 是 25%)   → HALT
  4. 单月 MDD > 12%              → COOL_OFF (暂停新仓 7 日)

软边界:
  - 当日 turnover > 50% 总仓位
  - 单日持仓只数 < 3

Fast-validation:
  - T+3mo (63 trading days) 若 live SR < 0.5 → DO_NOT_UPGRADE
  - T+6mo (126 trading days) 若 live SR < 0.5 → HALT (重回研究)

用法:
    from live.event_kill_switch import evaluate
    report = evaluate(nav_series, start_date)
    if report.action == KillAction.HALT:
        ...
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from enum import Enum

import numpy as np
import pandas as pd


ROLLING_SR_WINDOW = 30  # trading days
SR_HALVE_THRESHOLD = 0.5
SR_HALT_RUN_DAYS = 10
CUM_DD_HALT = 0.20  # 20%
MONTHLY_MDD_COOL = 0.12  # 12%
COOL_OFF_DAYS = 7

TURNOVER_SOFT_WARN = 0.50  # 50% of NAV per day
MIN_POSITIONS_SOFT = 3

FAST_CHECK_3MO_DAYS = 63
FAST_CHECK_6MO_DAYS = 126
FAST_CHECK_SR_FLOOR = 0.5


class KillAction(str, Enum):
    OK = "ok"
    WARN = "warn"
    COOL_OFF = "cool_off"       # 暂停新仓 N 日
    HALVE = "halve"             # 仓位减半
    DO_NOT_UPGRADE = "do_not_upgrade"  # T+3mo 判定
    HALT = "halt"               # 全减, 下线


@dataclass
class KillReport:
    """Structured kill-switch evaluation for a given day."""
    as_of: str                          # YYYY-MM-DD
    action: KillAction                  # most-severe action triggered
    reasons: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    cool_off_days: int = 0              # if action == COOL_OFF, how many days
    rolling_sr_30d: float | None = None
    cum_drawdown: float | None = None
    monthly_mdd: float | None = None
    running_days: int = 0
    live_sharpe: float | None = None

    def is_halted(self) -> bool:
        return self.action == KillAction.HALT

    def should_trade_new(self) -> bool:
        """Is it OK to open new entries today?"""
        return self.action not in (KillAction.HALT, KillAction.COOL_OFF)

    def position_scale(self) -> float:
        """Scale to apply to new positions (1.0 normal, 0.5 halved, 0.0 halted)."""
        if self.action == KillAction.HALT:
            return 0.0
        if self.action == KillAction.HALVE:
            return 0.5
        return 1.0

    def to_dict(self) -> dict:
        return {
            "as_of": self.as_of,
            "action": self.action.value,
            "reasons": list(self.reasons),
            "warnings": list(self.warnings),
            "cool_off_days": self.cool_off_days,
            "rolling_sr_30d": self.rolling_sr_30d,
            "cum_drawdown": self.cum_drawdown,
            "monthly_mdd": self.monthly_mdd,
            "running_days": self.running_days,
            "live_sharpe": self.live_sharpe,
        }


def _sharpe(rets: pd.Series) -> float:
    if len(rets) < 2 or rets.std() == 0:
        return 0.0
    return float(rets.mean() / rets.std() * np.sqrt(252))


def _max_drawdown(nav: pd.Series) -> float:
    """Negative number, e.g. -0.15 = 15% drawdown."""
    if len(nav) == 0:
        return 0.0
    peak = nav.cummax()
    dd = (nav / peak - 1.0).min()
    return float(dd)


def evaluate(
    nav: pd.Series,
    as_of: str | date | pd.Timestamp | None = None,
    n_positions_today: int | None = None,
    turnover_today: float | None = None,
    external_triggers: list[dict] | None = None,
) -> KillReport:
    """
    Evaluate DSR #30 kill switches.

    Args:
        nav: NAV series indexed by trade date (datetime index), latest last.
        as_of: day to evaluate (default = nav.index[-1]).
        n_positions_today: current holdings count (for soft warn).
        turnover_today: today's turnover / NAV (for soft warn).
        external_triggers: 外部模块传入的额外触发器, 与 NAV-based 触发器合并取最严重.
            每个 trigger 是 {"action": "halve"|"halt"|"cool_off"|..., "reason": "..."}.
            典型来源: pipeline/live_vs_backtest.py::check_and_alert 在 z-score≥3σ 时
            返回的 to_kill_trigger() dict (Issue #41 tracking_divergence).

    Returns:
        KillReport with the most severe action across all triggers.
    """
    if len(nav) == 0:
        return KillReport(as_of="", action=KillAction.OK, reasons=["empty nav"])

    nav = nav.sort_index()
    if as_of is None:
        as_of_ts = pd.Timestamp(nav.index[-1]).normalize()
    else:
        as_of_ts = pd.Timestamp(as_of).normalize()

    nav_upto = nav.loc[:as_of_ts]
    if len(nav_upto) < 2:
        return KillReport(
            as_of=as_of_ts.strftime("%Y-%m-%d"),
            action=KillAction.OK,
            reasons=["insufficient history"],
            running_days=len(nav_upto),
        )

    # Compute daily returns up to as_of
    rets = nav_upto.pct_change().dropna()
    running_days = len(rets)

    # ----- 硬边界 ---------------------------------------------------------
    reasons: list[str] = []
    warnings: list[str] = []
    actions: list[KillAction] = []

    # 1) 累计 DD > 20%
    cum_dd = _max_drawdown(nav_upto)
    if cum_dd < -CUM_DD_HALT:
        reasons.append(f"累计回撤 {cum_dd:.2%} > {CUM_DD_HALT:.0%}")
        actions.append(KillAction.HALT)

    # 2) 30 日滚动 SR
    rolling_sr = None
    if len(rets) >= ROLLING_SR_WINDOW:
        last30 = rets.tail(ROLLING_SR_WINDOW)
        rolling_sr = _sharpe(last30)
        if rolling_sr < 0:
            # 连续 10 日负 SR 才 HALT; 否则 HALVE if < 0.5
            # 判定"连续 10 日" via rolling on daily 30d SR series
            if len(rets) >= ROLLING_SR_WINDOW + SR_HALT_RUN_DAYS:
                sr_series = rets.rolling(ROLLING_SR_WINDOW).apply(_sharpe, raw=False)
                last_run = sr_series.tail(SR_HALT_RUN_DAYS).dropna()
                if len(last_run) == SR_HALT_RUN_DAYS and (last_run < 0).all():
                    reasons.append(f"30 日滚动 SR 连续 {SR_HALT_RUN_DAYS} 日 < 0")
                    actions.append(KillAction.HALT)
                else:
                    reasons.append(f"30 日滚动 SR {rolling_sr:.2f} < 0.5")
                    actions.append(KillAction.HALVE)
            else:
                reasons.append(f"30 日滚动 SR {rolling_sr:.2f} < 0.5")
                actions.append(KillAction.HALVE)
        elif rolling_sr < SR_HALVE_THRESHOLD:
            reasons.append(f"30 日滚动 SR {rolling_sr:.2f} < {SR_HALVE_THRESHOLD}")
            actions.append(KillAction.HALVE)

    # 3) 单月 MDD > 12%
    monthly_mdd = None
    month_start = as_of_ts.replace(day=1)
    nav_month = nav_upto.loc[month_start:]
    if len(nav_month) >= 2:
        monthly_mdd = _max_drawdown(nav_month)
        if monthly_mdd < -MONTHLY_MDD_COOL:
            reasons.append(f"单月 MDD {monthly_mdd:.2%} > {MONTHLY_MDD_COOL:.0%}")
            actions.append(KillAction.COOL_OFF)

    # 4) Fast-validation (3 mo / 6 mo)
    live_sharpe = _sharpe(rets)
    if running_days >= FAST_CHECK_6MO_DAYS and live_sharpe < FAST_CHECK_SR_FLOOR:
        reasons.append(
            f"T+6mo live Sharpe {live_sharpe:.2f} < {FAST_CHECK_SR_FLOOR} (spec v2 §5 fast-check)")
        actions.append(KillAction.HALT)
    elif running_days >= FAST_CHECK_3MO_DAYS and live_sharpe < FAST_CHECK_SR_FLOOR:
        reasons.append(
            f"T+3mo live Sharpe {live_sharpe:.2f} < {FAST_CHECK_SR_FLOOR} (spec v2 §5 fast-check)")
        actions.append(KillAction.DO_NOT_UPGRADE)

    # ----- 软边界 ---------------------------------------------------------
    if turnover_today is not None and turnover_today > TURNOVER_SOFT_WARN:
        warnings.append(f"当日 turnover {turnover_today:.1%} > {TURNOVER_SOFT_WARN:.0%}")
    if n_positions_today is not None and n_positions_today < MIN_POSITIONS_SOFT:
        warnings.append(f"当日持仓只数 {n_positions_today} < {MIN_POSITIONS_SOFT}")

    # ----- 外部触发器 (e.g. tracking divergence from live_vs_backtest) -----
    if external_triggers:
        for trig in external_triggers:
            if not isinstance(trig, dict):
                continue
            action_raw = trig.get("action", "")
            reason = trig.get("reason", "external trigger (no reason)")
            try:
                ext_action = KillAction(str(action_raw).lower())
            except (ValueError, AttributeError):
                # 无效 action, 记 warning 但不当作触发
                warnings.append(f"[external] 无效 action '{action_raw}': {reason}")
                continue
            if ext_action == KillAction.OK:
                continue
            actions.append(ext_action)
            reasons.append(f"[external] {reason}")

    # Pick most severe action
    severity = {
        KillAction.OK: 0,
        KillAction.WARN: 1,
        KillAction.DO_NOT_UPGRADE: 2,
        KillAction.COOL_OFF: 3,
        KillAction.HALVE: 4,
        KillAction.HALT: 5,
    }
    if actions:
        action = max(actions, key=lambda a: severity[a])
    elif warnings:
        action = KillAction.WARN
    else:
        action = KillAction.OK

    cool_off_days = COOL_OFF_DAYS if action == KillAction.COOL_OFF else 0

    return KillReport(
        as_of=as_of_ts.strftime("%Y-%m-%d"),
        action=action,
        reasons=reasons,
        warnings=warnings,
        cool_off_days=cool_off_days,
        rolling_sr_30d=rolling_sr,
        cum_drawdown=cum_dd,
        monthly_mdd=monthly_mdd,
        running_days=running_days,
        live_sharpe=live_sharpe,
    )


if __name__ == "__main__":
    # Smoke test
    dates = pd.bdate_range("2026-01-02", periods=80)
    np.random.seed(0)
    # Simulate a losing streak
    rets = np.random.normal(0.0001, 0.015, 80)
    rets[50:70] = -0.005  # long losing streak
    nav = pd.Series(1_000_000 * (1 + pd.Series(rets, index=dates)).cumprod())

    report = evaluate(nav, n_positions_today=5, turnover_today=0.3)
    print("Kill switch report:")
    for k, v in report.to_dict().items():
        print(f"  {k}: {v}")
    print(f"  should_trade_new = {report.should_trade_new()}")
    print(f"  position_scale = {report.position_scale()}")
    print("  ✅ smoke test ok")
