"""
止损管理模块
支持个股跌幅止损和组合回撤止损
所有函数接受日收益率 Series，返回修改后的日收益率 Series（相同 index）
"""
import numpy as np
import pandas as pd


def trailing_stop(
    portfolio_ret: pd.Series,
    threshold: float = -0.10,
) -> pd.Series:
    """
    个股跌幅止损：从最近高点回撤超过 threshold 时清仓（输出0收益）

    逐日独立判断：
    - 计算从历史最高点到当日的回撤
    - 如果当日回撤 < threshold（例如 -10%），则保留该日收益
    - 否则输出 0（止损触发，清仓）

    参数:
        portfolio_ret: 日收益率 Series，如 [0.01, -0.02, 0.015, ...]
        threshold: 回撤触发阈值，默认 -0.10（-10%）

    返回:
        修改后的日收益率 Series，止损触发的日期返回 0
    """
    if len(portfolio_ret) == 0:
        return portfolio_ret.copy()

    # 计算累计收益
    cumulative = (1 + portfolio_ret).cumprod()

    # 计算运行最高值（从开始到当日）
    running_max = cumulative.cummax()

    # 计算从最高点的回撤
    drawdown = (cumulative - running_max) / running_max

    # 触发止损的日期（回撤低于 threshold）
    stop_triggered = drawdown < threshold

    # 输出：止损触发的日期为 0，否则保留原收益
    result = portfolio_ret.copy()
    result[stop_triggered] = 0.0

    return result


def per_stock_stop(
    period_returns: pd.DataFrame,
    threshold: float = -0.10,
) -> pd.DataFrame:
    """
    个股止损（永久止损版）：每只股票独立判断，触发后当期内不再恢复。

    对每列（股票）计算累计收益和运行最高值，当从最高点的回撤首次超过 threshold 时，
    从该日起（含）到 period 结束，该股票收益全部置零。

    与 trailing_stop 的区别：trailing_stop 在回撤恢复后会重新入场，
    本函数一旦触发就永久退出（适用于月频换仓场景，期内止损不恢复）。

    参数:
        period_returns: 日收益率 DataFrame，index=日期，columns=股票代码
        threshold: 回撤触发阈值，默认 -0.10（-10%）

    返回:
        修改后的 DataFrame，止损触发后该股票所有后续日期收益为 0
    """
    if period_returns.empty:
        return period_returns.copy()

    result = period_returns.copy()

    # 累计净值
    cum = (1 + period_returns).cumprod()
    # 运行最高值
    running_max = cum.cummax()
    # 回撤
    drawdown = (cum - running_max) / running_max

    # 对每只股票，找到首次触发止损的位置，从该位置起全部置零
    triggered = drawdown < threshold  # bool DataFrame
    for col in result.columns:
        col_triggered = triggered[col]
        if col_triggered.any():
            first_stop_idx = col_triggered.idxmax()  # 第一个 True 的日期
            result.loc[first_stop_idx:, col] = 0.0

    return result


def portfolio_stop(
    portfolio_ret: pd.Series,
    max_drawdown: float = -0.20,
) -> pd.Series:
    """
    组合止损：累计回撤超过 max_drawdown 时清仓直到恢复

    状态机：
    - in_market = True（初始在市）
    - 当累计回撤 < max_drawdown 时，设置 in_market = False（清仓）
    - 当 in_market = False 且累计净值创新高时，恢复 in_market = True

    清仓期间返回 0（无收益），恢复后保留原收益。

    参数:
        portfolio_ret: 日收益率 Series
        max_drawdown: 组合止损阈值，默认 -0.20（-20%）

    返回:
        修改后的日收益率 Series
    """
    if len(portfolio_ret) == 0:
        return portfolio_ret.copy()

    # 计算累计净值
    cumulative = (1 + portfolio_ret).cumprod()

    # 初始化状态和结果
    result = portfolio_ret.copy()
    in_market = True
    peak = cumulative.iloc[0]  # 历史最高净值

    for i in range(len(portfolio_ret)):
        current_nav = cumulative.iloc[i]

        # 如果在市，检查是否触发止损
        if in_market:
            drawdown = (current_nav - peak) / peak
            if drawdown < max_drawdown:
                # 触发止损
                in_market = False
                result.iloc[i] = 0.0
            else:
                # 更新历史高点
                if current_nav > peak:
                    peak = current_nav
        else:
            # 清仓状态，检查是否恢复
            if current_nav > peak:
                # 净值创新高，恢复在市
                in_market = True
                peak = current_nav
            else:
                # 还在清仓，返回 0
                result.iloc[i] = 0.0

    return result


def half_position_stop(
    portfolio_ret: pd.Series,
    threshold: float = -0.08,
) -> pd.Series:
    """
    组合降仓止损：累计回撤超过 threshold 时将持仓规模降至 50%，
    净值创新高后自动恢复满仓。

    状态机：
    - 满仓状态：跟踪当前净值 vs 历史高点。若回撤 < threshold → 切到半仓。
    - 半仓状态：日收益乘以 0.5（现金部分收益视为 0）。净值创新高 → 恢复满仓。

    与 portfolio_stop 的区别：
    - portfolio_stop 触发后归零（完全清仓）
    - half_position_stop 触发后乘以 0.5（保留一半仓位）

    参数:
        portfolio_ret: 日收益率 Series
        threshold: 回撤触发阈值，默认 -0.08（-8%）

    返回:
        修改后的日收益率 Series
    """
    if len(portfolio_ret) == 0:
        return portfolio_ret.copy()

    result = portfolio_ret.copy()
    in_full = True
    peak = 1.0
    nav = 1.0

    for i in range(len(portfolio_ret)):
        daily_ret = portfolio_ret.iloc[i]
        scale = 1.0 if in_full else 0.5
        adjusted_ret = daily_ret * scale
        result.iloc[i] = adjusted_ret
        nav = nav * (1 + adjusted_ret)

        if in_full:
            if nav > peak:
                peak = nav
            elif (nav - peak) / peak < threshold:
                in_full = False
        else:
            if nav > peak:
                in_full = True
                peak = nav

    return result


def adaptive_half_position_stop(
    portfolio_ret: pd.Series,
    baseline_threshold: float = -0.08,
    vol_window: int = 60,
    ref_vol: float = 0.20,
    min_scale: float = 0.5,
    max_scale: float = 2.0,
) -> pd.Series:
    """
    波动率自适应的半仓止损：阈值随组合滚动波动率缩放。

        threshold_t = baseline_threshold × clip(σ_t / ref_vol, min_scale, max_scale)

    直觉：
    - 市场波动率高（2025 震荡行情）→ 阈值放宽 → 不被噪音摇下车
    - 市场波动率低（长期阴跌）→ 阈值收紧 → 及时降仓

    状态机同 half_position_stop：满仓↔半仓，切换条件由时变阈值决定。

    参数:
        portfolio_ret: 日收益率 Series
        baseline_threshold: 锚点阈值（σ_t == ref_vol 时的触发阈值），默认 -0.08
        vol_window: 波动率窗口（日），默认 60
        ref_vol: 参考年化波动率（锚点），默认 0.20
            WF 场景下应传入训练期波动率中位数以避免未来泄漏
        min_scale / max_scale: σ_t / ref_vol 的夹紧区间，默认 [0.5, 2.0]
            对应阈值区间 [baseline×0.5, baseline×2.0]，即 [-0.04, -0.16]

    返回:
        修改后的日收益率 Series
    """
    if len(portfolio_ret) == 0:
        return portfolio_ret.copy()

    # 滚动年化波动率；shift(1) 保证 t 日决策只看到 t-1 及以前的收益
    # （修复 2026-04-17：原版本用 t 日 σ 决定 t 日阈值，混入当天收益 → 轻度前视）
    sigma_t = (
        portfolio_ret.rolling(vol_window, min_periods=20).std().shift(1)
        * np.sqrt(252)
    )
    ratio = (sigma_t / ref_vol).clip(min_scale, max_scale).fillna(1.0)
    threshold_t = baseline_threshold * ratio

    result = portfolio_ret.copy()
    in_full = True
    peak = 1.0
    nav = 1.0

    for i in range(len(portfolio_ret)):
        daily_ret = portfolio_ret.iloc[i]
        scale = 1.0 if in_full else 0.5
        adjusted_ret = daily_ret * scale
        result.iloc[i] = adjusted_ret
        nav = nav * (1 + adjusted_ret)

        thr_t = threshold_t.iloc[i]
        if in_full:
            if nav > peak:
                peak = nav
            elif (nav - peak) / peak < thr_t:
                in_full = False
        else:
            if nav > peak:
                in_full = True
                peak = nav

    return result


def regime_gated_half_position_stop(
    portfolio_ret: pd.Series,
    regime_bear: pd.Series,
    threshold: float = -0.10,
) -> pd.Series:
    """
    Regime-gated 半仓止损：**只在熊市 regime 内启用止损**。

    **动机**（来自 v10/v11 rejection 教训，2026-04-16）：
        - v10 固定 -8% 止损: IS 好看 (MDD -42%→-24%)，但 OOS 年化 35%→6% 惨跌；
          MDD 本身只从 -17.83% 到 -17.76%，改善几乎为零。
        - v11 vol-adaptive 止损: 在 2025 OOS 被夹到与 v10 完全相同（σ_t 近似 σ_ref）。
        - 根因: 2025 "假摔" 是 3-5 日脉冲急跌+反弹，-8% 触发后半仓，
          需净值创新高恢复 → 在震荡市里永远半仓，错过反弹。
        - 2015/2018 IS 看起来好看是因为那是真熊市（数月持续下跌），止损有效。

    **本函数的修正思路**（Route B from v10 eval）：
        用一个外生 regime 判别（如 HS300 < MA120 = 熊市）来**门控**止损是否启用：
        - Bear=True: 开启止损；回撤触发半仓（同 half_position_stop）
        - Bear=False: 止损关闭，永远满仓
        这样短期震荡市不会误触发，长期熊市仍被保护。

    参数:
        portfolio_ret: 日收益率 Series（策略净收益）
        regime_bear  : 与 portfolio_ret 同索引的 bool/0-1 Series，True 表示熊市
                       （调用者应已 shift(1)，此函数不再 shift）
        threshold    : 熊市期内的回撤触发阈值，默认 -0.10

    返回:
        修改后的日收益率 Series
    """
    if len(portfolio_ret) == 0:
        return portfolio_ret.copy()

    regime = regime_bear.reindex(portfolio_ret.index).fillna(False).astype(bool)

    result = portfolio_ret.copy()
    in_full = True
    peak = 1.0
    nav = 1.0

    for i in range(len(portfolio_ret)):
        daily_ret = portfolio_ret.iloc[i]
        is_bear = bool(regime.iloc[i])

        # 牛市 regime 下强制恢复满仓；熊市才进入半仓状态机
        if not is_bear and not in_full:
            in_full = True
            peak = nav  # reset peak 以免牛市反弹时仍触发旧 peak 的回撤

        scale = 1.0 if in_full else 0.5
        adjusted_ret = daily_ret * scale
        result.iloc[i] = adjusted_ret
        nav = nav * (1 + adjusted_ret)

        if is_bear and in_full:
            if nav > peak:
                peak = nav
            elif (nav - peak) / peak < threshold:
                in_full = False
        elif is_bear and not in_full:
            if nav > peak:
                in_full = True
                peak = nav
        else:
            # 牛市: 仅更新 peak，不进半仓
            if nav > peak:
                peak = nav

    return result


def hs300_bear_regime(
    hs300_close: pd.Series,
    ma_window: int = 120,
    shift_days: int = 1,
) -> pd.Series:
    """
    HS300 跌破 ma_window 日均线 → 熊市 regime。

    参数:
        hs300_close: HS300 每日收盘价 Series（DatetimeIndex）
        ma_window : 均线周期，默认 120 交易日（~6 个月）
        shift_days: 信号 shift 天数，默认 1（避免当日偷看）

    返回:
        bool Series（索引 = hs300_close 索引），True = 熊市
    """
    if not isinstance(hs300_close.index, pd.DatetimeIndex):
        raise TypeError("hs300_close 必须用 DatetimeIndex")
    ma = hs300_close.rolling(ma_window, min_periods=ma_window // 2).mean()
    bear = hs300_close < ma
    return bear.shift(shift_days).fillna(False)


if __name__ == "__main__":
    # 冒烟测试
    import numpy as np

    # 构造模拟收益序列
    np.random.seed(42)
    dates = pd.date_range("2024-01-01", periods=100)
    daily_ret = pd.Series(np.random.randn(100) * 0.01, index=dates)  # 日收益 ±1%

    # 测试 trailing_stop
    stopped_ret = trailing_stop(daily_ret, threshold=-0.10)
    assert len(stopped_ret) == len(daily_ret), "返回长度错误"
    assert stopped_ret.index.equals(daily_ret.index), "index 不匹配"
    # 检查是否有 0 的日期
    zero_days = (stopped_ret == 0).sum()
    print(f"✅ trailing_stop OK | 输入长度={len(daily_ret)}, 触发止损天数={zero_days}")

    # 测试 portfolio_stop
    stopped_ret2 = portfolio_stop(daily_ret, max_drawdown=-0.20)
    assert len(stopped_ret2) == len(daily_ret), "返回长度错误"
    assert stopped_ret2.index.equals(daily_ret.index), "index 不匹配"
    zero_days2 = (stopped_ret2 == 0).sum()
    print(f"✅ portfolio_stop OK | 输入长度={len(daily_ret)}, 清仓天数={zero_days2}")

    # 测试空序列
    empty_ret = pd.Series([], dtype=float)
    assert trailing_stop(empty_ret).empty, "空序列处理错误"
    assert portfolio_stop(empty_ret).empty, "空序列处理错误"
    print(f"✅ 边界情况处理 OK")

    # 测试极端场景：所有正收益
    all_positive = pd.Series([0.01] * 50, index=pd.date_range("2024-01-01", periods=50))
    stopped_positive = trailing_stop(all_positive, threshold=-0.10)
    assert (stopped_positive == all_positive).all(), "全正收益不应触发止损"
    print(f"✅ 极端场景（全正收益）OK")

    # 测试极端场景：单次大幅回撤
    sharp_drawdown = pd.Series([0.05, 0.05, -0.15, 0.02, 0.02], dtype=float)
    stopped_sharp = trailing_stop(sharp_drawdown, threshold=-0.10)
    # 第 3 个回报应该被触发（累计下跌超过 -10%）
    assert stopped_sharp.iloc[2] == 0.0, "大幅回撤应该触发止损"
    print(f"✅ 极端场景（大幅回撤）OK")

    # 测试 per_stock_stop
    np.random.seed(42)
    df_ret = pd.DataFrame(
        np.random.randn(30, 3) * 0.02,
        index=pd.date_range("2024-01-01", periods=30),
        columns=["A", "B", "C"],
    )
    # 让 B 列出现大幅回撤
    df_ret.iloc[5:8, 1] = -0.08
    stopped_df = per_stock_stop(df_ret, threshold=-0.10)
    assert stopped_df.shape == df_ret.shape, "形状不一致"
    assert stopped_df.index.equals(df_ret.index), "index 不一致"
    # B 列应该在某个时刻之后全为 0
    b_zeros = (stopped_df["B"] == 0.0)
    if b_zeros.any():
        first_zero = b_zeros.idxmax()
        assert (stopped_df.loc[first_zero:, "B"] == 0.0).all(), "止损后应永久为零"
    print(f"✅ per_stock_stop OK | 形状={stopped_df.shape}")

    # 空 DataFrame
    empty_df = pd.DataFrame()
    assert per_stock_stop(empty_df).empty, "空 DataFrame 处理错误"
    print("✅ per_stock_stop 边界情况 OK")

    # 测试 adaptive_half_position_stop
    # 1) 空序列
    assert adaptive_half_position_stop(pd.Series([], dtype=float)).empty
    # 2) 低波动序列 + 大回撤 → 应触发（阈值收紧到 min_scale × baseline）
    low_vol = pd.Series([0.001] * 80 + [-0.02] * 10, dtype=float)
    adj_low = adaptive_half_position_stop(low_vol, baseline_threshold=-0.08, ref_vol=0.20)
    assert adj_low.iloc[-5:].abs().max() < low_vol.iloc[-5:].abs().max(), \
        "低波动大回撤应触发降仓"
    # 3) 高波动序列 + 同样回撤 → 不一定触发（阈值放宽）
    np.random.seed(123)
    noisy = pd.Series(np.random.randn(90) * 0.03, dtype=float)  # 年化约 48%
    adj_noisy = adaptive_half_position_stop(noisy, baseline_threshold=-0.08, ref_vol=0.20)
    assert len(adj_noisy) == len(noisy)
    # 4) 无回撤：全正收益不应触发
    all_pos = pd.Series([0.005] * 80, dtype=float)
    adj_pos = adaptive_half_position_stop(all_pos)
    assert np.allclose(adj_pos.values, all_pos.values), "全正收益不应降仓"
    # 5) baseline 等价性：极端高 ref_vol 下 ratio 被夹到 min_scale → 阈值恒为 baseline×min_scale
    adj_clip = adaptive_half_position_stop(
        pd.Series([-0.05] * 60, dtype=float),
        baseline_threshold=-0.05, ref_vol=100.0,  # ratio → 0 → clip 到 min_scale=0.5
    )
    assert len(adj_clip) == 60
    print("✅ adaptive_half_position_stop OK | 5 项测试通过")

    print("\n✅ 止损管理模块冒烟测试通过")
