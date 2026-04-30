"""
MD&A 漂移因子 alphalens 审计（年度因子，含 forward fill）

因子: data/processed/mda_drift_scores.parquet
索引: fiscal_year (int)，列: symbol，值: drift score
说明: 年度报告 MD&A 文本相对前一年度的漂移程度。

为了让 alphalens 能 quintile cut，做两步:
  1. (fiscal_year, symbol) → publish_date → 下一交易日（effective_date）
  2. effective_date 之后向前持有一年（forward fill），让每个交易日截面都有
     几百只股票同时被观察 —— 否则因子稀疏导致 quantile bin 崩溃

数据局限:
    - 只覆盖 2019-2025 fiscal years 共 7 年
    - 全样本仅 500 只股票
    - 是年频信号，forward returns 用 20/60/120/250 日
    - 跳过 consistency_check（alphalens 内部 fill_method='pad' 与本地不可对齐）

跑法:
    python research/alphalens_audits/audit_mda_drift.py
"""
from __future__ import annotations

from pathlib import Path
import sys

import numpy as np
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))

from research.alphalens_audits._runner import _load_default_price_panel, run_audit  # noqa: E402


FACTOR_PATH = PROJECT_ROOT / "data" / "processed" / "mda_drift_scores.parquet"
MANIFEST_PATH = PROJECT_ROOT / "data" / "processed" / "mda_drift_manifest.parquet"


def map_fiscal_year_to_publish_date(
    factor_long: pd.DataFrame,
    manifest: pd.DataFrame,
    trading_calendar: pd.DatetimeIndex,
) -> pd.DataFrame:
    """
    把 (fiscal_year, symbol, score) 长表 join 上 manifest 的 publish_date，
    publish_date 对齐到下一个交易日（年报常常周末/盘后披露），
    返回 (date, symbol) 宽表。
    """
    m = manifest[["symbol", "fiscal_year", "publish_date"]].copy()
    m["publish_date"] = pd.to_datetime(m["publish_date"])

    # 向量化对齐到下一个交易日（searchsorted on the whole Series, 而不是 .apply 逐行）
    cal = trading_calendar.sort_values()
    idx = cal.searchsorted(m["publish_date"].values, side="left")
    safe_idx = np.minimum(idx, len(cal) - 1)
    eff = cal.values[safe_idx]
    m["effective_date"] = pd.to_datetime(np.where(idx >= len(cal), pd.NaT, eff))
    m = m.dropna(subset=["effective_date"])

    merged = factor_long.merge(m, on=["symbol", "fiscal_year"], how="inner")
    # 同一 (symbol, year) 多份披露 → 取最早 effective_date
    merged = merged.sort_values("effective_date").drop_duplicates(
        subset=["symbol", "fiscal_year"], keep="first"
    )
    wide = merged.pivot_table(
        index="effective_date", columns="symbol", values="score"
    )
    wide.index.name = "date"
    return wide.sort_index()


def main():
    raw = pd.read_parquet(FACTOR_PATH)  # idx=fiscal_year, cols=symbol
    print(f"raw factor: {raw.shape} fiscal_years={raw.index.tolist()}")

    factor_long = (
        raw.stack(future_stack=True)
        .dropna()
        .rename("score")
        .reset_index()
    )
    print(f"long-format records: {len(factor_long)}")

    manifest = pd.read_parquet(MANIFEST_PATH)
    print(f"manifest: {manifest.shape}")

    # 主价格宽表只读一次：既给 trading_calendar 也透传给 run_audit（避免重复读 ~MB 级 parquet）
    price_panel = _load_default_price_panel()
    trading_calendar = pd.DatetimeIndex(price_panel.index)

    factor_sparse = map_fiscal_year_to_publish_date(
        factor_long, manifest, trading_calendar
    )
    print(
        f"sparse wide: {factor_sparse.shape}, "
        f"date range {factor_sparse.index.min().date()} ~ {factor_sparse.index.max().date()}"
    )

    # 把稀疏年频因子 forward fill 到日度
    # 每个 (date, symbol) 取最近一次 publish 的 score，最多持有 250 个交易日
    factor_daily = factor_sparse.reindex(
        trading_calendar.intersection(
            pd.date_range(
                factor_sparse.index.min(),
                factor_sparse.index.max() + pd.Timedelta(days=400),
            )
        )
    ).ffill(limit=250)
    factor_wide = factor_daily.dropna(how="all")
    print(
        f"daily-ffilled wide: {factor_wide.shape}, non-NaN ratio per row median: "
        f"{factor_wide.notna().sum(axis=1).median():.0f} stocks/day"
    )

    # 年度因子用更长的 forward returns；
    # 稀疏年频数据（7×500）和 alphalens 内部 pad 行为对不齐，跳过一致性校验
    run_audit(
        factor_name="mda_drift",
        factor_wide=factor_wide,
        price_wide=price_panel,
        periods=(20, 60, 120, 250),
        quantiles=5,
        skip_consistency=True,
    )


if __name__ == "__main__":
    main()
