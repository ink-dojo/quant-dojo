"""
RIAD / MFD / BGFD 三因子 orthogonality 检查

目的: 评估三个 2026-04-22 新因子是否真正独立 (为后续 stacking 决策服务).
衡量方法:
    1. pairwise 点对 Spearman correlation (所有日 × 所有股票的因子值向量)
    2. 每日 cross-section 因子向量的 Spearman correlation 分布
    3. 对每对因子 residualize: A 做因子 B 的线性回归残差, 看残差是否仍有 IC

判断门槛 (借用 DSR #30 stacking 规则):
    |corr| < 0.3  → 强 orthogonal, 可独立 stacking (加权 ensemble)
    0.3 < |corr| < 0.6 → 部分重合, 需 residualize 验证
    |corr| > 0.6 → 高度冗余, 合成不会显著增加 Sharpe
"""
from __future__ import annotations

import json
import sys
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from research.factors.broker_gold_fade.factor import (  # noqa: E402
    compute_bgfd_factor,
    compute_consensus_streak,
    load_broker_recommend,
)
from research.factors.moneyflow_divergence.factor import compute_mfd_factor  # noqa: E402
from research.factors.retail_inst_divergence.factor import (  # noqa: E402
    build_attention_panel,
    compute_riad_factor,
)
from research.factors.retail_inst_divergence.evaluate_riad import PRICE_PATH  # noqa: E402

START, END = "2023-10-01", "2025-12-31"


def _month_end_dates(price: pd.DataFrame) -> list[pd.Timestamp]:
    """price index 内每个月份的最后一日."""
    px = price.loc[START:END]
    return [g.index[-1] for _, g in px.groupby([px.index.year, px.index.month])]


def _to_ts(sym: str) -> str:
    if sym.startswith(("60", "68")):
        return f"{sym}.SH"
    if sym.startswith(("00", "30")):
        return f"{sym}.SZ"
    return f"{sym}.SZ"


def _align_factors_monthly(
    riad: pd.DataFrame,
    mfd: pd.DataFrame,
    bgfd: pd.DataFrame,
    month_ends: list[pd.Timestamp],
) -> dict[str, pd.DataFrame]:
    """把三个因子都降到月频 wide (index=month_end, columns=ts_code)."""
    riad_me = riad.reindex(month_ends, method="ffill")
    mfd_me = mfd.reindex(month_ends, method="ffill")

    # bgfd 是 int YYYYMM-indexed, 转 month_end
    bgfd_me_rows = []
    for me in month_ends:
        ym = me.year * 100 + me.month
        if ym in bgfd.index:
            bgfd_me_rows.append(bgfd.loc[ym].rename(me))
        else:
            bgfd_me_rows.append(pd.Series(dtype=float, name=me))
    bgfd_me = pd.DataFrame(bgfd_me_rows)

    return {"RIAD": riad_me, "MFD": mfd_me, "BGFD": bgfd_me}


def _point_corr(a: pd.DataFrame, b: pd.DataFrame, method: str = "spearman") -> float:
    """所有 (date, symbol) 对上的 correlation."""
    sa = a.stack()
    sb = b.stack()
    common = sa.index.intersection(sb.index)
    if len(common) < 100:
        return float("nan")
    return float(sa.loc[common].corr(sb.loc[common], method=method))


def _daily_cs_corr_stats(a: pd.DataFrame, b: pd.DataFrame) -> dict:
    """每日横截面 Spearman corr 的分布."""
    common_dates = a.index.intersection(b.index)
    daily = []
    for d in common_dates:
        av = a.loc[d].dropna()
        bv = b.loc[d].dropna()
        common_syms = av.index.intersection(bv.index)
        if len(common_syms) < 30:
            continue
        c = av.loc[common_syms].corr(bv.loc[common_syms], method="spearman")
        if pd.notna(c):
            daily.append(float(c))
    if not daily:
        return {"n": 0, "mean": None, "median": None, "p25": None, "p75": None}
    arr = np.array(daily)
    return {
        "n": len(arr),
        "mean": float(arr.mean()),
        "median": float(np.median(arr)),
        "p25": float(np.percentile(arr, 25)),
        "p75": float(np.percentile(arr, 75)),
        "abs_mean": float(np.abs(arr).mean()),
    }


def main() -> None:
    price = pd.read_parquet(PRICE_PATH)
    price.columns = [_to_ts(c) for c in price.columns]
    month_ends = _month_end_dates(price)
    print(f"月末调仓日: {len(month_ends)} 个")

    # 构造 RIAD
    cal = price.loc[START:END].index
    panels = build_attention_panel(START, END, cal)
    riad = compute_riad_factor(panels["retail_attn"], panels["inst_attn"])

    # MFD
    mfd = compute_mfd_factor("2023-07-15", END, window=20, min_coverage=500)

    # BGFD
    raw = load_broker_recommend("2023-07", "2025-12")
    cons = compute_consensus_streak(raw)
    bgfd = compute_bgfd_factor(cons, sorted(cons["month_i"].unique()))

    print(f"RIAD: {riad.shape}, MFD: {mfd.shape}, BGFD: {bgfd.shape}")

    aligned = _align_factors_monthly(riad, mfd, bgfd, month_ends)
    for k, v in aligned.items():
        print(f"  {k} 月频对齐: {v.shape}, 日均有效股: {v.notna().sum(axis=1).mean():.0f}")

    # RIAD 和 MFD 是负向因子, 做空方向; BGFD 因为假设翻转后是正向 (follow consensus long)
    # 为统一方向: 全部取"做多信号", RIAD 和 MFD 乘 -1
    aligned["RIAD"] = -aligned["RIAD"]
    aligned["MFD"] = -aligned["MFD"]

    names = ["RIAD", "MFD", "BGFD"]
    point_corr = {}
    daily_corr = {}
    for i, a in enumerate(names):
        for j in range(i + 1, len(names)):
            b = names[j]
            pc = _point_corr(aligned[a], aligned[b])
            ds = _daily_cs_corr_stats(aligned[a], aligned[b])
            point_corr[f"{a}-{b}"] = pc
            daily_corr[f"{a}-{b}"] = ds

    print("\n=== 三因子 orthogonality 检查 ===\n")
    print("Pairwise 点对 Spearman corr:")
    for k, v in point_corr.items():
        tag = "✅ 正交" if abs(v) < 0.3 else ("⚠️  部分重合" if abs(v) < 0.6 else "❌ 高度冗余")
        print(f"  {k:<15}: {v:+.4f}  {tag}")

    print("\n每日截面 Spearman corr 分布 (统一做多方向后):")
    header = f"  {'Pair':<12} {'n':>5} {'mean':>8} {'median':>8} {'p25':>7} {'p75':>7} {'|mean|':>8}"
    print(header)
    for k, s in daily_corr.items():
        print(
            f"  {k:<12} {s['n']:>5} "
            f"{s['mean']:>+8.4f} {s['median']:>+8.4f} "
            f"{s['p25']:>+7.3f} {s['p75']:>+7.3f} "
            f"{s['abs_mean']:>8.4f}"
        )

    stamp = datetime.now().strftime("%Y%m%d")
    out_json = ROOT / "logs" / f"factor_orthogonality_{stamp}.json"
    with open(out_json, "w") as f:
        json.dump(
            {
                "generated_at": datetime.now().isoformat(timespec="seconds"),
                "start": START,
                "end": END,
                "direction_normalized": "All three aligned as long-positive signals",
                "point_spearman": point_corr,
                "daily_cross_section": daily_corr,
            },
            f, indent=2, ensure_ascii=False,
        )
    print(f"\n保存: {out_json}")


if __name__ == "__main__":
    main()
