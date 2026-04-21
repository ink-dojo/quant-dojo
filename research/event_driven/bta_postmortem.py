"""BTA post-mortem — 为什么 sanity t=+8.52 但 portfolio ann -4%?

假设:
A. top-30 by amount 的选股 subset 跟 unconditional 机构吸筹 mean 不同
B. 汇总机制 bug (cross-sectional mean vs portfolio return)
C. 2022 重仓 concentration risk 被特定股票拖累
D. amount 正比于 market cap → top-30 = 白马股 = 高 beta 抱团股
"""
from __future__ import annotations
from pathlib import Path

import numpy as np
import pandas as pd


def main():
    # Sanity 阶段 enriched events 已有 fwd_21d
    events = pd.read_parquet("research/event_driven/block_trade_events_enriched.parquet")
    listing = pd.read_parquet("data/raw/listing_metadata.parquet")
    main_board = set(listing[listing["board"] == "主板"]["symbol"].tolist())

    inst_accum = events[
        (events["is_institutional_buyer"] == 1) &
        (events["is_institutional_seller"] == 0) &
        (events["symbol"].isin(main_board))
    ].copy()
    print(f"主板 × 机构吸筹 events: {len(inst_accum):,}")
    print(f"unconditional mean_fwd_21d: {inst_accum['fwd_21d'].mean():+.4f}")

    # 月度 cross-section top-30 by amount
    inst_accum["month"] = inst_accum["trade_date"].dt.to_period("M")
    monthly_top_returns = []
    for month, grp in inst_accum.groupby("month"):
        sym_amt = grp.groupby("symbol").agg(
            total_amount=("amount", "sum"),
            mean_fwd_21d=("fwd_21d", "mean"),  # 一股多事件时平均
        ).reset_index()
        if len(sym_amt) == 0:
            continue
        top = sym_amt.nlargest(30, "total_amount")
        rest = sym_amt.nsmallest(max(len(sym_amt) - 30, 1), "total_amount")
        monthly_top_returns.append({
            "month": month,
            "n_total": len(sym_amt),
            "n_top": len(top),
            "top_mean": top["mean_fwd_21d"].mean(),
            "rest_mean": rest["mean_fwd_21d"].mean() if len(rest) > 0 else np.nan,
            "all_mean": sym_amt["mean_fwd_21d"].mean(),
            "top_sum_amt": top["total_amount"].sum(),
        })
    mdf = pd.DataFrame(monthly_top_returns)
    print(f"\n月度 top-30 by amount (n months = {len(mdf)}):")
    print(f"  top-30 mean_fwd_21d: {mdf['top_mean'].mean():+.4f}")
    print(f"  rest (其余)        : {mdf['rest_mean'].mean():+.4f}")
    print(f"  all (全体)         : {mdf['all_mean'].mean():+.4f}")
    print(f"  top-30 Welch vs rest: diff={mdf['top_mean'].mean() - mdf['rest_mean'].mean():+.4f}")

    # 年度 top-30 mean_fwd_21d
    mdf["year"] = mdf["month"].astype(str).str[:4].astype(int)
    print(f"\n年度 top-30 mean_fwd_21d:")
    print(mdf.groupby("year").agg(
        n_months=("month", "count"),
        top_mean=("top_mean", "mean"),
        rest_mean=("rest_mean", "mean"),
        all_mean=("all_mean", "mean"),
    ).round(4).to_string())

    # 比较 ranking: 按事件数 count 排名取 top-30 vs 按 amount 排名
    print("\n=== 按事件数 (cluster count) 而不是 amount 排 top-30 ===")
    results_by_count = []
    for month, grp in inst_accum.groupby("month"):
        sym = grp.groupby("symbol").agg(
            n_events=("amount", "size"),
            mean_fwd_21d=("fwd_21d", "mean"),
        ).reset_index()
        if len(sym) == 0:
            continue
        top = sym.nlargest(30, "n_events")
        results_by_count.append({
            "month": month,
            "top_mean": top["mean_fwd_21d"].mean(),
            "all_mean": sym["mean_fwd_21d"].mean(),
        })
    cdf = pd.DataFrame(results_by_count)
    print(f"  top-30 by count mean_fwd_21d: {cdf['top_mean'].mean():+.4f}")
    print(f"  all mean_fwd_21d            : {cdf['all_mean'].mean():+.4f}")

    # 比较 cluster threshold (2+ events in month)
    print("\n=== cluster >= 2 events (不 top-30) 的 unconditional ===")
    clust = inst_accum.groupby(["month", "symbol"]).agg(
        n=("amount", "size"),
        fwd=("fwd_21d", "mean"),
    )
    print(f"  1 event  (n={len(clust[clust['n']==1]):,})  mean_fwd_21d: {clust[clust['n']==1]['fwd'].mean():+.4f}")
    print(f"  2 events (n={len(clust[clust['n']==2]):,})  mean_fwd_21d: {clust[clust['n']==2]['fwd'].mean():+.4f}")
    print(f"  3+ events(n={len(clust[clust['n']>=3]):,})  mean_fwd_21d: {clust[clust['n']>=3]['fwd'].mean():+.4f}")

    # 画 amount vs fwd_21d scatter (decile)
    print("\n=== amount decile vs fwd_21d (全主板机构吸筹) ===")
    inst_accum["amt_dec"] = pd.qcut(inst_accum["amount"], 10, labels=False, duplicates="drop")
    print(inst_accum.groupby("amt_dec").agg(
        n=("amount", "size"),
        mean_amt=("amount", "mean"),
        mean_fwd_21d=("fwd_21d", "mean"),
        wr=("fwd_21d", lambda x: (x > 0).mean()),
    ).round(4).to_string())


if __name__ == "__main__":
    main()
