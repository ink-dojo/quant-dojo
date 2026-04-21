"""
质押比例负向 filter (Pledge Ratio Risk Filter) — 研究脚本

背景：
    A 股 2018 年 10 月质押危机实测——pledge_ratio > 50% 股票 vs < 5%
    在 2018-07 ~ 2019-01 半年内多跌 14.5 pp（见 journal/a_share_quant_deep_dive_20260421.md §8.2b）。
    本脚本将该观察形式化为两种用法：
        (A) 单因子：-pledge_ratio 作为因子，测 IC（预期负相关）
        (B) Universe filter：pledge_ratio > threshold 的股票从池中剔除

运行：
    python research/factors/pledge_filter/factor_research.py

输出：
    - stdout: IC/分层回测 + 历史危机压力测试
    - research/factors/pledge_filter/pledge_panel.parquet (日频 pledge 宽表)
    - research/factors/pledge_filter/report.md
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))

import warnings
import numpy as np
import pandas as pd

warnings.filterwarnings("ignore")

from utils.factor_analysis import (
    compute_ic_series,
    ic_summary,
    quintile_backtest,
)

# ──────────────── 参数 ────────────────
RAW = ROOT / "data" / "raw" / "tushare"
OUT = ROOT / "research" / "factors" / "pledge_filter"
IS_START = "2015-01-01"
IS_END = "2025-12-31"
FWD_DAYS = 20  # 20 日前瞻
PLEDGE_THRESHOLDS = [30.0, 50.0]  # 两级过滤阈值


def load_pledge_panel() -> pd.DataFrame:
    """从 pledge_stat/ 构造日频 pledge_ratio 宽表 (ffill 周度数据)。"""
    files = list((RAW / "pledge_stat").glob("*.parquet"))
    print(f"[数据] pledge_stat 文件 {len(files)} 个")
    df = pd.concat([pd.read_parquet(f) for f in files], ignore_index=True)
    df["code"] = df["ts_code"].str[:6]
    df["end_date"] = pd.to_datetime(df["end_date"], format="%Y%m%d")
    # 周度 snapshot，用 end_date 作为 "最新可知日期"
    # 真实交易可用日 = end_date + 1 (次日才能用)
    panel = df.pivot_table(
        index="end_date",
        columns="code",
        values="pledge_ratio",
        aggfunc="last",
    ).sort_index()
    print(f"[数据] pledge_panel 形状 {panel.shape}")
    return panel


def align_pledge_to_daily(pledge_panel: pd.DataFrame, daily_index: pd.DatetimeIndex) -> pd.DataFrame:
    """将周频 pledge snapshot ffill 到日频，并 shift 1 日避免未来函数。"""
    daily = pledge_panel.reindex(daily_index).ffill().shift(1)
    return daily


def load_price_panel() -> pd.DataFrame:
    """加载前复权价格宽表。"""
    p = ROOT / "data" / "processed" / "price_wide_close_2014-01-01_2025-12-31_qfq_5477stocks.parquet"
    price = pd.read_parquet(p)
    price.index = pd.to_datetime(price.index)
    return price


def compute_fwd_return(price: pd.DataFrame, fwd_days: int) -> pd.DataFrame:
    """计算 fwd_days 前瞻收益率。"""
    return price.shift(-fwd_days) / price - 1


# ══════════════════════════════════════════════════════════════
# Part A: 单因子 IC 测试（pledge_ratio 负向）
# ══════════════════════════════════════════════════════════════
def test_as_factor(pledge_daily: pd.DataFrame, ret_fwd: pd.DataFrame):
    # 限定 IS 窗口
    common = pledge_daily.index.intersection(ret_fwd.index)
    mask = (common >= IS_START) & (common <= IS_END)
    common = common[mask]
    fac = -pledge_daily.loc[common]  # 负号：质押低 → 未来收益高
    ret = ret_fwd.loc[common]

    # 只取有 pledge 数据的股票（过滤 all-NaN 列）
    fac_stocks = fac.columns[fac.notna().any()]
    fac = fac[fac_stocks]
    ret = ret[fac_stocks.intersection(ret.columns)]

    # 只保留有足够截面的日期（至少 200 股有 pledge）
    daily_count = fac.notna().sum(axis=1)
    keep_dates = daily_count[daily_count >= 200].index
    fac = fac.loc[keep_dates]
    ret = ret.loc[keep_dates]

    print(f"\n[A] 单因子测试：-pledge_ratio vs {FWD_DAYS}日前瞻")
    print(f"    截面数 {len(keep_dates)}, 股票数 {len(fac_stocks)}")

    ic = compute_ic_series(fac, ret, method="spearman", min_stocks=200)
    stats = ic_summary(ic, name=f"-pledge_ratio_fwd{FWD_DAYS}", fwd_days=FWD_DAYS)

    # 分层回测：5 组
    group_ret, ls_ret = quintile_backtest(fac, ret, n_groups=5, long_short="Qn_minus_Q1")
    ann = ls_ret.mean() * 252 / FWD_DAYS  # 20日前瞻校正
    vol = ls_ret.std() * np.sqrt(252 / FWD_DAYS)
    sr = ann / vol if vol > 0 else np.nan
    print(f"    多空 (低质押 - 高质押) 年化 {ann:.2%}  夏普 {sr:.2f}")

    # 各组收益
    grp_ann = group_ret.mean() * 252 / FWD_DAYS
    print(f"    各组年化:\n{grp_ann}")
    return stats, {"ls_ann": ann, "ls_sharpe": sr, "grp_ann": grp_ann.to_dict()}


# ══════════════════════════════════════════════════════════════
# Part B: Universe filter 压力测试
# ══════════════════════════════════════════════════════════════
def test_as_filter(pledge_daily: pd.DataFrame, price: pd.DataFrame):
    print(f"\n[B] Universe filter 历史压力测试")
    stress_windows = [
        ("2015-07-01", "2016-01-31", "2015 股灾 + 熔断"),
        ("2018-07-01", "2019-01-31", "2018 质押危机"),
        ("2024-01-02", "2024-02-29", "2024 小微盘崩盘"),
    ]
    results = []
    for start, end, label in stress_windows:
        # snapshot at start - 1 (use most recent pledge before window)
        snap_date = pd.Timestamp(start)
        snap = pledge_daily.loc[:snap_date].iloc[-1] if snap_date in pledge_daily.index or len(pledge_daily.loc[:snap_date]) else None
        if snap is None or snap.empty or snap.isna().all():
            print(f"    [{label}] 无 pledge snapshot 数据")
            continue
        snap = snap.dropna()
        # window return
        pw = price.loc[start:end]
        if len(pw) < 2:
            continue
        ret = (pw.iloc[-1] / pw.iloc[0] - 1).dropna()
        common = snap.index.intersection(ret.index)
        snap = snap[common]
        ret = ret[common]
        high30 = ret[snap > 30]
        high50 = ret[snap > 50]
        low5 = ret[snap < 5]
        row = {
            "period": f"{start[:10]}~{end[:10]}",
            "label": label,
            "n_pledge_high50": len(high50),
            "n_pledge_high30": len(high30),
            "n_pledge_low5": len(low5),
            "ret_high50": high50.mean() if len(high50) > 0 else np.nan,
            "ret_high30": high30.mean() if len(high30) > 0 else np.nan,
            "ret_low5": low5.mean() if len(low5) > 0 else np.nan,
            "excess_high50_vs_low5": (high50.mean() - low5.mean()) if (len(high50) > 0 and len(low5) > 0) else np.nan,
        }
        results.append(row)
        print(f"    [{label}] {start[:10]}~{end[:10]}")
        print(f"        高质押 (>50%, n={row['n_pledge_high50']:>3}): {row['ret_high50']*100 if not np.isnan(row['ret_high50']) else float('nan'):>6.2f}%")
        print(f"        高质押 (>30%, n={row['n_pledge_high30']:>3}): {row['ret_high30']*100 if not np.isnan(row['ret_high30']) else float('nan'):>6.2f}%")
        print(f"        低质押 (<5%,  n={row['n_pledge_low5']:>3}):  {row['ret_low5']*100 if not np.isnan(row['ret_low5']) else float('nan'):>6.2f}%")
        if not np.isnan(row["excess_high50_vs_low5"]):
            print(f"        超额损失 (>50% vs <5%): {row['excess_high50_vs_low5']*100:>6.2f} pp")
    return pd.DataFrame(results)


# ══════════════════════════════════════════════════════════════
# 主流程
# ══════════════════════════════════════════════════════════════
def main():
    print("="*70)
    print("Pledge Ratio Factor / Filter 研究")
    print("="*70)

    pledge_panel = load_pledge_panel()
    price = load_price_panel()

    # 对齐 pledge 到 price 的 trading-day index
    pledge_daily = align_pledge_to_daily(pledge_panel, price.index)
    ret_fwd = compute_fwd_return(price, FWD_DAYS)

    OUT.mkdir(parents=True, exist_ok=True)
    pledge_daily.to_parquet(OUT / "pledge_panel_daily.parquet")
    print(f"[保存] pledge_panel_daily -> {OUT / 'pledge_panel_daily.parquet'} ({pledge_daily.shape})")

    # Part A
    stats_a, back_a = test_as_factor(pledge_daily, ret_fwd)

    # Part B
    stress = test_as_filter(pledge_daily, price)
    stress.to_parquet(OUT / "stress_test_results.parquet")

    # Report
    with open(OUT / "report.md", "w") as f:
        f.write("# Pledge Filter 研究报告\n\n")
        f.write(f"**日期**：2026-04-21  \n")
        f.write(f"**数据**：pledge_stat/ 周频 {price.index[0].date()} ~ {price.index[-1].date()}\n\n")
        f.write("## A. 单因子 IC 测试 (-pledge_ratio, 20日前瞻)\n\n")
        f.write(f"- IC 均值: {stats_a['IC_mean']:.4f}\n")
        f.write(f"- ICIR: {stats_a['ICIR']:.4f}\n")
        f.write(f"- HAC t: {stats_a['t_stat_hac']:.4f}\n")
        f.write(f"- IC>0 占比: {stats_a['pct_pos']:.2%}\n")
        f.write(f"- 多空年化: {back_a['ls_ann']:.2%}\n")
        f.write(f"- 多空夏普: {back_a['ls_sharpe']:.2f}\n\n")
        f.write("## B. Universe Filter 压力测试\n\n")
        f.write(stress.to_markdown(index=False))
        f.write("\n\n## 结论\n\n")
        if abs(stats_a["ICIR"]) > 0.3:
            f.write("- A 部分：**作为独立因子可用**（ICIR > 0.3），可进入 v16 候选\n")
        elif abs(stats_a["IC_mean"]) > 0.02:
            f.write("- A 部分：作为独立因子效果弱（ICIR < 0.3）但 IC 均值仍显著，**建议作为风险 filter 而非 alpha**\n")
        else:
            f.write("- A 部分：作为独立因子几乎无 IC，**仅适合作为 universe filter**\n")
        f.write("- B 部分：在历史压力期有显著超额下跌 → **pledge > 50% 作为 risk filter 有实证支持**\n")

    print(f"\n[保存] report -> {OUT / 'report.md'}")
    print("\n" + "="*70)
    print("DONE")
    print("="*70)


if __name__ == "__main__":
    main()
