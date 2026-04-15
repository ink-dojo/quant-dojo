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
    shadow_lower,
    idiosyncratic_volatility,
    industry_momentum,
    insider_buying_proxy,
    amihud_illiquidity,
    price_volume_divergence,
)
from utils.factor_analysis import neutralize_factor_by_industry, compute_ic_series
from utils.fundamental_loader import get_industry_classification
from utils.local_data_loader import (
    load_price_wide,
    load_factor_wide,
    get_all_symbols,
)
from utils.listing_metadata import universe_at_date

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

    # 确定日期范围（因子计算需要回看窗口）
    end = date or datetime.now().strftime("%Y-%m-%d")
    start = str(int(end[:4]) - 1) + end[4:]  # 回看1年

    if symbols is None:
        # 用"当日已上市且尚未退市"的股票池，修复幸存者偏差。
        # 若元数据模块失败（首次运行网络异常等），退回 get_all_symbols()
        try:
            symbols = universe_at_date(end, require_local_data=True)
            if not symbols:
                warnings.warn(f"universe_at_date({end}) 返回空，退回 get_all_symbols")
                symbols = get_all_symbols()
        except Exception as exc:
            warnings.warn(f"listing_metadata 不可用，退回 get_all_symbols（有幸存者偏差）: {exc}")
            symbols = get_all_symbols()

    n_input_symbols = len(symbols)

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

    # 注意时间方向：IC 权重应用 T 日因子预测 T+1 日收益（forward return）。
    # pct_change() 是当日收益（T 日因子 ↔ T 日收益），存在前视偏差。
    # shift(-1) 将每行移为"次日收益"，即 ret_wide.loc[t] = close[t+1]/close[t] - 1，
    # 与 factor_wide.loc[t] 配对 → 正确的 1 日 forward IC。
    ret_wide = price_wide.pct_change().shift(-1)

    # ── 计算因子 ──────────────────────────────────────────────
    factor_dict = {}

    if strategy == "auto_gen":
        # ── auto_gen 策略：从 strategies/generated/auto_gen_latest.json 加载 ──
        from pipeline.auto_gen_loader import (
            load_auto_gen_definition,
            compute_auto_gen_factors,
        )
        try:
            strategy_def = load_auto_gen_definition()
        except FileNotFoundError as e:
            return {
                "date": actual_date,
                "picks": [],
                "scores": {},
                "error": str(e),
            }

        try:
            factors_with_dir = compute_auto_gen_factors(
                strategy_def, price_wide, symbols, start, end,
            )
        except Exception as e:
            return {
                "date": actual_date,
                "picks": [],
                "scores": {},
                "error": f"auto_gen 因子计算失败: {e}",
            }

        # 应用方向并构建 raw_factors（与 v7/v8 同结构）
        raw_factors = {}
        for name, (fac_wide, direction) in factors_with_dir.items():
            raw_factors[name] = fac_wide * direction

        # 行业中性化（若策略定义要求）
        do_neutralize = bool(strategy_def.get("neutralize", True))
        if do_neutralize:
            try:
                industry_df = get_industry_classification(symbols=symbols)
            except Exception as e:
                warnings.warn(f"行业分类加载失败: {e}")
                industry_df = pd.DataFrame(columns=["symbol", "industry_code"])
        else:
            industry_df = pd.DataFrame(columns=["symbol", "industry_code"])

        neutralized_factors = {}
        ic_series_dict = {}
        for name, fac_wide in raw_factors.items():
            if fac_wide.empty or fac_wide.dropna(how="all").shape[0] < 30:
                continue
            if do_neutralize:
                try:
                    neutral = neutralize_factor_by_industry(fac_wide, industry_df)
                except Exception as e:
                    warnings.warn(f"中性化失败 {name}: {e}")
                    neutral = fac_wide
            else:
                neutral = fac_wide
            neutralized_factors[name] = neutral
            try:
                ic_s = compute_ic_series(neutral, ret_wide, method="spearman")
                ic_series_dict[name] = ic_s
            except Exception as e:
                warnings.warn(f"IC 序列计算失败 {name}: {e}，该因子不参与加权")

        # IC 加权合成（同 v7/v8）
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

        last_day_vals = {name: fac_wide.iloc[-1] for name, fac_wide in neutralized_factors.items()}
        factor_df = pd.DataFrame(last_day_vals)
        weight_series = pd.Series({n: weights.get(n, 0) for n in factor_df.columns})
        valid_mask = factor_df.notna()
        effective_weights = valid_mask.multiply(weight_series, axis=1)
        weight_sums = effective_weights.sum(axis=1)
        effective_weights = effective_weights.div(weight_sums, axis=0)
        composite_series = (factor_df * effective_weights).sum(axis=1)
        composite_series[weight_sums == 0] = np.nan

        composite = composite_series.dropna().sort_values(ascending=False)
        factor_dict = {name: raw_factors[name].iloc[-1] for name in raw_factors}
        snapshot_dict = {name: fac_wide.iloc[-1] for name, fac_wide in neutralized_factors.items()}

    elif strategy in ("v7", "v8"):
        # ── v7/v8 策略：行业中性化 + IC 加权合成 ────────────────
        # v8 在 v7 基础上加入 shadow_lower（微观结构因子，ICIR=0.51）
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

        # v8 额外因子：shadow_lower（微观结构-下影线支撑）
        if strategy == "v8":
            try:
                high_wide = load_price_wide(symbols, start, end, field="high")
                low_wide = load_price_wide(symbols, start, end, field="low")
                if not high_wide.empty and not low_wide.empty:
                    shadow_lower_wide = shadow_lower(price_wide, low_wide)
                    raw_factors["shadow_lower"] = shadow_lower_wide
            except Exception:
                warnings.warn("shadow_lower 计算失败，跳过")

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
            if fac_wide.empty or fac_wide.dropna(how="all").shape[0] < 30:
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
            except Exception as e:
                warnings.warn(f"IC 序列计算失败 {name}: {e}，该因子不参与加权")

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

        # 加权合成 composite（NaN 安全：缺失因子不传播 NaN，按有效权重重归一化）
        last_day_vals = {}
        for name, fac_wide in neutralized_factors.items():
            last_day_vals[name] = fac_wide.iloc[-1]
        factor_df = pd.DataFrame(last_day_vals)
        weight_series = pd.Series({n: weights.get(n, 0) for n in factor_df.columns})
        # 每只股票只用有数据的因子加权，权重重归一化
        valid_mask = factor_df.notna()
        effective_weights = valid_mask.multiply(weight_series, axis=1)
        weight_sums = effective_weights.sum(axis=1)
        effective_weights = effective_weights.div(weight_sums, axis=0)
        composite_series = (factor_df * effective_weights).sum(axis=1)
        # 完全没有因子数据的股票置为 NaN
        composite_series[weight_sums == 0] = np.nan

        if composite_series is None:
            return {
                "date": actual_date,
                "picks": [],
                "scores": {},
                "factor_values": {},
                "excluded": [],
                "metadata": {
                    "strategy": strategy,
                    "n_input_symbols": n_input_symbols,
                    "error": "所有因子数据不足，无法生成合成评分",
                },
            }

        composite = composite_series.dropna().sort_values(ascending=False)
        # Store raw (non-neutralized) factors for factor_values output
        factor_dict = {name: raw_factors[name].iloc[-1] for name in raw_factors}
        # 快照用中性化后的因子（factor_monitor 需要这些做 IC 计算）
        snapshot_dict = {name: fac_wide.iloc[-1] for name, fac_wide in neutralized_factors.items()}

    elif strategy == "v9":
        # ── v9 策略：v7 三核心 + 特质波动率 + 行业动量 + 增持代理 ──
        # 覆盖六类 alpha：技术 / 行为金融 / 基本面 / 风险 / 行业轮动 / 微观结构

        # cgo_simple 不再使用；用更强的正交因子替代
        raw_factors = {}

        try:
            raw_factors["low_vol_20d"] = low_vol_20d(price_wide)
        except Exception:
            warnings.warn("low_vol_20d 计算失败，跳过")

        try:
            raw_factors["team_coin"] = team_coin(price_wide)
        except Exception:
            warnings.warn("team_coin 计算失败，跳过")

        # bp 因子（PB 财务数据）
        bp_wide = pd.DataFrame(np.nan, index=price_wide.index, columns=price_wide.columns)
        try:
            pb_wide = load_factor_wide(symbols, "pb", start, end)
            if not pb_wide.empty:
                bp_wide = bp_factor(pb_wide)
        except Exception:
            warnings.warn("PB 数据不可用，跳过 bp 因子")
        raw_factors["bp"] = bp_wide

        # 特质波动率：函数内部已取负（方向=-1 → 正向信号）
        try:
            raw_factors["idiosyncratic_vol"] = idiosyncratic_volatility(price_wide)
        except Exception:
            warnings.warn("idiosyncratic_vol 计算失败，跳过")

        # 行业动量：需要行业分类
        try:
            industry_df = get_industry_classification(symbols=symbols)
        except Exception as _ie:
            warnings.warn(f"行业分类加载失败: {_ie}")
            industry_df = pd.DataFrame(columns=["symbol", "industry_code"])

        if not industry_df.empty and "industry_code" in industry_df.columns:
            _ind_map = industry_df.set_index("symbol")["industry_code"].to_dict()
            try:
                raw_factors["industry_momentum"] = industry_momentum(price_wide, _ind_map)
            except Exception:
                warnings.warn("industry_momentum 计算失败，跳过")
        else:
            _ind_map = {}

        # 增持代理：需要 high / low / volume 宽表
        try:
            high_wide_v9 = load_price_wide(symbols, start, end, field="high")
            low_wide_v9 = load_price_wide(symbols, start, end, field="low")
            vol_wide_v9 = load_factor_wide(symbols, "volume", start, end)
            if not high_wide_v9.empty and not low_wide_v9.empty and not vol_wide_v9.empty:
                raw_factors["insider_buying_proxy"] = insider_buying_proxy(
                    price_wide, high_wide_v9, low_wide_v9, vol_wide_v9
                )
        except Exception:
            warnings.warn("insider_buying_proxy 计算失败（high/low/volume 不可用），跳过")

        # 行业中性化 + IC 加权合成（与 v7/v8 相同逻辑）
        neutralized_factors = {}
        ic_series_dict = {}
        for name, fac_wide in raw_factors.items():
            if fac_wide.empty or fac_wide.dropna(how="all").shape[0] < 30:
                continue
            try:
                neutral = neutralize_factor_by_industry(fac_wide, industry_df)
            except Exception as e:
                warnings.warn(f"中性化失败 {name}: {e}")
                neutral = fac_wide
            neutralized_factors[name] = neutral
            try:
                ic_s = compute_ic_series(neutral, ret_wide, method="spearman")
                ic_series_dict[name] = ic_s
            except Exception as e:
                warnings.warn(f"IC 序列计算失败 {name}: {e}，该因子不参与加权")

        # IC 加权合成
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

        last_day_vals = {}
        for name, fac_wide in neutralized_factors.items():
            last_day_vals[name] = fac_wide.iloc[-1]
        factor_df = pd.DataFrame(last_day_vals)
        weight_series = pd.Series({n: weights.get(n, 0) for n in factor_df.columns})
        valid_mask = factor_df.notna()
        effective_weights = valid_mask.multiply(weight_series, axis=1)
        weight_sums = effective_weights.sum(axis=1)
        effective_weights = effective_weights.div(weight_sums, axis=0)
        composite_series = (factor_df * effective_weights).sum(axis=1)
        composite_series[weight_sums == 0] = np.nan

        if composite_series is None or composite_series.dropna().empty:
            return {
                "date": actual_date,
                "picks": [],
                "scores": {},
                "factor_values": {},
                "excluded": [],
                "metadata": {
                    "strategy": strategy,
                    "n_input_symbols": n_input_symbols,
                    "error": "v9 所有因子数据不足，无法生成合成评分",
                },
            }

        composite = composite_series.dropna().sort_values(ascending=False)
        factor_dict = {name: raw_factors[name].iloc[-1] for name in raw_factors}
        snapshot_dict = {name: fac_wide.iloc[-1] for name, fac_wide in neutralized_factors.items()}

    elif strategy == "v10":
        # ── v10 策略：因子审计精选，5 个互不高度相关的有效因子 ──
        # low_vol_20d(0.72) / team_coin(0.63) / shadow_lower(-0.49,反向) /
        # amihud_illiq(0.38) / price_vol_divergence(0.38)
        raw_factors = {}
        factor_directions = {}  # 1=正向, -1=反向

        try:
            raw_factors["low_vol_20d"] = low_vol_20d(price_wide)
            factor_directions["low_vol_20d"] = 1
        except Exception:
            warnings.warn("low_vol_20d 计算失败，跳过")

        try:
            raw_factors["team_coin"] = team_coin(price_wide)
            factor_directions["team_coin"] = 1
        except Exception:
            warnings.warn("team_coin 计算失败，跳过")

        # shadow_lower：需要 low 宽表，方向=-1（ICIR=-0.49）
        try:
            low_wide_v10 = load_price_wide(symbols, start, end, field="low")
            if not low_wide_v10.empty:
                sl_wide = shadow_lower(price_wide, low_wide_v10.reindex_like(price_wide))
                raw_factors["shadow_lower"] = sl_wide
                factor_directions["shadow_lower"] = -1
            else:
                warnings.warn("low 宽表为空，shadow_lower 跳过")
        except Exception:
            warnings.warn("shadow_lower 计算失败（low 数据不可用），跳过")

        # amihud_illiq + price_vol_divergence：需要 volume 宽表
        try:
            vol_wide_v10 = load_price_wide(symbols, start, end, field="volume")
            if not vol_wide_v10.empty:
                vol_aligned = vol_wide_v10.reindex_like(price_wide)
                try:
                    raw_factors["amihud_illiq"] = amihud_illiquidity(price_wide, vol_aligned)
                    factor_directions["amihud_illiq"] = 1
                except Exception:
                    warnings.warn("amihud_illiq 计算失败，跳过")
                try:
                    raw_factors["price_vol_divergence"] = price_volume_divergence(price_wide, vol_aligned)
                    factor_directions["price_vol_divergence"] = 1
                except Exception:
                    warnings.warn("price_vol_divergence 计算失败，跳过")
            else:
                warnings.warn("volume 宽表为空，amihud_illiq / price_vol_divergence 跳过")
        except Exception:
            warnings.warn("volume 数据加载失败，amihud_illiq / price_vol_divergence 跳过")

        # 行业分类（中性化）
        try:
            industry_df = get_industry_classification(symbols=symbols)
        except Exception as _ie:
            warnings.warn(f"行业分类加载失败: {_ie}")
            industry_df = pd.DataFrame(columns=["symbol", "industry_code"])

        # 应用方向并行业中性化 + IC 加权合成
        neutralized_factors = {}
        ic_series_dict = {}
        for name, fac_wide in raw_factors.items():
            if fac_wide.empty or fac_wide.dropna(how="all").shape[0] < 30:
                continue
            # 应用方向（-1 反向因子取负，统一为正向）
            directed = fac_wide * factor_directions.get(name, 1)
            try:
                neutral = neutralize_factor_by_industry(directed, industry_df)
            except Exception as e:
                warnings.warn(f"中性化失败 {name}: {e}")
                neutral = directed
            neutralized_factors[name] = neutral
            try:
                ic_s = compute_ic_series(neutral, ret_wide, method="spearman")
                ic_series_dict[name] = ic_s
            except Exception as e:
                warnings.warn(f"IC 序列计算失败 {name}: {e}，该因子不参与加权")

        # IC 加权合成（与 v7/v8/v9 相同逻辑）
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

        last_day_vals = {}
        for name, fac_wide in neutralized_factors.items():
            last_day_vals[name] = fac_wide.iloc[-1]
        factor_df = pd.DataFrame(last_day_vals)
        weight_series = pd.Series({n: weights.get(n, 0) for n in factor_df.columns})
        valid_mask = factor_df.notna()
        effective_weights = valid_mask.multiply(weight_series, axis=1)
        weight_sums = effective_weights.sum(axis=1)
        effective_weights = effective_weights.div(weight_sums, axis=0)
        composite_series = (factor_df * effective_weights).sum(axis=1)
        composite_series[weight_sums == 0] = np.nan

        if composite_series is None or composite_series.dropna().empty:
            return {
                "date": actual_date,
                "picks": [],
                "scores": {},
                "factor_values": {},
                "excluded": [],
                "metadata": {
                    "strategy": strategy,
                    "n_input_symbols": n_input_symbols,
                    "error": "v10 所有因子数据不足，无法生成合成评分",
                },
            }

        composite = composite_series.dropna().sort_values(ascending=False)
        factor_dict = {name: raw_factors[name].iloc[-1] for name in raw_factors}
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
    # 数据 vintage 指纹：记录当次用的输入数据状态，便于事后复查
    try:
        from utils.data_manifest import compute_data_manifest
        data_manifest = compute_data_manifest(symbols=symbols)
    except Exception as _mf_exc:
        data_manifest = {"status": "error", "error": str(_mf_exc)}

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
        "data_manifest": data_manifest,
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
        choices=["ad_hoc", "v7", "v8", "v9", "auto_gen"],
        help="因子策略：ad_hoc/v7/v8/v9/auto_gen（auto_gen 由 quant_dojo generate 生成）",
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
