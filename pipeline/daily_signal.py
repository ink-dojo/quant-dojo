"""
每日信号生成管道
加载数据 → 计算因子 → 合成评分 → 过滤 → 输出选股名单
"""
import argparse
import json
import os
import warnings
from datetime import datetime, timezone, date as _date
from pathlib import Path

import numpy as np
import pandas as pd

from utils.alpha_factors import (
    team_coin,
    low_vol_20d,
    enhanced_momentum,
    bp_factor,
)
from utils.factor_analysis import neutralize_factor_by_industry, compute_ic_series
from utils.fundamental_loader import get_industry_classification
from utils.local_data_loader import (
    load_price_wide,
    load_factor_wide,
    get_all_symbols,
)

SIGNAL_DIR = Path(__file__).parent.parent / "live" / "signals"
SNAPSHOT_DIR = Path(__file__).parent.parent / "live" / "factor_snapshot"


def _get_filter_params():
    """
    从运行时配置读取过滤参数。
    降级策略：runtime_config → 硬编码默认值

    返回:
        tuple: (min_price, min_listing_days, signal_n_stocks)
    """
    try:
        from utils.runtime_config import (
            get_min_price,
            get_min_listing_days,
            get_signal_n_stocks,
        )
        return (
            get_min_price(),
            get_min_listing_days(),
            get_signal_n_stocks(),
        )
    except Exception:
        # 降级到硬编码默认值
        return 2.0, 60, 30


def run_daily_pipeline(
    date: str = None,
    n_stocks: int = None,
    symbols: list = None,
    strategy: str = "ad_hoc",
) -> dict:
    """
    生成当日选股信号

    参数:
        date     : 信号日期，如 "2026-03-20"，默认取当日日期；
                   若指定日期在数据中不存在则抛出 ValueError
        n_stocks : 选股数量，默认从运行时配置读取；若明确指定则使用指定值
        symbols  : 股票池，默认全 A 股
        strategy : 因子策略，"ad_hoc"（默认）或 "v7"
                   ad_hoc: 动量/EP/低波动/换手率反转等权合成
                   v7: team_coin + low_vol_20d + cgo_simple + enhanced_momentum + bp
                       行业中性化 + IC 加权合成

    返回:
        dict，包含 date, picks, scores, factor_values, excluded, metadata
    """
    # 读取运行时配置的过滤参数
    min_price, min_listing_days, default_n_stocks = _get_filter_params()

    # 若 n_stocks 未指定，使用配置值；否则使用显式指定的值
    if n_stocks is None:
        n_stocks = default_n_stocks

    if symbols is None:
        symbols = get_all_symbols()

    n_input_symbols = len(symbols)

    # 确定日期范围（因子计算需要回看窗口）
    end = date or datetime.now().strftime("%Y-%m-%d")
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

    if strategy == "v7":
        # ── v7 策略：行业中性化 + IC 加权合成 ────────────────
        # 计算各因子宽表（日期 × 股票）
        try:
            team_coin_wide = team_coin(price_wide)
        except Exception:
            warnings.warn("team_coin 计算失败，跳过")
            team_coin_wide = pd.DataFrame(np.nan, index=price_wide.index, columns=price_wide.columns)

        try:
            low_vol_wide = low_vol_20d(price_wide)
        except Exception:
            warnings.warn("low_vol_20d 计算失败，跳过")
            low_vol_wide = pd.DataFrame(np.nan, index=price_wide.index, columns=price_wide.columns)

        try:
            enhanced_mom_wide = enhanced_momentum(price_wide)
        except Exception:
            warnings.warn("enhanced_momentum 计算失败，跳过")
            enhanced_mom_wide = pd.DataFrame(np.nan, index=price_wide.index, columns=price_wide.columns)

        # cgo_simple = -(price / price.rolling(60).mean() - 1)
        cgo_simple_wide = -(price_wide / price_wide.rolling(60).mean() - 1)

        # bp 因子需要 PB 数据
        bp_wide = pd.DataFrame(np.nan, index=price_wide.index, columns=price_wide.columns)
        try:
            pb_wide = load_factor_wide(symbols, "pb", start, end)
            if not pb_wide.empty:
                bp_wide = bp_factor(pb_wide)
        except Exception:
            warnings.warn("PB 数据不可用，跳过 bp 因子")

        raw_factors = {
            "team_coin": team_coin_wide,
            "low_vol_20d": low_vol_wide,
            "cgo_simple": cgo_simple_wide,
            "enhanced_mom_60": enhanced_mom_wide,
            "bp": bp_wide,
        }

        # 行业分类
        try:
            industry_df = get_industry_classification(symbols=symbols)
        except Exception as e:
            warnings.warn(f"行业分类加载失败: {e}")
            industry_df = pd.DataFrame(columns=["symbol", "industry_code"])

        # 对每个因子做行业中性化，然后 IC 加权合成
        neutralized_factors = {}
        ic_series_dict = {}
        for name, fac_wide in raw_factors.items():
            if fac_wide.empty or fac_wide.dropna().shape[0] < 30:
                continue
            try:
                neutral = neutralize_factor_by_industry(fac_wide, industry_df)
            except Exception as e:
                warnings.warn(f"中性化失败 {name}: {e}")
                neutral = fac_wide
            neutralized_factors[name] = neutral
            # 计算 IC 序列（用当日因子值与次日收益的截面相关）
            try:
                ic_s = compute_ic_series(neutral, ret_wide, method="spearman")
                ic_series_dict[name] = ic_s
            except Exception:
                pass

        # IC 加权合成：取最近 60 日 IC 均值绝对值作为权重
        if neutralized_factors and ic_series_dict:
            ic_df = pd.DataFrame(ic_series_dict)
            rolling_ic = ic_df.rolling(60, min_periods=20).mean()
            last_ic = rolling_ic.iloc[-1].abs()
            total_ic = last_ic.sum()
            if total_ic > 0:
                weights = last_ic / total_ic
            else:
                weights = pd.Series(1.0 / len(neutralized_factors), index=last_ic.index)
        else:
            n = len(neutralized_factors) or 1
            weights = pd.Series(1.0 / n, index=neutralized_factors.keys())

        # 加权合成 composite
        composite_series = None
        for name, fac_wide in neutralized_factors.items():
            w = weights.get(name, 0)
            # 取最后一个交易日
            last_vals = fac_wide.iloc[-1]
            if composite_series is None:
                composite_series = last_vals * w
            else:
                composite_series = composite_series + last_vals * w

        composite = composite_series.dropna().sort_values(ascending=False)
        # Store raw (non-neutralized) factors for factor_values output
        factor_dict = {name: raw_factors[name].iloc[-1] for name in raw_factors}
        # 快照用中性化后的因子（factor_monitor 需要这些做 IC 计算）
        snapshot_dict = {name: fac_wide.iloc[-1] for name, fac_wide in neutralized_factors.items()}

    else:
        # ── ad_hoc 策略（默认） ──────────────────────────────
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

        # 截面标准化 + 等权合成
        scored = pd.DataFrame(factor_dict)
        # z-score 标准化
        scored = (scored - scored.mean()) / scored.std()
        # 等权合成
        composite = scored.mean(axis=1)
        # ad_hoc 分支：快照与 factor_dict 一致（无中性化步骤）
        snapshot_dict = factor_dict

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

    # 排除上市不足 min_listing_days 日
    valid_days = price_wide.notna().sum()
    new_mask = valid_days < min_listing_days
    excluded["new_listing"] = int(new_mask.sum())
    composite[new_mask.reindex(composite.index, fill_value=False)] = np.nan

    # 排除价格 < min_price 元
    last_price = price_wide.iloc[-1]
    low_mask = last_price < min_price
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
        "strategy": strategy,
        "factors_used": list(factor_dict.keys()),
        "config_snapshot": {
            "n_stocks": n_stocks,
            "min_price": min_price,
            "min_listing_days": min_listing_days,
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
        snapshot = pd.DataFrame(snapshot_dict)
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
    parser = argparse.ArgumentParser(description="每日信号生成管道")
    parser.add_argument("--date", type=str, default=None, help="信号日期，如 2026-03-20")
    parser.add_argument("--n-stocks", type=int, default=None, help="选股数量")
    parser.add_argument(
        "--strategy",
        type=str,
        default="ad_hoc",
        choices=["ad_hoc", "v7"],
        help="因子策略：ad_hoc（默认）或 v7（行业中性+IC加权）",
    )
    args = parser.parse_args()

    result = run_daily_pipeline(
        date=args.date,
        n_stocks=args.n_stocks,
        strategy=args.strategy,
    )
    print(f"\n选股名单（前10）: {result['picks'][:10]}")
    print(f"排除统计: {result['excluded']}")
    print(f"策略: {result['metadata'].get('strategy', 'unknown')}")
