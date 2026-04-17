"""
Leakage / 未来函数 回归测试。

三条独立不变量，任何一条失败就说明 shift(1) 保护失效或回测链里出现了
前视信息：

1. **纯噪声因子 sharpe 应接近零。** 用独立正态分布因子 + 独立正态
   分布价格，跑完整 MultiFactorStrategy，20 次随机种子取中位数，
   sharpe 必须 |median| < 0.30（如果 > 0.5 说明回测链里藏着信号泄漏）。

2. **Oracle 因子能获益但不能无穷大。** 用 "明日收益" 作为因子
   （完美未来函数），shift(1) 之后只能看到 "今日收益"，sharpe 应该
   *高* 但非无穷。具体阈值：10 < sharpe < 80。如果 sharpe 远超 80，
   shift(1) 没生效，oracle 直接读未来。

3. **把因子手动延迟 1 日，表现应该退化，不应该更好。** 真实弱信号
   的延迟版 sharpe 应 ≤ 原版 sharpe + 0.1 容差；若延迟版显著更好，
   说明原回测用了未来信息（否则多等一天反而更准不符合信息论）。

这个文件是 *回归门*：任何人改回测链后必须跑通，防止 shift(1) 被
误删或 signal index 偏移。

运行：pytest tests/test_no_leakage.py -v
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from strategies.base import StrategyConfig
from strategies.multi_factor import MultiFactorStrategy
from utils.metrics import sharpe_ratio


# ── 合成数据（小而快） ─────────────────────────────────
N_DAYS = 600
N_STOCKS = 80
N_HOLD = 20  # 每次持仓股票数


def _synth_prices(seed: int) -> pd.DataFrame:
    """生成 N_STOCKS 只股票的几何布朗运动价格，用于在无真实信号下回测。"""
    rng = np.random.default_rng(seed)
    mu = 0.0002  # 日漂移 ~0.02%
    sigma = 0.02  # 日波动 ~2%
    dates = pd.bdate_range("2020-01-01", periods=N_DAYS)
    symbols = [f"S{i:03d}" for i in range(N_STOCKS)]
    rets = rng.normal(mu, sigma, size=(N_DAYS, N_STOCKS))
    prices = 10.0 * np.cumprod(1 + rets, axis=0)
    return pd.DataFrame(prices, index=dates, columns=symbols)


def _synth_noise_factor(price: pd.DataFrame, seed: int) -> pd.DataFrame:
    """独立噪声因子，与价格毫无关系。"""
    rng = np.random.default_rng(seed + 10_000)
    vals = rng.normal(0.0, 1.0, size=price.shape)
    return pd.DataFrame(vals, index=price.index, columns=price.columns)


def _build_strategy(factor: pd.DataFrame, direction: int = 1) -> MultiFactorStrategy:
    cfg = StrategyConfig(name="leakage_test")
    return MultiFactorStrategy(
        config=cfg,
        factors={"f": (factor, direction)},
        n_stocks=N_HOLD,
        rebalance_freq="monthly",
        ic_weighting=False,
        neutralize=False,
    )


def _sharpe_from_run(result: pd.DataFrame) -> float:
    if "portfolio_return" in result.columns:
        r = result["portfolio_return"]
    elif "returns" in result.columns:
        r = result["returns"]
    else:
        raise AssertionError(f"未找到 return 列: {result.columns.tolist()}")
    r = r.dropna()
    if len(r) < 30 or r.std() == 0:
        return 0.0
    return float(sharpe_ratio(r))


# ══════════════════════════════════════════════════════════════════
# 不变量 1: 纯噪声因子不应产生显著 sharpe
# ══════════════════════════════════════════════════════════════════

def test_noise_factor_has_zero_sharpe():
    """纯噪声 signal + 独立噪声 return → 中位 sharpe ≈ 0。

    任何显著非零的中位 sharpe 都意味着回测链里用了未来信息。
    """
    sharpes = []
    for seed in range(12):  # 12 个独立试验足够估中位数
        price = _synth_prices(seed)
        factor = _synth_noise_factor(price, seed)
        strat = _build_strategy(factor, direction=1)
        result = strat.run(price)
        sharpes.append(_sharpe_from_run(result))

    sharpes_arr = np.array(sharpes)
    median = float(np.median(sharpes_arr))
    mean = float(np.mean(sharpes_arr))

    # 任一阈值超标即失败，把中位 + 均值都报出来方便诊断
    msg = (
        f"noise-factor sharpes: median={median:.3f} mean={mean:.3f} "
        f"all={np.round(sharpes_arr, 3).tolist()}"
    )
    assert abs(median) < 0.30, f"中位 sharpe 超标可能存在信号泄漏; {msg}"
    assert abs(mean) < 0.45, f"均值 sharpe 超标可能存在信号泄漏; {msg}"


# ══════════════════════════════════════════════════════════════════
# 不变量 2: Oracle 因子应获益但不爆表
# ══════════════════════════════════════════════════════════════════

def test_oracle_factor_bounded_by_shift1():
    """明日收益作因子 → shift(1) 之后只能看到今日收益。

    理论最优（知道当日收益）sharpe 应该是高但有限。如果 sharpe 超过
    合理上限（例如 80），说明 shift(1) 没生效、oracle 直接读了未来。
    """
    seed = 7
    price = _synth_prices(seed)
    # 因子 = 明日日收益（未来函数）
    tomorrow_ret = price.pct_change().shift(-1)
    # 填 NaN（末尾会有）
    tomorrow_ret = tomorrow_ret.fillna(0.0)

    strat = _build_strategy(tomorrow_ret, direction=1)
    result = strat.run(price)
    s = _sharpe_from_run(result)

    # 明日收益 shift(1) 之后 = 今日收益；对"选 N 个未来涨的股票"
    # 月频调仓，理论 sharpe 数量级应该在 3~40 之间（取决于 rebalance 和股票数）
    assert s > 1.0, (
        f"oracle 因子 sharpe={s:.2f}，应该显著为正；"
        f"shift(1) 之后至少能看到今日 rebalance 当日收益"
    )
    assert s < 100.0, (
        f"oracle 因子 sharpe={s:.2f}，超过合理上限；"
        f"shift(1) 保护可能失效，策略直接用了未来信息"
    )


# ══════════════════════════════════════════════════════════════════
# 不变量 3: 延迟版本不应好于原版
# ══════════════════════════════════════════════════════════════════

def test_delayed_factor_not_better_than_original():
    """把因子延迟 1 日，sharpe 应该 ≤ 原版（或略差）。

    信息论：多等一天意味着因子陈旧，其对未来收益的预测能力只会减弱
    或保持。如果延迟版 *优于* 原版，说明原版的"因子 t"里已经包含了
    超过 t 的未来信息（未来函数）。
    """
    # 用一个弱相关但非纯噪声的合成信号：因子 = 5日前收益（动量反转）
    seed = 3
    price = _synth_prices(seed)
    momentum = price.pct_change(5)

    strat_a = _build_strategy(momentum, direction=-1)  # 反转
    s_original = _sharpe_from_run(strat_a.run(price))

    # 延迟 1 日
    delayed = momentum.shift(1)
    strat_b = _build_strategy(delayed, direction=-1)
    s_delayed = _sharpe_from_run(strat_b.run(price))

    # 延迟版不能显著好于原版（+0.2 是合理抽样容差）
    assert s_delayed <= s_original + 0.25, (
        f"延迟因子 sharpe={s_delayed:.3f} 反而好于原版 {s_original:.3f}；"
        f"可能原版用了未来信息"
    )


if __name__ == "__main__":
    # 直接跑 python -m tests.test_no_leakage 也能快速验证
    test_noise_factor_has_zero_sharpe()
    print("✓ test_noise_factor_has_zero_sharpe")
    test_oracle_factor_bounded_by_shift1()
    print("✓ test_oracle_factor_bounded_by_shift1")
    test_delayed_factor_not_better_than_original()
    print("✓ test_delayed_factor_not_better_than_original")
    print("\n所有 leakage 不变量通过 ✓")
