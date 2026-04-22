"""
Frog-in-the-Pan (FiP) 因子 — Da, Gurun, Warachka (2014) RFS.

核心论点：同样幅度的动量，通过「连续小步累积」产生的 → 市场关注度低 → 定价慢 → 持续;
通过「跳跃式大单日涨跌」产生的 → 吸引注意 → 快速定价完成 → 反转。

信息离散度 (Information Discreteness, ID):
    ID = sign(ret_window) × (%neg_days − %pos_days)

对于正动量股票 (ret_window > 0):
    - 低 ID (很多正天、少负天 = 稳定上涨) → momentum 持续
    - 高 ID (少正天、多负天 + 个别大阳线 = 跳跃) → momentum 反转

FiP 因子 = −ID × sign(momentum) × |momentum|^α
           直觉: 低 ID 的正动量 + 低 ID 的负动量（空头方向一致）做多信号强

A 股证据：孙谦 2019《信息离散度与动量效应的增强》— 12m skip 1m 下
          Rank IC ≈ 0.025, 显著改善单纯 momentum。

参数锁死（防 overfit）：
    - lookback = 250 trading days (≈ 12m)
    - skip = 21 trading days (≈ 1m, 规避短期反转污染)
    - 这是论文原始参数，不调
"""
from __future__ import annotations
import numpy as np
import pandas as pd


def compute_fip(
    close: pd.DataFrame,
    lookback: int = 250,
    skip: int = 21,
) -> pd.DataFrame:
    """
    计算 Frog-in-the-Pan 因子。

    参数:
        close    : 宽表 date × symbol, 复权收盘价
        lookback : 动量窗口长度（默认 250 天 = 12m）
        skip     : 近端规避天数（默认 21 天 = 1m）

    返回:
        因子宽表 date × symbol，正值做多，负值做空。
    """
    daily_ret = close.pct_change()
    # 计算 t-skip 到 t-skip-lookback 的累计动量
    skipped = daily_ret.shift(skip)
    momentum = (1.0 + skipped).rolling(lookback, min_periods=lookback // 2).apply(
        lambda x: np.prod(x) - 1.0, raw=True
    )

    # 信息离散度：pos/neg/zero 天数占比
    pos_count = (daily_ret > 0).shift(skip).rolling(lookback, min_periods=lookback // 2).sum()
    neg_count = (daily_ret < 0).shift(skip).rolling(lookback, min_periods=lookback // 2).sum()
    n_valid = daily_ret.shift(skip).rolling(lookback, min_periods=lookback // 2).count()

    pct_pos = pos_count / n_valid
    pct_neg = neg_count / n_valid

    # ID = sign(momentum) × (pct_neg − pct_pos)
    # 正动量时 pct_neg - pct_pos 应该为负（正天多），ID < 0 = 低离散 = 持续
    id_score = np.sign(momentum) * (pct_neg - pct_pos)

    # FiP 因子 = −ID × sign(momentum) = (pct_pos − pct_neg)（同向动量条件下）
    # 直接乘 −1 使「低 ID」对应「高因子值」做多
    fip = -id_score
    # winsorize ±3σ 避免极值
    mu = fip.mean(axis=1)
    sd = fip.std(axis=1)
    fip = fip.sub(mu, axis=0).div(sd.replace(0, np.nan), axis=0).clip(-3, 3)
    return fip


if __name__ == "__main__":
    # 最小验证：随机价格序列跑通
    rng = np.random.default_rng(42)
    idx = pd.date_range("2022-01-01", periods=500, freq="B")
    cols = [f"S{i:04d}" for i in range(50)]
    close = pd.DataFrame(
        100.0 * np.exp(rng.normal(0.0003, 0.02, (500, 50)).cumsum(axis=0)),
        index=idx,
        columns=cols,
    )
    f = compute_fip(close)
    valid_start = f.first_valid_index()
    assert valid_start is not None, "因子全 NaN"
    print(f"FiP factor ok | first valid: {valid_start.date()} | shape: {f.shape}")
    print(f"sample distribution:\n{f.dropna(how='all').iloc[-1].describe()}")
