"""
6-因子 orthogonality matrix (2026-04-22 第二轮)

扩展到 6 个因子, 保持 Issue #33 开题的"差异化 + A 股独有"原则.
因子清单 (统一做多方向):
    RIAD_ls   : -zscore(RIAD_raw)        散户-机构关注度 (做多低散户关注高机构关注)
    MFD_ls    : -zscore(MFD_raw)         资金流背离反转 (做多 elg↓ + sm↑)
    BGFD_ls   : +zscore(BGFD_raw)        券商金股共识度 (follow consensus)
    LULR_ls   : -zscore(LULR_raw)        连板反转 (做多炸板 / 跌停)
    THCC_ls   : -zscore(THCC_inst_raw)   筹码集中度反向 (机构撤离反而 alpha)
    SB_ls     : +zscore(SB_raw)          调研 burst (原设计正向, 虽 null)

输出: orthogonality matrix, 相关度 > 0.3 的 pair 标注.
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
from research.factors.limit_up_ladder.factor import compute_lulr_factor, load_limit_list  # noqa: E402
from research.factors.moneyflow_divergence.factor import compute_mfd_factor  # noqa: E402
from research.factors.retail_inst_divergence.evaluate_riad import PRICE_PATH  # noqa: E402
from research.factors.retail_inst_divergence.factor import (  # noqa: E402
    build_attention_panel,
    compute_riad_factor,
)
from research.factors.survey_burst.factor import compute_sb_factor, load_survey_counts  # noqa: E402
from research.factors.top_holder_concentration.evaluate_thcc import ffill_with_staleness  # noqa: E402
from research.factors.top_holder_concentration.factor import (  # noqa: E402
    compute_thcc_factors,
    load_top10_float,
)

START, END = "2024-01-01", "2025-12-31"  # 交集期 (LULR 有长历史; 其他因子受限于 stk_surv 2023-10)


def _to_ts(sym: str) -> str:
    if sym.startswith(("60", "68")):
        return f"{sym}.SH"
    if sym.startswith(("00", "30")):
        return f"{sym}.SZ"
    return f"{sym}.SZ"


def _zscore_row(df: pd.DataFrame) -> pd.DataFrame:
    mu = df.mean(axis=1)
    sd = df.std(axis=1).replace(0.0, np.nan)
    return df.sub(mu, axis=0).div(sd, axis=0)


def _month_end_dates(price: pd.DataFrame) -> list[pd.Timestamp]:
    px = price.loc[START:END]
    return [g.index[-1] for _, g in px.groupby([px.index.year, px.index.month])]


def _point_corr(a: pd.DataFrame, b: pd.DataFrame, method: str = "spearman") -> float:
    sa = a.stack()
    sb = b.stack()
    common = sa.index.intersection(sb.index)
    if len(common) < 50:
        return float("nan")
    return float(sa.loc[common].corr(sb.loc[common], method=method))


def main() -> None:
    price = pd.read_parquet(PRICE_PATH)
    price.columns = [_to_ts(c) for c in price.columns]
    me = _month_end_dates(price)
    print(f"月末调仓日: {len(me)}")

    cal = price.loc[START:END].index
    # 1. RIAD
    panels = build_attention_panel("2023-10-01", END, cal)
    riad = compute_riad_factor(panels["retail_attn"], panels["inst_attn"])

    # 2. MFD
    mfd = compute_mfd_factor("2023-07-15", END, window=20, min_coverage=500)

    # 3. BGFD
    br_raw = load_broker_recommend("2023-07", "2025-12")
    cons = compute_consensus_streak(br_raw)
    bgfd_monthly = compute_bgfd_factor(cons, sorted(cons["month_i"].unique()))

    # 4. LULR
    ll_long = load_limit_list("2023-10-01", END)
    lulr = compute_lulr_factor(ll_long)

    # 5. THCC (inst)
    thcc_raw = load_top10_float(2022, 2025)
    thcc_wide = compute_thcc_factors(thcc_raw)["thcc_inst"]
    thcc_daily = ffill_with_staleness(thcc_wide, cal)

    # 6. SB
    sb_long = load_survey_counts("2023-10-01", END)
    sb = compute_sb_factor(sb_long, cal)

    # 降到月末截面, 统一做多方向
    factors = {}
    # BGFD monthly->month_end
    bgfd_me_rows = []
    for d in me:
        ym = d.year * 100 + d.month
        if ym in bgfd_monthly.index:
            bgfd_me_rows.append(bgfd_monthly.loc[ym].rename(d))
        else:
            bgfd_me_rows.append(pd.Series(dtype=float, name=d))
    bgfd_me = pd.DataFrame(bgfd_me_rows)

    factors["RIAD_ls"] = -riad.reindex(me, method="ffill")
    factors["MFD_ls"] = -mfd.reindex(me, method="ffill")
    factors["BGFD_ls"] = bgfd_me
    factors["LULR_ls"] = -lulr.reindex(me, method="ffill")
    factors["THCC_ls"] = -thcc_daily.reindex(me, method="ffill")
    factors["SB_ls"] = sb.reindex(me, method="ffill")

    for k, v in factors.items():
        cov = v.notna().sum(axis=1).mean()
        print(f"  {k}: shape={v.shape}, 日均有效股 {cov:.0f}")

    names = list(factors.keys())
    matrix = pd.DataFrame(np.nan, index=names, columns=names)
    for i, a in enumerate(names):
        matrix.loc[a, a] = 1.0
        for j in range(i + 1, len(names)):
            b = names[j]
            pc = _point_corr(factors[a], factors[b])
            matrix.loc[a, b] = pc
            matrix.loc[b, a] = pc

    print("\n=== 6-因子 Spearman 相关矩阵 (2024-01 ~ 2025-12, 月末) ===\n")
    print(matrix.round(3).to_string())

    # 识别 > 0.3 pair
    pairs_above = []
    for i, a in enumerate(names):
        for j in range(i + 1, len(names)):
            b = names[j]
            c = matrix.loc[a, b]
            if pd.notna(c) and abs(c) > 0.3:
                pairs_above.append((a, b, float(c)))

    print("\n相关度 |corr| > 0.3 的 pair:")
    if pairs_above:
        for a, b, c in pairs_above:
            print(f"  {a} ↔ {b}: {c:+.3f}")
    else:
        print("  (无) — 6 个因子两两弱相关, 正交组合可行")

    stamp = datetime.now().strftime("%Y%m%d")
    out_json = ROOT / "logs" / f"factor_orthogonality_6f_{stamp}.json"
    with open(out_json, "w") as f:
        json.dump(
            {
                "generated_at": datetime.now().isoformat(timespec="seconds"),
                "start": START,
                "end": END,
                "direction_normalized": "All 6 aligned as long-positive signals",
                "matrix": {a: {b: float(matrix.loc[a, b]) if pd.notna(matrix.loc[a, b]) else None for b in names} for a in names},
                "pairs_above_0_3": [{"a": a, "b": b, "corr": c} for a, b, c in pairs_above],
            },
            f, indent=2, ensure_ascii=False,
        )
    print(f"\n保存: {out_json}")


if __name__ == "__main__":
    main()
