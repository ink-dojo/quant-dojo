"""
每日信号生成管道
加载数据 → 计算因子 → 合成评分 → 过滤 → 输出选股名单
"""
import json
import os
import warnings
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

from utils.local_data_loader import (
    load_price_wide,
    load_factor_wide,
    get_all_symbols,
)

SIGNAL_DIR = Path(__file__).parent.parent / "live" / "signals"
SNAPSHOT_DIR = Path(__file__).parent.parent / "live" / "factor_snapshot"

# 过滤参数常量
_MIN_PRICE = 2.0
_MIN_LISTING_DAYS = 60


def run_daily_pipeline(
    date: str = None,
    n_stocks: int = 30,
    symbols: list = None,
) -> dict:
    """
    生成当日选股信号

    参数:
        date     : 信号日期，如 "2026-03-20"，默认取数据最新日期；
                   若指定日期在数据中不存在则抛出 ValueError
        n_stocks : 选股数量，默认 30
        symbols  : 股票池，默认全 A 股

    返回:
        dict，包含 date, picks, scores, factor_values, excluded, metadata
    """
    if symbols is None:
        symbols = get_all_symbols()

    n_input_symbols = len(symbols)

    # 确定日期范围（因子计算需要回看窗口）
    end = date or "2026-03-20"
    start = str(int(end[:4]) - 1) + end[4:]  # 回看1年

    # ── 加载数据 ──────────────────────────────────────────────
    try:
        price_wide = load_price_wide(symbols, start, end, field="close")
    except Exception as e:
        warnings.warn(f"加载价格数据失败: {e}")
        return {"date": end, "picks": [], "scores": {}, "error": str(e)}

    if price_wide.empty:
        return {"date": end, "picks": [], "scores": {}, "error": "无价格数据"}

    # 实际最新日期
    actual_date = str(price_wide.index[-1].date())

    # ── 日期校验：指定日期必须存在于数据中 ────────────────────
    if date is not None:
        index_dates = [str(d.date()) for d in price_wide.index]
        if date not in index_dates:
            raise ValueError(
                f"指定日期 {date} 在数据中不存在，最新可用日期为 {actual_date}"
            )

    ret_wide = price_wide.pct_change()

    # ── 计算因子 ──────────────────────────────────────────────
    factor_dict = {}

    # 1. 动量因子（20日）：过去20日收益率
    mom_20 = price_wide.pct_change(20).iloc[-1]
    factor_dict["momentum_20"] = mom_20

    # 2. EP（盈利收益率 = 1/PE，反向因子）
    try:
        pe_wide = load_factor_wide(symbols, "pe_ttm", start, end)
        ep = (1.0 / pe_wide.iloc[-1]).replace([np.inf, -np.inf], np.nan)
        ep[pe_wide.iloc[-1] <= 0] = np.nan  # PE 为负的置 NaN
        factor_dict["ep"] = ep
    except Exception:
        warnings.warn("PE 数据不可用，跳过 EP 因子")

    # 3. 低波动因子（20日实现波动率取负）
    vol_20 = ret_wide.rolling(20).std().iloc[-1] * np.sqrt(252)
    factor_dict["low_vol"] = -vol_20  # 取负：低波动 = 高分

    # 4. 换手率反转（取负：低换手 = 高分）
    try:
        turnover_wide = load_factor_wide(symbols, "turnover", start, end)
        turnover_20 = turnover_wide.rolling(20).mean().iloc[-1]
        factor_dict["turnover_rev"] = -turnover_20
    except Exception:
        warnings.warn("换手率数据不可用，跳过换手率因子")

    # ── 截面标准化 + 等权合成 ──────────────────────────────────
    scored = pd.DataFrame(factor_dict)
    # z-score 标准化
    scored = (scored - scored.mean()) / scored.std()
    # 等权合成
    composite = scored.mean(axis=1)

    # ── 过滤 ──────────────────────────────────────────────────
    excluded = {"st": 0, "new_listing": 0, "low_price": 0}

    # 排除 ST
    try:
        st_wide = load_factor_wide(symbols, "is_st", start, end)
        st_mask = st_wide.iloc[-1] == 1
        excluded["st"] = int(st_mask.sum())
        composite[st_mask.reindex(composite.index, fill_value=False)] = np.nan
    except Exception:
        pass

    # 排除上市不足 _MIN_LISTING_DAYS 日
    valid_days = price_wide.notna().sum()
    new_mask = valid_days < _MIN_LISTING_DAYS
    excluded["new_listing"] = int(new_mask.sum())
    composite[new_mask.reindex(composite.index, fill_value=False)] = np.nan

    # 排除价格 < _MIN_PRICE 元
    last_price = price_wide.iloc[-1]
    low_mask = last_price < _MIN_PRICE
    excluded["low_price"] = int(low_mask.sum())
    composite[low_mask.reindex(composite.index, fill_value=False)] = np.nan

    # ── 选股 ──────────────────────────────────────────────────
    composite = composite.dropna().sort_values(ascending=False)
    n_after_filters = len(composite)
    picks = composite.head(n_stocks).index.tolist()
    scores = composite.head(n_stocks).to_dict()

    # 因子原始值（选中的股票）
    factor_values = {}
    for fname, fvals in factor_dict.items():
        factor_values[fname] = {
            sym: round(float(fvals.get(sym, np.nan)), 4)
            for sym in picks
            if not np.isnan(fvals.get(sym, np.nan))
        }

    # ── 元数据 ────────────────────────────────────────────────
    metadata = {
        "n_input_symbols": n_input_symbols,
        "n_after_filters": n_after_filters,
        "config_snapshot": {
            "n_stocks": n_stocks,
            "min_price": _MIN_PRICE,
            "min_listing_days": _MIN_LISTING_DAYS,
        },
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }

    result = {
        "date": actual_date,
        "picks": picks,
        "scores": {k: round(float(v), 4) for k, v in scores.items()},
        "factor_values": factor_values,
        "excluded": excluded,
        "metadata": metadata,
    }

    # ── 原子写入：先写临时文件，成功后重命名 ──────────────────
    SIGNAL_DIR.mkdir(parents=True, exist_ok=True)
    SNAPSHOT_DIR.mkdir(parents=True, exist_ok=True)

    signal_path = SIGNAL_DIR / f"{actual_date}.json"
    signal_tmp = signal_path.with_suffix(".tmp")
    snapshot_path = SNAPSHOT_DIR / f"{actual_date}.parquet"
    snapshot_tmp = snapshot_path.with_suffix(".tmp")

    # ── JSON 信号写入（必须成功） ──────────────────
    try:
        # 写信号 JSON 到临时文件
        with open(signal_tmp, "w", encoding="utf-8") as f:
            json.dump(result, f, ensure_ascii=False, indent=2)
        signal_tmp.rename(signal_path)
    except Exception as e:
        # 清理 JSON 临时文件，避免留下损坏数据
        if signal_tmp.exists():
            signal_tmp.unlink()
        raise

    # ── 因子快照写入（可选，失败时仅警告） ──────────────────
    try:
        snapshot = pd.DataFrame(factor_dict)
        snapshot.to_parquet(snapshot_tmp)
        snapshot_tmp.rename(snapshot_path)
    except Exception as e:
        # 清理快照临时文件
        if snapshot_tmp.exists():
            snapshot_tmp.unlink()
        # 发出警告但不中断主流程
        warnings.warn(
            f"因子快照写入失败（通常因 pyarrow 未安装）: {e}",
            stacklevel=2
        )

    print(f"✅ 信号已生成: {actual_date}")
    print(f"   选股 {len(picks)} 只，排除 ST={excluded['st']} 次新={excluded['new_listing']} 低价={excluded['low_price']}")
    print(f"   保存: {signal_path}")

    return result


if __name__ == "__main__":
    # 最小验证：用最新日期生成信号
    result = run_daily_pipeline(date="2026-03-20")
    print(f"\n选股名单（前10）: {result['picks'][:10]}")
    print(f"排除统计: {result['excluded']}")
