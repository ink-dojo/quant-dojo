"""
基金持仓拥挤度因子模块

核心假设
--------
公募基金每季度披露重仓持股，当大量基金重仓同一批股票时：
  1. 同向赎回风险：市场下行时多只基金同时减仓，形成踩踏
  2. 估值透支：共识持仓往往已充分定价（乃至过度定价）
  3. 流动性误匹配：基金承诺 T+1 赎回，但重仓股流动性在极端市场会变差

因此：拥挤度高 → 因子值高 → 未来收益差（负向因子）
取负后：低拥挤度 = 高因子值 = 预期更好。

拥挤度指标
----------
1. 持有基金数量（Coverage）：持有该股的基金数量 / 全市场基金总数
2. AUM 加权持股比例（AUM-weighted）：各基金持股市值之和 / 股票总流通市值
3. 集中度变化（Δcrowding）：本季度拥挤度 - 上季度（变化方向，流出信号）

三个指标可单独使用，也可合成综合拥挤度因子（取负后为正向因子）。

数据来源
--------
akshare: stock_report_fund_hold（某只股票的基金持仓情况）
数据频率：季度（3月/6月/9月/12月末，公告延迟约 15~45 天）

前视偏差处理
-----------
Q1 报告（3月末）约在 4月底前公告，Q2 约 7月底前，以此类推。
本模块使用保守的季度 shift(1)，即用上一季度末已公告的数据。
如有精确公告日数据，应替换为 announcement_date 时间戳。
"""

import warnings
import time
from pathlib import Path

import numpy as np
import pandas as pd

_CACHE_DIR = Path(__file__).parent.parent.parent.parent / "data" / "raw" / "fund_crowding"
_CACHE_DIR.mkdir(parents=True, exist_ok=True)


# ─────────────────────────────────────────────
# 数据拉取
# ─────────────────────────────────────────────

def get_fund_holding_for_stock(
    symbol: str,
    period: str,
    use_cache: bool = True,
) -> pd.DataFrame:
    """
    获取某只股票在指定季报期的基金持仓情况

    参数
    ----
    symbol : 股票代码，如 "000001"
    period : 季报期，格式 "YYYYMMDD"，如 "20231231"（Q4 末）
    use_cache : 是否使用本地缓存

    返回
    ----
    DataFrame，列：fund_code, fund_name, hold_shares, hold_value, hold_pct
        hold_pct = 持股比例（占基金净值 %）
    """
    cache_path = _CACHE_DIR / f"{symbol}_{period}.parquet"

    if use_cache and cache_path.exists():
        return pd.read_parquet(cache_path)

    try:
        import akshare as ak
        # stock_report_fund_hold: 个股的基金持仓，来自东方财富
        raw = ak.stock_report_fund_hold(symbol=symbol, market="sh" if symbol.startswith("6") else "sz")
        time.sleep(0.3)
    except Exception as e:
        warnings.warn(f"[fund_crowding] {symbol} @ {period} 拉取失败: {e}")
        return pd.DataFrame(columns=["fund_code", "hold_shares", "hold_value"])

    col_map = {
        "基金代码": "fund_code",
        "基金名称": "fund_name",
        "持股数（万股）": "hold_shares",
        "持股市值（万元）": "hold_value",
        "占基金净值比例（%）": "hold_pct",
    }
    available = {k: v for k, v in col_map.items() if k in raw.columns}
    df = raw[list(available.keys())].rename(columns=available).copy()

    for col in ["hold_shares", "hold_value", "hold_pct"]:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")

    df.to_parquet(cache_path)
    return df


def build_crowding_panel(
    symbols: list,
    periods: list,
    max_workers: int = 4,
) -> pd.DataFrame:
    """
    批量构建拥挤度面板数据（长表）

    参数
    ----
    symbols : 股票代码列表
    periods : 季报期列表，如 ["20221231", "20230331", ...]
    max_workers : 并发线程数（akshare 限速，建议不超过 4）

    返回
    ----
    DataFrame，列：period, symbol, n_funds, total_hold_value
        n_funds          : 持有该股的基金数量
        total_hold_value : 基金总持股市值（万元）
    """
    from concurrent.futures import ThreadPoolExecutor, as_completed

    rows = []

    def _fetch(sym, period):
        df = get_fund_holding_for_stock(sym, period)
        n_funds = len(df) if not df.empty else 0
        total_val = df["hold_value"].sum() if "hold_value" in df.columns and not df.empty else 0
        return {"period": period, "symbol": sym, "n_funds": n_funds, "total_hold_value": total_val}

    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        futs = [pool.submit(_fetch, sym, period) for sym in symbols for period in periods]
        for fut in as_completed(futs):
            try:
                rows.append(fut.result())
            except Exception as e:
                warnings.warn(f"[fund_crowding] panel 构建出错: {e}")

    panel = pd.DataFrame(rows)
    panel["period"] = pd.to_datetime(panel["period"])
    return panel.sort_values(["period", "symbol"]).reset_index(drop=True)


# ─────────────────────────────────────────────
# 因子计算
# ─────────────────────────────────────────────

def _quarterly_to_daily(
    quarterly_wide: pd.DataFrame,
    date_range: pd.DatetimeIndex,
) -> pd.DataFrame:
    """季度数据对齐到日频（shift(1) 防前视偏差 + ffill）"""
    shifted = quarterly_wide.shift(1)
    daily = shifted.reindex(date_range).ffill()
    return daily


def compute_fund_coverage(
    panel: pd.DataFrame,
    date_range: pd.DatetimeIndex,
) -> pd.DataFrame:
    """
    计算基金覆盖度因子（持有基金数量宽表，取负作为低拥挤因子）

    因子方向：-n_funds（持有基金越少 = 因子值越高 = 预期收益越好）

    参数
    ----
    panel      : build_crowding_panel 的返回值（长表）
    date_range : 目标日频 DatetimeIndex

    返回
    ----
    宽表 (date × symbol)，值为 -持有基金数量（负向拥挤度）
    """
    wide = panel.pivot(index="period", columns="symbol", values="n_funds")
    wide = wide.sort_index()
    # 取负：低覆盖 = 高因子值
    neg_coverage = -wide.astype(float)
    return _quarterly_to_daily(neg_coverage, date_range)


def compute_fund_crowding_value(
    panel: pd.DataFrame,
    market_cap_wide: pd.DataFrame,
    date_range: pd.DatetimeIndex,
) -> pd.DataFrame:
    """
    计算 AUM 加权拥挤度（基金持股市值 / 流通市值，取负）

    参数
    ----
    panel           : build_crowding_panel 的返回值
    market_cap_wide : 流通市值宽表 (date × symbol)，单位万元
    date_range      : 目标日频 DatetimeIndex

    返回
    ----
    宽表 (date × symbol)，值为 -(基金持股 / 流通市值)
    """
    hold_val = panel.pivot(index="period", columns="symbol", values="total_hold_value")
    hold_val = hold_val.sort_index().astype(float)

    # 对齐市值（取季末最近日的市值）
    common_syms = hold_val.columns.intersection(market_cap_wide.columns)
    hold_val = hold_val[common_syms]

    # 用季末最近 5 日的市值均值对齐
    mktcap_q = pd.DataFrame(index=hold_val.index, columns=common_syms, dtype=float)
    for period in hold_val.index:
        window = market_cap_wide.loc[:period].tail(5)
        if not window.empty:
            mktcap_q.loc[period, common_syms] = window[common_syms].mean()

    mktcap_q = mktcap_q.astype(float)
    mktcap_q = mktcap_q.replace(0, np.nan)

    crowding_ratio = hold_val / mktcap_q
    crowding_ratio = crowding_ratio.clip(0, 1)  # 占比不超过 100%

    # 取负
    neg_crowding = -crowding_ratio
    return _quarterly_to_daily(neg_crowding, date_range)


def compute_crowding_change(
    panel: pd.DataFrame,
    date_range: pd.DatetimeIndex,
) -> pd.DataFrame:
    """
    计算拥挤度变化因子（本季 - 上季，取负）

    基金开始减仓（拥挤度下降）时，因子值为正（买入信号）。
    捕捉机构"离场"早期迹象。

    参数
    ----
    panel      : build_crowding_panel 的返回值
    date_range : 目标日频 DatetimeIndex

    返回
    ----
    宽表 (date × symbol)，值为 -(当季拥挤度 - 上季拥挤度)
    """
    wide = panel.pivot(index="period", columns="symbol", values="n_funds")
    wide = wide.sort_index().astype(float)

    # 拥挤度变化（本季 - 上季）
    crowding_delta = wide.diff(1)

    # 取负：基金减仓（delta < 0）→ 因子值 > 0（买入信号）
    neg_delta = -crowding_delta
    return _quarterly_to_daily(neg_delta, date_range)


def compute_composite_crowding(
    panel: pd.DataFrame,
    date_range: pd.DatetimeIndex,
    market_cap_wide: pd.DataFrame = None,
    weights: tuple = (0.4, 0.3, 0.3),
) -> pd.DataFrame:
    """
    合成拥挤度因子（基金数量 + 持仓市值占比 + 变化方向）

    若无市值数据，退化为 (0.6, 0.0, 0.4) 等效合成。

    参数
    ----
    panel           : build_crowding_panel 的返回值
    date_range      : 目标日频 DatetimeIndex
    market_cap_wide : 流通市值宽表（可选，为 None 时跳过 AUM 加权分项）
    weights         : (w_coverage, w_value, w_change)，合计须为 1

    返回
    ----
    宽表 (date × symbol)，合成拥挤度因子值（越高 = 越不拥挤 = 更好）
    """
    assert abs(sum(weights) - 1.0) < 1e-9, "权重之和须为 1"
    w_cov, w_val, w_chg = weights

    def _cross_zscore(df: pd.DataFrame) -> pd.DataFrame:
        mean = df.mean(axis=1)
        std = df.std(axis=1).replace(0, np.nan)
        return df.sub(mean, axis=0).div(std, axis=0)

    coverage_z = _cross_zscore(compute_fund_coverage(panel, date_range))
    change_z = _cross_zscore(compute_crowding_change(panel, date_range))

    if market_cap_wide is not None:
        value_z = _cross_zscore(compute_fund_crowding_value(panel, market_cap_wide, date_range))
        common_idx = coverage_z.index.intersection(value_z.index).intersection(change_z.index)
        common_col = coverage_z.columns.intersection(value_z.columns).intersection(change_z.columns)
        composite = (
            w_cov * coverage_z.loc[common_idx, common_col]
            + w_val * value_z.loc[common_idx, common_col]
            + w_chg * change_z.loc[common_idx, common_col]
        )
    else:
        # 无市值数据：coverage 和 change 重新分配权重
        adj_w_cov = w_cov / (w_cov + w_chg)
        adj_w_chg = w_chg / (w_cov + w_chg)
        common_idx = coverage_z.index.intersection(change_z.index)
        common_col = coverage_z.columns.intersection(change_z.columns)
        composite = (
            adj_w_cov * coverage_z.loc[common_idx, common_col]
            + adj_w_chg * change_z.loc[common_idx, common_col]
        )

    return _cross_zscore(composite)


# ─────────────────────────────────────────────
# 最小验证（mock 数据）
# ─────────────────────────────────────────────

if __name__ == "__main__":
    np.random.seed(42)

    print("验证 fund_crowding_factor 模块（mock 数据）...")

    # 构造 mock 季度面板
    periods = pd.date_range("2020-03-31", periods=16, freq="QE")
    symbols = [f"{i:06d}" for i in range(1, 31)]

    rows = []
    for period in periods:
        for sym in symbols:
            rows.append({
                "period": period,
                "symbol": sym,
                "n_funds": max(0, int(np.random.poisson(15))),
                "total_hold_value": max(0, np.random.exponential(5000)),
            })
    mock_panel = pd.DataFrame(rows)

    date_range = pd.bdate_range("2020-01-01", "2024-12-31")

    # 测试 coverage 因子
    cov = compute_fund_coverage(mock_panel, date_range)
    assert cov.shape == (len(date_range), len(symbols))
    assert (cov <= 0).all().all(), "coverage 因子取负后应全部 <= 0"
    print(f"✅ fund_coverage  形状: {cov.shape} | 非空比例: {cov.notna().mean().mean():.1%}")

    # 测试 change 因子
    chg = compute_crowding_change(mock_panel, date_range)
    assert chg.shape == (len(date_range), len(symbols))
    print(f"✅ crowding_change 形状: {chg.shape} | 非空比例: {chg.notna().mean().mean():.1%}")

    # 测试合成（无市值数据）
    comp = compute_composite_crowding(mock_panel, date_range, market_cap_wide=None)
    assert comp.shape[1] == len(symbols)
    cross_mean = comp.mean(axis=1).abs().mean()
    assert cross_mean < 1.0, f"合成因子截面均值偏大: {cross_mean:.4f}"
    print(f"✅ composite_crowding 形状: {comp.shape} | 截面均值绝对值: {cross_mean:.4f}")
    print("✅ fund_crowding_factor 验证通过")
