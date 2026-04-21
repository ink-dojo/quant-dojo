"""
F12 股东增减持因子 (Insider Trading / 高管大股东信号)

背景:
    A 股股东增减持公告 = 散户可见, 低频, HFT 无法抢跑。
    理论: 高管/大股东净增持 = 内部人看多; 净减持 = 看空。
    实际: A 股减持常为例行解锁, alpha 较弱; 增持信号相对强。

数据:
    data/raw/events/_all_ggcg_2018_2025.parquet
    93,735 条公告, 2018-01 ~ 2025-12
    增持 15,711 / 减持 78,024 (5:1 倾斜)

构造:
    net_buying_60d[t, i] = 过去 60 交易日内 (sum 增持 pct - sum 减持 pct of float)
    事件生效日 = 公告日 + 1 交易日

变体:
    (A) net_buying_20d / 60d / 120d
    (B) 只看增持 (大股东信念最强信号)
    (C) 行业 & size 中性化

运行: python research/factors/insider_trading/factor_research.py
"""
import sys
import warnings
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))

import numpy as np
import pandas as pd

warnings.filterwarnings("ignore")

from utils.factor_analysis import compute_ic_series, ic_summary, quintile_backtest, neutralize_factor_by_industry
from utils.fundamental_loader import get_industry_classification

EVENTS = ROOT / "data" / "raw" / "events" / "_all_ggcg_2018_2025.parquet"
PRICE = ROOT / "data" / "processed" / "price_wide_close_2014-01-01_2025-12-31_qfq_5477stocks.parquet"
OUT = ROOT / "research" / "factors" / "insider_trading"

IS_START = "2018-01-01"
IS_END = "2025-12-31"


def build_daily_flow(events: pd.DataFrame, trading_dates: pd.DatetimeIndex, codes: list) -> tuple:
    """
    返回每日每股票的增持/减持 pct_of_float 两个面板 (未滚动, 当日原始值)。
    信号日 = 公告日 + 1 交易日 (严格防未来函数)。
    """
    trading_dates = pd.DatetimeIndex(trading_dates).sort_values()
    code_set = set(codes)
    ev = events.rename(columns={
        "代码": "code", "公告日": "ann_date",
        "持股变动信息-增减": "direction",
        "持股变动信息-占流通股比例": "pct_float",
    })
    ev = ev.dropna(subset=["code", "ann_date", "direction", "pct_float"])
    ev = ev[ev["code"].isin(code_set)].copy()
    ev["ann_date"] = pd.to_datetime(ev["ann_date"], errors="coerce")
    ev = ev.dropna(subset=["ann_date"])
    # ann_date+1: searchsorted side=right gives first day strictly > ann_date
    idx_arr = trading_dates.searchsorted(ev["ann_date"].values, side="right")
    valid = idx_arr < len(trading_dates)
    ev = ev.iloc[valid].copy()
    ev["eff_day"] = trading_dates[idx_arr[valid]]

    buy = ev[ev["direction"] == "增持"]
    sell = ev[ev["direction"] == "减持"]

    buy_daily = buy.groupby(["eff_day", "code"])["pct_float"].sum().unstack(fill_value=0.0)
    sell_daily = sell.groupby(["eff_day", "code"])["pct_float"].sum().unstack(fill_value=0.0)
    buy_daily = buy_daily.reindex(index=trading_dates, columns=codes, fill_value=0.0)
    sell_daily = sell_daily.reindex(index=trading_dates, columns=codes, fill_value=0.0)

    print(f"  increases daily non-zero cells: {(buy_daily > 0).sum().sum():,}")
    print(f"  decreases daily non-zero cells: {(sell_daily > 0).sum().sum():,}")
    return buy_daily, sell_daily


def rolling_net(buy_daily, sell_daily, window):
    net = buy_daily - sell_daily
    return net.rolling(window, min_periods=1).sum()


def cs_residualize(y, x):
    x_m = x.mean(axis=1)
    y_m = y.mean(axis=1)
    xc = x.sub(x_m, axis=0)
    yc = y.sub(y_m, axis=0)
    var_x = (xc ** 2).sum(axis=1)
    cov = (xc * yc).sum(axis=1)
    beta = cov / var_x.replace(0, np.nan)
    return y - xc.mul(beta, axis=0).add(y_m, axis=0)


def main():
    print("=" * 70)
    print("F12 股东增减持因子研究")
    print("=" * 70)
    OUT.mkdir(parents=True, exist_ok=True)

    events = pd.read_parquet(EVENTS)
    print(f"[数据] 事件 {len(events):,} 条")

    price = pd.read_parquet(PRICE)
    price.index = pd.to_datetime(price.index)
    price = price.loc[IS_START:IS_END]
    codes = list(price.columns)
    print(f"[价格] {len(price)} 交易日 × {len(codes)} 股")

    print("\n[面板] 构造日频 buy/sell 流...")
    buy, sell = build_daily_flow(events, price.index, codes)

    # 多窗口 net buying
    net_20 = rolling_net(buy, sell, 20)
    net_60 = rolling_net(buy, sell, 60)
    net_120 = rolling_net(buy, sell, 120)
    # 只看增持
    buy_60 = buy.rolling(60, min_periods=1).sum()

    # 行业中性 + size 代理
    print("\n[中性化]...")
    industry_df = get_industry_classification(symbols=codes, use_cache=True)
    log_p = np.log(price.replace(0, np.nan))

    net_60_neu = neutralize_factor_by_industry(net_60, industry_df, show_progress=False)
    net_60_both = cs_residualize(net_60_neu, log_p)
    buy_60_both = cs_residualize(neutralize_factor_by_industry(buy_60, industry_df, show_progress=False), log_p)

    ret20 = price.shift(-20) / price - 1

    print("\n[IC] @ fwd 20d:")
    results = {}
    variants = [
        ("net_20", net_20),
        ("net_60", net_60),
        ("net_120", net_120),
        ("buy_60", buy_60),
        ("net_60_ind+size", net_60_both),
        ("buy_60_ind+size", buy_60_both),
    ]
    for name, fac in variants:
        ic = compute_ic_series(fac, ret20, method="spearman", min_stocks=500)
        s = ic_summary(ic, name=name, fwd_days=20, verbose=False)
        print(f"    {name:<20} IC {s['IC_mean']:+.4f}  ICIR {s['ICIR']:+.3f}  HAC t {s['t_stat_hac']:+.2f}  n {s['n']}")
        results[name] = s

    # IS/OOS on best variant
    best_name = max(results, key=lambda k: abs(results[k]["ICIR"]))
    print(f"\n[IS/OOS] {best_name} @ fwd 20d:")
    best_fac = dict(variants)[best_name]
    ic_ser = compute_ic_series(best_fac, ret20, method="spearman", min_stocks=500)
    for label, sl in [("IS 2018-2022", slice("2018-01-01", "2022-12-31")),
                      ("OOS 2023-2025", slice("2023-01-01", "2025-12-31"))]:
        ic_sl = ic_ser.loc[sl]
        s_sl = ic_summary(ic_sl, name=label, fwd_days=20, verbose=False)
        print(f"    {label:<20} IC {s_sl['IC_mean']:+.4f}  ICIR {s_sl['ICIR']:+.3f}  HAC t {s_sl['t_stat_hac']:+.2f}  n {s_sl['n']}")

    # Quintile
    print(f"\n[分层] {best_name} @ 20d, 5 组:")
    try:
        grp, ls = quintile_backtest(best_fac, ret20, n_groups=5, long_short="Qn_minus_Q1")
        ann = ls.mean() * 252 / 20
        vol = ls.std() * np.sqrt(252 / 20)
        sr = ann / vol if vol > 0 else np.nan
        print(f"    多空年化 {ann:.2%}  夏普 {sr:.2f}")
        print(f"    各组: {(grp.mean() * 252/20).to_dict()}")
    except Exception as e:
        print(f"    分层失败: {e}")
        ann = sr = np.nan

    # 保存最佳变体 + 原始
    net_60.to_parquet(OUT / "net_buying_60d.parquet")
    net_60_both.to_parquet(OUT / "net_buying_60d_ind_size_neu.parquet")
    buy_60.to_parquet(OUT / "buy_only_60d.parquet")

    # 报告
    with open(OUT / "report.md", "w") as f:
        f.write("# F12 股东增减持因子研究报告\n\n")
        f.write(f"**日期**: 2026-04-21  \n")
        f.write(f"**数据**: 股东增减持公告 2018-2025 (93,735 条)\n\n")
        f.write("## 因子构造\n\n")
        f.write("- net_buying_Nd[t, i] = 过去 N 天内 (增持 pct - 减持 pct) of float\n")
        f.write("- 信号日 = ann_date + 1 交易日\n\n")
        f.write("## IC 汇总\n\n")
        f.write("| 因子 | IC | ICIR | HAC t | n |\n")
        f.write("| --- | ---: | ---: | ---: | ---: |\n")
        for k, s in results.items():
            f.write(f"| {k} | {s['IC_mean']:+.4f} | {s['ICIR']:+.3f} | {s['t_stat_hac']:+.2f} | {s['n']} |\n")
        f.write(f"\n## 最佳变体: {best_name}, 年化 {ann:.2%}, 夏普 {sr:.2f}\n\n")
        f.write("## 结论\n\n")
        best_icir = abs(results[best_name]["ICIR"])
        if best_icir > 0.4:
            f.write(f"- ✅ {best_name} ICIR {best_icir:.2f} > 0.4, 合格\n")
        elif best_icir > 0.3:
            f.write(f"- ⚠️ {best_name} ICIR {best_icir:.2f} 边缘合格\n")
        else:
            f.write(f"- ❌ 最佳 ICIR {best_icir:.2f} 未达 0.3 门槛\n")

    print(f"\n[保存] {OUT}")
    print("=" * 70)
    print("DONE")


if __name__ == "__main__":
    main()
