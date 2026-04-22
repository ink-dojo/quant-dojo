"""
RIAD — Retail-Institution Attention Divergence 因子

核心假设 (Barber & Odean 2008 + A 股 retail dominance):
    - 散户注意力驱动买入 → attention bias → 短期追高 → 未来收益差
    - 机构调研驱动研究 → informed interest → 未来收益好
    - 二者背离越大, cross-sectional signal 越强

因子构造:
    retail_attn_s,t  = 过去 N 日股票 s 在 ths_hot + dc_hot A 股榜单的加权得分
                       (在榜得分 = (top_n - rank + 1) / top_n, 不在榜 = 0)
    inst_attn_s,t    = 过去 N 日股票 s 在 stk_surv 的调研机构数 log1p
    RIAD_s,t         = zscore(retail_attn) - zscore(inst_attn)
    信号方向         = 做多 RIAD 低分 (机构关注高 / 散户关注低)
                       做空 RIAD 高分 (散户关注高 / 机构关注低)

数据依赖 (见 journal/tushare_data_inventory_20260420.md):
    data/raw/tushare/ths_hot/{year}/ths_hot_YYYYMMDD.parquet — 同花顺热榜 (2020+)
    data/raw/tushare/dc_hot/{year}/dc_hot_YYYYMMDD.parquet   — 东财热榜 (2020+)
    data/raw/tushare/stk_surv/stk_surv_{symbol6}.parquet     — 机构调研 (2023-10+)

样本期间: 2023-10 ~ 2026-04 (受 stk_surv 起点约束),
         重点评估 2025 年作为 out-of-sample regime.
"""
from __future__ import annotations

import logging
from pathlib import Path

import numpy as np
import pandas as pd

log = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parents[3]
THS_DIR = ROOT / "data" / "raw" / "tushare" / "ths_hot"
DC_DIR = ROOT / "data" / "raw" / "tushare" / "dc_hot"
STK_SURV_DIR = ROOT / "data" / "raw" / "tushare" / "stk_surv"

# A 股股票代码首位白名单:
#   SH: 600/601/603/605 主板, 688 科创
#   SZ: 000/001 主板, 002/003 中小, 300/301 创业
#   BJ: 北交所 4xxxxx/8xxxxx
# 排除: ETF (15/16/18/51/52/58), 封基, LOF, 指数
_A_SHARE_SH = r"^(60[01358]|688)\d{3}\.SH$"
_A_SHARE_SZ = r"^(00[012]|003|30[01])\d{3}\.SZ$"
_A_SHARE_BJ = r"^[48]\d{5}\.BJ$"
A_SHARE_PATTERN = f"({_A_SHARE_SH})|({_A_SHARE_SZ})|({_A_SHARE_BJ})"


def _is_a_share(ts_code: pd.Series) -> pd.Series:
    return ts_code.astype(str).str.match(A_SHARE_PATTERN, na=False)


def load_retail_hot_daily(start: str, end: str) -> pd.DataFrame:
    """
    聚合 ths_hot + dc_hot 每日 A 股热度榜单.

    对每只 A 股每日至多保留 ths 和 dc 两个分数的最大值.
    得分 = (榜单容量 - rank + 1) / 榜单容量, 线性衰减 [0, 1].

    返回: long-format DataFrame with columns [trade_date, ts_code, retail_score]
    """
    start_i, end_i = int(start.replace("-", "")), int(end.replace("-", ""))
    records: list[pd.DataFrame] = []

    for src_dir, name in [(THS_DIR, "ths"), (DC_DIR, "dc")]:
        if not src_dir.exists():
            log.warning("hot source missing: %s", src_dir)
            continue
        for year_dir in sorted(src_dir.iterdir()):
            if not year_dir.is_dir():
                continue
            for f in sorted(year_dir.glob("*.parquet")):
                # 文件名形如 ths_hot_20250102.parquet
                try:
                    date_i = int(f.stem.split("_")[-1])
                except ValueError:
                    continue
                if date_i < start_i or date_i > end_i:
                    continue
                try:
                    df = pd.read_parquet(f)
                except Exception as e:  # 损坏的 parquet 跳过
                    log.debug("skip corrupt %s: %s", f.name, e)
                    continue
                if "ts_code" not in df.columns or "rank" not in df.columns or df.empty:
                    continue
                df = df[_is_a_share(df["ts_code"])]
                if df.empty:
                    continue
                top_n = len(df)
                df = df.loc[:, ["trade_date", "ts_code", "rank"]].copy()
                df["retail_score"] = (top_n - df["rank"].astype(float) + 1.0) / top_n
                df["source"] = name
                records.append(df[["trade_date", "ts_code", "retail_score", "source"]])

    if not records:
        return pd.DataFrame(columns=["trade_date", "ts_code", "retail_score"])

    all_df = pd.concat(records, ignore_index=True)
    # 同一日同一 ts_code 取 ths/dc 两者中的较大值 (攻击性口径)
    agg = (
        all_df.groupby(["trade_date", "ts_code"])["retail_score"]
        .max()
        .reset_index()
    )
    agg["trade_date"] = pd.to_datetime(
        agg["trade_date"].astype(str).str.strip(), format="%Y%m%d"
    )
    return agg


def load_inst_surveys(start: str, end: str) -> pd.DataFrame:
    """
    加载 stk_surv 机构调研明细, 按 (trade_date, ts_code) 聚合参与机构数.

    返回: long-format DataFrame with columns [trade_date, ts_code, n_surv]
    n_surv = 当日该股票被调研的独立机构数 (rece_org 去重)
    """
    if not STK_SURV_DIR.exists():
        return pd.DataFrame(columns=["trade_date", "ts_code", "n_surv"])

    start_i, end_i = int(start.replace("-", "")), int(end.replace("-", ""))
    frames: list[pd.DataFrame] = []
    for f in sorted(STK_SURV_DIR.glob("stk_surv_*.parquet")):
        df = pd.read_parquet(f, columns=["ts_code", "surv_date", "rece_org"])
        if df.empty:
            continue
        df = df[df["surv_date"].astype(int).between(start_i, end_i)]
        if df.empty:
            continue
        frames.append(df)

    if not frames:
        return pd.DataFrame(columns=["trade_date", "ts_code", "n_surv"])

    raw = pd.concat(frames, ignore_index=True)
    # 以日-股-机构粒度去重, 然后 count
    raw = raw.drop_duplicates(subset=["ts_code", "surv_date", "rece_org"])
    out = (
        raw.groupby(["surv_date", "ts_code"])["rece_org"]
        .count()
        .reset_index()
        .rename(columns={"surv_date": "trade_date", "rece_org": "n_surv"})
    )
    out["trade_date"] = pd.to_datetime(out["trade_date"].astype(str), format="%Y%m%d")
    return out


def _to_wide(df_long: pd.DataFrame, value_col: str, index_dates: pd.DatetimeIndex) -> pd.DataFrame:
    """long → wide, reindex 到统一交易日历, 缺失填 0 (无关注 = 分数 0)."""
    if df_long.empty:
        return pd.DataFrame(index=index_dates)
    wide = (
        df_long.pivot_table(
            index="trade_date",
            columns="ts_code",
            values=value_col,
            aggfunc="sum",
            fill_value=0.0,
        )
        .reindex(index_dates, fill_value=0.0)
    )
    return wide


def build_attention_panel(
    start: str,
    end: str,
    trade_calendar: pd.DatetimeIndex,
    retail_window: int = 20,
    inst_window: int = 60,
) -> dict[str, pd.DataFrame]:
    """
    构造散户/机构关注度宽表 (wide panels).

    retail_window : 散户关注度的 rolling 求和窗口 (默认 20 日 ≈ 1 个月)
    inst_window   : 机构关注度的 rolling 求和窗口 (默认 60 日 ≈ 3 个月,
                    因机构调研 sparse 需更长窗口覆盖)

    返回 dict:
        retail_attn : wide DataFrame (dates × symbols), rolling sum 后的散户分数
        inst_attn   : wide DataFrame (dates × symbols), rolling sum 后的机构调研机构数
    """
    retail_long = load_retail_hot_daily(start, end)
    inst_long = load_inst_surveys(start, end)

    retail_wide_daily = _to_wide(retail_long, "retail_score", trade_calendar)
    inst_wide_daily = _to_wide(inst_long, "n_surv", trade_calendar)

    retail_attn = retail_wide_daily.rolling(retail_window, min_periods=1).sum()
    inst_attn = inst_wide_daily.rolling(inst_window, min_periods=1).sum()

    return {"retail_attn": retail_attn, "inst_attn": inst_attn}


def compute_riad_factor(
    retail_attn: pd.DataFrame,
    inst_attn: pd.DataFrame,
    min_coverage: int = 200,
) -> pd.DataFrame:
    """
    计算 RIAD 因子 (散户-机构 关注度背离).

    因子值 = cross-section zscore(retail_attn) - cross-section zscore(log1p(inst_attn))

    注意:
        - 只在 cross-section 同时存在 retail_attn > 0 或 inst_attn > 0 的股票上计算.
        - 机构调研 sparse, 用 log1p 压缩.
        - 每日截面样本 < min_coverage 时该日因子整体置 NaN.

    返回: wide DataFrame (dates × symbols), NaN 表示当日该股不可打分.
    """
    # symbols 用并集: 有 retail 无 inst 的股票 = 机构不关心 (inst=0), 也要参与排序
    common_dates = retail_attn.index.intersection(inst_attn.index)
    all_syms = retail_attn.columns.union(inst_attn.columns)
    ra = retail_attn.reindex(index=common_dates, columns=all_syms, fill_value=0.0)
    ia_raw = inst_attn.reindex(index=common_dates, columns=all_syms, fill_value=0.0)
    ia = np.log1p(ia_raw)

    # 关注度任一 > 0 才计分, 其余置 NaN (避免 0/0 零分股稀释截面)
    mask = (ra > 0) | (ia > 0)
    ra_masked = ra.where(mask)
    ia_masked = ia.where(mask)

    # 按行 zscore (cross-section)
    def _zscore_row(df: pd.DataFrame) -> pd.DataFrame:
        mu = df.mean(axis=1)
        sd = df.std(axis=1).replace(0.0, np.nan)
        return df.sub(mu, axis=0).div(sd, axis=0)

    ra_z = _zscore_row(ra_masked)
    ia_z = _zscore_row(ia_masked)

    factor = ra_z - ia_z

    # 覆盖度门限
    daily_count = factor.notna().sum(axis=1)
    factor = factor.where(daily_count.reindex(factor.index) >= min_coverage, np.nan)
    return factor


if __name__ == "__main__":
    # 最小验证: 2025 年一季度
    print("=== RIAD 因子最小验证 (2025-01 ~ 2025-03) ===")
    start, end = "2025-01-01", "2025-03-31"

    # 构造简短交易日历 (用 daily_basic 000001 当期日作为参考)
    db = pd.read_parquet(
        ROOT / "data" / "raw" / "tushare" / "daily_basic" / "000001.parquet",
        columns=["trade_date"],
    )
    db["trade_date"] = pd.to_datetime(db["trade_date"].astype(str), format="%Y%m%d")
    cal = pd.DatetimeIndex(
        sorted(
            db[(db["trade_date"] >= start) & (db["trade_date"] <= end)]["trade_date"].unique()
        )
    )
    print(f"交易日: {len(cal)}  ({cal[0].date()} ~ {cal[-1].date()})")

    panels = build_attention_panel(start, end, cal)
    print(f"retail_attn shape: {panels['retail_attn'].shape}")
    print(f"inst_attn shape:   {panels['inst_attn'].shape}")
    print(f"retail_attn 非零覆盖 (最近一日): {(panels['retail_attn'].iloc[-1] > 0).sum()} 只")
    print(f"inst_attn   非零覆盖 (最近一日): {(panels['inst_attn'].iloc[-1] > 0).sum()} 只")

    factor = compute_riad_factor(panels["retail_attn"], panels["inst_attn"])
    print(f"RIAD factor shape: {factor.shape}")
    latest = factor.iloc[-1].dropna()
    print(f"最新一日有效股票数: {len(latest)}")
    print(f"RIAD 分位: p10={latest.quantile(0.1):.3f} | p50={latest.quantile(0.5):.3f} | p90={latest.quantile(0.9):.3f}")
    print("最 negative (机构关注 > 散户关注) Top 10:")
    print(latest.nsmallest(10).to_string())
    print("最 positive (散户关注 > 机构关注) Top 10:")
    print(latest.nlargest(10).to_string())
    print("✅ 最小验证通过")
