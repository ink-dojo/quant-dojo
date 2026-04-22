"""
FMD — Foreign-Margin Divergence 因子

核心假设 (smart money vs levered retail):
    - 北向持股 (外资, HK-Connect) 代表 informed / long-horizon 资金
    - 融资余额 (两融) 代表 retail leverage / sentiment-driven 资金
    - 两者方向背离时 cross-sectional 信号最强:
        * 北向 ↑ + 融资 ↓ (外资加仓, 散户减杠杆)  → bullish
        * 北向 ↓ + 融资 ↑ (外资撤离, 散户追高加杠杆) → bearish

因子构造 (N 日 = 20 交易日默认):
    nb_chg_s,t    = (nb_ratio[t] - nb_ratio[t-N]) / max(nb_ratio[t-N], 0.1)
                    北向持股占流通比例的 N 日变化 (相对)
    margin_chg_s,t = log(rzye[t]) - log(rzye[t-N])
                    融资余额 N 日对数变化
    FMD_s,t       = zscore(nb_chg) - zscore(margin_chg)
    信号方向      = 做多 FMD 高分, 做空 FMD 低分 (正向因子)

数据依赖:
    data/raw/tushare/northbound/{symbol6}.parquet  (2017+, 覆盖 HK-Connect 标的)
    data/raw/tushare/margin/{symbol6}.parquet      (两融标的)

样本交集约 1,000 只大中盘股 (northbound ∩ margin), 是差异化点 —
主流 factor research 集中在全 A 股 cross-section, 但 FMD 专门在
大中盘+蓝筹层面捕捉 "smart vs levered retail" divergence.
"""
from __future__ import annotations

import logging
from pathlib import Path

import numpy as np
import pandas as pd

log = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parents[3]
NB_DIR = ROOT / "data" / "raw" / "tushare" / "northbound"
MG_DIR = ROOT / "data" / "raw" / "tushare" / "margin"


def load_northbound_panel(start: str, end: str) -> pd.DataFrame:
    """聚合 northbound/ 每日持股 ratio (占流通市值 %).

    返回: wide DataFrame (date × ts_code), NaN = 非 HK-Connect 标的或停牌.
    """
    start_i, end_i = int(start.replace("-", "")), int(end.replace("-", ""))
    frames = []
    for f in sorted(NB_DIR.glob("*.parquet")):
        try:
            df = pd.read_parquet(f, columns=["ts_code", "trade_date", "ratio"])
        except Exception:
            continue
        if df.empty:
            continue
        df = df[df["trade_date"].astype(int).between(start_i, end_i)]
        if df.empty:
            continue
        frames.append(df)
    if not frames:
        return pd.DataFrame()
    raw = pd.concat(frames, ignore_index=True)
    raw["trade_date"] = pd.to_datetime(
        raw["trade_date"].astype(str).str.strip(), format="%Y%m%d"
    )
    wide = raw.pivot_table(
        index="trade_date", columns="ts_code", values="ratio", aggfunc="last"
    )
    return wide


def load_margin_panel(start: str, end: str) -> pd.DataFrame:
    """聚合 margin/ 每日融资余额 rzye (元).

    返回: wide DataFrame (date × ts_code).
    """
    start_i, end_i = int(start.replace("-", "")), int(end.replace("-", ""))
    frames = []
    for f in sorted(MG_DIR.glob("*.parquet")):
        try:
            df = pd.read_parquet(f, columns=["ts_code", "trade_date", "rzye"])
        except Exception:
            continue
        if df.empty:
            continue
        df = df[df["trade_date"].astype(int).between(start_i, end_i)]
        if df.empty:
            continue
        frames.append(df)
    if not frames:
        return pd.DataFrame()
    raw = pd.concat(frames, ignore_index=True)
    raw["trade_date"] = pd.to_datetime(
        raw["trade_date"].astype(str).str.strip(), format="%Y%m%d"
    )
    wide = raw.pivot_table(
        index="trade_date", columns="ts_code", values="rzye", aggfunc="last"
    )
    return wide


def compute_fmd_factor(
    nb_ratio: pd.DataFrame,
    margin_rzye: pd.DataFrame,
    window: int = 20,
    min_coverage: int = 200,
) -> pd.DataFrame:
    """FMD 因子 (正向因子: 值越大越应做多).

    nb_chg:     N 日北向 ratio 相对变化 (ratio 单位是 %, 直接相减避免除零)
    margin_chg: N 日融资余额对数变化
    FMD       = cross-section zscore(nb_chg) - zscore(margin_chg)
    """
    # 对齐到并集: 有 margin 无 northbound 的股票, nb_chg 视为 NaN 从截面剔除
    common_dates = nb_ratio.index.intersection(margin_rzye.index)
    common_syms = nb_ratio.columns.intersection(margin_rzye.columns)
    nb = nb_ratio.loc[common_dates, common_syms]
    mg = margin_rzye.loc[common_dates, common_syms]

    # N 日差分
    nb_chg = nb - nb.shift(window)  # percentage point change in ratio
    # 融资余额可为 0 (两融标的调出), 先用前值填后再 log
    mg_filled = mg.replace(0.0, np.nan).ffill(limit=3)
    mg_chg = np.log(mg_filled) - np.log(mg_filled.shift(window))

    # cross-section zscore
    def _zscore_row(df: pd.DataFrame) -> pd.DataFrame:
        mu = df.mean(axis=1)
        sd = df.std(axis=1).replace(0.0, np.nan)
        return df.sub(mu, axis=0).div(sd, axis=0)

    nb_z = _zscore_row(nb_chg)
    mg_z = _zscore_row(mg_chg)

    factor = nb_z - mg_z

    daily_count = factor.notna().sum(axis=1)
    factor = factor.where(daily_count >= min_coverage, np.nan)
    return factor


if __name__ == "__main__":
    print("=== FMD 因子最小验证 (2025-01 ~ 2025-03) ===")
    start, end = "2024-10-01", "2025-03-31"  # 留出 window buffer

    nb = load_northbound_panel(start, end)
    mg = load_margin_panel(start, end)
    print(f"northbound 宽表: {nb.shape}")
    print(f"margin 宽表: {mg.shape}")
    print(f"交集 symbols: {len(nb.columns.intersection(mg.columns))}")

    factor = compute_fmd_factor(nb, mg, window=20)
    factor_2025 = factor.loc["2025-01-01":"2025-03-31"]
    print(f"FMD 因子 (2025Q1): {factor_2025.shape}")
    latest = factor_2025.iloc[-1].dropna()
    print(f"最新一日有效股票数: {len(latest)}")
    if len(latest):
        print(
            f"FMD 分位: p10={latest.quantile(0.1):.3f} | "
            f"p50={latest.quantile(0.5):.3f} | "
            f"p90={latest.quantile(0.9):.3f}"
        )
        print("最 positive (外资加仓 + 散户减杠杆) Top 10:")
        print(latest.nlargest(10).to_string())
        print("最 negative (外资撤离 + 散户加杠杆) Top 10:")
        print(latest.nsmallest(10).to_string())
    print("✅ 最小验证通过")
