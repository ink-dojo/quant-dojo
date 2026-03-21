"""
价值因子计算模块
支持 EP（市盈率倒数）、BP（市净率倒数）、SP（市销率倒数）及合成价值因子
"""
import numpy as np
import pandas as pd


def compute_ep(pe_wide: pd.DataFrame) -> pd.DataFrame:
    """
    计算 EP 因子（市盈率倒数）

    参数:
        pe_wide : PE 宽表 (date × symbol)，值为市盈率（PE_TTM）

    返回:
        ep_wide : EP 因子宽表 (date × symbol)
                  EP = 1 / PE，PE <= 0 时置 NaN（负 PE 无经济意义）
    """
    ep = pe_wide.copy().astype(float)
    ep[ep <= 0] = np.nan
    return 1.0 / ep


def compute_bp(pb_wide: pd.DataFrame) -> pd.DataFrame:
    """
    计算 BP 因子（市净率倒数）

    参数:
        pb_wide : PB 宽表 (date × symbol)，值为市净率

    返回:
        bp_wide : BP 因子宽表 (date × symbol)
                  BP = 1 / PB，PB <= 0 时置 NaN（净资产为负无意义）
    """
    bp = pb_wide.copy().astype(float)
    bp[bp <= 0] = np.nan
    return 1.0 / bp


def compute_sp(ps_wide: pd.DataFrame) -> pd.DataFrame:
    """
    计算 SP 因子（市销率倒数）

    参数:
        ps_wide : PS 宽表 (date × symbol)，值为市销率（Price/Sales）

    返回:
        sp_wide : SP 因子宽表 (date × symbol)
                  SP = 1 / PS，PS <= 0 时置 NaN
    """
    sp = ps_wide.copy().astype(float)
    sp[sp <= 0] = np.nan
    return 1.0 / sp


def compute_composite_value(
    ep: pd.DataFrame,
    bp: pd.DataFrame,
    sp: pd.DataFrame,
    weights: tuple = (1 / 3, 1 / 3, 1 / 3),
) -> pd.DataFrame:
    """
    合成价值因子：各维度截面 z-score 标准化后加权合成

    参数:
        ep      : EP 因子宽表 (date × symbol)
        bp      : BP 因子宽表 (date × symbol)
        sp      : SP 因子宽表 (date × symbol)
        weights : 三个维度的权重，默认等权 (1/3, 1/3, 1/3)

    返回:
        composite : 合成价值因子宽表 (date × symbol)
                    每个截面经 z-score 标准化后加权求和，再做一次截面标准化
    """
    assert abs(sum(weights) - 1.0) < 1e-9, "权重之和必须等于 1"

    def cross_zscore(df: pd.DataFrame) -> pd.DataFrame:
        """按行（每个截面日）做 z-score 标准化"""
        mean = df.mean(axis=1)
        std = df.std(axis=1)
        # 避免除以零
        std = std.replace(0, np.nan)
        return df.sub(mean, axis=0).div(std, axis=0)

    ep_z = cross_zscore(ep)
    bp_z = cross_zscore(bp)
    sp_z = cross_zscore(sp)

    w_ep, w_bp, w_sp = weights

    # 对齐 index 和 columns
    common_idx = ep_z.index.intersection(bp_z.index).intersection(sp_z.index)
    common_col = ep_z.columns.intersection(bp_z.columns).intersection(sp_z.columns)

    composite = (
        w_ep * ep_z.loc[common_idx, common_col]
        + w_bp * bp_z.loc[common_idx, common_col]
        + w_sp * sp_z.loc[common_idx, common_col]
    )

    # 最终再做一次截面 z-score，使输出量纲统一
    composite = cross_zscore(composite)

    return composite


if __name__ == "__main__":
    # 最小验证：用 mock 数据检验各函数
    np.random.seed(42)
    dates = pd.bdate_range("2024-01-01", periods=60)
    symbols = ["000001", "000002", "000003", "000004", "000005"]

    # 生成模拟估值数据（绝大多数为正，偶有负值）
    pe_mock = pd.DataFrame(
        np.abs(np.random.randn(60, 5)) * 20 + 10,
        index=dates, columns=symbols,
    )
    pb_mock = pd.DataFrame(
        np.abs(np.random.randn(60, 5)) * 2 + 1,
        index=dates, columns=symbols,
    )
    ps_mock = pd.DataFrame(
        np.abs(np.random.randn(60, 5)) * 3 + 1,
        index=dates, columns=symbols,
    )

    # 手动插入几个负值，验证置 NaN 逻辑
    pe_mock.iloc[0, 0] = -5.0
    pb_mock.iloc[1, 1] = -1.0
    ps_mock.iloc[2, 2] = -0.5

    ep = compute_ep(pe_mock)
    bp = compute_bp(pb_mock)
    sp = compute_sp(ps_mock)

    assert ep.iloc[0, 0] is np.nan or np.isnan(ep.iloc[0, 0]), "负PE应置NaN"
    assert bp.iloc[1, 1] is np.nan or np.isnan(bp.iloc[1, 1]), "负PB应置NaN"
    assert sp.iloc[2, 2] is np.nan or np.isnan(sp.iloc[2, 2]), "负PS应置NaN"
    assert ep.shape == pe_mock.shape
    assert bp.shape == pb_mock.shape
    assert sp.shape == ps_mock.shape
    print(f"✅ EP 形状: {ep.shape}, 非空比例: {ep.notna().mean().mean():.1%}")
    print(f"✅ BP 形状: {bp.shape}, 非空比例: {bp.notna().mean().mean():.1%}")
    print(f"✅ SP 形状: {sp.shape}, 非空比例: {sp.notna().mean().mean():.1%}")

    composite = compute_composite_value(ep, bp, sp)
    assert composite.shape == ep.shape
    # 截面均值应接近 0（z-score 后）
    cross_mean = composite.mean(axis=1).abs().mean()
    assert cross_mean < 0.5, f"截面均值偏离过大: {cross_mean:.4f}"
    print(f"✅ 合成因子 形状: {composite.shape}, 截面均值绝对值: {cross_mean:.4f}")
    print("✅ 价值因子模块验证通过")
