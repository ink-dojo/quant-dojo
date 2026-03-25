"""
Alpha 因子库 — quant-dojo 标准化因子构建模块

所有因子输入 price_wide（日期 × 股票代码），输出同形状 DataFrame。
正值 = 预期未来收益为正的方向。

因子分类：
  - 技术/统计：reversal, low_vol, turnover_rev
  - 基本面：ep, bp
  - 微观结构：shadow_line, amplitude_momentum, high_price_amplitude
  - 行为金融：cgo (处置效应), str_salience (凸显理论), team_coin (球队硬币)

参考文献：
  - 上下影线: 东吴证券《技术分析遇上选股因子》系列二 (2020)
  - CGO: 国信证券《行为金融学系列之二：处置效应》(2019)
  - STR/STV: Cosemans & Frehen (2021) + 方正证券 A 股适配
  - 球队硬币: 方正证券 (2022), Moskowitz (2021) JF
  - 振幅切割动量: 开源证券《市场微观结构系列七》(2020)
"""
import numpy as np
import pandas as pd


# ══════════════════════════════════════════════════════════════
# 现有因子（从 strategy_eval 迁移过来，统一接口）
# ══════════════════════════════════════════════════════════════

def reversal_1m(price: pd.DataFrame) -> pd.DataFrame:
    """1 月反转因子：过去 21 天收益率取负"""
    return -price.pct_change(21)


def low_vol_20d(price: pd.DataFrame) -> pd.DataFrame:
    """低波动因子：过去 20 天日收益波动率取负"""
    return -price.pct_change().rolling(20).std()


def turnover_rev(price: pd.DataFrame) -> pd.DataFrame:
    """换手率反转因子：过去 20 天日收益绝对值均值取负（活跃度代理）"""
    return -price.pct_change().abs().rolling(20).mean()


def ep_factor(pe_wide: pd.DataFrame) -> pd.DataFrame:
    """盈利收益率因子：1/PE（PE 为负时设 NaN）"""
    return 1.0 / pe_wide.where(pe_wide > 0)


def bp_factor(pb_wide: pd.DataFrame) -> pd.DataFrame:
    """账面市值比因子：1/PB（PB 为负时设 NaN）"""
    return 1.0 / pb_wide.where(pb_wide > 0)


# ══════════════════════════════════════════════════════════════
# 新因子 1：上下影线因子 (Shadow Line)
# ══════════════════════════════════════════════════════════════

def shadow_line_upper(high: pd.DataFrame, close: pd.DataFrame,
                      window: int = 20) -> pd.DataFrame:
    """
    上影线因子（Williams 式）：卖压指标。

    公式：williams_upper = high - close
    标准化：除以 5 日均值后取 20 日均值
    方向：取负（上影线大 = 卖压大 = 看空）
    """
    raw = high - close
    # 标准化：除以 5 日均值（避免绝对价格影响）
    std_shadow = raw / raw.rolling(5, min_periods=1).mean().replace(0, np.nan)
    return -std_shadow.rolling(window).mean()


def shadow_line_lower(close: pd.DataFrame, low: pd.DataFrame,
                      window: int = 20) -> pd.DataFrame:
    """
    下影线因子：买盘支撑指标。

    公式：williams_lower = close - low
    方向：正值（下影线大 = 买盘支撑强 = 看多）
    """
    raw = close - low
    std_shadow = raw / raw.rolling(5, min_periods=1).mean().replace(0, np.nan)
    return std_shadow.rolling(window).mean()


# ══════════════════════════════════════════════════════════════
# 新因子 2：处置效应因子 CGO (Capital Gains Overhang)
# ══════════════════════════════════════════════════════════════

def cgo_factor(close: pd.DataFrame, turnover: pd.DataFrame,
               lookback: int = 100) -> pd.DataFrame:
    """
    处置效应因子：衡量持股者平均浮盈/浮亏比例。

    核心思路：用换手率加权计算历史参考成本价，再算 (现价/成本 - 1)。
    浮盈大 → 持股者倾向卖出（处置效应） → 未来收益偏低 → 因子取负。

    参数:
        close: 收盘价宽表
        turnover: 换手率宽表（0-100 的百分比）
        lookback: 回溯天数（默认 100）
    """
    # 换手率归一化到 0-1
    turn = turnover / 100.0 if turnover.max().max() > 1 else turnover.copy()
    turn = turn.clip(0.001, 1.0)  # 避免零换手

    result = pd.DataFrame(np.nan, index=close.index, columns=close.columns)

    for i in range(lookback, len(close)):
        # 过去 lookback 天的权重：turnover[t] * prod(1-turnover[s], s=t+1..today)
        window_turn = turn.iloc[i - lookback:i].values  # (lookback, n_stocks)
        window_close = close.iloc[i - lookback:i].values

        # 计算权重（从最近到最远）
        # weight[t] = turn[t] * prod(1-turn[s]) for s > t
        weights = np.zeros_like(window_turn)
        cum_survive = np.ones(window_turn.shape[1])
        for t in range(lookback - 1, -1, -1):
            weights[t] = window_turn[t] * cum_survive
            cum_survive *= (1 - window_turn[t])

        # 归一化权重
        w_sum = weights.sum(axis=0)
        w_sum[w_sum == 0] = 1
        weights /= w_sum

        # 参考价格
        ref_price = (weights * window_close).sum(axis=0)

        # CGO = (current / reference) - 1
        current = close.iloc[i].values
        cgo = current / np.where(ref_price > 0, ref_price, np.nan) - 1
        result.iloc[i] = cgo

    # 取负：浮盈大 → 预期未来收益低
    return -result


# ══════════════════════════════════════════════════════════════
# 新因子 3：凸显理论 STR/STV 因子 (Salience Theory)
# ══════════════════════════════════════════════════════════════

def str_salience(stock_ret: pd.DataFrame, market_ret: pd.Series,
                 window: int = 20) -> pd.DataFrame:
    """
    凸显理论因子（STR）：关注度加权收益。

    核心思路：与市场偏离大的收益日更"显著"，投资者过度关注极端日。
    高 STR 的股票被过度关注 → 未来回归均值 → 取负。

    公式:
        sigma_t = |r_stock - r_market| / (|r_stock| + |r_market| + 0.1)
        STR = rolling_mean(sigma * r_stock, window)
    """
    # 对齐 market_ret 到 stock_ret 的 index
    mkt = market_ret.reindex(stock_ret.index)

    # 逐日计算 salience weight
    abs_stock = stock_ret.abs()
    abs_mkt = mkt.abs()

    # sigma = |r_stock - r_market| / (|r_stock| + |r_market| + 0.1)
    diff = stock_ret.sub(mkt, axis=0).abs()
    denom = abs_stock.add(abs_mkt, axis=0) + 0.1
    sigma = diff / denom

    # STR = rolling mean of (sigma * r_stock)
    weighted_ret = sigma * stock_ret
    str_factor = weighted_ret.rolling(window).mean()

    # 取负：高 STR（被过度关注） → 未来收益低
    return -str_factor


# ══════════════════════════════════════════════════════════════
# 新因子 4：球队硬币因子 (Team-Coin / Sports-Betting)
# ══════════════════════════════════════════════════════════════

def team_coin(price: pd.DataFrame, window: int = 20) -> pd.DataFrame:
    """
    球队硬币因子：条件反转/动量。

    核心思路：
      - 低波动股 = "硬币"（人们错误预期反转）→ 实际有动量 → 取正收益
      - 高波动股 = "球队"（反转是对的）→ 取负收益
    综合后比简单反转更有效。

    Moskowitz (2021) Journal of Finance
    """
    daily_ret = price.pct_change()
    ret_mean = daily_ret.rolling(window).mean()
    ret_std = daily_ret.rolling(window).std()

    # 每天的市场平均波动
    market_avg_std = ret_std.mean(axis=1)

    # 低波动（"硬币"）→ 动量方向（正收益）
    # 高波动（"球队"）→ 反转方向（负收益）
    is_coin = ret_std.lt(market_avg_std, axis=0)

    # 硬币：取均值（动量）；球队：取负均值（反转）
    factor = ret_mean.where(is_coin, -ret_mean)
    return factor


# ══════════════════════════════════════════════════════════════
# 新因子 5：振幅切割动量 (Amplitude-Split Momentum)
# ══════════════════════════════════════════════════════════════

def amplitude_momentum(high: pd.DataFrame, low: pd.DataFrame,
                       close: pd.DataFrame, lookback: int = 120) -> pd.DataFrame:
    """
    振幅切割动量：A 股专用动量因子。

    核心思路：
      - 低振幅日累计收益 = 纯动量信号（A 股有效）
      - 高振幅日累计收益 = 纯反转信号
    只取低振幅部分的动量。

    开源证券《市场微观结构系列七》(2020)
    """
    daily_ret = close.pct_change()
    amplitude = high / low - 1  # 日内振幅

    result = pd.DataFrame(np.nan, index=close.index, columns=close.columns)

    for i in range(lookback, len(close)):
        amp_window = amplitude.iloc[i - lookback:i]
        ret_window = daily_ret.iloc[i - lookback:i]

        # 对每只股票：按振幅排序，取低振幅半的累计收益
        for col in close.columns:
            a = amp_window[col].dropna()
            r = ret_window[col].dropna()
            common = a.index.intersection(r.index)
            if len(common) < 20:
                continue
            a_c, r_c = a[common], r[common]
            # 低振幅半
            median_amp = a_c.median()
            low_amp_ret = r_c[a_c <= median_amp].sum()
            result.at[close.index[i], col] = low_amp_ret

    return result


# ══════════════════════════════════════════════════════════════
# 辅助：批量构建所有因子
# ══════════════════════════════════════════════════════════════

def build_all_factors(price: pd.DataFrame, high: pd.DataFrame = None,
                      low: pd.DataFrame = None, pe: pd.DataFrame = None,
                      pb: pd.DataFrame = None, turnover: pd.DataFrame = None,
                      market_ret: pd.Series = None) -> dict:
    """
    一次性构建所有可用因子。

    参数:
        price: 收盘价宽表
        high/low: 最高/最低价宽表（可选，不传则跳过 OHLC 因子）
        pe/pb: PE/PB 宽表（可选，不传则跳过基本面因子）
        turnover: 换手率宽表（可选）
        market_ret: 市场收益率序列（可选，用于 STR 因子）

    返回:
        dict: {因子名: DataFrame}
    """
    daily_ret = price.pct_change()
    factors = {}

    # 技术因子（只需 close）
    factors["reversal_1m"] = reversal_1m(price)
    factors["low_vol_20d"] = low_vol_20d(price)
    factors["turnover_rev"] = turnover_rev(price)
    factors["team_coin"] = team_coin(price)

    # OHLC 因子
    if high is not None and low is not None:
        factors["shadow_upper"] = shadow_line_upper(high, price)
        factors["shadow_lower"] = shadow_line_lower(price, low)
        factors["amp_momentum"] = amplitude_momentum(high, low, price, lookback=60)

    # 基本面因子
    if pe is not None:
        factors["ep"] = ep_factor(pe).reindex_like(price)
    if pb is not None:
        factors["bp"] = bp_factor(pb).reindex_like(price)

    # 行为金融因子
    if turnover is not None:
        factors["cgo"] = cgo_factor(price, turnover, lookback=60)

    if market_ret is not None:
        factors["str_salience"] = str_salience(daily_ret, market_ret)

    return factors


if __name__ == "__main__":
    import sys
    sys.path.insert(0, str(__import__("pathlib").Path(__file__).parent.parent))
    from utils.local_data_loader import get_all_symbols, load_price_wide

    symbols = get_all_symbols()[:50]
    price = load_price_wide(symbols, "2023-01-01", "2024-12-31", field="close")
    print(f"测试数据: {price.shape}")

    factors = build_all_factors(price)
    for name, fac in factors.items():
        valid = fac.notna().sum().sum()
        print(f"  {name:<20} 有效值: {valid}")

    print("✅ alpha_factors import ok")
