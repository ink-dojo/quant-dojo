"""
Alpha 因子库 — quant-dojo 完整因子集

所有因子接受宽表输入（日期 × 股票），返回同形状 DataFrame。
正值 = 预期未来收益高的方向。

=== 因子分类 ===

技术/统计（6）：
  reversal_1m, low_vol_20d, turnover_rev,
  enhanced_momentum, quality_momentum, ma_ratio_momentum

基本面（2 + 1）：
  ep, bp
  accruals_quality（应计异象，需财务宽表）

流动性（1）：
  amihud_illiquidity（Amihud 非流动性，需 volume）

微观结构（4）：
  shadow_upper, shadow_lower, amplitude_hidden, w_reversal

行为金融（3）：
  cgo, str_salience, team_coin

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
"""
import numpy as np
import pandas as pd


# ══════════════════════════════════════════════════════════════
# 技术/统计因子
# ══════════════════════════════════════════════════════════════

def reversal_1m(price: pd.DataFrame) -> pd.DataFrame:
    """1 月反转：-pct_change(21)"""
    return -price.pct_change(21)


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
    return ret_n - 3000 * sigma ** 2


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
    return cum_ret - 3000 * sigma ** 2


def ma_ratio_momentum(price: pd.DataFrame, window: int = 120) -> pd.DataFrame:
    """
    MA 比率动量：MA(N) / Price，单调性更强。

    来源：QuantsPlaybook/B-因子构建类/再论动量因子
    取负：MA/Price > 1 说明价格在 MA 下方（看空）
    """
    return -(price.rolling(window).mean() / price)


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
    """盈利收益率：1/PE（PE<=0 设 NaN）"""
    return 1.0 / pe_wide.where(pe_wide > 0)


def bp_factor(pb_wide: pd.DataFrame) -> pd.DataFrame:
    """账面市值比：1/PB（PB<=0 设 NaN）"""
    return 1.0 / pb_wide.where(pb_wide > 0)


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
# 批量构建
# ══════════════════════════════════════════════════════════════

def build_fast_factors(price: pd.DataFrame, high: pd.DataFrame = None,
                       low: pd.DataFrame = None, open_price: pd.DataFrame = None,
                       pe: pd.DataFrame = None, pb: pd.DataFrame = None,
                       market_ret: pd.Series = None,
                       volume: pd.DataFrame = None) -> dict:
    """
    构建所有快速因子（不含需要逐行循环的慢因子）。

    快速因子用 rolling/向量化计算，适合全量回测。

    参数:
        price      : 收盘价宽表（日期 × 股票），必填
        high       : 最高价宽表，用于微观结构因子
        low        : 最低价宽表，用于微观结构因子
        open_price : 开盘价宽表，用于 APM 因子
        pe         : 市盈率宽表，用于 EP 因子
        pb         : 市净率宽表，用于 BP 因子
        market_ret : 市场日收益率序列，用于 STR/凸显理论因子
        volume     : 成交量宽表，用于 Amihud 非流动性因子

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
    "amihud_illiq": {"category": "流动性", "source": "Amihud2002", "data": "close,volume"},
    "shadow_upper": {"category": "微观结构", "source": "东吴证券", "data": "high,close"},
    "shadow_lower": {"category": "微观结构", "source": "东吴证券", "data": "close,low"},
    "cgo_simple": {"category": "行为金融", "source": "国信证券-处置效应", "data": "close"},
    "str_salience": {"category": "行为金融", "source": "Cosemans2021+方正证券", "data": "close,market"},
    "team_coin": {"category": "行为金融", "source": "Moskowitz2021JF", "data": "close"},
    "apm_overnight": {"category": "网络/关系", "source": "QuantsPlaybook-APM", "data": "open,close"},
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
    print("✅ alpha_factors import ok")
