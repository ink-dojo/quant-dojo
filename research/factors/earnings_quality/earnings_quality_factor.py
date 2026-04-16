"""
盈利质量因子模块

核心假设
--------
A 股上市公司财务操纵空间大，"盈利 = 经营现金流 + 应计项目"。
应计项目（Accruals）可被管理层通过应收账款、存货、递延收入等调节，
经营现金流则相对难以造假。

因此：
  - CFO/NI 高 → 盈利含金量高 → 未来收益更好
  - Accruals/TA 高 → 盈利质量低 → 未来收益更差（取负作为因子）

两个子因子可单独使用，也可截面 z-score 等权合成。

数据来源
--------
akshare: stock_cash_flow_sheet_by_report_em（现金流量表）
         stock_financial_analysis_indicator（综合财务指标，含总资产）

前视偏差处理
-----------
季报公告日滞后报告期末约 1~3 个月。
本模块对季报数据 shift(1) 后 ffill 对齐日频，确保只使用已公开数据。
如有 announcement_date 数据，应替换 shift(1) 以做到更精确处理。
"""
import warnings
from pathlib import Path
import numpy as np
import pandas as pd

# 本地缓存目录，与 fundamental_loader 保持一致
_CACHE_DIR = Path(__file__).parent.parent.parent.parent / "data" / "raw" / "fundamentals"
_CACHE_DIR.mkdir(parents=True, exist_ok=True)


# ─────────────────────────────────────────────
# 数据拉取
# ─────────────────────────────────────────────

def get_cash_flow(symbol: str, use_cache: bool = True) -> pd.DataFrame:
    """
    获取单只股票现金流量表（按报告期）

    参数
    ----
    symbol   : 股票代码，如 "000001"
    use_cache: 是否使用 parquet 缓存（7 天 TTL）

    返回
    ----
    DataFrame，index 为报告期（DatetimeIndex），列：
        cfo        经营活动产生的现金流量净额（元）
        net_profit 净利润（元），部分接口可能为 NaN
        total_assets 总资产（元）
    """
    import time
    cache_path = _CACHE_DIR / f"{symbol}_cashflow.parquet"

    # TTL: 7天（财务数据变动频率低）
    if use_cache and cache_path.exists():
        age_days = (pd.Timestamp.now() - pd.Timestamp(cache_path.stat().st_mtime, unit="s")).days
        if age_days < 7:
            return pd.read_parquet(cache_path)

    try:
        import akshare as ak
        raw = ak.stock_cash_flow_sheet_by_report_em(symbol=symbol)
        time.sleep(0.3)
    except Exception as e:
        warnings.warn(f"[earnings_quality] {symbol} 现金流量表拉取失败: {e}")
        return pd.DataFrame(columns=["cfo", "net_profit", "total_assets"])

    # 列名映射（东方财富接口列名）
    col_map = {
        "报告期": "report_date",
        "经营活动产生的现金流量净额": "cfo",
        "净利润": "net_profit",
        "资产总计": "total_assets",
    }
    available = {k: v for k, v in col_map.items() if k in raw.columns}
    if "报告期" not in available:
        warnings.warn(f"[earnings_quality] {symbol} 现金流量表列名不匹配，跳过")
        return pd.DataFrame(columns=["cfo", "net_profit", "total_assets"])

    df = raw[list(available.keys())].rename(columns=available).copy()
    df["report_date"] = pd.to_datetime(df["report_date"], errors="coerce")
    df = df.dropna(subset=["report_date"]).set_index("report_date").sort_index()

    for col in ["cfo", "net_profit", "total_assets"]:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")
        else:
            df[col] = np.nan

    df.to_parquet(cache_path)
    return df


def build_cashflow_wide(
    symbols: list,
    start: str,
    end: str,
    max_workers: int = 6,
) -> dict:
    """
    批量构建现金流宽表

    参数
    ----
    symbols     : 股票代码列表
    start / end : 日期范围（YYYY-MM-DD）
    max_workers : 并发线程数

    返回
    ----
    dict: {"cfo": DataFrame, "net_profit": DataFrame, "total_assets": DataFrame}
    每个 DataFrame 的 index 为报告期（季度频），columns 为股票代码
    """
    from concurrent.futures import ThreadPoolExecutor, as_completed

    per_symbol: dict[str, pd.DataFrame] = {}
    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        futs = {pool.submit(get_cash_flow, sym): sym for sym in symbols}
        for fut in as_completed(futs):
            sym = futs[fut]
            try:
                df = fut.result()
                if not df.empty:
                    per_symbol[sym] = df.loc[start:end]
            except Exception as e:
                warnings.warn(f"[earnings_quality] {sym} 宽表构建失败: {e}")

    result = {}
    for field in ["cfo", "net_profit", "total_assets"]:
        cols = {sym: df[field] for sym, df in per_symbol.items() if field in df.columns}
        if cols:
            result[field] = pd.DataFrame(cols).sort_index()

    return result


# ─────────────────────────────────────────────
# 因子计算
# ─────────────────────────────────────────────

def _quarterly_to_daily(
    quarterly_wide: pd.DataFrame,
    date_range: pd.DatetimeIndex,
) -> pd.DataFrame:
    """
    季度数据对齐到日频（shift(1) 防前视偏差 + ffill）

    shift(1) 使用上一报告期数据，确保任意交易日只用已公告数据。
    更严格处理应以实际公告日替换报告期末。
    """
    shifted = quarterly_wide.shift(1)
    daily = shifted.reindex(date_range).ffill()
    return daily


def compute_cfo_ni_ratio(
    cashflow_wide: dict,
    date_range: pd.DatetimeIndex,
) -> pd.DataFrame:
    """
    计算 CFO/NI 盈利质量因子（日频宽表）

    CFO/NI = 经营现金流 / 净利润
      > 1 : 现金流超过账面盈利，盈利质量高
      < 0 : 经营现金流为负（亏损经营），最差质量
      NaN : 净利润为 0 或 NaN

    处理规则：
      - 净利润 <= 0 时置 NaN（亏损股，分母无意义）
      - 截尾：[-2, 5]（防止分母趋近 0 时的极端值）
      - shift(1) + ffill 对齐日频（防前视偏差）

    参数
    ----
    cashflow_wide : build_cashflow_wide 的返回值
    date_range    : 目标日频 DatetimeIndex

    返回
    ----
    宽表 (date × symbol)，值为 CFO/NI
    """
    cfo = cashflow_wide.get("cfo")
    ni = cashflow_wide.get("net_profit")
    if cfo is None or ni is None:
        raise ValueError("cashflow_wide 必须包含 'cfo' 和 'net_profit' 字段")

    # 对齐列
    common = cfo.columns.intersection(ni.columns)
    cfo, ni = cfo[common], ni[common]

    # 净利润 <= 0 时置 NaN（分母无意义）
    ni_clean = ni.where(ni > 0)

    ratio = cfo[common] / ni_clean

    # 截尾：[-2, 5] 防极端值（当 NI 极小时 ratio 会爆炸）
    ratio = ratio.clip(-2.0, 5.0)

    # 对齐到日频
    return _quarterly_to_daily(ratio, date_range)


def compute_accruals(
    cashflow_wide: dict,
    date_range: pd.DatetimeIndex,
) -> pd.DataFrame:
    """
    计算应计项目因子（Accruals，日频宽表）

    Accruals/TA = (净利润 - 经营现金流) / 总资产
      正值 = 应计项目多，盈利质量低
      因子方向取负：低应计 = 高因子值 = 好

    参数
    ----
    cashflow_wide : build_cashflow_wide 的返回值
    date_range    : 目标日频 DatetimeIndex

    返回
    ----
    宽表 (date × symbol)，值为 -Accruals/TA（越高越好）
    """
    cfo = cashflow_wide.get("cfo")
    ni = cashflow_wide.get("net_profit")
    ta = cashflow_wide.get("total_assets")
    if cfo is None or ni is None or ta is None:
        raise ValueError("cashflow_wide 必须包含 'cfo'、'net_profit'、'total_assets'")

    common = cfo.columns.intersection(ni.columns).intersection(ta.columns)
    cfo, ni, ta = cfo[common], ni[common], ta[common]

    # 总资产 <= 0 时置 NaN
    ta_clean = ta.where(ta > 0)

    accruals = (ni - cfo) / ta_clean
    # 截尾：[-0.5, 0.5]（正常范围；极端值通常是数据错误）
    accruals = accruals.clip(-0.5, 0.5)

    # 取负：低应计 = 高因子值 = 好
    neg_accruals = -accruals

    return _quarterly_to_daily(neg_accruals, date_range)


def compute_composite_earnings_quality(
    cashflow_wide: dict,
    date_range: pd.DatetimeIndex,
    weights: tuple = (0.5, 0.5),
) -> pd.DataFrame:
    """
    合成盈利质量因子（CFO/NI + 负应计项目，截面 z-score 等权合成）

    参数
    ----
    cashflow_wide : build_cashflow_wide 的返回值
    date_range    : 目标日频 DatetimeIndex
    weights       : (w_cfo_ni, w_accruals)，合计须为 1

    返回
    ----
    宽表 (date × symbol)，合成因子值
    """
    assert abs(sum(weights) - 1.0) < 1e-9, "权重之和必须为 1"
    w1, w2 = weights

    cfo_ni = compute_cfo_ni_ratio(cashflow_wide, date_range)
    accruals = compute_accruals(cashflow_wide, date_range)

    def _cross_zscore(df: pd.DataFrame) -> pd.DataFrame:
        mean = df.mean(axis=1)
        std = df.std(axis=1).replace(0, np.nan)
        return df.sub(mean, axis=0).div(std, axis=0)

    cfo_ni_z = _cross_zscore(cfo_ni)
    accruals_z = _cross_zscore(accruals)

    # 对齐后加权合成
    common_idx = cfo_ni_z.index.intersection(accruals_z.index)
    common_col = cfo_ni_z.columns.intersection(accruals_z.columns)

    composite = (
        w1 * cfo_ni_z.loc[common_idx, common_col]
        + w2 * accruals_z.loc[common_idx, common_col]
    )
    return _cross_zscore(composite)


# ─────────────────────────────────────────────
# 最小验证
# ─────────────────────────────────────────────

if __name__ == "__main__":
    import numpy as np

    print("验证 earnings_quality_factor 模块（使用 mock 数据）...")

    # 构造 mock 现金流数据（5 只股票 × 12 个季度）
    np.random.seed(42)
    report_dates = pd.date_range("2021-03-31", periods=12, freq="QE")
    symbols = ["000001", "000002", "000003", "000004", "000005"]

    def _mock_series(n_dates, n_syms, scale=1e8):
        return pd.DataFrame(
            np.random.randn(n_dates, n_syms) * scale + scale,
            index=report_dates, columns=symbols
        )

    mock_cashflow = {
        "cfo":          _mock_series(12, 5, scale=5e8),
        "net_profit":   _mock_series(12, 5, scale=4e8),
        "total_assets": _mock_series(12, 5, scale=1e10),
    }
    # 手动插入几个负利润（测试 NaN 处理）
    mock_cashflow["net_profit"].iloc[0, 0] = -1e8
    mock_cashflow["net_profit"].iloc[3, 2] = 0

    date_range = pd.bdate_range("2021-01-01", "2024-12-31")

    # 测试 CFO/NI
    cfo_ni = compute_cfo_ni_ratio(mock_cashflow, date_range)
    assert cfo_ni.shape == (len(date_range), len(symbols))
    assert cfo_ni.isna().sum().sum() > 0, "负利润期应有 NaN"
    print(f"✅ CFO/NI 因子  形状: {cfo_ni.shape} | 非空比例: {cfo_ni.notna().mean().mean():.1%}")

    # 测试 Accruals
    acc = compute_accruals(mock_cashflow, date_range)
    assert acc.shape == (len(date_range), len(symbols))
    print(f"✅ Accruals 因子 形状: {acc.shape} | 非空比例: {acc.notna().mean().mean():.1%}")

    # 测试合成
    comp = compute_composite_earnings_quality(mock_cashflow, date_range)
    assert comp.shape[1] == len(symbols)
    cross_mean = comp.mean(axis=1).abs().mean()
    assert cross_mean < 1.0, f"合成因子截面均值偏离过大: {cross_mean:.4f}"
    print(f"✅ 合成因子     形状: {comp.shape} | 截面均值绝对值: {cross_mean:.4f}")
    print("✅ earnings_quality_factor 验证通过")
