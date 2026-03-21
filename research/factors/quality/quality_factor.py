"""
质量因子模块

实现 ROE、ROE 稳定性、毛利率三个质量维度，并合成综合质量因子。

前视偏差处理原则
----------------
财报数据在季末后约 1~3 个月才公布（如 Q1 报告通常 4 月底前公布）。
为严格避免前视偏差，本模块对季度财报数据先 shift(1)（使用上一期数据），
再 ffill 对齐到日频，确保任意交易日只能看到已公开的财报数据。

注意：实际公布日期（announcement date）与报告期末不同。
如需更严格处理，应以实际公告日为时间戳替换报告期末日期。
"""

import numpy as np
import pandas as pd


def compute_roe_factor(financials_dict: dict) -> pd.DataFrame:
    """
    构建 ROE 宽表（date × symbol），季度数据对齐到日频。

    参数
    ----
    financials_dict : dict
        {symbol: df} 字典，来自 fundamental_loader.get_financials。
        每个 df 的 index 为报告期（DatetimeIndex），包含 'roe' 列。

    返回
    ----
    pd.DataFrame
        date × symbol 的 ROE 宽表，已对齐到日频（ffill 填充）。

    前视偏差风险
    -----------
    季末财报公布存在 1~3 个月滞后。本函数通过 shift(1) 确保任意交易日
    使用的是上一期已公布数据，而非当期可能未公布的数据。
    更严格处理需引入实际公告日（announcement_date）时间戳。
    """
    frames = []
    for symbol, df in financials_dict.items():
        if "roe" not in df.columns:
            continue
        s = df["roe"].copy()
        s.index = pd.to_datetime(s.index)
        s = s.sort_index()
        # shift(1): 使用上一期数据，防止当季末数据尚未公布即被使用
        s = s.shift(1)
        frames.append(s.rename(symbol))

    if not frames:
        return pd.DataFrame()

    # 拼成宽表，按报告期对齐
    wide = pd.concat(frames, axis=1)
    wide = wide.sort_index()

    # 扩展到日频日期范围，再 ffill（用最近已知季报数据填充交易日空缺）
    date_range = pd.date_range(wide.index.min(), wide.index.max(), freq="D")
    wide = wide.reindex(date_range).ffill()

    return wide


def compute_roe_stability(roe_wide: pd.DataFrame, window: int = 8) -> pd.DataFrame:
    """
    计算 ROE 稳定性因子（滚动 window 期负标准差）。

    参数
    ----
    roe_wide : pd.DataFrame
        date × symbol 的 ROE 宽表（通常为季度频率，或已对齐到日频）。
    window : int
        滚动窗口期数（默认 8 期，约 2 年季度数据）。

    返回
    ----
    pd.DataFrame
        date × symbol 的稳定性宽表，值越大表示 ROE 越稳定（负标准差）。

    前视偏差风险
    -----------
    稳定性计算依赖历史 ROE 序列。若 roe_wide 已经过 shift(1) 处理，
    则本函数不引入额外前视偏差。直接在原始财报时间序列上计算则存在风险。
    """
    stability = -roe_wide.rolling(window=window, min_periods=window // 2).std()
    return stability


def compute_gross_margin(financials_dict: dict) -> pd.DataFrame:
    """
    构建毛利率宽表（date × symbol），季度数据对齐到日频。

    参数
    ----
    financials_dict : dict
        {symbol: df} 字典，来自 fundamental_loader.get_financials。
        优先使用 'gross_margin' 列；若不存在则退回 'net_margin'。

    返回
    ----
    pd.DataFrame
        date × symbol 的毛利率宽表，已对齐到日频（ffill 填充）。

    前视偏差风险
    -----------
    同 compute_roe_factor：通过 shift(1) + ffill 防止前视偏差。
    实际公告日与报告期末存在差异，更严格处理需引入公告日时间戳。
    """
    frames = []
    for symbol, df in financials_dict.items():
        # 优先 gross_margin，否则退回 net_margin
        if "gross_margin" in df.columns:
            col = "gross_margin"
        elif "net_margin" in df.columns:
            col = "net_margin"
        else:
            continue
        s = df[col].copy()
        s.index = pd.to_datetime(s.index)
        s = s.sort_index()
        s = s.shift(1)
        frames.append(s.rename(symbol))

    if not frames:
        return pd.DataFrame()

    wide = pd.concat(frames, axis=1)
    wide = wide.sort_index()

    date_range = pd.date_range(wide.index.min(), wide.index.max(), freq="D")
    wide = wide.reindex(date_range).ffill()

    return wide


def _cross_section_zscore(wide: pd.DataFrame) -> pd.DataFrame:
    """截面 z-score 标准化，逐行（逐日）处理。"""
    mean = wide.mean(axis=1)
    std = wide.std(axis=1).replace(0, np.nan)
    return wide.sub(mean, axis=0).div(std, axis=0)


def compute_composite_quality(
    roe: pd.DataFrame,
    roe_stability: pd.DataFrame,
    gross_margin: pd.DataFrame,
) -> pd.DataFrame:
    """
    合成综合质量因子（截面 z-score 后等权合成）。

    参数
    ----
    roe : pd.DataFrame
        date × symbol 的 ROE 宽表。
    roe_stability : pd.DataFrame
        date × symbol 的 ROE 稳定性宽表。
    gross_margin : pd.DataFrame
        date × symbol 的毛利率宽表。

    返回
    ----
    pd.DataFrame
        date × symbol 的综合质量因子宽表（截面 z-score 等权合成后再 z-score）。

    前视偏差风险
    -----------
    合成因子的前视偏差完全来自各子因子。确保输入已经过 shift(1) + ffill 处理。
    截面 z-score 使用当日截面均值/标准差，不引入跨期前视偏差。
    """
    # 各维度截面 z-score
    roe_z = _cross_section_zscore(roe)
    stab_z = _cross_section_zscore(roe_stability)
    gm_z = _cross_section_zscore(gross_margin)

    # 对齐索引后等权求和，按有效维度数归一化
    composite = roe_z.add(stab_z, fill_value=0).add(gm_z, fill_value=0)
    count = (
        roe_z.notna().astype(float)
        .add(stab_z.notna().astype(float), fill_value=0)
        .add(gm_z.notna().astype(float), fill_value=0)
    )
    composite = composite.div(count.replace(0, np.nan))

    return composite


if __name__ == "__main__":
    print("验证 quality_factor 模块...")

    # 构造 mock 数据（3 支股票，12 个季报期）
    np.random.seed(42)
    report_dates = pd.date_range("2020-03-31", periods=12, freq="QE")
    symbols = ["000001", "000002", "000003"]

    mock_financials = {}
    for sym in symbols:
        df = pd.DataFrame(
            {
                "roe": np.random.uniform(0.05, 0.25, size=12),
                "net_margin": np.random.uniform(0.08, 0.30, size=12),
            },
            index=report_dates,
        )
        mock_financials[sym] = df

    roe_wide = compute_roe_factor(mock_financials)
    gm_wide = compute_gross_margin(mock_financials)
    stab_wide = compute_roe_stability(roe_wide)
    composite = compute_composite_quality(roe_wide, stab_wide, gm_wide)

    assert roe_wide.shape[1] == 3, "ROE 宽表列数应为 3"
    assert not roe_wide.empty, "ROE 宽表不应为空"
    assert not composite.empty, "综合因子不应为空"

    print(f"✅ ROE 宽表形状: {roe_wide.shape}")
    print(f"✅ 毛利率宽表形状: {gm_wide.shape}")
    print(f"✅ 稳定性宽表形状: {stab_wide.shape}")
    print(f"✅ 综合质量因子形状: {composite.shape}")
    print("✅ quality_factor 验证通过")
