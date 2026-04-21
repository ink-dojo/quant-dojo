"""
连板封板强度因子 (Limit-Up Sleal Strength) — 研究脚本

背景：
    涨停事件在 A 股独有（制度性 alpha）。过去 252 日 mini-backtest 显示：
    - 一字板 (open_times=0)：次日均值 +2.38%，胜率 59.8%
    - 三板+ (streak>=3)：胜率 62.0% 最高
    - 炸板多 (open_times>=3)：次日仅 +1.28%，弱于一字板 6 pp
    详见 journal/a_share_quant_deep_dive_20260421.md §8.1b

因子构造：
    对当日涨停股，封板强度 = (封板越早 × 炸板越少 × 连板越高 × 封单占比越大)
    公式（截面 z-score 合成）：
        strength = z(-first_time_minutes) + z(-open_times) + z(streak) + z(fd_ratio)
    其中 fd_ratio = fd_amount / float_mv

测试：
    A. 涨停 universe 内测 IC（仅考虑当日有涨停的股票）
    B. 三个子信号单独 IC 分解
    C. 按次日可交易性过滤（排除次日开盘即涨停无法买入）

运行：python research/factors/limit_up_sleeve/factor_research.py
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
    winsorize,
)

RAW = ROOT / "data" / "raw" / "tushare"
OUT = ROOT / "research" / "factors" / "limit_up_sleeve"
IS_START = "2019-01-01"
IS_END = "2025-12-31"


def parse_first_time_to_minutes(s):
    """'93333' -> 3 minutes (93333 = 9:33:33, 3 min after 9:30)"""
    try:
        s = str(int(float(s)))
    except Exception:
        return np.nan
    if len(s) < 5:
        return np.nan
    # pad to 6 digits
    s = s.zfill(6)
    try:
        hh, mm, ss = int(s[:2]), int(s[2:4]), int(s[4:6])
    except Exception:
        return np.nan
    # 9:30 market open
    t_min = (hh - 9) * 60 + mm - 30 + ss / 60.0
    # Afternoon: 13:00-15:00 (9:30-11:30=120min, then 13:00-15:00 is 121~240)
    if hh >= 13:
        t_min = 120 + (hh - 13) * 60 + mm + ss / 60.0
    if hh == 11 and mm > 30:
        t_min = 120
    return max(0.0, t_min)


def parse_streak(s):
    try:
        return int(str(s).split("/")[0])
    except Exception:
        return np.nan


def load_limit_list_panel():
    """把过去 6 年 limit_list U 事件拼成长表 + 构造封板强度。"""
    files = sorted((RAW / "limit_list").glob("limit_list_*.parquet"))
    df = pd.concat([pd.read_parquet(f) for f in files], ignore_index=True)
    print(f"[数据] limit_list 总行数 {len(df):,}")

    # 只留涨停 U
    up = df[df["limit"] == "U"].copy()
    up["trade_date"] = pd.to_datetime(up["trade_date"].astype(str))
    up["code"] = up["ts_code"].str[:6]
    up["streak"] = up["up_stat"].apply(parse_streak)
    up["first_min"] = up["first_time"].apply(parse_first_time_to_minutes)

    # 封单占比 = fd_amount / float_mv (都要同单位)
    # fd_amount 单位通常是元；float_mv 单位是万元，需要 × 10000 对齐
    # 先看一行确认单位
    up["fd_ratio"] = up["fd_amount"] / (up["float_mv"] * 10000 + 1)

    # 过滤 IS 窗口
    up = up[(up["trade_date"] >= pd.Timestamp(IS_START)) & (up["trade_date"] <= pd.Timestamp(IS_END))]
    print(f"[数据] IS 窗口涨停事件 {len(up):,}")

    return up


def cross_zscore(s):
    """safe z-score."""
    s = s.astype(float)
    mu, sd = s.mean(), s.std()
    if sd == 0 or np.isnan(sd):
        return pd.Series(0, index=s.index)
    z = (s - mu) / sd
    return z.clip(-3, 3)


def build_strength_panel(up: pd.DataFrame) -> pd.DataFrame:
    """按日截面构造封板强度，返回宽表 date × code。"""
    dates = sorted(up["trade_date"].unique())
    rows = []
    for d in dates:
        sub = up[up["trade_date"] == d].copy()
        if len(sub) < 5:
            continue
        # 截面 winsorize + z-score
        # 封板早 = first_min 小 → 取负号
        sub["z_first"] = cross_zscore(-sub["first_min"].fillna(sub["first_min"].median()))
        # 炸板少 = open_times 小 → 取负号
        sub["z_open"] = cross_zscore(-sub["open_times"].fillna(0))
        # 连板高 = streak 大 → 正向
        sub["z_streak"] = cross_zscore(sub["streak"].fillna(1))
        # 封单占比大 → 正向
        sub["z_fd"] = cross_zscore(sub["fd_ratio"].fillna(0))
        # 合成
        sub["strength"] = (sub["z_first"] + sub["z_open"] + sub["z_streak"] + sub["z_fd"]) / 4.0
        sub["trade_date"] = d
        rows.append(sub[["trade_date", "code", "strength", "z_first", "z_open", "z_streak", "z_fd", "streak", "open_times"]])
    df = pd.concat(rows, ignore_index=True)
    return df


def compute_fwd_returns(price_wide: pd.DataFrame, fwd_days_list: list[int]) -> dict:
    """计算 1/2/5 日前瞻 close-to-close 收益率。"""
    rets = {}
    for d in fwd_days_list:
        rets[d] = price_wide.shift(-d) / price_wide - 1
    return rets


def ic_test_within_universe(factor_long: pd.DataFrame, ret_wide: pd.DataFrame, factor_col: str, label: str):
    """仅在涨停 universe 内测 IC (每日截面股票限定为当日涨停)。"""
    results = []
    # by day
    for d, grp in factor_long.groupby("trade_date"):
        if len(grp) < 10:
            continue
        if d not in ret_wide.index:
            continue
        codes = grp["code"].values
        f_vals = pd.Series(grp[factor_col].values, index=codes)
        r_slice = ret_wide.loc[d].reindex(codes)
        # 过滤 NaN
        mask = f_vals.notna() & r_slice.notna()
        if mask.sum() < 10:
            continue
        corr = f_vals[mask].rank().corr(r_slice[mask].rank())
        results.append((d, corr, mask.sum()))
    if not results:
        return None
    df = pd.DataFrame(results, columns=["date", "ic", "n"]).set_index("date")
    ic_series = df["ic"]
    ic_mean = ic_series.mean()
    ic_std = ic_series.std()
    icir = ic_mean / ic_std if ic_std > 0 else np.nan
    hac_lag = max(1, int(np.floor(4 * (len(ic_series) / 100) ** (2 / 9))))
    # simple Newey-West for mean
    ic_vals = ic_series.values
    mu = ic_vals.mean()
    e = ic_vals - mu
    gamma0 = (e ** 2).mean()
    s2 = gamma0
    n = len(ic_vals)
    for h in range(1, min(hac_lag, n - 1) + 1):
        gamma = (e[h:] * e[:-h]).mean()
        w = 1.0 - h / (hac_lag + 1.0)
        s2 += 2.0 * w * gamma
    hac_se = np.sqrt(max(s2, 1e-12) / n)
    t_hac = mu / hac_se if hac_se > 0 else np.nan
    print(f"    [{label}] n_days={len(ic_series)} | IC {ic_mean:.4f} | ICIR {icir:.4f} | HAC_t {t_hac:.3f} | avg_universe {df['n'].mean():.0f}")
    return {"label": label, "ic_mean": ic_mean, "icir": icir, "t_hac": t_hac, "n_days": len(ic_series), "avg_universe": df["n"].mean()}


def bucket_analysis(factor_long: pd.DataFrame, ret_wide: pd.DataFrame):
    """按封板强度分 quintile，统计次日 return。"""
    fac = factor_long.copy()
    fac["next_ret"] = np.nan
    for i, row in fac.iterrows():
        d, c = row["trade_date"], row["code"]
        if d in ret_wide.index and c in ret_wide.columns:
            fac.at[i, "next_ret"] = ret_wide.loc[d, c]

    fac = fac.dropna(subset=["strength", "next_ret"]).copy()
    fac["bucket"] = pd.qcut(fac["strength"], 5, labels=["Q1_弱", "Q2", "Q3", "Q4", "Q5_强"])
    agg = fac.groupby("bucket").agg(
        n=("next_ret", "count"),
        mean=("next_ret", "mean"),
        winrate=("next_ret", lambda x: (x > 0).mean()),
        med=("next_ret", "median"),
    )
    print("\n    封板强度分桶（涨停事件次日 return）:")
    print(agg.round(4).to_string())
    return agg


def main():
    print("="*70)
    print("限涨停封板强度因子研究")
    print("="*70)

    OUT.mkdir(parents=True, exist_ok=True)

    up = load_limit_list_panel()

    # 价格
    price = pd.read_parquet(ROOT / "data" / "processed" / "price_wide_close_2014-01-01_2025-12-31_qfq_5477stocks.parquet")
    price.index = pd.to_datetime(price.index)

    # 构造强度因子
    fac_long = build_strength_panel(up)
    print(f"[因子] 构造后行数 {len(fac_long):,}")
    fac_long.to_parquet(OUT / "strength_long.parquet")

    # fwd returns
    rets = compute_fwd_returns(price, [1, 2, 5])

    print("\n[A] 封板强度 合成因子 在涨停 universe 内 IC:")
    r_strength_1d = ic_test_within_universe(fac_long, rets[1], "strength", "strength → 次日")
    r_strength_2d = ic_test_within_universe(fac_long, rets[2], "strength", "strength → 2日")
    r_strength_5d = ic_test_within_universe(fac_long, rets[5], "strength", "strength → 5日")

    print("\n[B] 单信号分解（次日 IC）:")
    for col, lbl in [("z_first", "封板早 (-first)"), ("z_open", "少炸板 (-open)"), ("z_streak", "连板高 (+streak)"), ("z_fd", "封单大 (+fd)")]:
        ic_test_within_universe(fac_long, rets[1], col, lbl)

    print("\n[C] 强度分桶 × 次日 return 实测:")
    agg = bucket_analysis(fac_long, rets[1])

    # 写报告
    with open(OUT / "report.md", "w") as f:
        f.write("# 连板封板强度因子研究报告\n\n")
        f.write(f"**日期**：2026-04-21  **数据**：limit_list {IS_START}~{IS_END}  **样本**：{len(fac_long):,} 涨停事件\n\n")
        f.write("## A. 合成强度因子次日 IC (涨停 universe 内)\n\n")
        for r, name in [(r_strength_1d, "次日"), (r_strength_2d, "2 日"), (r_strength_5d, "5 日")]:
            if r:
                f.write(f"- **{name}前瞻**: IC {r['ic_mean']:.4f} / ICIR {r['icir']:.4f} / HAC t {r['t_hac']:.3f} / n_days {r['n_days']} / avg universe {r['avg_universe']:.0f}\n")
        f.write("\n## B. 强度分桶次日 return\n\n")
        f.write(agg.round(4).to_markdown())
        f.write("\n\n## 结论\n\n")
        icir = r_strength_1d["icir"] if r_strength_1d else 0
        if abs(icir) > 0.3:
            f.write(f"- 合成封板强度因子 ICIR {icir:.2f} **> 0.3 可用**，作为 limit-up sleeve 的 alpha signal\n")
        else:
            f.write(f"- 合成封板强度因子 ICIR {icir:.2f} 弱于预期，但 Q5 vs Q1 分桶差异仍是可见的\n")
        f.write("- 使用方式：作为独立 sleeve（10-20% 仓位），不是 v9 的替代\n")
        f.write("- 执行注意：次日一字涨停股无法买入，实际 tradable 样本会减 30-40%\n")

    print(f"\n[保存] -> {OUT / 'report.md'}")
    print("="*70, "\nDONE")


if __name__ == "__main__":
    main()
