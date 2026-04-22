"""
MFD — MoneyFlow Divergence 因子

核心假设:
    超大单 (elg) ≈ 机构/大户行为, 小单 (sm) ≈ 散户行为.
    两者方向背离时 cross-sectional 信号最强:
        * 机构净流入 + 散户净流出 → bullish (informed accumulation)
        * 机构净流出 + 散户净流入 → bearish (distribution to retail)

    这个背离假设比"净资金流"(net_mf_amount) 更精细,
    因为 net_mf 把 sm/md/lg/elg 简单合并, 掩盖 smart/dumb money 对立.

因子构造 (N 日 = 20 交易日默认, 即约 1 个月):
    elg_net_s,t  = sum_{t-N+1..t} (buy_elg_amount - sell_elg_amount)
    sm_net_s,t   = sum_{t-N+1..t} (buy_sm_amount  - sell_sm_amount)
    total_amt_s,t = sum_{t-N+1..t} (全部买入 + 全部卖出金额)
    elg_ratio    = elg_net / total_amt
    sm_ratio     = sm_net  / total_amt
    MFD_s,t      = cross-section zscore(elg_ratio) - zscore(sm_ratio)

    信号方向 = 做多 MFD 高分 (正向因子)

数据依赖 (2020-01-02 至今 ~ 每股 1523 日):
    data/raw/tushare/moneyflow/{symbol6}.parquet

差异化点 (vs 传统 net_mf_amount):
    - 拆分机构 (elg) 与散户 (sm) 信号, 在 divergence 最大的截面位做信号
    - 避免 net_mf 被中单 (md: 4~20 万元) 稀释
    - 2025 年 A 股量化化程度上升, elg vs sm divergence 的 alpha 稳定性应增强
"""
from __future__ import annotations

import logging
from pathlib import Path

import numpy as np
import pandas as pd

log = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parents[3]
MF_DIR = ROOT / "data" / "raw" / "tushare" / "moneyflow"

USED_COLS = [
    "ts_code", "trade_date",
    "buy_sm_amount", "sell_sm_amount",
    "buy_md_amount", "sell_md_amount",
    "buy_lg_amount", "sell_lg_amount",
    "buy_elg_amount", "sell_elg_amount",
]


def load_moneyflow_long(start: str, end: str) -> pd.DataFrame:
    """拼装 moneyflow long-format panel.

    返回 columns: [trade_date(datetime), ts_code, elg_net, sm_net, total_amt]
    """
    start_i, end_i = int(start.replace("-", "")), int(end.replace("-", ""))
    frames = []
    for f in sorted(MF_DIR.glob("*.parquet")):
        try:
            df = pd.read_parquet(f, columns=USED_COLS)
        except Exception:
            continue
        if df.empty:
            continue
        df = df[df["trade_date"].astype(int).between(start_i, end_i)]
        if df.empty:
            continue
        frames.append(df)
    if not frames:
        return pd.DataFrame(columns=["trade_date", "ts_code", "elg_net", "sm_net", "total_amt"])

    raw = pd.concat(frames, ignore_index=True)
    raw["trade_date"] = pd.to_datetime(
        raw["trade_date"].astype(str).str.strip(), format="%Y%m%d"
    )
    raw["elg_net"] = raw["buy_elg_amount"] - raw["sell_elg_amount"]
    raw["sm_net"] = raw["buy_sm_amount"] - raw["sell_sm_amount"]
    raw["total_amt"] = (
        raw["buy_sm_amount"] + raw["sell_sm_amount"] +
        raw["buy_md_amount"] + raw["sell_md_amount"] +
        raw["buy_lg_amount"] + raw["sell_lg_amount"] +
        raw["buy_elg_amount"] + raw["sell_elg_amount"]
    )
    return raw[["trade_date", "ts_code", "elg_net", "sm_net", "total_amt"]]


def _to_wide(df_long: pd.DataFrame, value_col: str) -> pd.DataFrame:
    return df_long.pivot_table(
        index="trade_date", columns="ts_code", values=value_col, aggfunc="last"
    )


def compute_mfd_factor(
    start: str,
    end: str,
    window: int = 20,
    min_coverage: int = 500,
) -> pd.DataFrame:
    """MFD 因子计算.

    window        : rolling 窗口长度 (交易日)
    min_coverage  : 截面最小有效股数
    """
    long = load_moneyflow_long(start, end)
    if long.empty:
        return pd.DataFrame()

    elg_wide = _to_wide(long, "elg_net").sort_index()
    sm_wide = _to_wide(long, "sm_net").sort_index()
    tot_wide = _to_wide(long, "total_amt").sort_index()

    # N 日累积
    elg_sum = elg_wide.rolling(window, min_periods=window).sum()
    sm_sum = sm_wide.rolling(window, min_periods=window).sum()
    tot_sum = tot_wide.rolling(window, min_periods=window).sum()

    # 归一化: 除以 N 日总成交额, 再乘 2 (因为 buy+sell 重复计, 但比例上等价)
    denom = tot_sum.replace(0.0, np.nan)
    elg_ratio = elg_sum / denom
    sm_ratio = sm_sum / denom

    def _zscore_row(df: pd.DataFrame) -> pd.DataFrame:
        mu = df.mean(axis=1)
        sd = df.std(axis=1).replace(0.0, np.nan)
        return df.sub(mu, axis=0).div(sd, axis=0)

    elg_z = _zscore_row(elg_ratio)
    sm_z = _zscore_row(sm_ratio)
    factor = elg_z - sm_z

    daily_count = factor.notna().sum(axis=1)
    factor = factor.where(daily_count >= min_coverage, np.nan)
    return factor


if __name__ == "__main__":
    print("=== MFD 因子最小验证 (2025Q1) ===")
    start, end = "2024-10-01", "2025-03-31"  # 前留 window buffer
    factor = compute_mfd_factor(start, end, window=20)
    print(f"factor shape: {factor.shape}")
    factor_2025 = factor.loc["2025-01-01":"2025-03-31"]
    print(f"2025Q1 非空日数: {factor_2025.notna().any(axis=1).sum()}")
    print(f"日均有效股数: {factor_2025.notna().sum(axis=1).mean():.0f}")
    latest = factor.iloc[-1].dropna()
    print(f"最新一日有效: {len(latest)}")
    if len(latest):
        print(
            f"MFD 分位: p10={latest.quantile(0.1):.3f} | "
            f"p50={latest.quantile(0.5):.3f} | "
            f"p90={latest.quantile(0.9):.3f}"
        )
        print("Top 10 最 positive (机构买 + 散户卖):")
        print(latest.nlargest(10).to_string())
        print("Top 10 最 negative (机构卖 + 散户买):")
        print(latest.nsmallest(10).to_string())
    print("✅ 最小验证通过")
