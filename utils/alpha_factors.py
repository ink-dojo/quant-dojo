"""
Alpha 因子库 — quant-dojo 完整因子集

所有因子接受宽表输入（日期 × 股票），返回同形状 DataFrame。
正值 = 预期未来收益高的方向。

=== 因子分类 ===

技术/统计（8）：
  reversal_1m, reversal_5d, reversal_skip1m, low_vol_20d, turnover_rev,
  enhanced_momentum, quality_momentum, ma_ratio_momentum

基本面（4 + 1）：
  ep, bp, earnings_momentum, dividend_yield
  accruals_quality（应计异象，需财务宽表）

流动性（1）：
  amihud_illiquidity（Amihud 非流动性，需 volume）

微观结构（4）：
  shadow_upper, shadow_lower, amplitude_hidden, w_reversal

行为金融（4）：
  cgo, str_salience, team_coin, retail_open_trap

网络/关系（2）：
  network_scc, apm_overnight

筹码（4）：
  chip_arc, chip_vrc, chip_src, chip_krc

=== 参考文献 ===
  [1] 东吴证券-技术分析遇上选股因子（上下影线）
  [2] 国信证券-行为金融学系列之二（处置效应 CGO）
  [3] Cosemans & Frehen 2021 / 方正证券（凸显理论 STR）
  [4] Moskowitz 2021 JF / 方正证券（球队硬币）
  [5] 开源证券-市场微观结构系列七（振幅切割）
  [6] 开源证券-市场微观结构系列一（W 因子）
  [7] QuantsPlaybook-网络中心度因子（SCC/TCC）
  [8] QuantsPlaybook-APM 因子模型（隔夜/日间）
  [9] QuantsPlaybook-筹码因子（ARC/VRC/SRC/KRC）
  [10] QuantsPlaybook-再论动量因子（MA 比率）
  [11] QuantsPlaybook-高质量动量因子（风险调整动量）
  [12] Amihud 2002 / A股流动性溢价（非流动性因子）
  [13] Sloan 1996 / 应计异象（盈利质量）
  [14] Novy-Marx 2013 / 盈利动量（盈利加速度）
  [15] 价值投资经典 / 股息率因子
  [16] Barber & Odean 2008 JF / A股散户开盘追涨行为
  [17] 方正证券-A股行为金融系列（高开低走机构分配）
"""
import numpy as np
import pandas as pd


# ══════════════════════════════════════════════════════════════
# 因子 winsorize 契约
# ══════════════════════════════════════════════════════════════
#
# 本文件中大多数因子**默认不自我 winsorize**，依赖调用方（通常是
# strategies/multi_factor.py:_winsorize_zscore，±3σ 截尾）做全局去极值。
#
# 但以下类别的因子**必须自我 winsorize**，以免在非 multi_factor 路径
# （notebook 直接 IC / daily_signal 单因子查看 / 新策略接入）下产生爆炸值：
#   1. 估值倒数（ep / bp）：PE 或 PB 接近 0 时值会炸到百千量级
#   2. 对数收益减方差惩罚（enhanced/quality_momentum）：窗口早期
#      sigma 极小会让 3000 * sigma^2 相对 ret_n 接近 0，但极端个股的
#      ret_n 本身能到数倍量级
#   3. 比率型因子（vol_asymmetry = vol_down/vol_up）：分母小会炸
#   4. 归一化但无硬边界的微观结构因子（volume_surge / close_minus_open_volume
#      / overnight_return / bid_ask_spread_proxy / earnings_window_proxy）
#
# 自我 winsorize 用截面 1%/99% quantile clip（MAD-free，对分布形状不敏感），
# 而不是 ±3σ。理由：σ 本身受极端值影响，quantile 更鲁棒。


def _cross_winsorize(df: pd.DataFrame, lower_q: float = 0.01,
                     upper_q: float = 0.99) -> pd.DataFrame:
    """逐日截面 quantile clip。

    对每个交易日独立计算 lower_q / upper_q 分位数并 clip，NaN 不参与统计。
    当截面有效样本 <5 时该日不处理，原样返回（避免对稀疏截面过度截断）。
    """
    def _clip_row(row: pd.Series) -> pd.Series:
        valid = row.dropna()
        if len(valid) < 5:
            return row
        lo = valid.quantile(lower_q)
        hi = valid.quantile(upper_q)
        return row.clip(lower=lo, upper=hi)
    return df.apply(_clip_row, axis=1)


# ══════════════════════════════════════════════════════════════
# 技术/统计因子
# ══════════════════════════════════════════════════════════════

def reversal_1m(price: pd.DataFrame) -> pd.DataFrame:
    """1 月反转：-pct_change(21)"""
    return -price.pct_change(21)


def reversal_5d(price: pd.DataFrame) -> pd.DataFrame:
    """超短期5日反转：-pct_change(5)

    A股高频反转效应，散户主导的过度反应后均值回归。
    信号衰减快，适合高换手策略。
    """
    return -price.pct_change(5)


def reversal_skip1m(price: pd.DataFrame,
                    short_window: int = 5,
                    long_window: int = 60) -> pd.DataFrame:
    """跳过近1个月的中期反转：-(ret_60d - ret_5d)

    用60日累积收益减去近5日，规避短期动量噪声，
    捕捉1-3个月区间的均值回归。与 enhanced_mom_60 天然对冲。
    """
    log_ret = np.log(price / price.shift(1))
    ret_long = log_ret.rolling(long_window).sum()
    ret_short = log_ret.rolling(short_window).sum()
    return -(ret_long - ret_short)


def low_vol_20d(price: pd.DataFrame) -> pd.DataFrame:
    """低波动：-std(ret, 20)"""
    return -price.pct_change().rolling(20).std()


def turnover_rev(price: pd.DataFrame) -> pd.DataFrame:
    """换手率反转：-mean(|ret|, 20)"""
    return -price.pct_change().abs().rolling(20).mean()


def enhanced_momentum(price: pd.DataFrame, window: int = 60) -> pd.DataFrame:
    """
    风险调整动量：ret_N - 3000 * sigma^2

    来源：QuantsPlaybook/B-因子构建类/再论动量因子
    """
    log_ret = np.log(price / price.shift(1))
    ret_n = log_ret.rolling(window).sum()
    sigma = log_ret.rolling(window).std()
    return _cross_winsorize(ret_n - 3000 * sigma ** 2)


def quality_momentum(price: pd.DataFrame, window: int = 60) -> pd.DataFrame:
    """
    高质量动量：排除涨停日 + 方差惩罚。

    近似实现：排除 |ret| > 9.5% 的天数。
    来源：QuantsPlaybook/B-因子构建类/高质量动量因子选股
    """
    ret = price.pct_change()
    # 排除接近涨跌停的日收益
    filtered = ret.where(ret.abs() < 0.095, 0)
    cum_ret = filtered.rolling(window).sum()
    sigma = filtered.rolling(window).std()
    return _cross_winsorize(cum_ret - 3000 * sigma ** 2)


def ma_ratio_momentum(price: pd.DataFrame, window: int = 120) -> pd.DataFrame:
    """
    MA 比率动量：MA(N) / Price，单调性更强。

    来源：QuantsPlaybook/B-因子构建类/再论动量因子
    取负：MA/Price > 1 说明价格在 MA 下方（看空）
    """
    return _cross_winsorize(-(price.rolling(window).mean() / price))


# ══════════════════════════════════════════════════════════════
# 流动性因子
# ══════════════════════════════════════════════════════════════

def amihud_illiquidity(price: pd.DataFrame, volume: pd.DataFrame,
                       window: int = 20) -> pd.DataFrame:
    """
    Amihud 非流动性因子：单位成交量的价格冲击。

    ILLIQ = mean(|ret| / volume, window)
    高值 = 流动性差 = 未来有流动性溢价（正向因子）

    参数:
        price  : 收盘价宽表（日期 × 股票）
        volume : 成交量宽表（日期 × 股票），单位任意（分子分母相消）
        window : 滚动窗口，默认 20 日

    返回:
        同形状 DataFrame；值越大流动性越差（未来溢价越高）

    来源：Amihud 2002 / A股已验证有效
    """
    ret = price.pct_change().abs()
    # 成交量为 0 时设 NaN，避免除零
    vol = volume.replace(0, np.nan)
    illiq = (ret / vol).rolling(window).mean()
    # 按全表 99 分位截断极端值，防止极低成交量时数值爆炸
    upper = illiq.stack().quantile(0.99) if illiq.stack().shape[0] > 0 else np.inf
    return illiq.clip(upper=upper)


# ══════════════════════════════════════════════════════════════
# 基本面因子
# ══════════════════════════════════════════════════════════════

def ep_factor(pe_wide: pd.DataFrame) -> pd.DataFrame:
    """盈利收益率：1/PE（PE<=0 设 NaN）。截面 1%/99% quantile winsorize。"""
    return _cross_winsorize(1.0 / pe_wide.where(pe_wide > 0))


def bp_factor(pb_wide: pd.DataFrame) -> pd.DataFrame:
    """账面市值比：1/PB（PB<=0 设 NaN）。截面 1%/99% quantile winsorize。"""
    return _cross_winsorize(1.0 / pb_wide.where(pb_wide > 0))


def roe_factor(pe_wide: pd.DataFrame, pb_wide: pd.DataFrame) -> pd.DataFrame:
    """
    ROE 因子：PB/PE 近似（DuPont 恒等式）。

    ROE_TTM = E/BV = (1/PE) / (1/PB) = PB/PE
    高 ROE = 质量因子 = 正向
    """
    roe = pb_wide / pe_wide.where(pe_wide > 0)
    return roe.clip(-1, 5)  # 截断极端值


def accruals_quality(net_income_wide: pd.DataFrame,
                     total_assets_wide: pd.DataFrame,
                     ocf_wide: pd.DataFrame = None) -> pd.DataFrame:
    """
    应计异象因子（盈利质量）。

    accruals = (净利润 - 经营性现金流) / 总资产
    若无现金流数据，用净利润变化量近似：delta_NI / total_assets

    高应计 = 非现金盈利占比高 = 盈利质量差 = 未来超额收益低（反向因子，direction=-1）
    使用时需取反，或在组合权重中设 direction=-1。

    参数:
        net_income_wide  : 净利润宽表（日期 × 股票），季报频率，可 ffill 到日频
        total_assets_wide: 总资产宽表（日期 × 股票）
        ocf_wide         : 经营性现金流宽表（可选）；为 None 时用净利润变化量近似

    返回:
        同形状 DataFrame，值域截断至 [-1, 1]

    来源：Sloan 1996 / 应计异象
    注意：输入为季报频率时建议先 ffill 对齐到日频再传入
    """
    assets = total_assets_wide.replace(0, np.nan)
    if ocf_wide is not None:
        # 标准定义：(净利润 - 经营性现金流) / 总资产
        accruals = (net_income_wide - ocf_wide) / assets
    else:
        # 简化近似：净利润季度变化 / 总资产（适用于只有利润表的场景）
        delta_ni = net_income_wide.diff()
        accruals = delta_ni / assets
    return accruals.clip(-1, 1)


def earnings_momentum(net_profit_growth_wide: pd.DataFrame,
                      window: int = 4) -> pd.DataFrame:
    """
    盈利动量因子（Earnings Acceleration）。

    计算净利润同比增速的环比变化（加速度），正向因子。
    季报频率输入，ffill后适用于日频策略。

    EPS_ACC = net_profit_growth_t - net_profit_growth_{t-window}

    参数:
        net_profit_growth_wide: 净利润同比增速宽表（季报×股票，已ffill到日频）
        window: 差分窗口，默认4季（即同比加速度）

    返回:
        同形状 DataFrame，盈利加速度；截断至 [-2, 2]（增速变化超过200%视为异常）

    来源：Novy-Marx 2013 / 盈利动量研究
    """
    acc = net_profit_growth_wide.diff(window)
    # 截断极端值（增速变化超过200%视为异常）
    return acc.clip(-2, 2)


def dividend_yield(close_wide: pd.DataFrame,
                   dps_wide: pd.DataFrame) -> pd.DataFrame:
    """
    股息率因子：DPS / 收盘价，正向（高股息=价值洼地）。

    参数:
        close_wide: 收盘价宽表（日期 × 股票）
        dps_wide: 每股股息宽表（年频数据，ffill到日频）

    返回:
        股息率宽表，截断到 [0, 0.2]（防止极端值）

    来源：价值投资经典 / 高股息溢价
    """
    dy = dps_wide / close_wide.replace(0, np.nan)
    return dy.clip(0, 0.2)


# ══════════════════════════════════════════════════════════════
# 微观结构因子
# ══════════════════════════════════════════════════════════════

def shadow_upper(high: pd.DataFrame, close: pd.DataFrame,
                 window: int = 20) -> pd.DataFrame:
    """上影线（Williams 式）：-mean(high-close, 20)，卖压"""
    raw = high - close
    std = raw / raw.rolling(5, min_periods=1).mean().replace(0, np.nan)
    return -std.rolling(window).mean()


def shadow_lower(close: pd.DataFrame, low: pd.DataFrame,
                 window: int = 20) -> pd.DataFrame:
    """下影线：mean(close-low, 20)，买盘支撑"""
    raw = close - low
    std = raw / raw.rolling(5, min_periods=1).mean().replace(0, np.nan)
    return std.rolling(window).mean()


def amplitude_hidden(high: pd.DataFrame, low: pd.DataFrame,
                     close: pd.DataFrame, window: int = 20,
                     lamb: float = 0.2) -> pd.DataFrame:
    """
    振幅隐藏结构 V_high：高价日振幅。

    按每只股票过去 N 天的收盘价排序，只取最高 lamb 比例天数的振幅均值。
    来源：开源证券-市场微观结构系列七
    """
    amp = high / low - 1
    result = pd.DataFrame(np.nan, index=close.index, columns=close.columns)

    for col in close.columns:
        c = close[col].dropna()
        a = amp[col].dropna()
        common = c.index.intersection(a.index)
        if len(common) < window:
            continue
        c, a = c[common], a[common]
        for i in range(window, len(c)):
            w = slice(i - window, i)
            c_w = c.iloc[w]
            a_w = a.iloc[w]
            # 高价天数（top lamb 比例）
            thresh = c_w.quantile(1 - lamb)
            high_days = c_w >= thresh
            v_high = a_w[high_days].mean()
            result.at[c.index[i], col] = v_high

    # 取负：高价日振幅大 = 顶部剧烈波动 = 看空
    return -result


def w_reversal(price: pd.DataFrame, amount: pd.DataFrame = None,
               window: int = 20) -> pd.DataFrame:
    """
    W 因子反转：按成交额高低分天，取高额日累计收益 - 低额日累计收益。

    高 W = 大资金推升了价格 → 未来反转概率大 → 取负。
    来源：开源证券-市场微观结构系列一
    """
    ret = price.pct_change()
    if amount is None:
        # 用 |ret| * price 作为成交额代理
        amount = ret.abs() * price

    result = pd.DataFrame(np.nan, index=price.index, columns=price.columns)
    for i in range(window, len(price)):
        r_w = ret.iloc[i - window:i]
        a_w = amount.iloc[i - window:i]
        # 按成交额中位数分组
        median_a = a_w.median(axis=0)
        high_amt = a_w >= median_a
        m_high = (r_w * high_amt).sum(axis=0)
        m_low = (r_w * ~high_amt).sum(axis=0)
        result.iloc[i] = m_high - m_low

    return -result


# ══════════════════════════════════════════════════════════════
# 行为金融因子
# ══════════════════════════════════════════════════════════════

def cgo(price: pd.DataFrame, turnover: pd.DataFrame = None,
        lookback: int = 60) -> pd.DataFrame:
    """
    处置效应因子（CGO）：换手率加权历史成本 vs 现价。

    简化版：用 rolling VWAP 近似参考价格。
    来源：国信证券行为金融系列二
    """
    if turnover is not None:
        # 换手率加权均价
        turn = turnover.clip(0.01, None)
        weighted_price = (price * turn).rolling(lookback).sum() / turn.rolling(lookback).sum()
    else:
        weighted_price = price.rolling(lookback).mean()

    # CGO = (price / reference) - 1，取负
    return -(price / weighted_price - 1)


def str_salience(stock_ret: pd.DataFrame, market_ret: pd.Series,
                 window: int = 20) -> pd.DataFrame:
    """
    凸显理论因子（STR）：关注度加权收益。

    来源：Cosemans & Frehen 2021 + 方正证券
    """
    mkt = market_ret.reindex(stock_ret.index)
    diff = stock_ret.sub(mkt, axis=0).abs()
    denom = stock_ret.abs().add(mkt.abs(), axis=0) + 0.1
    sigma = diff / denom
    return -(sigma * stock_ret).rolling(window).mean()


def team_coin(price: pd.DataFrame, window: int = 20) -> pd.DataFrame:
    """
    球队硬币因子：低波动看动量，高波动看反转。

    来源：Moskowitz 2021 JF / 方正证券
    """
    ret = price.pct_change()
    ret_mean = ret.rolling(window).mean()
    ret_std = ret.rolling(window).std()
    mkt_std = ret_std.mean(axis=1)
    is_coin = ret_std.lt(mkt_std, axis=0)
    return ret_mean.where(is_coin, -ret_mean)


# ══════════════════════════════════════════════════════════════
# 网络/关系因子
# ══════════════════════════════════════════════════════════════

def network_scc(price: pd.DataFrame, window: int = 20) -> pd.DataFrame:
    """
    空间中心度因子（SCC）：与其他股票收益相关性的均值。

    高 SCC = 跟随市场走 → 低特异性 → 取负（低 SCC 有更高超额）。
    来源：QuantsPlaybook/B-因子构建类/股票网络与网络中心度因子
    """
    ret = price.pct_change()
    result = pd.DataFrame(np.nan, index=price.index, columns=price.columns)

    # 每 5 天算一次（加速）
    for i in range(window, len(ret), 5):
        r_w = ret.iloc[i - window:i].dropna(axis=1, how="all")
        if r_w.shape[1] < 10:
            continue
        # 截面平均相关系数
        corr = r_w.corr()
        n = len(corr)
        avg_corr = (corr.sum(axis=1) - 1) / (n - 1)  # 去掉自相关
        # SCC = 1 / (2*(1 - avg_corr))
        scc = 1.0 / (2 * (1 - avg_corr.clip(-0.99, 0.99)))
        for col in scc.index:
            if col in result.columns:
                result.at[price.index[i], col] = scc[col]

    # 填充（每 5 天算一次，中间 ffill）
    result = result.ffill()
    # 低中心度 = 高超额
    return -result


def apm_overnight(open_price: pd.DataFrame, close: pd.DataFrame,
                  market_open: pd.Series = None, market_close: pd.Series = None,
                  window: int = 20) -> pd.DataFrame:
    """
    APM 因子（隔夜/日间分离）：隔夜收益的信息含量。

    隔夜收益 = open_today / close_yesterday - 1
    日间收益 = close_today / open_today - 1
    APM = t-stat(overnight_resid - daytime_resid)

    来源：QuantsPlaybook/B-因子构建类/APM因子模型
    """
    overnight = open_price / close.shift(1) - 1
    daytime = close / open_price - 1

    # 如果有基准则回归取残差，否则直接用差
    if market_open is not None and market_close is not None:
        mkt_on = market_open / market_close.shift(1) - 1
        mkt_dt = market_close / market_open - 1
        # 简化：减去市场
        overnight = overnight.sub(mkt_on, axis=0)
        daytime = daytime.sub(mkt_dt, axis=0)

    # APM = rolling mean(overnight - daytime) / std(overnight - daytime) * sqrt(N)
    diff = overnight - daytime
    mean_d = diff.rolling(window).mean()
    std_d = diff.rolling(window).std()
    apm = mean_d / std_d.replace(0, np.nan) * np.sqrt(window)
    return apm


# ══════════════════════════════════════════════════════════════
# 筹码因子
# ══════════════════════════════════════════════════════════════

def _chip_moments(price: pd.DataFrame, turnover: pd.DataFrame,
                  lookback: int = 60):
    """
    计算筹码分布的四个矩（ARC, VRC, SRC, KRC）。

    来源：QuantsPlaybook/B-因子构建类/筹码因子

    返回 dict of DataFrames: {arc, vrc, src, krc}
    """
    turn = turnover / 100 if turnover.max().max() > 1 else turnover.copy()
    turn = turn.clip(0.001, 1.0)

    arc = pd.DataFrame(np.nan, index=price.index, columns=price.columns)
    vrc = arc.copy()
    src = arc.copy()
    krc = arc.copy()

    for i in range(lookback, len(price)):
        p_w = price.iloc[i - lookback:i].values  # (lookback, n)
        t_w = turn.iloc[i - lookback:i].values

        current = price.iloc[i].values

        # 权重：换手率 × 后续存活率
        weights = np.zeros_like(t_w)
        survive = np.ones(t_w.shape[1])
        for t in range(lookback - 1, -1, -1):
            weights[t] = t_w[t] * survive
            survive *= (1 - t_w[t])
        w_sum = weights.sum(axis=0)
        w_sum[w_sum == 0] = 1
        weights /= w_sum

        # 相对成本
        rc = 1 - p_w / np.where(current > 0, current, np.nan)

        # 四矩
        _arc = (weights * rc).sum(axis=0)
        _vrc = (weights * (rc - _arc) ** 2).sum(axis=0)
        _vrc = np.clip(_vrc, 1e-10, None)
        _src = (weights * (rc - _arc) ** 3).sum(axis=0) / _vrc ** 1.5
        _krc = (weights * (rc - _arc) ** 4).sum(axis=0) / _vrc ** 2

        arc.iloc[i] = _arc
        vrc.iloc[i] = _vrc
        src.iloc[i] = _src
        krc.iloc[i] = _krc

    return {"arc": arc, "vrc": vrc, "src": src, "krc": krc}


def chip_arc(price: pd.DataFrame, turnover: pd.DataFrame,
             lookback: int = 60) -> pd.DataFrame:
    """筹码平均相对成本：ARC > 0 表示平均浮盈"""
    return _chip_moments(price, turnover, lookback)["arc"]


def chip_vrc(price: pd.DataFrame, turnover: pd.DataFrame,
             lookback: int = 60) -> pd.DataFrame:
    """筹码成本离散度：高 VRC = 持仓成本分散"""
    return _chip_moments(price, turnover, lookback)["vrc"]


# ══════════════════════════════════════════════════════════════
# 风险因子
# ══════════════════════════════════════════════════════════════

def idiosyncratic_volatility(price: pd.DataFrame,
                             market_ret: pd.Series = None,
                             window: int = 60) -> pd.DataFrame:
    """
    特质波动率因子（IVOL）：个股相对市场的残差波动率。

    假设：特质波动率高的股票难以套利，趋向被高估，未来收益偏低。
    方向：-1（高 IVOL → 低收益，取负后高值 = 看多信号）

    计算步骤：
      1. 计算日收益率；若无市场收益率则用截面等权均值
      2. 滚动估计 beta = cov(ret, mkt) / var(mkt)
      3. 残差 = ret - beta * mkt
      4. IVOL = rolling std(残差, window)
      5. 取负（方向修正）

    实现采用向量化方式，避免逐股票循环：
      - rolling cov/var 用 pandas rolling().cov()

    参数:
        price      : 收盘价宽表（日期 × 股票）
        market_ret : 市场日收益率序列（可选）；为 None 时用截面等权均值
        window     : 滚动窗口天数，默认 60

    返回:
        同形状 DataFrame，值越大表示特质风险越低（看多方向）

    来源：Ang et al. 2006 JF / A股特质波动率异象
    """
    ret = price.pct_change()

    # 市场收益：传入或用截面均值
    if market_ret is None:
        mkt = ret.mean(axis=1)
    else:
        mkt = market_ret.reindex(ret.index)

    # 向量化滚动 OLS：beta = rolling_cov(ret, mkt) / rolling_var(mkt)
    # rolling().cov() 返回 DataFrame（stock × date）
    roll_cov = ret.rolling(window).cov(mkt)       # shape: (date × stock)
    roll_var = mkt.rolling(window).var()           # shape: (date,)

    # 避免除零
    roll_var_safe = roll_var.replace(0, np.nan)
    beta = roll_cov.div(roll_var_safe, axis=0)     # shape: (date × stock)

    # 残差 = ret - beta * mkt
    residual = ret.sub(beta.mul(mkt, axis=0), axis=0)

    # IVOL = rolling std of residuals（min_periods = window//2 保留边缘数据）
    ivol = residual.rolling(window, min_periods=window // 2).std()

    # 方向 -1：高 IVOL 预期低收益
    return -ivol


# ══════════════════════════════════════════════════════════════
# 行业因子
# ══════════════════════════════════════════════════════════════

def industry_momentum(price: pd.DataFrame,
                      industry_map: dict,
                      formation: int = 60,
                      skip: int = 5) -> pd.DataFrame:
    """
    行业动量因子：过去 formation 天（跳过最近 skip 天）的行业平均收益。

    假设：A 股板块轮动明显，行业动量效应显著，强势行业持续跑赢。
    方向：+1（高行业动量 → 正向信号）

    计算步骤：
      1. 计算股票日收益率
      2. 按 industry_map 分组，等权平均得到行业日收益率
      3. 每只股票的因子值 = 其所属行业的 formation 期累计收益
         （窗口为 [t-formation-skip, t-skip]，跳过最近 skip 天）
      4. 将行业因子值映射回个股

    参数:
        price        : 收盘价宽表（日期 × 股票）
        industry_map : dict，股票代码 → 行业代码（SW 一级行业）
        formation    : 动量形成期天数，默认 60
        skip         : 跳过最近 N 天（避免短期反转污染），默认 5

    返回:
        同形状 DataFrame，值越大表示行业动量越强

    来源：Moskowitz & Grinblatt 1999 JF / A股行业动量研究
    """
    ret = price.pct_change()

    # 将 industry_map 对齐到当前股票列（忽略 map 中不存在的股票）
    stocks = price.columns.tolist()
    ind_series = pd.Series({s: industry_map.get(s) for s in stocks})

    # 计算行业等权日收益率：行业 × 日期
    ind_codes = ind_series.dropna().unique()
    ind_ret = {}
    for ind in ind_codes:
        members = ind_series[ind_series == ind].index.tolist()
        # 只取当前 price 中有的股票
        members = [m for m in members if m in ret.columns]
        if members:
            ind_ret[ind] = ret[members].mean(axis=1)
    ind_ret_df = pd.DataFrame(ind_ret)  # shape: (date × industry)

    # 行业动量：窗口 [t-formation-skip, t-skip] 的累计收益
    # = rolling sum over formation days, shifted by skip days
    ind_mom = ind_ret_df.rolling(formation).sum().shift(skip)

    # 将行业动量映射回个股
    result = pd.DataFrame(np.nan, index=price.index, columns=price.columns)
    for stock in stocks:
        ind = industry_map.get(stock)
        if ind is not None and ind in ind_mom.columns:
            result[stock] = ind_mom[ind]

    return result


# ══════════════════════════════════════════════════════════════
# 微观结构因子（续）
# ══════════════════════════════════════════════════════════════

def price_volume_divergence(price: pd.DataFrame,
                            volume: pd.DataFrame,
                            window: int = 20) -> pd.DataFrame:
    """
    价量背离因子：价格变化与成交量变化的滚动 Spearman 相关系数。

    假设：价涨量缩（或价跌量增）是行情不可持续的信号，价量背离者未来收益偏低。
    方向：-1（价量相关性低 = 背离信号 = 看空；取负后高值 = 价量一致 = 看多）

    计算步骤（rank-then-pearson 近似 Spearman，避免逐列循环）：
      1. price_chg = price.pct_change()
      2. vol_chg   = volume.pct_change()
      3. 分别对 price_chg、vol_chg 计算滚动截面排名（归一化到 [0,1]）
      4. 两组排名的滚动 Pearson 相关（列维度）≈ Spearman 相关
      5. 取负（方向修正）

    注意：此处 Spearman 是对每只股票时序上的相关，而非截面相关。
    逐列 rolling corr 是 pandas 原生操作，性能可接受。

    参数:
        price  : 收盘价宽表（日期 × 股票）
        volume : 成交量宽表（日期 × 股票），与 price 形状对齐
        window : 滚动窗口天数，默认 20

    返回:
        同形状 DataFrame，值越大表示价量越一致（看多）

    来源：价量关系研究 / A股微观结构
    """
    price_chg = price.pct_change()
    vol_chg = volume.pct_change()

    # 滚动排名（rank-then-pearson 近似 Spearman）
    # pandas rolling().rank() 返回窗口内的排名（1 到 window）
    price_rank = price_chg.rolling(window).rank()
    vol_rank = vol_chg.rolling(window).rank()

    # 逐列计算滚动 Pearson（近似 Spearman）
    # rolling().corr() 对两个 DataFrame 逐列配对
    spearman_approx = price_rank.rolling(window).corr(vol_rank)

    # 方向 -1：价量背离（负相关）= 看空，取负后高值 = 价量一致
    return -spearman_approx


# ══════════════════════════════════════════════════════════════
# 行为金融因子（续）
# ══════════════════════════════════════════════════════════════

def relative_turnover(turnover: pd.DataFrame,
                      short_window: int = 10,
                      long_window: int = 60) -> pd.DataFrame:
    """
    相对换手率因子：短期换手率相对长期均值的倍数。

    假设：换手率异常飙升反映散户追涨行为，短期热度股票往往后续反转（A股注意力效应）。
    方向：-1（高相对换手率 → 反转 → 取负后高值 = 低换手 = 看多）

    计算步骤：
      1. short_avg = turnover.rolling(short_window).mean()
      2. long_avg  = turnover.rolling(long_window).mean()
      3. rel_turn  = short_avg / long_avg
      4. 截断（1%, 99% Winsorize）去极端值
      5. 取负（方向修正）

    参数:
        turnover     : 换手率宽表（日期 × 股票），值域通常 0~1 或 0%~100%
        short_window : 短期均值窗口，默认 10 天
        long_window  : 长期均值窗口，默认 60 天

    返回:
        同形状 DataFrame，值越大表示相对换手越低（反转概率越小，看多）

    来源：Barber & Odean 2008 / A股散户注意力效应
    """
    short_avg = turnover.rolling(short_window).mean()
    long_avg = turnover.rolling(long_window).mean()

    # 避免除零
    long_avg_safe = long_avg.replace(0, np.nan)
    rel_turn = short_avg / long_avg_safe

    # Winsorize 1% / 99%（按全表分位数）
    stacked = rel_turn.stack()
    if len(stacked) > 0:
        lo = stacked.quantile(0.01)
        hi = stacked.quantile(0.99)
        rel_turn = rel_turn.clip(lower=lo, upper=hi)

    # 方向 -1：高换手倍数 → 反转风险高
    return -rel_turn


# ══════════════════════════════════════════════════════════════
# 基本面质量因子（续）
# ══════════════════════════════════════════════════════════════

def cfo_accrual_quality(
    net_income_wide: pd.DataFrame,
    ocf_wide: pd.DataFrame,
    total_assets_wide: pd.DataFrame,
    window_quarters: int = 8,
) -> pd.DataFrame:
    """
    现金流应计利润质量因子（CFO Accrual Quality）。

    应计利润标准差衡量盈利质量，A股存在盈利操纵，波动越低说明质量越高。
    通过计算单季度应计利润的滚动标准差来度量盈利的稳定性：
    标准差越低表示每季度报告利润与实际现金流之间的差异越稳定，盈利质量越高。

    计算步骤：
      1. 单季度应计利润：accruals_q = (净利润 - 经营性现金流) / 总资产
         （总资产为 0 时替换为 NaN 避免除零）
      2. 滚动标准差：rolling(window_quarters, min_periods=6).std()
      3. 方向 -1：标准差越低 = 盈利质量越高 = 预期收益越高；取负作为正向信号
      4. 截面 Winsorize（1%/99%）：按每个报告期对截面做去极端值处理

    参数:
        net_income_wide  : 季报净利润宽表（report_date × symbol）
        ocf_wide         : 季报经营性现金流宽表（report_date × symbol），与 net_income_wide 索引对齐
        total_assets_wide: 季报总资产宽表（report_date × symbol），与 net_income_wide 索引对齐
        window_quarters  : 滚动窗口（季度数），默认 8 季（两年）

    返回:
        同形状 DataFrame（report_date × symbol），值越大表示盈利质量越高（正向因子）

    来源：Dechow & Dichev 2002 / 应计利润质量模型
    """
    # 步骤1：单季度应计利润，总资产为0时替换 NaN
    assets_safe = total_assets_wide.replace(0, np.nan)
    accruals_q = (net_income_wide - ocf_wide) / assets_safe

    # 步骤2：滚动标准差，要求至少 6 期有效
    accrual_std = accruals_q.rolling(window_quarters, min_periods=6).std()

    # 步骤3：方向 -1，取负（低标准差 → 高值 → 高盈利质量）
    factor = -accrual_std

    # 步骤4：截面 Winsorize（1%/99%），按每个报告期行处理
    def _winsorize_row(row: pd.Series) -> pd.Series:
        valid = row.dropna()
        if len(valid) < 5:
            return row
        lo = valid.quantile(0.01)
        hi = valid.quantile(0.99)
        return row.clip(lower=lo, upper=hi)

    factor = factor.apply(_winsorize_row, axis=1)
    return factor


# ══════════════════════════════════════════════════════════════
# 微观结构因子（增持代理）
# ══════════════════════════════════════════════════════════════

def insider_buying_proxy(
    close: pd.DataFrame,
    high: pd.DataFrame,
    low: pd.DataFrame,
    volume: pd.DataFrame,
    ch_window: int = 10,
    vol_window: int = 20,
) -> pd.DataFrame:
    """
    增持代理因子（Insider Buying Proxy）。

    代理大股东增持的量价结构因子，通过收盘价位置和向上成交量占比识别机构积累行为。
    机构资金在建仓时倾向于将收盘价推至日内高位，同时上涨日成交量占比明显高于普通交易日。

    计算步骤：
      1. 收盘价在日内价格区间的相对位置：
         ctr = (close - low) / (high - low + 1e-8)，值域 [0, 1]
      2. 排除涨停日（收益率 >= 9.85%）和跌停日（收益率 <= -9.85%）：
         这些日子的价格位置失真，设为 NaN
      3. 滚动均值：ch_ratio = ctr.rolling(ch_window, min_periods=5).mean()
      4. 向上成交量占比：
         - is_up：每日收益率 > 0 的布尔标记
         - up_vol_frac = rolling_sum(volume * is_up, vol_window) / rolling_sum(volume, vol_window)
      5. 截面排名合成（0~1 均匀化）：
         score = 0.5 * rank(ch_ratio) + 0.5 * rank(up_vol_frac)，逐日截面排名
      6. 方向 +1：分值越高代表积累信号越强

    参数:
        close      : 收盘价宽表（日期 × 股票）
        high       : 最高价宽表（日期 × 股票）
        low        : 最低价宽表（日期 × 股票）
        volume     : 成交量宽表（日期 × 股票）
        ch_window  : 收盘价位置滚动均值窗口，默认 10 天
        vol_window : 成交量统计滚动窗口，默认 20 天

    返回:
        同形状 DataFrame，值越大表示积累信号越强（正向因子）

    来源：国泰君安2020 / 增持预测因子
    """
    # 步骤1：收盘价在日内区间的相对位置（close-to-range ratio）
    ctr = (close - low) / (high - low + 1e-8)

    # 步骤2：排除涨跌停日（价格位置失真）
    daily_ret = close.pct_change()
    is_limit_up = daily_ret >= 0.0985
    is_limit_down = daily_ret <= -0.0985
    # 涨停或跌停日设为 NaN
    ctr = ctr.where(~is_limit_up, np.nan)
    ctr = ctr.where(~is_limit_down, np.nan)

    # 步骤3：滚动均值，要求至少 5 期有效
    ch_ratio = ctr.rolling(ch_window, min_periods=5).mean()

    # 步骤4：向上成交量占比
    is_up = (daily_ret > 0).astype(float)
    up_vol = (volume * is_up).rolling(vol_window, min_periods=10).sum()
    total_vol = volume.rolling(vol_window, min_periods=10).sum()
    up_vol_frac = up_vol / total_vol.replace(0, np.nan)

    # 步骤5：截面排名合成（逐日，axis=1）
    # pct=True 返回 0~1 分位数，na_option='keep' 保留 NaN
    ch_rank = ch_ratio.rank(axis=1, pct=True, na_option="keep")
    uv_rank = up_vol_frac.rank(axis=1, pct=True, na_option="keep")
    score = 0.5 * ch_rank + 0.5 * uv_rank

    return score


# ══════════════════════════════════════════════════════════════
# 新增因子批次（Round 2）
# ══════════════════════════════════════════════════════════════

def high_52w_ratio(price: pd.DataFrame) -> pd.DataFrame:
    """
    52 周高点锚定效应：价格距 52 周高点的接近程度。
    公式：close / rolling(252, min_periods=126).max()
    方向：+1，比值越高说明动量越强，锚定效应使其延续上涨。
    """
    return price / price.rolling(252, min_periods=126).max()


def return_skewness_20d(price: pd.DataFrame) -> pd.DataFrame:
    """
    20 日收益率偏度（彩票效应）：A 股散户偏好高偏度股票导致其被高估。
    公式：pct_change().rolling(20, min_periods=10).skew() * -1
    方向：-1，高偏度股票未来收益偏低，取负使高分对应看多。
    """
    return price.pct_change().rolling(20, min_periods=10).skew() * -1


def beta_factor(price: pd.DataFrame) -> pd.DataFrame:
    """
    低 beta 异象：低 beta 股票因被散户忽视而被低估，长期超额收益更高。
    公式：rolling(60) cov(ret, market_ret) / var(market_ret)，取负后低 beta 得高分。
    方向：-1，高 beta 看空；函数内取负输出，低 beta = 高因子值 = 看多。
    """
    ret = price.pct_change()
    # 等权市场收益（截面均值）
    market_ret = ret.mean(axis=1)

    # 向量化 rolling beta：cov(ret_i, mkt) / var(mkt)
    # rolling().cov(other) 对每列分别计算与 other 的滚动协方差
    roll_cov = ret.rolling(60, min_periods=30).cov(market_ret)   # shape: date × stock
    roll_var = market_ret.rolling(60, min_periods=30).var()       # shape: date

    beta = roll_cov.div(roll_var.replace(0, np.nan), axis=0)
    # 取负：低 beta 得高分
    return -beta


def max_ret_1m(price: pd.DataFrame) -> pd.DataFrame:
    """
    最大单日收益（MAX effect）：过去一个月最大单日涨幅越高，未来收益越低（彩票效应）。
    公式：pct_change().rolling(20, min_periods=10).max() * -1
    方向：-1，高 MAX 看空，函数内取负后高值对应低 MAX 的看多方向。
    """
    return price.pct_change().rolling(20, min_periods=10).max() * -1


def turnover_acceleration(turnover: pd.DataFrame) -> pd.DataFrame:
    """
    换手率加速：短期换手率相对中期均值的加速比，捕捉资金入场/出场信号。
    公式：rolling(5).mean() / rolling(20).mean()
    方向：待测试（先 +1，让 IC 告知方向）；比值 >1 表示换手加速。
    """
    short_mean = turnover.rolling(5, min_periods=3).mean()
    long_mean = turnover.rolling(20, min_periods=10).mean()
    return short_mean / long_mean.replace(0, np.nan)


def bollinger_pct(price: pd.DataFrame) -> pd.DataFrame:
    """
    Bollinger 带位置百分比：散户主导市场中，价格偏离 Bollinger 带有均值回归倾向。
    公式：(price - lower) / (upper - lower)，然后取负后偏移 0.5 使低位置得高分。
    方向：+1（低位置 = 超卖 = 看多），返回 -(pct - 0.5) 使超卖区域因子值为正。
    """
    ma20 = price.rolling(20).mean()
    std20 = price.rolling(20).std()
    upper = ma20 + 2 * std20
    lower = ma20 - 2 * std20
    band_width = (upper - lower).replace(0, np.nan)
    pct = (price - lower) / band_width
    # 低位置(pct→0)看多；取负后偏移 0.5 使超卖时值为正
    return -(pct - 0.5)


def volume_surge(price: pd.DataFrame, volume: pd.DataFrame) -> pd.DataFrame:
    """
    量价突增（smart money 代理）：放量上涨是机构资金入场信号，量缩下跌是出场信号。
    公式：vol_ratio = volume / rolling(20).mean()；surge = pct_change * vol_ratio；返回 rolling(5).mean()
    方向：+1，正值表示放量上涨（看多），负值表示放量下跌（看空）。
    """
    vol_mean = volume.rolling(20, min_periods=10).mean().replace(0, np.nan)
    vol_ratio = volume / vol_mean
    surge_flag = price.pct_change() * vol_ratio
    return _cross_winsorize(surge_flag.rolling(5).mean())


def bid_ask_spread_proxy(high: pd.DataFrame, low: pd.DataFrame) -> pd.DataFrame:
    """
    买卖价差代理（简化 Corwin-Schultz spread）：high-low spread 估计流动性成本。
    公式：spread = (high - low) / ((high + low) / 2)，rolling(20).mean()，取负。
    方向：-1（低 spread = 流动性好 = 高因子值），取负后低成本得高分。
    """
    mid = (high + low) / 2
    spread = (high - low) / mid.replace(0, np.nan)
    spread_20d = spread.rolling(20, min_periods=10).mean()
    return _cross_winsorize(-spread_20d)


# ══════════════════════════════════════════════════════════════
# Round 2 新因子（2026-04-14 因子挖掘会话）
# ══════════════════════════════════════════════════════════════


def price_anchor_dist(price: pd.DataFrame, window: int = 20) -> pd.DataFrame:
    """
    价格整数心理锚距离因子（A 股行为金融）。
    A 股散户对整数价格（5/10/20 元）有强心理锚，接近整数时抛压集中。
    frac = price % 1（小数部分）；考虑到最近整数：dist = min(frac, 1-frac)。
    小 dist = 价格紧贴整数 = 阻力/支撑密集 → 预期短期均值回归。
    方向：-1（高值=远离整数=阻力少=看多；取负后低 dist 高分）
    返回值已取负（-dist 截面 z-score），高值=远离整数=看多。
    """
    frac = price % 1.0
    dist_to_nearest = pd.concat([frac, 1.0 - frac], axis=0).groupby(level=0).min()
    # 截面 z-score 标准化（消除不同时期的量级差异），取负让"远离整数"为正
    rolling_mean = dist_to_nearest.rolling(window, min_periods=window // 2).mean()
    rolling_std  = dist_to_nearest.rolling(window, min_periods=window // 2).std().clip(lower=1e-8)
    zscore = (dist_to_nearest - rolling_mean) / rolling_std
    return zscore  # 正值=当前距整数比历史更远=阻力少=看多


def close_minus_open_volume(close: pd.DataFrame, open_price: pd.DataFrame,
                             volume: pd.DataFrame, window: int = 20) -> pd.DataFrame:
    """
    价格方向 × 成交量（主力净买入代理）。
    (close - open) * volume 捕捉单日资金净流向，rolling mean 平滑信号。
    正值 = 持续放量上涨 = 主力吸筹；负值 = 放量下跌 = 主力出货。
    方向：+1（持续正值 = 买方主导 = 看多）
    """
    direction = (close - open_price) / close.replace(0, np.nan)  # 归一化到收益率尺度
    signal = direction * volume / volume.rolling(window, min_periods=window // 2).mean().replace(0, np.nan)
    return _cross_winsorize(signal.rolling(window, min_periods=window // 2).mean())


def win_rate_trend(price: pd.DataFrame, window: int = 20) -> pd.DataFrame:
    """
    胜率趋势因子：短期胜率 vs 长期胜率的差。
    胜率上升趋势代表资金持续流入，与量无关，捕捉纯方向性持续性。
    方向：+1（胜率上升 = 买方持续主导 = 看多）
    """
    ret = price.pct_change()
    up = (ret > 0).astype(float)
    long_win  = up.rolling(window, min_periods=window // 2).mean()
    short_win = up.rolling(window // 2, min_periods=max(window // 4, 3)).mean()
    return short_win - long_win  # 正 = 最近胜率在提升

def overnight_return(open_price: pd.DataFrame, close: pd.DataFrame,
                     window: int = 20) -> pd.DataFrame:
    """
    隔夜收益因子：open_t / close_{t-1} - 1 的滚动均值。
    代理信息不对称与隔夜信息流入强度，与日内动量（low_vol）机制不同。
    方向：+1（持续正隔夜收益 = 信息积累 = 看多）
    """
    overnight = open_price / close.shift(1) - 1
    return _cross_winsorize(overnight.rolling(window, min_periods=window // 2).mean())


def sharpe_20d(price: pd.DataFrame, window: int = 20) -> pd.DataFrame:
    """
    20 日 Sharpe 比率（风险调整后动量）。
    = mean(ret) / std(ret)，不同于 low_vol_20d（纯波动）和动量（纯方向）。
    方向：+1（高 Sharpe = 稳定上涨 = 看多）
    """
    ret = price.pct_change()
    mean_ret = ret.rolling(window, min_periods=window // 2).mean()
    std_ret = ret.rolling(window, min_periods=window // 2).std()
    return mean_ret / std_ret.replace(0, np.nan)


def up_down_volume_ratio(close: pd.DataFrame, volume: pd.DataFrame,
                          window: int = 20) -> pd.DataFrame:
    """
    上涨日成交量 / 下跌日成交量 比率（买卖盘积极性代理）。
    A 股特征：主力吸筹时上涨放量、下跌缩量；出货时相反。
    方向：+1（高比值 = 上涨吸引更多成交 = 看多）
    """
    ret = close.pct_change()
    up_vol = volume.where(ret > 0, 0).rolling(window, min_periods=window // 2).mean()
    down_vol = volume.where(ret < 0, 0).rolling(window, min_periods=window // 2).mean()
    return up_vol / down_vol.replace(0, np.nan)


def ret_autocorr_1d(price: pd.DataFrame, window: int = 20) -> pd.DataFrame:
    """
    日收益率 lag-1 自相关系数（均值回归速度代理）。
    高负自相关 = 快速均值回归 = 逆势因子；高正自相关 = 动量延续。
    方向：-1（负自相关高 = 强均值回归 = 未来反转，取负后高值看空）
    实际返回值已取负：返回 -autocorr，正向因子（低负自相关，即接近 0 或正，较稳定）。
    """
    ret = price.pct_change()

    def _rolling_autocorr(col: pd.Series) -> pd.Series:
        return col.rolling(window, min_periods=window // 2).apply(
            lambda x: pd.Series(x).autocorr(lag=1) if len(x) >= 4 else np.nan,
            raw=False
        )

    # 向量化版本：手动计算 lag-1 Pearson 相关
    ret_lag = ret.shift(1)
    n = window
    # rolling cov(ret, ret_lag) / (std(ret) * std(ret_lag))
    mean_r  = ret.rolling(n, min_periods=n // 2).mean()
    mean_l  = ret_lag.rolling(n, min_periods=n // 2).mean()
    cov_rl  = (ret * ret_lag).rolling(n, min_periods=n // 2).mean() - mean_r * mean_l
    std_r   = ret.rolling(n, min_periods=n // 2).std()
    std_l   = ret_lag.rolling(n, min_periods=n // 2).std()
    autocorr = cov_rl / (std_r * std_l).replace(0, np.nan)
    return -autocorr  # 取负：负自相关 → 高正值 → 看空（强均值回归后反转）


def momentum_6m_skip1m(price: pd.DataFrame) -> pd.DataFrame:
    """
    6 个月动量跳过最近 1 个月（标准截面动量因子）。
    = price_{t-21} / price_{t-126} - 1，避免短期反转噪音。
    A 股中长期动量效应虽弱于美股，但跳过反转期后信号更干净。
    方向：+1（过去 6 个月（跳过最近 1 个月）涨幅高 = 看多）
    """
    return price.shift(21) / price.shift(126) - 1


def vol_asymmetry(price: pd.DataFrame, window: int = 60) -> pd.DataFrame:
    """
    上涨/下跌波动率非对称性因子（尾部风险代理）。
    vol_up = std(returns on positive days, window)
    vol_down = std(returns on negative days, window)
    asymmetry = vol_down / vol_up
    高比值 = 下跌时波动更大 = 尾部崩溃风险高
    低比值 = 上涨下跌对称 = 稳定股票
    方向：-1（高 vol_down/vol_up = 高崩溃风险 = 看空）
    """
    ret = price.pct_change()
    up_mask = ret > 0
    vol_up = ret.where(up_mask).rolling(window, min_periods=window//4).std()
    vol_down = ret.where(~up_mask).rolling(window, min_periods=window//4).std()
    return _cross_winsorize(vol_down / vol_up.replace(0, np.nan))


def earnings_window_proxy(price: pd.DataFrame, window: int = 5) -> pd.DataFrame:
    """
    季末收益公告窗口代理（A 股财报披露效应）。
    A 股季报在 4/8/10/4 月底前后披露；季末前后成交量和价格往往异动。
    用价格相对 MA 在季末月份（3/6/9/12 月最后 20 日）的偏离度作为代理。
    = (price - MA20) / MA20，只在季末 20 日内计算，其余置 0。
    方向：需经 IC 验证
    注意：这是一个季节性/日历因子，信号稀疏但可能捕捉财报效应。
    方向：+1（季末上涨 = 预期好结果 = 动量延续）
    """
    ma = price.rolling(20, min_periods=10).mean().replace(0, np.nan)
    dev = (price - ma) / ma
    # 仅在月末 20 日内有效（月份的后 20 个交易日）
    day_of_month = pd.Series(price.index.day, index=price.index)
    month_end_mask = day_of_month >= 10  # 简化：月中以后的交易日
    return _cross_winsorize(dev.where(month_end_mask.values.reshape(-1, 1), 0))


def return_zscore_20d(price: pd.DataFrame) -> pd.DataFrame:
    """
    当日收益率在近 20 日收益率分布中的 z-score（极端收益信号）。
    = (today_ret - mean_20d_ret) / std_20d_ret
    高 z-score = 今天涨幅远超近期均值 = 短期强力追高 = 反转信号
    低 z-score = 今天跌幅远超近期均值 = 超卖 = 反弹信号
    方向：-1（高 z-score 当日 = 追高 = 均值回归压力）
    """
    ret = price.pct_change()
    mean_ret = ret.rolling(20, min_periods=10).mean()
    std_ret = ret.rolling(20, min_periods=10).std().clip(lower=1e-6)
    return (ret - mean_ret) / std_ret


def avg_intraday_range(high: pd.DataFrame, low: pd.DataFrame,
                       price: pd.DataFrame, window: int = 20) -> pd.DataFrame:
    """
    平均日内波动幅度（振幅稳定性因子）。
    = rolling_mean[(high - low) / price] over window days
    高振幅 = 每天价格大幅波动 = 高散户情绪/噪音
    低振幅 = 价格平稳 = 机构稳定持有或流动性不足
    方向：-1（高振幅 = 高风险/散户主导 = 看空；低振幅 = 质量信号）
    """
    daily_range = (high - low) / price.replace(0, np.nan)
    return daily_range.rolling(window, min_periods=window // 2).mean()


def volume_concentration(volume: pd.DataFrame, window: int = 20) -> pd.DataFrame:
    """
    量能集中度（单日成交量峰值占比）。
    = rolling_max(volume, window) / rolling_sum(volume, window)
    高值：成交量集中在一天（事件驱动/消息刺激，散户一次性拥入）
    低值：成交量均匀分布（持续稳定积累，机构有序买入信号）
    A 股散户倾向在单日消息后集中买入，之后量能迅速萎缩并均值回归。
    方向：-1（高集中度=非持续性拥入=后续看空；选量能均匀的稳定股票）
    """
    vol_max = volume.rolling(window, min_periods=window // 2).max()
    vol_sum = volume.rolling(window, min_periods=window // 2).sum().replace(0, np.nan)
    return vol_max / vol_sum


def vol_regime(price: pd.DataFrame, fast: int = 20, slow: int = 120) -> pd.DataFrame:
    """
    波动率状态比（短期/长期波动率比较）。
    = rolling_fast_vol / rolling_slow_vol
    > 1：当前波动率高于历史基准 = 市场不稳定/过渡期
    < 1：当前波动率低于历史基准 = 价格稳定/积聚期
    在 A 股中：波动率压缩后通常会有方向性突破
    方向：需通过 IC 测试确定（不确定是看多还是看空）
    """
    ret = price.pct_change()
    vol_fast = ret.rolling(fast, min_periods=fast // 2).std()
    vol_slow = ret.rolling(slow, min_periods=slow // 2).std().replace(0, np.nan)
    return vol_fast / vol_slow


def price_momentum_quality(price: pd.DataFrame, window: int = 20) -> pd.DataFrame:
    """
    动量质量因子（风险调整动量）。
    = rolling_window_return / rolling_window_vol
    = 短期夏普比率代理
    高值 = 上涨质量好（涨而不波动）= 机构有序建仓
    低值 = 下跌或高波动上涨 = 散户追涨或不稳定
    方向：需通过 IC 测试确定（A 股可能是反转，也可能是动量延续）
    """
    ret = price.pct_change()
    cum_ret = ret.rolling(window, min_periods=window // 2).sum()
    vol = ret.rolling(window, min_periods=window // 2).std().clip(lower=1e-6)
    return cum_ret / vol


def momentum_3m_skip1m(price: pd.DataFrame) -> pd.DataFrame:
    """
    3 个月动量跳过最近 1 个月（中短期截面动量）。
    = price_{t-21} / price_{t-63} - 1
    区别于 momentum_6m_skip1m（使用 126 日），此处用 63 日，
    捕捉更短的趋势时间窗口。
    A 股中短期动量通常也呈反转，但时间尺度不同于 6M。
    方向：需通过 IC 测试确定（A 股若为反转则方向=-1）
    """
    return price.shift(21) / price.shift(63) - 1


def win_rate_60d(price: pd.DataFrame) -> pd.DataFrame:
    """
    60 日胜率（正收益天数占比）。
    = rolling_60d_mean(daily_ret > 0) — 过去 60 天中正收益的频率
    高胜率 = 持续上涨 = 超买压力（A 股散户追涨）
    低胜率 = 持续下跌 = 超卖机会（A 股均值回归）
    方向：-1（高胜率 = 超买 = 看空；低胜率 = 超卖 = 看多）
    """
    ret = price.pct_change()
    return (ret > 0).astype(float).rolling(60, min_periods=30).mean()


def stock_max_drawdown_60d(price: pd.DataFrame) -> pd.DataFrame:
    """
    股票近 60 日个股最大回撤（风险筛选因子）。
    = (rolling_60d_high - price) / rolling_60d_high
    高最大回撤 = 股票近期波动大/风险高 = 看空（多头组合回避高回撤）
    低最大回撤 = 价格相对平稳 = 低波质量股（配合 low_vol 使用）
    方向：-1（高回撤 = 高风险 = 看空；选近期回撤小的稳定股票）
    """
    rolling_high = price.rolling(60, min_periods=30).max()
    return (rolling_high - price) / rolling_high.replace(0, np.nan)


def vol_scaled_reversal(price: pd.DataFrame, rev_window: int = 5, vol_window: int = 20) -> pd.DataFrame:
    """
    波动率调整的短期反转（风险归因的超买超卖）。
    = (price/price.shift(rev_window)-1) / rolling_vol(vol_window)
    = 短期收益率 ÷ 近期波动率 → 风险调整后的超买程度
    rev_window=5（默认：5 日），vol_window=20（归一化波动率窗口）
    方向：-1（高值=快涨=风险调整后超买=均值回归压力）
    """
    ret_5d = price / price.shift(rev_window) - 1
    vol = price.pct_change().rolling(vol_window, min_periods=vol_window // 2).std().clip(lower=1e-6)
    return ret_5d / vol


def rsi_factor(price: pd.DataFrame, window: int = 14) -> pd.DataFrame:
    """
    RSI 因子（相对强弱指数）。
    RSI = 100 - 100/(1+RS)，RS = avg_up / avg_down over window days。
    低 RSI = 超卖 = 均值回归机会（A 股散户追涨杀跌导致 RSI 极端后反转）。
    方向：-1（高 RSI = 超买 = 看空；取反后低 RSI = 超卖 = 看多）
    """
    delta = price.diff()
    up = delta.clip(lower=0)
    down = (-delta).clip(lower=0)
    avg_up = up.rolling(window, min_periods=window // 2).mean()
    avg_down = down.rolling(window, min_periods=window // 2).mean().replace(0, np.nan)
    rs = avg_up / avg_down
    return 100 - 100 / (1 + rs)


def chaikin_money_flow(close: pd.DataFrame, high: pd.DataFrame,
                       low: pd.DataFrame, volume: pd.DataFrame,
                       window: int = 20) -> pd.DataFrame:
    """
    Chaikin 资金流量因子（CMF）。
    CLV = (2*close - high - low) / (high - low + 1e-6)  → [-1, +1] 日内资金方向
    CMF = rolling_sum(CLV * volume, window) / rolling_sum(volume, window)
    CMF > 0：资金持续流入（机构吸筹）；CMF < 0：资金持续流出（出货）
    方向：+1（高 CMF = 持续资金净流入 = 看多）
    """
    clv = (2 * close - high - low) / (high - low + 1e-6).clip(lower=1e-6)
    clv_vol = clv * volume
    cmf = (clv_vol.rolling(window, min_periods=window // 2).sum() /
           volume.rolling(window, min_periods=window // 2).sum().replace(0, np.nan))
    return cmf


def price_distance_from_ma(price: pd.DataFrame, window: int = 60) -> pd.DataFrame:
    """
    价格相对长期均线的偏离度（均值回归距离因子）。
    = (price - MA_window) / MA_window
    正值：价格高于均线（均值回归压力）
    负值：价格低于均线（均值回归动能）
    长窗口（60d）捕捉中期超买超卖，区别于短期 RSI 指标。
    方向：-1（正偏离 = 高于均线 = 看空，选择低于均线的超卖股票）
    """
    ma = price.rolling(window, min_periods=window // 2).mean().replace(0, np.nan)
    return (price - ma) / ma


def intraday_direction_efficiency(close: pd.DataFrame, open_price: pd.DataFrame,
                                   high: pd.DataFrame, low: pd.DataFrame,
                                   window: int = 20) -> pd.DataFrame:
    """
    日内方向效率因子（趋向一致性）。
    = rolling_mean[(close - open) / (high - low + 1e-6)] over window days
    正值：收盘价更靠近当日最高价（日内趋势向上，机构持续吸筹信号）
    负值：收盘价更靠近当日最低价（日内趋势向下，主力持续出货信号）
    方向：+1（持续正值 = 日内吸筹 = 看多）
    """
    numerator = close - open_price
    denominator = (high - low).clip(lower=1e-6)
    ratio = numerator / denominator
    return ratio.rolling(window, min_periods=window // 2).mean()


def turnover_trend(turnover: pd.DataFrame, fast: int = 5, slow: int = 20) -> pd.DataFrame:
    """
    换手率趋势（智能资金的关注度变化）。
    = 短期换手率均值 / 长期换手率均值（换手率加速）的趋势版本
    与 turnover_acceleration 不同：这里用的是 z-score 形式，
    捕捉换手率的持续上升（资金开始关注）vs 持续下降（资金撤离）。
    z = (fast_ma - slow_ma) / slow_ma.std(slow)
    方向：-1（换手率加速上涨 = 散户涌入 = 均值回归看空）
    """
    fast_ma = turnover.rolling(fast, min_periods=fast // 2).mean()
    slow_ma = turnover.rolling(slow, min_periods=slow // 2).mean().replace(0, np.nan)
    slow_std = turnover.rolling(slow, min_periods=slow // 2).std().clip(lower=1e-8)
    return (fast_ma - slow_ma) / slow_std


def reversal_12m_skip3m(price: pd.DataFrame) -> pd.DataFrame:
    """
    12 个月反转跳过最近 3 个月。
    = price_{t-63} / price_{t-252} - 1，捕捉长期超强股的均值回归。
    A 股长期强势股往往在牛熊转换中大幅回撤；跳过 3 月避短期噪音。
    方向：-1（高 12M 涨幅 = 长期超买 = 均值回归；A 股反转效应）
    """
    return price.shift(63) / price.shift(252) - 1


def vwap_deviation(price: pd.DataFrame, volume: pd.DataFrame, window: int = 20) -> pd.DataFrame:
    """
    价格相对 VWAP 的偏离度（成交量加权平均价偏差因子）。
    VWAP = Σ(price * vol) / Σ(vol)，rolling window 天。
    偏差 = (price - vwap) / vwap，标准化后代表相对成本基础的贵/便宜程度。
    A 股散户倾向追高，价格远高于 VWAP 时通常面临压力。
    方向：-1（正偏差=价格高于均价=浮盈筹码多=压力大；取反选择价格低于均价的股票）
    """
    pv = price * volume
    rolling_pv = pv.rolling(window, min_periods=window // 2).sum()
    rolling_v = volume.rolling(window, min_periods=window // 2).sum().replace(0, np.nan)
    vwap = rolling_pv / rolling_v
    return (price - vwap) / vwap.replace(0, np.nan)


# ══════════════════════════════════════════════════════════════
# 行为金融 — 散户开盘追涨陷阱 (A股专属)
# ══════════════════════════════════════════════════════════════

def retail_open_trap(
    close: pd.DataFrame,
    open_price: pd.DataFrame,
    turnover: pd.DataFrame,
    window: int = 20,
    gap_threshold: float = 0.01,
    turnover_cap: float = 5.0,
) -> pd.DataFrame:
    """
    散户开盘追涨陷阱因子 (Retail Open Gap Trap, ROGT)

    === A 股散户行为背景 ===
    A 股散户有强烈的"隔夜追涨"行为：
      1. 收盘后在微信群/股吧收到推荐，带着「明天会大涨」的预期
      2. 9:30 集中下单追涨 → 股价跳空高开（显著高于前收盘）
      3. 机构利用散户热情在高位出货（分销）
      4. 当天高开低走，收盘价低于开盘价
      5. 追涨散户被套，未来几天持续抛压

    当这个模式在一只股票上持续出现，说明该股正被机构系统性分发，
    未来收益倾向于偏负。

    === 与现有因子的区别 ===
    - overnight_return：取隔夜涨跌均值，正负都算，不区分是否发生日内反转
    - intraday_direction_efficiency：只看日内(close-open)/(high-low)，不考虑开盘跳空幅度
    - close_minus_open_volume：方向 × 成交量，无跳空阈值，无分散户机构逻辑
    本因子专门捕捉「显著正跳空 + 当日收盘回落 + 换手放量」三者同时成立时的信号。

    === 因子构造 ===
    Step 1: 开盘跳空幅度
        gap = (open_t - close_{t-1}) / close_{t-1}
        仅取正跳空（gap > gap_threshold），小跳空视为噪音

    Step 2: 日内反转强度
        intraday_fall = max(open_t - close_t, 0) / open_t
        仅取从开盘下跌的部分（散户被套信号）

    Step 3: 换手率权重
        turnover_weight = turnover_t / rolling_mean(turnover, 60)
        换手放大 → 散户参与度高 → 信号更强
        cap 在 turnover_cap 倍（避免单日异常换手主导）

    Step 4: 日度陷阱强度
        daily_trap = (gap - gap_threshold).clip(0) × intraday_fall × turnover_weight

    Step 5: 滚动聚合（近 window 天的平均陷阱强度）
        raw_factor = rolling_mean(daily_trap, window)

    Step 6: 取负号
        因子值越高 = 近期陷阱越少 = 股价走势越"干净" = 预期超额收益越高
        factor = -raw_factor

    === 参数 ===
    close          : 收盘价宽表 (日期 × 股票)
    open_price     : 开盘价宽表 (日期 × 股票)
    turnover       : 换手率宽表 (日期 × 股票)，单位 %
    window         : 滚动窗口（交易日），默认 20
    gap_threshold  : 最小有效跳空幅度，默认 1%（过滤收盘价微小波动）
    turnover_cap   : 换手率权重上限倍数，默认 5x（防止停牌复牌日单日主导）

    === 因子方向 ===
    正向 (+1)：因子高 → 近期无散户追涨陷阱 → 价格走势干净 → 预期超额收益高

    === 参考文献 ===
    [16] Barber & Odean (2008) - Attention-Induced Trading, JF
         散户因注意力驱动集中买入表现差的股票（高开、上涨日、新闻日）
    [17] 方正证券 A 股行为金融系列 - 散户的开盘效应
         A 股 9:30 集合竞价存在系统性散户追涨行为，尤其在个股有前日涨停时
    """
    # ── Step 1: 开盘跳空幅度（前收盘用 shift(1) 近似）──────────
    prev_close = close.shift(1)
    gap = (open_price - prev_close) / prev_close.replace(0, np.nan)

    # 仅保留正跳空超过阈值的部分（负跳空、小跳空清零）
    gap_excess = (gap - gap_threshold).clip(lower=0)

    # ── Step 2: 日内反转强度（从开盘到收盘的下跌幅度）──────────
    intraday_fall = (open_price - close) / open_price.replace(0, np.nan)
    intraday_fall = intraday_fall.clip(lower=0)  # 只取下跌部分，上涨为 0

    # ── Step 3: 换手率权重（相对换手，衡量散户参与强度）──────────
    turnover_ma = turnover.rolling(60, min_periods=20).mean()
    turnover_weight = (turnover / turnover_ma.replace(0, np.nan)).clip(
        lower=0, upper=turnover_cap
    )

    # ── Step 4: 日度陷阱强度 ─────────────────────────────────────
    # 三个条件同时满足才有非零值：显著正跳空 × 当日下跌 × 换手放大
    daily_trap = gap_excess * intraday_fall * turnover_weight

    # ── Step 5: 滚动聚合 ─────────────────────────────────────────
    raw_factor = daily_trap.rolling(window, min_periods=max(window // 4, 3)).mean()

    # ── Step 6: 取负号（因子越高 = 陷阱越少 = 越看多）────────────
    factor = -raw_factor

    # ── Step 7: 过滤无效零值（关键！）───────────────────────────
    # 问题：factor 恒 ≤ 0，无跳空事件的股票 factor = 0，
    # 这些股票（低流动性/停牌/价格不动）会污染高分位数（Q5）。
    # 修复：窗口内至少有 min_active_days 天出现显著正跳空，
    #       才视为因子有效；否则置 NaN（信号不足，不参与截面排序）。
    min_active_days = max(window // 7, 2)
    gap = (open_price - close.shift(1)) / close.shift(1).replace(0, np.nan)
    active_count = (gap > gap_threshold).rolling(window, min_periods=1).sum()
    factor = factor.where(active_count >= min_active_days)

    return factor


# ══════════════════════════════════════════════════════════════
# 批量构建
# ══════════════════════════════════════════════════════════════

def build_fast_factors(
    price: pd.DataFrame,
    high: pd.DataFrame = None,
    low: pd.DataFrame = None,
    open_price: pd.DataFrame = None,
    pe: pd.DataFrame = None,
    pb: pd.DataFrame = None,
    market_ret: pd.Series = None,
    volume: pd.DataFrame = None,
    net_profit_growth: pd.DataFrame = None,
    dps: pd.DataFrame = None,
    turnover: pd.DataFrame = None,
    industry_map: dict = None,
    net_income_q: pd.DataFrame = None,
    ocf_q: pd.DataFrame = None,
    total_assets_q: pd.DataFrame = None,
) -> dict:
    """
    构建所有快速因子（不含需要逐行循环的慢因子）。

    快速因子用 rolling/向量化计算，适合全量回测。

    参数:
        price              : 收盘价宽表（日期 × 股票），必填
        high               : 最高价宽表，用于微观结构因子
        low                : 最低价宽表，用于微观结构因子
        open_price         : 开盘价宽表，用于 APM 因子
        pe                 : 市盈率宽表，用于 EP 因子
        pb                 : 市净率宽表，用于 BP 因子
        market_ret         : 市场日收益率序列，用于 STR/凸显理论因子
        volume             : 成交量宽表，用于 Amihud 非流动性因子
        net_profit_growth  : 净利润同比增速宽表（季报 ffill 到日频），用于盈利动量因子
        dps                : 每股股息宽表（年报 ffill 到日频），用于股息率因子
        turnover           : 换手率宽表（日期 × 股票），用于相对换手率因子
        industry_map       : dict[symbol, industry]，用于行业动量因子
        net_income_q       : 季报净利润宽表（report_date × symbol），用于现金流应计利润质量
        ocf_q              : 季报经营性现金流宽表（report_date × symbol），用于现金流应计利润质量
        total_assets_q     : 季报总资产宽表（report_date × symbol），用于现金流应计利润质量

    返回:
        dict，key 为因子名，value 为同形状 DataFrame
    """
    dr = price.pct_change()
    factors = {}

    # 技术
    factors["reversal_1m"] = reversal_1m(price)
    factors["low_vol_20d"] = low_vol_20d(price)
    factors["turnover_rev"] = turnover_rev(price)
    factors["enhanced_mom"] = enhanced_momentum(price, 60)
    factors["quality_mom"] = quality_momentum(price, 60)
    factors["ma_ratio_120"] = ma_ratio_momentum(price, 120)

    # 基本面
    if pe is not None:
        factors["ep"] = ep_factor(pe).reindex_like(price)
    if pb is not None:
        factors["bp"] = bp_factor(pb).reindex_like(price)

    # 微观结构（快速版）
    if high is not None and low is not None:
        factors["shadow_upper"] = shadow_upper(high, price)
        factors["shadow_lower"] = shadow_lower(price, low)

    # 行为金融
    factors["cgo_simple"] = -(price / price.rolling(60).mean() - 1)
    factors["team_coin"] = team_coin(price)

    if market_ret is not None:
        factors["str_salience"] = str_salience(dr, market_ret)

    # APM（需要 open）
    if open_price is not None:
        factors["apm_overnight"] = apm_overnight(open_price, price)

    # 流动性：Amihud 非流动性（需要 volume）
    if volume is not None:
        factors["amihud_illiq"] = amihud_illiquidity(price, volume)

    # 基本面：盈利动量（需要净利润同比增速，季报 ffill 到日频）
    if net_profit_growth is not None:
        factors["earnings_momentum"] = earnings_momentum(
            net_profit_growth.reindex_like(price)
        )

    # 基本面：股息率（需要每股股息，年报 ffill 到日频）
    if dps is not None:
        factors["dividend_yield"] = dividend_yield(price, dps.reindex_like(price))

    # 新增：特质波动率（始终可计算，仅依赖 price）
    factors["idiosyncratic_vol"] = idiosyncratic_volatility(price)

    # 新增：行业动量（需要 industry_map）
    if industry_map is not None:
        factors["industry_momentum"] = industry_momentum(price, industry_map)

    # 新增：量价乖离（需要 volume）
    if volume is not None:
        factors["price_vol_divergence"] = price_volume_divergence(price, volume)

    # 新增：相对换手率（需要 turnover）
    if turnover is not None:
        factors["relative_turnover"] = relative_turnover(turnover)

    # 新增：现金流应计利润质量（需要季报三张表）
    if net_income_q is not None and ocf_q is not None and total_assets_q is not None:
        factors["cfo_accrual_quality"] = cfo_accrual_quality(
            net_income_q, ocf_q, total_assets_q
        )

    # 新增：增持代理（需要 high/low/volume）
    if high is not None and low is not None and volume is not None:
        factors["insider_buying_proxy"] = insider_buying_proxy(price, high, low, volume)

    # ── Round 2 新因子 ──────────────────────────────────────────
    # 52 周高点锚定（仅需 price）
    factors["high_52w_ratio"] = high_52w_ratio(price)

    # 收益率偏度（彩票效应，仅需 price）
    factors["return_skewness_20d"] = return_skewness_20d(price)

    # 低 beta 异象（仅需 price）
    factors["beta_factor"] = beta_factor(price)

    # MAX effect（仅需 price）
    factors["max_ret_1m"] = max_ret_1m(price)

    # Bollinger 带位置（仅需 price）
    factors["bollinger_pct"] = bollinger_pct(price)

    # 换手率加速（需要 turnover）
    if turnover is not None:
        factors["turnover_acceleration"] = turnover_acceleration(turnover)

    # 量价突增（需要 volume）
    if volume is not None:
        factors["volume_surge"] = volume_surge(price, volume)

    # 买卖价差代理（需要 high/low）
    if high is not None and low is not None:
        factors["bid_ask_spread_proxy"] = bid_ask_spread_proxy(high, low)

    return factors


FACTOR_CATALOG = {
    "reversal_1m": {"category": "技术", "source": "经典反转", "data": "close"},
    "low_vol_20d": {"category": "技术", "source": "低波动异象", "data": "close"},
    "turnover_rev": {"category": "技术", "source": "换手率反转", "data": "close"},
    "enhanced_mom": {"category": "技术", "source": "QuantsPlaybook-再论动量", "data": "close"},
    "quality_mom": {"category": "技术", "source": "QuantsPlaybook-高质量动量", "data": "close"},
    "ma_ratio_120": {"category": "技术", "source": "QuantsPlaybook-MA比率", "data": "close"},
    "ep": {"category": "基本面", "source": "Fama-French", "data": "pe_ttm"},
    "bp": {"category": "基本面", "source": "Fama-French", "data": "pb"},
    "roe": {"category": "基本面", "source": "DuPont/质量因子", "data": "pe_ttm,pb"},
    "accruals": {"category": "基本面", "source": "Sloan1996", "data": "net_income,total_assets,ocf(可选)"},
    "earnings_momentum": {"category": "基本面", "source": "Novy-Marx2013", "data": "net_profit_growth(季报)"},
    "dividend_yield": {"category": "基本面", "source": "价值投资经典", "data": "close,dps(年报)"},
    "amihud_illiq": {"category": "流动性", "source": "Amihud2002", "data": "close,volume"},
    "shadow_upper": {"category": "微观结构", "source": "东吴证券", "data": "high,close"},
    "shadow_lower": {"category": "微观结构", "source": "东吴证券", "data": "close,low"},
    "cgo_simple": {"category": "行为金融", "source": "国信证券-处置效应", "data": "close"},
    "str_salience": {"category": "行为金融", "source": "Cosemans2021+方正证券", "data": "close,market"},
    "team_coin": {"category": "行为金融", "source": "Moskowitz2021JF", "data": "close"},
    "apm_overnight": {"category": "网络/关系", "source": "QuantsPlaybook-APM", "data": "open,close"},
    "idiosyncratic_vol": {
        "func": idiosyncratic_volatility,
        "category": "风险",
        "source": "Ang et al. 2006 JF / A股特质波动率异象",
        "data": ["close"],
    },
    "industry_momentum": {
        "func": industry_momentum,
        "category": "行业",
        "source": "Moskowitz & Grinblatt 1999 JF / A股行业动量研究",
        "data": ["close", "industry_map"],
    },
    "price_vol_divergence": {
        "func": price_volume_divergence,
        "category": "微观结构",
        "source": "价量关系研究 / A股微观结构",
        "data": ["close", "volume"],
    },
    "relative_turnover": {
        "func": relative_turnover,
        "category": "行为金融",
        "source": "Barber & Odean 2008 / A股散户注意力效应",
        "data": ["turnover"],
    },
    "cfo_accrual_quality": {
        "category": "基本面",
        "source": "Dechow&Dichev2002-应计利润质量",
        "data": ["net_income_q", "ocf_q", "total_assets_q"],
    },
    "insider_buying_proxy": {
        "category": "微观结构",
        "source": "国泰君安2020-增持预测因子",
        "data": ["close", "high", "low", "volume"],
    },
    # ── Round 2 新因子 ──────────────────────────────────────────
    "high_52w_ratio": {
        "category": "动量",
        "source": "George & Hwang 2004 / 52周高点锚定效应",
        "data": ["close"],
    },
    "return_skewness_20d": {
        "category": "行为金融",
        "source": "Bali et al. 2011 / 彩票效应-偏度",
        "data": ["close"],
    },
    "beta_factor": {
        "category": "风险",
        "source": "Frazzini & Pedersen 2014 / 低beta异象",
        "data": ["close"],
    },
    "max_ret_1m": {
        "category": "行为金融",
        "source": "Bali et al. 2011 / MAX effect-彩票效应",
        "data": ["close"],
    },
    "turnover_acceleration": {
        "category": "流动性",
        "source": "换手率加速度-资金入场信号",
        "data": ["turnover"],
    },
    "bollinger_pct": {
        "category": "技术",
        "source": "Bollinger 1992 / 技术分析-均值回归",
        "data": ["close"],
    },
    "volume_surge": {
        "category": "微观结构",
        "source": "量价突增-smart money代理",
        "data": ["close", "volume"],
    },
    "bid_ask_spread_proxy": {
        "category": "流动性",
        "source": "Corwin & Schultz 2012 / high-low spread估计",
        "data": ["high", "low"],
    },
}


if __name__ == "__main__":
    print(f"因子库共 {len(FACTOR_CATALOG)} 个快速因子")
    for name, info in FACTOR_CATALOG.items():
        print(f"  {name:<20} [{info['category']}] {info['source']}")
    print("\n慢因子（需要逐行循环，单独调用）:")
    print("  amplitude_hidden   [微观结构] 开源证券-振幅隐藏结构")
    print("  w_reversal         [微观结构] 开源证券-W因子")
    print("  network_scc        [网络] QuantsPlaybook-网络中心度")
    print("  chip_arc/vrc       [筹码] QuantsPlaybook-筹码因子")
    print("  cgo (full)         [行为金融] 国信证券-完整CGO")

    # ── 验证 earnings_momentum ──────────────────────────────────
    print("\n[验证] earnings_momentum")
    np.random.seed(42)
    idx = pd.date_range("2022-01-01", periods=20, freq="QS")
    stocks = ["000001.SZ", "000002.SZ", "600000.SH"]
    # 净利润同比增速：随机，含正负，模拟真实季报
    npg = pd.DataFrame(
        np.random.uniform(-0.5, 1.5, size=(20, 3)),
        index=idx, columns=stocks
    )
    em = earnings_momentum(npg, window=4)
    assert em.shape == npg.shape, "shape 不匹配"
    assert em.iloc[:4].isna().all().all(), "前 window 行应为 NaN"
    assert (em.dropna() >= -2).all().all(), "下限截断失败"
    assert (em.dropna() <= 2).all().all(), "上限截断失败"
    # 手动验证第5行第0列
    expected_val = npg.iloc[4, 0] - npg.iloc[0, 0]
    expected_clip = float(np.clip(expected_val, -2, 2))
    assert abs(em.iloc[4, 0] - expected_clip) < 1e-10, "diff(4) 计算错误"
    print("  shape OK, NaN前缀 OK, clip[-2,2] OK, 数值验证 OK")

    # ── 验证 dividend_yield ─────────────────────────────────────
    print("[验证] dividend_yield")
    idx_d = pd.date_range("2023-01-01", periods=50, freq="B")
    close = pd.DataFrame(
        np.random.uniform(5, 50, size=(50, 3)),
        index=idx_d, columns=stocks
    )
    # 每股股息：年频，少量 NaN
    dps_data = pd.DataFrame(
        np.random.uniform(0, 2, size=(50, 3)),
        index=idx_d, columns=stocks
    )
    # 注入一个极端值（应被 clip 截断）
    dps_data.iloc[10, 0] = 1000.0
    dy = dividend_yield(close, dps_data)
    assert dy.shape == close.shape, "shape 不匹配"
    assert (dy.dropna() >= 0).all().all(), "股息率不应为负"
    assert (dy.dropna() <= 0.2).all().all(), "上限 0.2 截断失败"
    # close=0 时应为 NaN（replace(0, nan) 保证）
    close_with_zero = close.copy()
    close_with_zero.iloc[5, 1] = 0
    dy_z = dividend_yield(close_with_zero, dps_data)
    assert pd.isna(dy_z.iloc[5, 1]), "close=0 时应为 NaN"
    print("  shape OK, clip[0,0.2] OK, close=0->NaN OK")

    print("\nalpha_factors import ok")
