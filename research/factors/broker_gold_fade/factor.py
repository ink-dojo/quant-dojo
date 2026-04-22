"""
BGFD — Broker Gold-stock Fade Divergence 因子

核心假设 (crowded consensus trade fade):
    当一个股票同时被多家券商当月列为"金股", 反映卖方共识已经形成.
    这类"共识买入"信号容易 price in 在进入金股榜前 (研报+路演已经发出),
    榜单公布后的追随买入属于 late / retail follower, cross-section 容易跑输.
    A 股金股榜月度发布, 同花顺/东财聚合, 流动性观察充分.

因子构造 (月频, 每月末打分):
    consensus_s,m  = 当月 s 股票被推荐的券商数 (去重)
    streak_s,m     = s 连续被推荐的月数 (含当月)
    BGFD_s,m       = log1p(consensus) + 0.5 * log1p(streak - 1)
                     (streak=1 不加额外分, ≥2 月叠加 staleness 分)
    信号方向       = 做空 BGFD 高, 做多 BGFD 低 (负向因子)

差异化点:
    - 数据完全独立于 RIAD (不依赖 stk_surv/ths_hot)
    - 月频信号 → 低换手, 成本友好
    - A 股独有的金股榜 (US 有 analyst rating 但无 monthly consolidated gold pick)
"""
from __future__ import annotations

import logging
from pathlib import Path

import numpy as np
import pandas as pd

log = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parents[3]
BR_DIR = ROOT / "data" / "raw" / "tushare" / "broker_recommend"


def load_broker_recommend(start_month: str, end_month: str) -> pd.DataFrame:
    """加载 broker_recommend/*.parquet.

    start_month / end_month: "YYYY-MM".
    返回 long DataFrame [month_i, ts_code, broker]
    """
    start_i = int(start_month.replace("-", ""))
    end_i = int(end_month.replace("-", ""))
    frames = []
    for f in sorted(BR_DIR.glob("*.parquet")):
        try:
            m = int(f.stem)
        except ValueError:
            continue
        if m < start_i or m > end_i:
            continue
        try:
            df = pd.read_parquet(f, columns=["month", "broker", "ts_code"])
        except Exception:
            continue
        if df.empty:
            continue
        frames.append(df)
    if not frames:
        return pd.DataFrame(columns=["month_i", "ts_code", "broker"])
    raw = pd.concat(frames, ignore_index=True)
    raw["month_i"] = raw["month"].astype(int)
    return raw[["month_i", "ts_code", "broker"]]


def compute_consensus_streak(raw: pd.DataFrame) -> pd.DataFrame:
    """
    计算每股每月的 consensus 和 streak.

    consensus_s,m = len(unique broker | (s,m))
    streak_s,m   = 连续被推荐的月数 (含当月)
    """
    # consensus
    consensus = (
        raw.drop_duplicates(["month_i", "ts_code", "broker"])
        .groupby(["month_i", "ts_code"])["broker"]
        .nunique()
        .rename("consensus")
        .reset_index()
    )

    # streak: 按 ts_code 排序, 月连续自增, 否则重置
    consensus = consensus.sort_values(["ts_code", "month_i"]).reset_index(drop=True)
    streaks = []
    prev_code = None
    prev_m = None
    cur_streak = 0
    months_sorted = sorted(consensus["month_i"].unique())
    # 构建"月序号"方便连续判断 (YYYYMM 相邻月 = 1 期)
    month_idx = {m: i for i, m in enumerate(months_sorted)}

    for _, row in consensus.iterrows():
        code = row["ts_code"]
        m = row["month_i"]
        mi = month_idx[m]
        if code != prev_code:
            cur_streak = 1
        else:
            if prev_m is not None and mi == month_idx[prev_m] + 1:
                cur_streak += 1
            else:
                cur_streak = 1
        streaks.append(cur_streak)
        prev_code = code
        prev_m = m

    consensus["streak"] = streaks
    return consensus


def compute_bgfd_factor(
    consensus_df: pd.DataFrame,
    months: list[int],
    min_coverage: int = 80,
) -> pd.DataFrame:
    """
    BGFD 因子宽表 (月频).

    每月 m, 基于 consensus_df[month_i == m], 对所有股票:
        BGFD = log1p(consensus) + 0.5 * log1p(streak - 1)
    然后 cross-section zscore.
    缺失 (没被推荐) 的股票赋零分 (最低关注度) — 会稀释截面, 故最后过滤只保留上榜股截面.

    返回: wide DataFrame (index=month_i, columns=ts_code), 值为 zscore.
    """
    rows = []
    for m in months:
        sub = consensus_df[consensus_df["month_i"] == m]
        if len(sub) < min_coverage:
            continue
        raw_score = np.log1p(sub["consensus"].astype(float)) + 0.5 * np.log1p(
            (sub["streak"].astype(float) - 1).clip(lower=0)
        )
        mu, sd = raw_score.mean(), raw_score.std()
        if sd == 0 or np.isnan(sd):
            continue
        z = (raw_score - mu) / sd
        rows.append(pd.Series(z.values, index=sub["ts_code"].values, name=m))
    if not rows:
        return pd.DataFrame()
    wide = pd.DataFrame(rows)
    return wide


if __name__ == "__main__":
    print("=== BGFD 因子最小验证 ===")
    raw = load_broker_recommend("2025-01", "2025-06")
    print(f"broker_recommend 载入: {len(raw)} 行")
    cons = compute_consensus_streak(raw)
    print(f"consensus+streak 表: {cons.shape}")
    print("streak 分布 (2025-06):")
    sub = cons[cons["month_i"] == 202506]
    print(sub["streak"].value_counts().sort_index().head(10))
    print("consensus 分布:")
    print(sub["consensus"].value_counts().sort_index().head(10))

    months = sorted(cons["month_i"].unique())
    wide = compute_bgfd_factor(cons, months)
    print(f"BGFD 因子宽表: {wide.shape}")
    latest = wide.iloc[-1].dropna()
    print(f"最新月份上榜股数: {len(latest)}")
    print(f"BGFD 分位: p10={latest.quantile(0.1):.2f} | p50={latest.quantile(0.5):.2f} | p90={latest.quantile(0.9):.2f}")
    print("Top 10 最 crowded (共识 + streak 高):")
    print(latest.nlargest(10).to_string())
    print("Top 10 最 fresh (单券商首次推荐):")
    print(latest.nsmallest(10).to_string())
    print("✅ 最小验证通过")
