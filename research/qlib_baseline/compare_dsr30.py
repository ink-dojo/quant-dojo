"""
Phase C: qlib Alpha158 baseline vs DSR #30 BB 主板 rescaled 对照

对齐重叠期 2018-01-02 ~ 2020-09-25 (~660 交易日, 2.5y),
按相同 cost basis 与 benchmark 算指标, 输出对照 Markdown 表给 jialong 决策。

跑法 (在主项目 venv, 不需要 qlib_baseline venv):
    python research/qlib_baseline/compare_dsr30.py
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[2]
QLIB_RUN_DIR = PROJECT_ROOT / "research" / "qlib_baseline" / "runs"
DSR_DIR = PROJECT_ROOT / "research" / "event_driven"

OVERLAP_START = pd.Timestamp("2018-01-02")
OVERLAP_END = pd.Timestamp("2020-09-25")

ANNUALIZATION = 252


def latest_qlib_run() -> Path:
    runs = sorted(QLIB_RUN_DIR.glob("*/meta.json"))
    if not runs:
        raise FileNotFoundError("no qlib baseline run; 先跑 run_baseline.py")
    return runs[-1].parent


def perf(daily_ret: pd.Series, label: str) -> dict:
    """同 CLAUDE.md 评审门槛的指标: 年化, Sharpe, MaxDD, 胜率, 累计."""
    r = daily_ret.dropna()
    n = len(r)
    if n < 30:
        return {"label": label, "n_days": n, "error": "数据不足"}
    ann_ret = (1 + r).prod() ** (ANNUALIZATION / n) - 1
    ann_vol = r.std() * np.sqrt(ANNUALIZATION)
    sharpe = (r.mean() * ANNUALIZATION) / (r.std() * np.sqrt(ANNUALIZATION)) if r.std() > 0 else float("nan")
    cum = (1 + r).cumprod()
    max_dd = (cum / cum.cummax() - 1).min()
    win_rate = (r > 0).mean()
    return {
        "label": label,
        "n_days": int(n),
        "ann_return": float(ann_ret),
        "ann_vol": float(ann_vol),
        "sharpe": float(sharpe),
        "max_dd": float(max_dd),
        "win_rate": float(win_rate),
        "cum_return": float(cum.iloc[-1] - 1),
    }


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
    # excess vs CSI300: 用 qlib bench 同期 (DSR #30 没自带 bench, 借 qlib 的)
    bench_aligned = qlib_bench.reindex(dsr_bb_overlap.index)
    # DSR 索引 ⊂ qlib 索引应该成立; 触发 NaN 说明 DSR 含 qlib 没有的日期, 是数据 bug
    assert bench_aligned.notna().all(), (
        "DSR 索引含 qlib bench 没有的日期 — 数据对齐有 bug 不能继续"
    )
    dsr_bb_excess = dsr_bb_overlap - bench_aligned

    # ensemble (recal 三足 + BB+PV) 也对照, 让 jialong 看 BB 单脚 vs ensemble
    dsr_ens = pd.read_parquet(DSR_DIR / "dsr30_mainboard_recal_ensemble_oos.parquet")
    dsr_ens.index = pd.to_datetime(dsr_ens.index)
    dsr_ens_overlap = dsr_ens.loc[OVERLAP_START:OVERLAP_END]["net_return"]
    dsr_ens_excess = dsr_ens_overlap - bench_aligned

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
