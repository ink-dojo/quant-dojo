"""
F11 解禁压力因子 (Lockup Release Pressure) — 散户低频 avoid filter

背景:
    A 股定增/首发/股权激励股解禁上市流通会造成抛压, 解禁前 20 日经常
    出现 "前瞻性卖出"。相反, 解禁后 overshoot 反转。
    散户友好: 数据公开 (交易所), 节奏慢 (提前数月公告), HFT 无法抢跑。

数据:
    data/raw/events/_all_lockup_2018_2025.parquet
    18,400 条事件, 2018-01 ~ 2025-12, 覆盖所有 lockup_type。

构造:
    lockup_pressure_20d[t, i] = 股票 i 未来 20 个交易日内将解禁的 pct_of_float 合计
    - 正数越大 → 抛压越大 → 未来 20 日预期 underperform
    - 作为因子用 -lockup_pressure_20d (负号后高 rank = 低解禁压力)

可选变体:
    (A) 未来 20d 合计解禁占比
    (B) 未来 10d/40d/60d 窗口 (测试最佳衰减)
    (C) 只看定增/首发 (股权激励抛压小)

测试:
    - 20 日前瞻 IC / ICIR / HAC t
    - 5 组分层 (避免组 vs 无解禁组)
    - IS 2018-2022 / OOS 2023-2025 拆分

运行: python research/factors/lockup_pressure/factor_research.py
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

EVENTS = ROOT / "data" / "raw" / "events" / "_all_lockup_2018_2025.parquet"
PRICE = ROOT / "data" / "processed" / "price_wide_close_2014-01-01_2025-12-31_qfq_5477stocks.parquet"
OUT = ROOT / "research" / "factors" / "lockup_pressure"

IS_START = "2018-01-01"
IS_END = "2025-12-31"


def build_pressure_panel(events: pd.DataFrame, trading_dates: pd.DatetimeIndex, codes: list, lookahead: int) -> pd.DataFrame:
    """
    对每个 (t, code) 计算 [t+1, t+lookahead] 内合计解禁 pct_of_float。
    用法：pressure_20d[t, i] = 股票 i 从 t+1 到 t+20 窗口内所有事件的 pct_of_float 累加

    关键: 在 t 日能否知晓未来解禁?
    解禁日期通常提前 1~6 个月公告 (首发/定增的锁定期公开), 所以 t 日可知未来 20d 事件。
    没有未来函数问题。
    """
    code_set = set(codes)
    trading_dates = pd.DatetimeIndex(trading_dates).sort_values()
    # 建一个 (release_date, code) 索引的 pct 小面板, 然后对每日滚动求未来 lookahead 天合计
    ev = events.dropna(subset=["release_date", "symbol", "pct_of_float"]).copy()
    ev = ev[ev["symbol"].isin(code_set)]
    ev["release_date"] = pd.to_datetime(ev["release_date"])
    # 把每条事件挂到 release_date 这一天 (如果非交易日, 取下一个交易日)
    idx_arr = trading_dates.searchsorted(ev["release_date"].values, side="left")
    valid = idx_arr < len(trading_dates)
    ev = ev.iloc[valid].copy()
    ev["eff_day"] = trading_dates[idx_arr[valid]]
    # 同一 (eff_day, symbol) 合并 pct (当日多笔合计)
    daily = ev.groupby(["eff_day", "symbol"])["pct_of_float"].sum().unstack(fill_value=0.0)
    daily = daily.reindex(index=trading_dates, columns=codes, fill_value=0.0)
    # 现在对每个 t, 取 [t+1, t+lookahead] 合计
    # 先做未来 lookahead 求和: 把 daily.shift(-k) 从 k=1 到 lookahead 累加
    pressure = daily.shift(-1).rolling(lookahead, min_periods=1).sum().shift(-(lookahead - 1))
    # 注意 shift(-(lookahead-1)) 把窗口对齐到 t (t 日看 t+1~t+lookahead)
    # 验证: pressure.loc[t, i] 应等于 daily.loc[t+1:t+lookahead, i].sum()
    return pressure


def main():
    print("=" * 70)
    print("F11 解禁压力因子研究")
    print("=" * 70)
    OUT.mkdir(parents=True, exist_ok=True)

    print("\n[1/5] 加载数据...")
    events = pd.read_parquet(EVENTS)
    print(f"  解禁事件 {len(events):,} 条, {events['release_date'].min().date()} ~ {events['release_date'].max().date()}")

    price = pd.read_parquet(PRICE)
    price.index = pd.to_datetime(price.index)
    price = price.loc[IS_START:IS_END]
    codes = list(price.columns)
    print(f"  价格 {len(price)} 交易日 × {len(codes)} 股")

    print("\n[2/5] 构造压力面板 (未来 10/20/40 日)...")
    p10 = build_pressure_panel(events, price.index, codes, 10)
    p20 = build_pressure_panel(events, price.index, codes, 20)
    p40 = build_pressure_panel(events, price.index, codes, 40)
    print(f"  p20 非零格 {(p20 > 0).sum().sum():,}, 覆盖 {(p20 > 0).any().sum()} 股")
    print(f"  p20 股票均值 (非零) {p20.where(p20 > 0).mean().mean():.4f}")

    # 负向信号: -pressure (压力越大 rank 越低)
    neg_p10 = -p10
    neg_p20 = -p20
    neg_p40 = -p40

    # 行业中性化 -p20 (关键: 地产/银行天生少解禁, 周期不能当低压力)
    print("\n[3/5] 行业中性化...")
    industry_df = get_industry_classification(symbols=codes, use_cache=True)
    neg_p20_neu = neutralize_factor_by_industry(neg_p20, industry_df, show_progress=False)
    print(f"  neg_p20_neu 非空 {neg_p20_neu.notna().sum().sum():,}")

    print("\n[4/5] IC 测试 (FWD 20d, Q5-Q1 多空):")
    ret20 = price.shift(-20) / price - 1

    results = {}
    variants = [
        ("neg_p10", neg_p10),
        ("neg_p20", neg_p20),
        ("neg_p40", neg_p40),
        ("neg_p20_ind_neu", neg_p20_neu),
    ]
    for name, fac in variants:
        ic = compute_ic_series(fac, ret20, method="spearman", min_stocks=500)
        s = ic_summary(ic, name=name, fwd_days=20, verbose=False)
        print(f"    {name:<20} IC {s['IC_mean']:+.4f}  ICIR {s['ICIR']:+.3f}  HAC t {s['t_stat_hac']:+.2f}  n {s['n']}")
        results[name] = s

    # IS/OOS 拆分
    print("\n[IS/OOS] neg_p20_ind_neu @ fwd 20d:")
    ic_ser = compute_ic_series(neg_p20_neu, ret20, method="spearman", min_stocks=500)
    for label, sl in [("IS 2018-2022", slice("2018-01-01", "2022-12-31")),
                      ("OOS 2023-2025", slice("2023-01-01", "2025-12-31"))]:
        ic_sl = ic_ser.loc[sl]
        s_sl = ic_summary(ic_sl, name=label, fwd_days=20, verbose=False)
        print(f"    {label:<20} IC {s_sl['IC_mean']:+.4f}  ICIR {s_sl['ICIR']:+.3f}  HAC t {s_sl['t_stat_hac']:+.2f}  n {s_sl['n']}")
        results[f"neg_p20_neu_{label.split()[0]}"] = s_sl

    # 分层回测
    print("\n[5/5] 分层回测 neg_p20_neu @ 20d, 5 组:")
    try:
        grp, ls = quintile_backtest(neg_p20_neu, ret20, n_groups=5, long_short="Qn_minus_Q1")
        ann = ls.mean() * 252 / 20
        vol = ls.std() * np.sqrt(252 / 20)
        sr = ann / vol if vol > 0 else np.nan
        print(f"    多空年化 {ann:.2%}  夏普 {sr:.2f}")
        grp_ann = grp.mean() * 252 / 20
        print(f"    各组年化:\n{grp_ann}")
    except Exception as e:
        print(f"    分层失败: {e}")
        ann = sr = np.nan

    # 与 v17 crowding 相关性
    print("\n[独立性] neg_p20_neu vs composite_crowding_sn 相关:")
    try:
        crowd = pd.read_parquet(ROOT / "research/factors/crowding_filter/composite_crowding_sn.parquet")
        crowd.index = pd.to_datetime(crowd.index)
        common_idx = neg_p20_neu.index.intersection(crowd.index)
        common_col = neg_p20_neu.columns.intersection(crowd.columns)
        a = neg_p20_neu.loc[common_idx, common_col]
        b = crowd.loc[common_idx, common_col]
        daily_corr = a.corrwith(b, axis=1)
        print(f"    日均截面相关 {daily_corr.mean():+.3f} (std {daily_corr.std():.3f})")
    except Exception as e:
        print(f"    计算失败: {e}")

    # 保存
    neg_p20.to_parquet(OUT / "neg_lockup_pressure_20d.parquet")
    neg_p20_neu.to_parquet(OUT / "neg_lockup_pressure_20d_ind_neu.parquet")

    with open(OUT / "report.md", "w") as f:
        f.write("# F11 解禁压力因子研究报告\n\n")
        f.write(f"**日期**: 2026-04-21  \n")
        f.write(f"**数据**: 解禁事件 2018-2025 (18,400 条)\n\n")
        f.write("## 因子构造\n\n")
        f.write("- lockup_pressure_20d[t, i] = 未来 20 交易日合计 pct_of_float\n")
        f.write("- 使用 `-pressure` (高 rank = 低抛压)\n\n")
        f.write("## IC 汇总\n\n")
        f.write("| 因子 | IC | ICIR | HAC t | n |\n")
        f.write("| --- | ---: | ---: | ---: | ---: |\n")
        for k, s in results.items():
            f.write(f"| {k} | {s['IC_mean']:+.4f} | {s['ICIR']:+.3f} | {s['t_stat_hac']:+.2f} | {s['n']} |\n")
        f.write("\n## 分层回测 (neg_p20_neu @ 20d)\n\n")
        f.write(f"- 多空年化 {ann:.2%}, 夏普 {sr:.2f}\n\n")
        f.write("## 结论\n\n")
        best_icir = max(abs(s["ICIR"]) for s in results.values())
        if best_icir > 0.4:
            f.write(f"- ✅ 最佳变体 ICIR {best_icir:.2f} > 0.4, 合格\n")
        elif best_icir > 0.3:
            f.write(f"- ⚠️ 最佳变体 ICIR {best_icir:.2f} 边缘合格\n")
        else:
            f.write(f"- ❌ 最佳 ICIR {best_icir:.2f} 未达 0.3 门槛\n")

    print(f"\n[保存] {OUT}")
    print("=" * 70)
    print("DONE")


if __name__ == "__main__":
    main()
