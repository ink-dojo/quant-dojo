"""
Phase C: qlib Alpha158 baseline vs DSR #30 BB 主板 rescaled 对照

对齐重叠期 2018-01-02 ~ 2020-09-25 (~660 交易日, 2.5y),
按相同 cost basis 与 benchmark 算指标, 输出对照 Markdown 表给 jialong 决策。

跑法 (在主项目 venv, 不需要 qlib_baseline venv):
    python research/qlib_baseline/compare_dsr30.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))

from utils.metrics import (  # noqa: E402
    annualized_return,
    annualized_volatility,
    max_drawdown,
    sharpe_ratio,
    win_rate as win_rate_metric,
)

QLIB_RUN_DIR = PROJECT_ROOT / "research" / "qlib_baseline" / "runs"
DSR_DIR = PROJECT_ROOT / "research" / "event_driven"

OVERLAP_START = pd.Timestamp("2018-01-02")
OVERLAP_END = pd.Timestamp("2020-09-25")


def latest_qlib_run() -> Path:
    runs = sorted(QLIB_RUN_DIR.glob("*/meta.json"))
    if not runs:
        raise FileNotFoundError("no qlib baseline run; 先跑 run_baseline.py")
    return runs[-1].parent


def perf(daily_ret: pd.Series, label: str) -> dict:
    """同 CLAUDE.md 评审门槛的指标。复用 utils.metrics 保证 sharpe / ddof / rf 与项目一致 (rf=0.02)。"""
    r = daily_ret.dropna()
    n = len(r)
    if n < 30:
        return {"label": label, "n_days": n, "error": "数据不足"}
    cum = (1 + r).cumprod()
    return {
        "label": label,
        "n_days": int(n),
        "ann_return": float(annualized_return(r)),
        "ann_vol": float(annualized_volatility(r)),
        "sharpe": float(sharpe_ratio(r)),
        "max_dd": float(max_drawdown(r)),
        "win_rate": float(win_rate_metric(r)),
        "cum_return": float(cum.iloc[-1] - 1),
    }


def _excess_with_assert(strat: pd.Series, bench: pd.Series, name: str) -> pd.Series:
    """对齐到策略索引算 excess; 索引不全在 bench 中 -> raise (静默 NaN 是 bug)。"""
    aligned = bench.reindex(strat.index)
    assert aligned.notna().all(), (
        f"{name} 索引含 qlib bench 没有的日期 — 数据对齐有 bug 不能继续"
    )
    return strat - aligned


def main():
    qlib_dir = latest_qlib_run()
    print(f"[compare] qlib run: {qlib_dir.name}")

    # qlib report: report_normal["return"] 是 portfolio 总收益 (含成本扣)
    # report_normal["cost"] 单独追踪. report_normal["bench"] 是 CSI300 收益率。
    # 算 net excess: (return - cost) - bench  = with-cost excess
    qlib_report = pd.read_parquet(qlib_dir / "test_report.parquet")
    qlib_report.index = pd.to_datetime(qlib_report.index)
    qlib_overlap = qlib_report.loc[OVERLAP_START:OVERLAP_END]
    print(f"[qlib]    overlap window {qlib_overlap.index.min().date()} ~ "
          f"{qlib_overlap.index.max().date()} ({len(qlib_overlap)} days)")

    qlib_net = qlib_overlap["return"] - qlib_overlap["cost"]
    qlib_excess = qlib_net - qlib_overlap["bench"]
    qlib_bench = qlib_overlap["bench"]
    # qlib bench 来自 SH000300 日度连续; DSR 是事件驱动可能跳过非事件日, 不应跳过
    # 全部交易日 -> 后面 reindex 到 DSR 索引时不应 fillna 触发 (DSR 索引 ⊂ qlib 索引)
    assert qlib_bench.notna().all(), "qlib bench 含 NaN, 重叠期切片有问题"

    # DSR #30 BB 主板 rescaled (issue body 指定): dsr30_mainboard_bb_oos
    # net_return 已含成本扣 (按 dsr30_mainboard_recal.py:142 命名约定)
    dsr_bb = pd.read_parquet(DSR_DIR / "dsr30_mainboard_bb_oos.parquet")
    dsr_bb.index = pd.to_datetime(dsr_bb.index)
    dsr_bb_overlap = dsr_bb.loc[OVERLAP_START:OVERLAP_END]["net_return"]
    print(f"[dsr_bb]  overlap window {dsr_bb_overlap.index.min().date()} ~ "
          f"{dsr_bb_overlap.index.max().date()} ({len(dsr_bb_overlap)} days)")
    # excess vs CSI300: DSR #30 原 backtest 没自带 bench, 借 qlib SH000300 同期算
    dsr_bb_excess = _excess_with_assert(dsr_bb_overlap, qlib_bench, "DSR BB")

    # ensemble (recal 三足 + BB+PV) 也对照, 让 jialong 看 BB 单脚 vs ensemble
    dsr_ens = pd.read_parquet(DSR_DIR / "dsr30_mainboard_recal_ensemble_oos.parquet")
    dsr_ens.index = pd.to_datetime(dsr_ens.index)
    dsr_ens_overlap = dsr_ens.loc[OVERLAP_START:OVERLAP_END]["net_return"]
    dsr_ens_excess = _excess_with_assert(dsr_ens_overlap, qlib_bench, "DSR ensemble")

    rows = [
        perf(qlib_net, "qlib Alpha158-LightGBM (net, 含成本)"),
        perf(qlib_excess, "qlib Alpha158-LightGBM (excess vs CSI300)"),
        perf(qlib_bench, "CSI300 benchmark"),
        perf(dsr_bb_overlap, "DSR #30 BB 主板 rescaled (net)"),
        perf(dsr_bb_excess, "DSR #30 BB 主板 (excess vs CSI300)"),
        perf(dsr_ens_overlap, "DSR #30 ensemble (BB+PV+recal, net)"),
        perf(dsr_ens_excess, "DSR #30 ensemble (excess vs CSI300)"),
    ]
    table = pd.DataFrame(rows).set_index("label")
    print()
    print(table.round(4).to_string())

    out = qlib_dir / "compare_dsr30.json"
    out.write_text(json.dumps(rows, indent=2, ensure_ascii=False, default=str))
    print(f"\n[compare] saved → {out}")
    return table


if __name__ == "__main__":
    main()
