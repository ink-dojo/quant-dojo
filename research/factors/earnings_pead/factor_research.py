"""
PEAD — 业绩预告漂移 (Post-Earnings Announcement Drift) 因子研究

背景:
    中国散户最适合的低频事件驱动 alpha。
    业绩预告披露后, 因个股信息扩散慢 + 散户反应滞后, 超预期消息在 20-60 日
    持续给 outperform (预增/扭亏), 不达预期持续 underperform (预减/首亏)。
    学术来源: Bernard & Thomas (1989) 美股 60 天 drift; 林海涛等 (2020) A 股验证。

数据:
    data/raw/events/_all_earnings_preview_2010_2025.parquet
    2010-2026Q1, 171,382 条, 5,547 只股票, 11 种预告类型。

构造:
    (A) surprise_ord: 预告类型 → ordinal
        扭亏 +3, 预增 +2, 略增/续盈/减亏 +1, 不确定 0,
        续亏/增亏 -1, 略减 -1.5, 预减 -2, 首亏 -3
    (B) surprise_yoy: 业绩变动幅度 (yoy %) 截面 winsorized → z-score
    (C) surprise_combo: 0.6 * rank(ord) + 0.4 * rank(yoy) 合成

窗口:
    ann_date + 1 交易日生效, 持续 60 日 (内部 fwd=20 评估; 叠加期按月换仓)

测试:
    - 20/40/60 日前瞻 IC / ICIR / HAC t
    - 5 组分层回测 (only stocks currently under event window)
    - 最近预告覆盖率验证

运行: python research/factors/earnings_pead/factor_research.py
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

EVENTS = ROOT / "data" / "raw" / "events" / "_all_earnings_preview_2010_2025.parquet"
PRICE = ROOT / "data" / "processed" / "price_wide_close_2014-01-01_2025-12-31_qfq_5477stocks.parquet"
OUT = ROOT / "research" / "factors" / "earnings_pead"

IS_START = "2014-01-01"
IS_END = "2025-12-31"
FWD_LIST = [20, 40, 60]

# 预告类型 → surprise 得分
TYPE_TO_SCORE = {
    "扭亏": +3.0,
    "预增": +2.0,
    "略增": +1.0,
    "续盈": +0.5,
    "减亏": +0.5,
    "不确定": 0.0,
    "续亏": -0.5,
    "增亏": -1.0,
    "略减": -1.0,
    "预减": -2.0,
    "首亏": -3.0,
}


def load_events() -> pd.DataFrame:
    df = pd.read_parquet(EVENTS)
    df = df.rename(columns={"股票代码": "code", "公告日期": "ann_date", "预告类型": "pred_type", "业绩变动幅度": "yoy"})
    df["ann_date"] = pd.to_datetime(df["ann_date"], errors="coerce")
    df = df.dropna(subset=["ann_date", "code", "pred_type"])
    df["score_ord"] = df["pred_type"].map(TYPE_TO_SCORE)
    df = df.dropna(subset=["score_ord"])
    df["yoy"] = pd.to_numeric(df["yoy"], errors="coerce")
    # 去掉同 (code, 报告期) 的早期预告, 只保留最后一次 (最接近正式财报的预告最准)
    df = df.sort_values(["code", "报告期", "ann_date"]).drop_duplicates(subset=["code", "报告期"], keep="last")
    print(f"[数据] 预告事件 {len(df):,} 条, {df['code'].nunique()} 股, {df['ann_date'].min().date()} ~ {df['ann_date'].max().date()}")
    print(f"       预告类型分布 top:")
    for k, v in df["pred_type"].value_counts().head(8).items():
        print(f"         {k:<6} {v:>7,}  score={TYPE_TO_SCORE.get(k)}")
    return df


def build_event_panel(events: pd.DataFrame, trading_dates: pd.DatetimeIndex, codes: list, hold_days: int) -> pd.DataFrame:
    """为每个事件在 [ann_date+1, ann_date+hold_days] 生成 signal 面板。
    重叠事件以最新一次为准(同 code 后一次事件覆盖前一次)。
    """
    trading_dates = pd.DatetimeIndex(trading_dates).sort_values()
    code_set = set(codes)
    rows = []
    for _, ev in events.iterrows():
        c = ev["code"]
        if c not in code_set:
            continue
        # 找 ann_date 之后的第一个交易日
        idx = trading_dates.searchsorted(ev["ann_date"], side="right")
        if idx >= len(trading_dates):
            continue
        eff_start = trading_dates[idx]
        eff_end_idx = min(idx + hold_days - 1, len(trading_dates) - 1)
        eff_end = trading_dates[eff_end_idx]
        rows.append((c, eff_start, eff_end, ev["score_ord"], ev["yoy"]))
    ev_df = pd.DataFrame(rows, columns=["code", "start", "end", "score_ord", "yoy"])
    print(f"[面板] {len(ev_df)} 个事件窗口覆盖 {ev_df['code'].nunique()} 股")

    # 构造日频面板
    panel_ord = pd.DataFrame(index=trading_dates, columns=codes, dtype=float)
    panel_yoy = pd.DataFrame(index=trading_dates, columns=codes, dtype=float)
    # 按 code 迭代，对每个 code 按 event start asc 依次覆盖（保证晚期事件覆盖早期）
    for c, grp in ev_df.sort_values(["code", "start"]).groupby("code"):
        for _, e in grp.iterrows():
            panel_ord.loc[e["start"]:e["end"], c] = e["score_ord"]
            panel_yoy.loc[e["start"]:e["end"], c] = e["yoy"]
    return panel_ord, panel_yoy


def winsorize_cs(df: pd.DataFrame, lower=0.01, upper=0.99) -> pd.DataFrame:
    q_lo = df.quantile(lower, axis=1)
    q_hi = df.quantile(upper, axis=1)
    return df.clip(lower=q_lo, upper=q_hi, axis=0)


def main():
    print("=" * 70)
    print("PEAD 业绩预告漂移因子研究")
    print("=" * 70)
    OUT.mkdir(parents=True, exist_ok=True)

    events = load_events()

    # 价格
    price = pd.read_parquet(PRICE)
    price.index = pd.to_datetime(price.index)
    price = price.loc[IS_START:IS_END]
    codes = list(price.columns)
    print(f"[价格] {len(price)} 交易日, {len(codes)} 股")

    # 用 60 日持有窗口作为 base (可覆盖多种 FWD 评估)
    panel_ord, panel_yoy = build_event_panel(events, price.index, codes, hold_days=60)
    print(f"[因子] panel_ord 非空格 {panel_ord.notna().sum().sum():,}, yoy 非空 {panel_yoy.notna().sum().sum():,}")

    # shift 1 避免未来函数 (事件 T 日公告 → T+1 才能用)
    # 注意 build 时已经把 eff_start = 公告日的下一交易日, 所以不需要额外 shift
    # 但保险起见再 shift 1 做 safety margin
    panel_ord = panel_ord.shift(1)
    panel_yoy = panel_yoy.shift(1)

    # yoy 截面 winsorize 后 z-score (减弱极端值影响)
    yoy_w = winsorize_cs(panel_yoy, 0.01, 0.99)
    yoy_mean = yoy_w.mean(axis=1)
    yoy_std = yoy_w.std(axis=1)
    yoy_z = yoy_w.sub(yoy_mean, axis=0).div(yoy_std.replace(0, np.nan), axis=0)

    # combo: ord & yoy_z 都归一再加权 (简单等权)
    # 先按日做 cross-sectional rank (0~1)
    def cs_rank(df):
        return df.rank(axis=1, pct=True) - 0.5  # center at 0
    combo = 0.6 * cs_rank(panel_ord) + 0.4 * cs_rank(yoy_z)

    # 行业中性化 (关键改进: 预亏/预增有行业集聚效应)
    print("\n[中性化] 构造行业中性 combo ...")
    industry_df = get_industry_classification(symbols=codes, use_cache=True)
    combo_neu = neutralize_factor_by_industry(combo, industry_df, show_progress=False)
    ord_neu = neutralize_factor_by_industry(panel_ord, industry_df, show_progress=False)
    yoy_neu = neutralize_factor_by_industry(yoy_z, industry_df, show_progress=False)
    print(f"  combo_neu 非空格 {combo_neu.notna().sum().sum():,}")

    results = {}
    variants = [
        ("surprise_ord", panel_ord),
        ("surprise_yoy_z", yoy_z),
        ("surprise_combo", combo),
        ("combo_ind_neu", combo_neu),
        ("ord_ind_neu", ord_neu),
    ]
    for fwd in FWD_LIST:
        ret_fwd = price.shift(-fwd) / price - 1
        print(f"\n--- FWD {fwd} 日 ---")
        for name, fac in variants:
            ic = compute_ic_series(fac, ret_fwd, method="spearman", min_stocks=50)
            s = ic_summary(ic, name=name, fwd_days=fwd, verbose=False)
            print(f"    {name:<20} IC {s['IC_mean']:+.4f}  ICIR {s['ICIR']:+.3f}  HAC t {s['t_stat_hac']:+.2f}  n {s['n']}")
            results[f"{name}_fwd{fwd}"] = s

    # IS/OOS 拆分 (combo_neu @ 20d)
    print("\n[IS/OOS] combo_ind_neu @ fwd 20d:")
    ret20 = price.shift(-20) / price - 1
    ic_series = compute_ic_series(combo_neu, ret20, method="spearman", min_stocks=50)
    for label, sl in [("IS 2014-2022", slice("2014-01-01", "2022-12-31")),
                      ("OOS 2023-2025", slice("2023-01-01", "2025-12-31"))]:
        ic_sl = ic_series.loc[sl]
        s_sl = ic_summary(ic_sl, name=label, fwd_days=20, verbose=False)
        print(f"    {label:<20} IC {s_sl['IC_mean']:+.4f}  ICIR {s_sl['ICIR']:+.3f}  HAC t {s_sl['t_stat_hac']:+.2f}  n {s_sl['n']}")
        results[f"combo_neu_{label.split()[0]}"] = s_sl

    # 分层回测 (combo_neu @ 20d)
    print("\n[分层] combo_ind_neu @ fwd 20d, 5 组:")
    ret_fwd = price.shift(-20) / price - 1
    try:
        grp, ls = quintile_backtest(combo_neu, ret_fwd, n_groups=5, long_short="Qn_minus_Q1")
        ann = ls.mean() * 252 / 20
        vol = ls.std() * np.sqrt(252 / 20)
        sr = ann / vol if vol > 0 else np.nan
        print(f"    多空年化 {ann:.2%}  夏普 {sr:.2f}")
        grp_ann = grp.mean() * 252 / 20
        print(f"    各组年化: {grp_ann.to_dict()}")
    except Exception as e:
        print(f"    分层失败: {e}")
        ann = sr = np.nan
        grp_ann = pd.Series()

    # 事件型因子特有测试: 仅在事件窗口内 IC (不对事件外的股票做截面 rank 会稀释)
    print("\n[事件内] combo masked to event-active stocks, fwd 20d IC:")
    combo_event = combo.where(panel_ord.notna())  # 只看有活跃事件的股票
    ic_ev = compute_ic_series(combo_event, ret_fwd, method="spearman", min_stocks=30)
    s_ev = ic_summary(ic_ev, name="combo_event_only", fwd_days=20, verbose=False)
    print(f"    IC {s_ev['IC_mean']:+.4f}  ICIR {s_ev['ICIR']:+.3f}  HAC t {s_ev['t_stat_hac']:+.2f}  n {s_ev['n']}")

    # 与 v17 crowding 相关性 (看是否独立)
    print("\n[独立性] combo_neu vs composite_crowding_sn 相关:")
    try:
        crowd = pd.read_parquet(ROOT / "research/factors/crowding_filter/composite_crowding_sn.parquet")
        crowd.index = pd.to_datetime(crowd.index)
        common_idx = combo_neu.index.intersection(crowd.index)
        common_col = combo_neu.columns.intersection(crowd.columns)
        a = combo_neu.loc[common_idx, common_col]
        b = crowd.loc[common_idx, common_col]
        # 每日截面相关, 再平均
        daily_corr = a.corrwith(b, axis=1)
        print(f"    日均截面相关 {daily_corr.mean():+.3f} (std {daily_corr.std():.3f})")
    except Exception as e:
        print(f"    计算失败: {e}")

    # 保存因子
    panel_ord.to_parquet(OUT / "surprise_ord.parquet")
    yoy_z.to_parquet(OUT / "surprise_yoy_z.parquet")
    combo.to_parquet(OUT / "surprise_combo.parquet")
    combo_neu.to_parquet(OUT / "surprise_combo_ind_neu.parquet")
    combo_event.to_parquet(OUT / "surprise_combo_event.parquet")

    # 报告
    with open(OUT / "report.md", "w") as f:
        f.write("# PEAD 业绩预告漂移因子研究\n\n")
        f.write(f"**日期**: 2026-04-21  \n")
        f.write(f"**数据**: 业绩预告 2010-2026 (171,382 事件)\n\n")
        f.write("## 因子构造\n\n")
        f.write("- surprise_ord: 预告类型 ordinal (-3 首亏 ~ +3 扭亏)\n")
        f.write("- surprise_yoy_z: 业绩变动幅度 截面 z-score (winsorize 1~99%)\n")
        f.write("- surprise_combo: 0.6*rank(ord) + 0.4*rank(yoy)\n\n")
        f.write("事件窗口: ann_date+1 ~ +60 交易日, 同 code 重叠事件以最新覆盖\n\n")
        f.write("## IC 汇总\n\n")
        f.write("| 因子 | fwd | IC | ICIR | HAC t | n |\n")
        f.write("| --- | ---: | ---: | ---: | ---: | ---: |\n")
        for k, s in results.items():
            f.write(f"| {k} | | {s['IC_mean']:+.4f} | {s['ICIR']:+.3f} | {s['t_stat_hac']:+.2f} | {s['n']} |\n")
        f.write(f"\n## 事件内 IC (仅事件窗口内)\n\n")
        f.write(f"- IC {s_ev['IC_mean']:+.4f}, ICIR {s_ev['ICIR']:+.3f}, HAC t {s_ev['t_stat_hac']:+.2f}\n\n")
        f.write("## 分层回测 combo @ 20d\n\n")
        f.write(f"- 多空年化 {ann:.2%}, 夏普 {sr:.2f}\n")
        f.write(f"- 各组: {grp_ann.to_dict()}\n\n")
        f.write("## 结论\n\n")
        best_icir = max(abs(s["ICIR"]) for s in results.values())
        if best_icir > 0.4:
            f.write(f"- ✅ 最佳变体 ICIR {best_icir:.2f} > 0.4, 推入 v18 候选\n")
        elif best_icir > 0.3:
            f.write(f"- ⚠️ 最佳变体 ICIR {best_icir:.2f} 边缘合格, 需配合其他因子\n")
        else:
            f.write(f"- ❌ 最佳 ICIR {best_icir:.2f} 未达 0.3 门槛\n")

    print(f"\n[保存] {OUT}")
    print("=" * 70)
    print("DONE")


if __name__ == "__main__":
    main()
