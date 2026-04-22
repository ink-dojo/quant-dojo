"""
LULR — Limit-Up Ladder Reversal 因子

核心假设 (2025 量化打板泛化后的反转溢价):
    高位连板股 (up_stat N/M 中 N ≥ 3) 通常处于情绪炒作末端,
    T+1 炸板概率 (open_times) 已经抬升, 散户追涨盘进来后往往无人接力.
    量化打板策略 (板后卖出) 泛化后, 连板高度与反转力度相关性更强.

信号来源 (tushare.limit_list):
    up_stat N/M   - 过去 M 日内 N 次涨停 (连板加权)
    limit_times   - 当日触及涨停次数
    open_times    - 当日炸板开板次数
    limit U/Z/D   - U=封板, Z=未封, D=跌停

因子构造 (每日):
    streak_s,t    = N (从 up_stat 解析)
    tightness_s,t = 1 if limit == 'U' else 0.3 if limit == 'Z' else 0
    fragility_s,t = open_times (当日炸板数)
    LULR_s,t      = log1p(streak) * tightness - 0.3 * log1p(fragility)
    信号方向      = 做空 LULR 高 = 高连板 + 封板紧但炸过 = 情绪末端

持仓窗口: 5 交易日 (短周期反转)
Universe: 所有出现在 limit_list 的股票 (约每天 100 只)
            → 只能做"上榜内"排序, 不做全 A cross-section.

和 RIAD/MFD/BGFD 差异:
    - 短周期 (5 日 vs 20 日)
    - 事件驱动 (涨停触发)
    - 不需要 size/industry 中性化 (universe 已过滤)
"""
from __future__ import annotations

import logging
from pathlib import Path

import numpy as np
import pandas as pd

log = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parents[3]
LL_DIR = ROOT / "data" / "raw" / "tushare" / "limit_list"


def _parse_up_stat(val: str | None) -> int:
    """解析 up_stat 'N/M' 返回 N (连板次数). 空值或无效返回 0."""
    if val is None or pd.isna(val):
        return 0
    try:
        n_str, _ = str(val).split("/")
        return int(n_str)
    except (ValueError, AttributeError):
        return 0


def load_limit_list(start: str, end: str) -> pd.DataFrame:
    """
    加载 limit_list/*.parquet 为 long DataFrame.

    返回 columns: [trade_date, ts_code, streak, fragility, limit_type, close]
        streak    = up_stat 里的 N (连板天数)
        fragility = open_times (当日炸板数)
        limit_type = U / Z / D
    """
    start_i, end_i = int(start.replace("-", "")), int(end.replace("-", ""))
    frames = []
    for f in sorted(LL_DIR.glob("*.parquet")):
        try:
            date_i = int(f.stem.split("_")[-1])
        except ValueError:
            continue
        if date_i < start_i or date_i > end_i:
            continue
        try:
            df = pd.read_parquet(
                f,
                columns=["trade_date", "ts_code", "up_stat", "open_times", "limit", "close"],
            )
        except Exception:
            continue
        if df.empty:
            continue
        frames.append(df)
    if not frames:
        return pd.DataFrame()
    raw = pd.concat(frames, ignore_index=True)
    raw["trade_date"] = pd.to_datetime(
        raw["trade_date"].astype(str).str.strip(), format="%Y%m%d"
    )
    raw["streak"] = raw["up_stat"].apply(_parse_up_stat).astype(float)
    raw["fragility"] = raw["open_times"].fillna(0).astype(float)
    return raw[["trade_date", "ts_code", "streak", "fragility", "limit", "close"]].rename(
        columns={"limit": "limit_type"}
    )


def compute_lulr_factor(long: pd.DataFrame) -> pd.DataFrame:
    """
    LULR 因子宽表.

    因子值 (每日每股, 仅 limit_list 覆盖的股票):
        tightness = 1.0 if limit_type == 'U' else 0.3 if 'Z' else -1.0  (D 跌停反向)
        LULR = log1p(streak) * tightness - 0.3 * log1p(fragility)

    返回 wide DataFrame (date × ts_code), NaN = 当日未上榜.
    """
    df = long.copy()
    df["tightness"] = np.where(
        df["limit_type"] == "U", 1.0,
        np.where(df["limit_type"] == "Z", 0.3, -1.0)
    )
    df["raw_score"] = (
        np.log1p(df["streak"]) * df["tightness"] - 0.3 * np.log1p(df["fragility"])
    )
    wide = df.pivot_table(
        index="trade_date", columns="ts_code", values="raw_score", aggfunc="last"
    )
    return wide


if __name__ == "__main__":
    print("=== LULR 因子最小验证 (2025Q1) ===")
    long = load_limit_list("2024-12-01", "2025-03-31")
    print(f"limit_list long rows: {len(long)}")
    wide = compute_lulr_factor(long)
    print(f"LULR 宽表: {wide.shape}")
    latest = wide.iloc[-1].dropna()
    print(f"最新一日上榜股数: {len(latest)}")
    print(f"因子分位: p10={latest.quantile(0.1):.2f} | p50={latest.quantile(0.5):.2f} | p90={latest.quantile(0.9):.2f}")
    print("最 high ladder (连板 + 封板) Top 10:")
    print(latest.nlargest(10).to_string())
    print("最 fragile (炸板 / 跌停) Top 10:")
    print(latest.nsmallest(10).to_string())
    print("✅ 最小验证通过")
