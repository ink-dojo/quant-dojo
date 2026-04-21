"""大宗交易 sanity v2 — 机构接盘 × 折价率 联合信号深挖.

v1 发现:
- 单纯 discount_rate 因子很弱 (monthly ICIR -0.20, t-stat -2.3)
- 但 buyer=机构专用 的事件平均 21d 收益 +0.79% vs 非机构 +0.20% → 差值 ~7% 年化

v2 目标:
1. 机构 vs 非机构 的 mean fwd_21d + 年度稳定性 + p-value
2. 机构 × 小折价 (conditional) 更强?
3. 卖方机构 (seller=机构专用) 有反向信号?
4. 买卖双方都是机构 (机构互换) 特殊 pattern?
5. 同股同月多次机构接盘 (cluster) 是否更强?
"""
from __future__ import annotations
import logging
from pathlib import Path

import numpy as np
import pandas as pd
from scipy import stats

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
logger = logging.getLogger(__name__)


def welch_ttest(a, b):
    """Welch t-test for unequal variance."""
    a = a[~np.isnan(a)]
    b = b[~np.isnan(b)]
    t, p = stats.ttest_ind(a, b, equal_var=False)
    return t, p, len(a), len(b), a.mean(), b.mean()


def main():
    events = pd.read_parquet("research/event_driven/block_trade_events_enriched.parquet")
    print(f"loaded events: {len(events):,}")
    print(f"institutional buyer: {events['is_institutional_buyer'].sum():,}")
    print(f"institutional seller: {events['is_institutional_seller'].sum():,}")
    print(f"both institutional: {((events['is_institutional_buyer']==1)&(events['is_institutional_seller']==1)).sum():,}")
    print()

    # === 1. 买方机构 vs 非机构: 全样本 + 年度 ===
    print("=== 1. buyer=机构 vs 非机构 (fwd_21d) ===")
    a = events.loc[events["is_institutional_buyer"] == 1, "fwd_21d"].values
    b = events.loc[events["is_institutional_buyer"] == 0, "fwd_21d"].values
    t, p, na, nb, ma, mb = welch_ttest(a, b)
    print(f"  机构 n={na:,} mean={ma:+.4f} | 非机构 n={nb:,} mean={mb:+.4f}")
    print(f"  Welch t={t:+.3f}  p={p:.3e}  diff={ma-mb:+.4f}  年化gross差≈{(ma-mb)*12:.2%}")

    print("\n年度稳定性:")
    events["year"] = events["trade_date"].dt.year
    for yr in sorted(events["year"].unique()):
        sub = events[events["year"] == yr]
        a = sub.loc[sub["is_institutional_buyer"] == 1, "fwd_21d"].values
        b = sub.loc[sub["is_institutional_buyer"] == 0, "fwd_21d"].values
        if len(a) < 30 or len(b) < 30:
            continue
        t, p, na, nb, ma, mb = welch_ttest(a, b)
        print(f"  {yr} 机构n={na:4,} mean={ma:+.4f} | 非机构n={nb:5,} mean={mb:+.4f} | diff={ma-mb:+.4f} p={p:.2e}")

    # === 2. 卖方机构 vs 非机构 ===
    print("\n=== 2. seller=机构 vs 非机构 (fwd_21d) ===")
    a = events.loc[events["is_institutional_seller"] == 1, "fwd_21d"].values
    b = events.loc[events["is_institutional_seller"] == 0, "fwd_21d"].values
    t, p, na, nb, ma, mb = welch_ttest(a, b)
    print(f"  机构卖 n={na:,} mean={ma:+.4f} | 非机构卖 n={nb:,} mean={mb:+.4f}")
    print(f"  Welch t={t:+.3f}  p={p:.3e}  diff={ma-mb:+.4f}")

    # === 3. 组合: 买机构 × 卖非机构 最优? ===
    print("\n=== 3. 四象限 ===")
    for (b_, s_), label in [
        ((1, 0), "买机构+卖非机构 (机构吸筹)"),
        ((1, 1), "买机构+卖机构 (机构对倒)"),
        ((0, 1), "买非机构+卖机构 (机构出货)"),
        ((0, 0), "散户/游资互换"),
    ]:
        sub = events[(events["is_institutional_buyer"] == b_) & (events["is_institutional_seller"] == s_)]
        if len(sub) < 30:
            continue
        fwd = sub["fwd_21d"].dropna().values
        print(f"  {label:28s} n={len(sub):5,} mean21d={fwd.mean():+.4f} wr={np.mean(fwd>0):.3f} "
              f"t-stat={fwd.mean()/(fwd.std()/np.sqrt(len(fwd))):+.2f}")

    # === 4. 买机构 × discount bucket ===
    print("\n=== 4. 机构接盘 × discount bucket (fwd_21d) ===")
    inst = events[events["is_institutional_buyer"] == 1].copy()
    inst["dec"] = pd.qcut(inst["discount_rate"], 5, labels=False, duplicates="drop")
    stats5 = inst.groupby("dec").agg(
        n=("discount_rate", "size"),
        mean_disc=("discount_rate", "mean"),
        mean_fwd21=("fwd_21d", "mean"),
        mean_fwd60=("fwd_60d", "mean"),
        wr21=("fwd_21d", lambda x: (x > 0).mean()),
    )
    print("机构接盘 (n=19,964) 按折价率分 5 桶:")
    print(stats5.round(4))

    # === 5. 仅看主板机构接盘 (避免小盘崩盘噪声) ===
    print("\n=== 5. 主板 × 机构接盘 (fwd_21d) ===")
    listing = pd.read_parquet("data/raw/listing_metadata.parquet")
    main_board = set(listing[listing["board"] == "主板"]["symbol"].tolist())
    inst["on_main"] = inst["symbol"].isin(main_board)
    for lbl, mask in [("主板", inst["on_main"]), ("非主板", ~inst["on_main"])]:
        sub = inst[mask]
        fwd = sub["fwd_21d"].dropna().values
        if len(fwd) < 30:
            continue
        print(f"  {lbl} n={len(sub):,} mean21d={fwd.mean():+.4f} wr={np.mean(fwd>0):.3f}")

    # === 6. cluster 效应: 同股同月多次机构接盘 ===
    print("\n=== 6. cluster effect: 同股同月机构接盘次数 ===")
    inst["month"] = inst["trade_date"].dt.to_period("M")
    cnt = inst.groupby(["month", "symbol"]).size().rename("n_inst")
    inst = inst.merge(cnt.reset_index(), on=["month", "symbol"])
    for threshold in [1, 2, 3]:
        sub = inst[inst["n_inst"] >= threshold]
        fwd = sub["fwd_21d"].dropna().values
        if len(fwd) < 30:
            continue
        print(f"  {threshold}+ 次机构接盘 n={len(sub):5,} unique={sub[['month','symbol']].drop_duplicates().shape[0]:5,} "
              f"mean21d={fwd.mean():+.4f} wr={np.mean(fwd>0):.3f}")

    # === 7. 把买卖信号合并成一个 score: signal = buyer_inst - seller_inst ===
    print("\n=== 7. signal = buyer_inst - seller_inst (机构净接盘强度) ===")
    events["inst_net"] = events["is_institutional_buyer"] - events["is_institutional_seller"]
    for s in [-1, 0, 1]:
        sub = events[events["inst_net"] == s]
        fwd = sub["fwd_21d"].dropna().values
        if len(fwd) < 30:
            continue
        lbl = {-1: "机构净卖出", 0: "双方同", 1: "机构净接盘"}[s]
        print(f"  {lbl:12s} n={len(sub):6,} mean21d={fwd.mean():+.4f} wr={np.mean(fwd>0):.3f}")

    # === 8. 时效: 信号在几天内集中? ===
    print("\n=== 8. 机构接盘: 1d/5d/21d/60d (比较 half-life) ===")
    inst_events = events[events["is_institutional_buyer"] == 1]
    noninst = events[events["is_institutional_buyer"] == 0]
    for w in [5, 21, 60]:
        col = f"fwd_{w}d"
        a = inst_events[col].dropna().values
        b = noninst[col].dropna().values
        t, p = stats.ttest_ind(a, b, equal_var=False)
        print(f"  fwd_{w:2d}d 机构mean={a.mean():+.4f} 非机构mean={b.mean():+.4f} diff={a.mean()-b.mean():+.4f} p={p:.2e}")


if __name__ == "__main__":
    main()
