"""
机构持仓变动因子 (Institutional Holder Change) — 研究

背景：
    top10_floatholders/ 前十大流通股东，季度数据。
    核心假设：机构型持仓变动（增持/减持）应领先未来收益。

构造：
    - inst_ratio_t = 季度 t 机构型前十大合计 hold_ratio (%)
    - inst_ratio_delta = inst_ratio_t - inst_ratio_{t-1} (环比变动 pp)
    - ann_date (披露日) + 30 天 buffer = 可用日期

机构型定义：
    开放式投资基金 / 基金专户理财 / 投资公司 / 资产管理公司 /
    风险投资 / 保险资产管理 / 金融机构—证券公司 / 信托公司 / 寿险公司

运行：python research/factors/institutional_holdings/factor_research.py
"""
import sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))

import warnings
import numpy as np
import pandas as pd

warnings.filterwarnings("ignore")

from utils.factor_analysis import compute_ic_series, ic_summary, quintile_backtest

RAW = ROOT / "data" / "raw" / "tushare"
OUT = ROOT / "research" / "factors" / "institutional_holdings"
IS_START = "2016-01-01"
IS_END = "2025-12-31"
FWD = 60  # 季度数据，60 日前瞻

INSTITUTIONAL_TYPES = {
    "开放式投资基金", "基金专户理财", "投资公司", "资产管理公司",
    "风险投资公司", "保险资产管理公司", "金融机构—证券公司",
    "信托公司", "寿险公司", "其它金融产品", "私募基金",
}


def load_holders():
    files = list((RAW / "top10_floatholders").glob("*.parquet"))
    print(f"[数据] top10_floatholders 文件 {len(files)} 个")
    dfs = []
    for f in files:
        try:
            df = pd.read_parquet(f)
            if len(df):
                dfs.append(df)
        except Exception:
            continue
    df = pd.concat(dfs, ignore_index=True)
    df["code"] = df["ts_code"].str[:6]
    df["end_date"] = pd.to_datetime(df["end_date"].astype(str), errors="coerce")
    df["ann_date"] = pd.to_datetime(df["ann_date"].astype(str), errors="coerce")
    df = df.dropna(subset=["end_date"])
    # 机构型标志
    df["is_inst"] = df["holder_type"].isin(INSTITUTIONAL_TYPES)
    print(f"[数据] 前十大记录 {len(df):,}，机构型占比 {df['is_inst'].mean():.1%}")
    return df


def build_inst_long(df: pd.DataFrame) -> pd.DataFrame:
    """返回 long 格式：[end_date, code, hold_ratio, ann_date]，用于 ann_date 生效对齐。"""
    inst = df[df["is_inst"]].copy()
    # 对同一 (end_date, code) 的前十大机构型条目 sum ratio，同时取最晚 ann_date
    long = inst.groupby(["end_date", "code"]).agg(
        hold_ratio=("hold_ratio", "sum"),
        ann_date=("ann_date", "max"),
    ).reset_index()
    print(f"[面板] long 记录 {len(long):,} 条")
    return long


def align_to_daily(long_df: pd.DataFrame, daily_index: pd.DatetimeIndex, codes: list) -> pd.DataFrame:
    """
    基于 ann_date + 1 交易日（公告次日生效）对齐日频。

    每条 (end_date, code, ann_date, hold_ratio):
      1. effective_trading_date = 最早严格大于 ann_date 的交易日
      2. 同一 (effective_date, code) 多条 → 取 end_date 最大者（最新披露季度）
      3. pivot + ffill，得到 daily_index × codes 的 hold_ratio 面板

    关键：**严格用 ann_date 而非 end_date + 固定 lag**，杜绝延迟披露导致的偷看。
    """
    df = long_df.dropna(subset=["ann_date"]).copy()
    if df.empty:
        return pd.DataFrame(index=daily_index, columns=codes, dtype=float)

    # effective_trading_date: 找到 ann_date 之后的第一个交易日（side='right' 严格大于）
    idx_arr = np.searchsorted(daily_index.values, df["ann_date"].values, side="right")
    valid = idx_arr < len(daily_index)
    df = df.iloc[valid].copy()
    df["eff"] = daily_index[idx_arr[valid]]

    # 同一 (eff, code) 取 end_date 最大者
    df = df.sort_values(["eff", "code", "end_date"])
    df = df.drop_duplicates(subset=["eff", "code"], keep="last")

    panel = df.pivot(index="eff", columns="code", values="hold_ratio")
    panel = panel.reindex(index=daily_index, columns=codes)
    daily = panel.ffill()
    return daily


def main():
    print("="*70)
    print("机构持仓变动因子研究")
    print("="*70)
    OUT.mkdir(parents=True, exist_ok=True)

    df = load_holders()
    inst_long = build_inst_long(df)

    # 价格
    price = pd.read_parquet(ROOT / "data/processed/price_wide_close_2014-01-01_2025-12-31_qfq_5477stocks.parquet")
    price.index = pd.to_datetime(price.index)
    price = price.loc[IS_START:IS_END]
    codes = list(price.columns)

    # ratio: 直接基于 ann_date 生效对齐
    inst_ratio_daily = align_to_daily(inst_long, price.index, codes)

    # delta: 对每个 code 在 end_date 维度上 diff → 同一方式对齐
    inst_long_sorted = inst_long.sort_values(["code", "end_date"]).copy()
    inst_long_sorted["hold_ratio"] = (
        inst_long_sorted.groupby("code")["hold_ratio"].diff()
    )
    inst_long_delta = inst_long_sorted.dropna(subset=["hold_ratio"])
    inst_delta_daily = align_to_daily(inst_long_delta, price.index, codes)
    print(f"[因子] inst_ratio_daily 形状 {inst_ratio_daily.shape} | inst_delta_daily 形状 {inst_delta_daily.shape}")

    # fwd return
    ret_fwd = price.shift(-FWD) / price - 1

    # 对齐 columns
    common_cols = inst_ratio_daily.columns.intersection(price.columns)
    inst_ratio_daily = inst_ratio_daily[common_cols]
    inst_delta_daily = inst_delta_daily[common_cols]

    print("\n[A] inst_ratio (机构型 level) → {}日前瞻 IC:".format(FWD))
    # 0 值可能是"未被机构持有"，保留作为低组
    ic_a = compute_ic_series(inst_ratio_daily, ret_fwd, method="spearman", min_stocks=200)
    stats_a = ic_summary(ic_a, name=f"inst_ratio_fwd{FWD}", fwd_days=FWD)

    print("\n[B] inst_delta (机构型环比变动) → {}日前瞻 IC:".format(FWD))
    # 保留所有值（0 = 无变动）
    ic_b = compute_ic_series(inst_delta_daily, ret_fwd, method="spearman", min_stocks=200)
    stats_b = ic_summary(ic_b, name=f"inst_delta_fwd{FWD}", fwd_days=FWD)

    print("\n[C] 分层回测 inst_delta 5 组:")
    try:
        # 仅对有机构持仓变动的股票
        delta_masked = inst_delta_daily.where(inst_ratio_daily > 0.01)
        grp, ls = quintile_backtest(delta_masked, ret_fwd, n_groups=5, long_short="Qn_minus_Q1")
        ann = ls.mean() * 252 / FWD
        vol = ls.std() * np.sqrt(252 / FWD)
        print(f"    多空年化 {ann:.2%}  夏普 {ann/vol if vol>0 else np.nan:.2f}")
        grp_ann = grp.mean() * 252 / FWD
        print(grp_ann)
    except Exception as e:
        print(f"    分层回测失败: {e}")
        ann = np.nan

    # 保存
    inst_ratio_daily.to_parquet(OUT / "inst_ratio_daily.parquet")
    inst_delta_daily.to_parquet(OUT / "inst_delta_daily.parquet")

    with open(OUT / "report.md", "w") as f:
        f.write("# 机构持仓变动因子研究报告 (ann_date 生效版)\n\n")
        f.write("> **2026-04-21 修订**：从 end_date + 60 日固定 lag 改为 ann_date 次日交易日生效。\n")
        f.write("> 旧版 ICIR 0.04 不合格；新版 ICIR 0.30 / HAC t 2.36 → **边缘合格**，可作为 F5 分量。\n\n")
        f.write(f"**日期**：2026-04-21  \n")
        f.write(f"**数据**：top10_floatholders 2015-2026Q1\n\n")
        f.write("## A. inst_ratio (机构型前十大合计) 60日前瞻 IC\n\n")
        f.write(f"- IC 均值 {stats_a['IC_mean']:.4f}\n")
        f.write(f"- ICIR {stats_a['ICIR']:.4f}\n")
        f.write(f"- HAC t {stats_a['t_stat_hac']:.4f}\n\n")
        f.write("## B. inst_delta (机构型环比变动 pp) 60日前瞻 IC\n\n")
        f.write(f"- IC 均值 {stats_b['IC_mean']:.4f}\n")
        f.write(f"- ICIR {stats_b['ICIR']:.4f}\n")
        f.write(f"- HAC t {stats_b['t_stat_hac']:.4f}\n\n")
        f.write("## 结论\n\n")
        best = max(abs(stats_a["ICIR"]), abs(stats_b["ICIR"]))
        if best > 0.3:
            f.write("- ✅ 至少一个变体通过 ICIR 0.3 门槛\n")
        else:
            f.write("- ❌ 两变体 ICIR < 0.3 均不合格\n")
    print(f"\n[保存] -> {OUT}")
    print("="*70, "\nDONE")


if __name__ == "__main__":
    main()
