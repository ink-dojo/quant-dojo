"""
THCC — Top-Holder Concentration Change 因子

核心假设 (institutional stealth accumulation):
    前十大流通股东持股合计占比 (concentration) 是"筹码集中度"的 proxy.
    季度环比上升 ⇒ 机构持续吸筹 / 筹码锁定 ⇒ 未来季度超额.
    下降 ⇒ 机构撤离 / 筹码松动 ⇒ 未来负 alpha.

更差异化变体 (THCC-INST):
    只统计 institutional holders (保险/基金/证券/社保/QFII), 排除个人 & 一般企业.
    纯机构集中度变化比混合口径更干净.

数据 (tushare.top10_floatholders):
    end_date       : 季度末 (3/31, 6/30, 9/30, 12/31)
    ann_date       : 公告日 (通常季度末后 1-1.5 个月披露)
    hold_float_ratio: 流通股占比 %
    holder_type    : 持有人性质

样本期: 每季度 1 个截面, 2015Q1+, 覆盖约 4,000 只有季报股东明细的股票.

因子频率: 季度调仓.
Universe : 有季度披露的股票 (约 4,000).
信号方向 : 做多 concentration_change > 0 的股票 (正向因子).
"""
from __future__ import annotations

import logging
from pathlib import Path

import numpy as np
import pandas as pd

log = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parents[3]
TFH_DIR = ROOT / "data" / "raw" / "tushare" / "top10_floatholders"

INST_KEYWORDS = (
    "保险", "基金", "证券", "信托", "银行", "社保", "QFII",
    "资管", "投资管理", "企业年金", "共同基金", "养老",
    "公募", "私募",
)


def _is_institutional(holder_type: str | None, holder_name: str | None) -> bool:
    """判断 holder 是否为机构 (保险/基金/证券/信托/社保/QFII/资管等)."""
    if holder_type:
        for kw in INST_KEYWORDS:
            if kw in str(holder_type):
                return True
    if holder_name:
        for kw in INST_KEYWORDS:
            if kw in str(holder_name):
                return True
    return False


def load_top10_float(start_year: int, end_year: int) -> pd.DataFrame:
    """
    聚合 top10_floatholders.

    返回 long DataFrame [ts_code, ann_date, end_date, hold_float_ratio, is_inst]
    end_date/ann_date 为 pandas Timestamp.
    """
    frames = []
    for f in sorted(TFH_DIR.glob("*.parquet")):
        try:
            df = pd.read_parquet(
                f,
                columns=["ts_code", "ann_date", "end_date",
                         "holder_name", "hold_float_ratio", "holder_type"],
            )
        except Exception:
            continue
        if df.empty:
            continue
        # end_date 年份筛选
        df["end_year"] = df["end_date"].astype(str).str[:4].astype(int)
        df = df[df["end_year"].between(start_year, end_year)]
        if df.empty:
            continue
        frames.append(df)
    if not frames:
        return pd.DataFrame()
    raw = pd.concat(frames, ignore_index=True)
    raw["end_date"] = pd.to_datetime(
        raw["end_date"].astype(str).str.strip(), format="%Y%m%d", errors="coerce"
    )
    raw["ann_date"] = pd.to_datetime(
        raw["ann_date"].astype(str).str.strip(), format="%Y%m%d", errors="coerce"
    )
    raw = raw.dropna(subset=["end_date", "ann_date"])
    raw["is_inst"] = raw.apply(
        lambda r: _is_institutional(r.get("holder_type"), r.get("holder_name")),
        axis=1,
    )
    raw["hold_float_ratio"] = raw["hold_float_ratio"].astype(float).fillna(0.0)
    return raw[["ts_code", "ann_date", "end_date", "hold_float_ratio", "is_inst"]]


def compute_thcc_factors(raw: pd.DataFrame) -> dict[str, pd.DataFrame]:
    """
    计算两个 THCC 变体:
        THCC-ALL  : 前 10 大合计占比 季度环比变化
        THCC-INST : 前 10 大中 institutional 合计占比 季度环比变化

    返回 dict:
        'thcc_all'  : wide DataFrame (index=ann_date, columns=ts_code)
        'thcc_inst' : wide DataFrame, 机构口径
        'conc_all'  : wide 水平值 (用于排序 & debug)
        'conc_inst' : wide 水平值
    """
    # 每 (ts_code, end_date) 汇总
    grp = raw.groupby(["ts_code", "end_date", "ann_date"])
    conc_all = grp["hold_float_ratio"].sum().rename("conc_all").reset_index()
    conc_inst = (
        raw[raw["is_inst"]].groupby(["ts_code", "end_date", "ann_date"])["hold_float_ratio"]
        .sum()
        .rename("conc_inst")
        .reset_index()
    )

    merged = conc_all.merge(conc_inst, on=["ts_code", "end_date", "ann_date"], how="left")
    merged["conc_inst"] = merged["conc_inst"].fillna(0.0)

    # 按 ts_code 排序 end_date, 取季度环比变化
    merged = merged.sort_values(["ts_code", "end_date"]).reset_index(drop=True)
    merged["thcc_all"] = merged.groupby("ts_code")["conc_all"].diff()
    merged["thcc_inst"] = merged.groupby("ts_code")["conc_inst"].diff()

    # ann_date 作为 signal 可用日 (信号在 ann_date 日开盘后可观察到)
    # 宽表: index = ann_date, columns = ts_code
    def _pivot(col: str) -> pd.DataFrame:
        w = merged.pivot_table(
            index="ann_date", columns="ts_code", values=col, aggfunc="last"
        )
        return w

    return {
        "thcc_all": _pivot("thcc_all"),
        "thcc_inst": _pivot("thcc_inst"),
        "conc_all": _pivot("conc_all"),
        "conc_inst": _pivot("conc_inst"),
    }


if __name__ == "__main__":
    print("=== THCC 因子最小验证 (2024-2025) ===")
    raw = load_top10_float(2024, 2025)
    print(f"raw rows: {len(raw)}")
    fac = compute_thcc_factors(raw)
    for k, v in fac.items():
        print(f"  {k}: shape={v.shape}, ann_date min/max = {v.index.min().date() if len(v) else 'N/A'} / {v.index.max().date() if len(v) else 'N/A'}")

    latest_ann = fac["thcc_inst"].index.max()
    latest = fac["thcc_inst"].loc[latest_ann].dropna()
    print(f"\n最新公告日 {latest_ann.date()}, 有效股数: {len(latest)}")
    print(f"THCC-INST 分位: p10={latest.quantile(0.1):.3f} p50={latest.quantile(0.5):.3f} p90={latest.quantile(0.9):.3f}")
    print("机构加仓最多 Top 10:")
    print(latest.nlargest(10).to_string())
    print("机构撤离最多 Top 10:")
    print(latest.nsmallest(10).to_string())
    print("✅ 最小验证通过")
