"""
北向资金因子模块

核心假设
--------
陆股通北向资金（沪股通 + 深股通）以外资机构为主，相对 A 股散户属于
"聪明钱"——持仓周期长、基本面驱动、跨市场定价能力强。

当外资持续净增持某只股票时：
  1. 信息优势：外资基本面研究更早发现低估
  2. 增量资金：持续买入形成价格支撑
  3. 信号传导：北向数据公开后本土机构跟进

因子定义
--------
Δholding_pct_N = (持股比例_t - 持股比例_{t-N}) / N

即：过去 N 个交易日的北向持股占比日均变化量。
正值 = 北向在净增持，负值 = 净减持。

数据来源
--------
akshare: stock_hsgt_hold_stock_em（沪/深股通逐日持股快照）

⚠️  重要：历史数据构建方式
----------------------------------------
akshare 的北向持股接口返回的是**当天快照**，没有完整历史。
本模块提供两套机制：
  1. `snapshot_today()` — 获取今日快照并追加到本地 parquet
  2. `load_historical_wide()` — 读取已积累的历史数据，构建因子宽表

建议从 daily_signal.py 的 post-run hook 中每日调用 snapshot_today()，
积累约 60 个交易日后，本因子的 N=20/N=60 版本开始有效。

初始回测替代方案
--------------
如需立即回测（无积累历史），可用以下两个代理：
  - 大单净流入比例（主力资金，来自 alpha_factors 的 apm_overnight 近似）
  - 北向每日净买卖额（指数级别，来自 akshare stock_hsgt_north_net_flow_in_em）
  这两个都是横截面代理，精度低于真实持股比例变化。
"""

import warnings
from pathlib import Path

import numpy as np
import pandas as pd

_SNAPSHOT_PATH = Path(__file__).parent.parent.parent.parent / "data" / "raw" / "northbound_holdings.parquet"
_SNAPSHOT_PATH.parent.mkdir(parents=True, exist_ok=True)


# ─────────────────────────────────────────────
# 数据采集（每日快照）
# ─────────────────────────────────────────────

def snapshot_today(save: bool = True) -> pd.DataFrame:
    """
    获取今日北向持股快照（沪股通 + 深股通合并）

    参数
    ----
    save : True 则追加写入本地 parquet（用于历史积累）

    返回
    ----
    DataFrame，列：date, symbol, holding_pct（持股占 A 股比例，%）
    """
    import time
    try:
        import akshare as ak
    except ImportError:
        raise ImportError("请先安装 akshare: pip install akshare")

    today = pd.Timestamp.today().normalize()
    frames = []

    for board in ["沪股通", "深股通"]:
        try:
            raw = ak.stock_hsgt_hold_stock_em(symbol=board)
            time.sleep(0.5)
        except Exception as e:
            warnings.warn(f"[northbound] {board} 持股快照拉取失败: {e}")
            continue

        # 列名映射（东方财富接口）
        col_map = {
            "股票代码": "symbol",
            "持股占A股百分比": "holding_pct",   # 占该股 A 股总股本的比例（%）
        }
        available = {k: v for k, v in col_map.items() if k in raw.columns}
        if "股票代码" not in available:
            warnings.warn(f"[northbound] {board} 列名不匹配，跳过")
            continue

        df = raw[list(available.keys())].rename(columns=available).copy()
        df["symbol"] = df["symbol"].astype(str).str.zfill(6)
        df["holding_pct"] = pd.to_numeric(df["holding_pct"], errors="coerce")
        df["date"] = today
        frames.append(df[["date", "symbol", "holding_pct"]])

    if not frames:
        return pd.DataFrame(columns=["date", "symbol", "holding_pct"])

    today_df = pd.concat(frames, ignore_index=True)
    # 同一股票在沪/深股通都有时，持股比例合并（理论上不重叠，但 SUM 保险）
    today_df = (
        today_df.groupby(["date", "symbol"], as_index=False)["holding_pct"].sum()
    )

    if save:
        _append_snapshot(today_df)

    return today_df


def _append_snapshot(today_df: pd.DataFrame) -> None:
    """将今日快照追加到本地 parquet（幂等：同一日期重复写入会覆盖）"""
    if _SNAPSHOT_PATH.exists():
        existing = pd.read_parquet(_SNAPSHOT_PATH)
        today = today_df["date"].iloc[0]
        existing = existing[existing["date"] != today]
        combined = pd.concat([existing, today_df], ignore_index=True)
    else:
        combined = today_df

    combined = combined.sort_values(["date", "symbol"]).reset_index(drop=True)
    combined.to_parquet(_SNAPSHOT_PATH, index=False)


# ─────────────────────────────────────────────
# 因子计算（从积累的历史数据）
# ─────────────────────────────────────────────

def load_holding_history() -> pd.DataFrame:
    """
    读取本地积累的北向持股历史快照

    返回
    ----
    DataFrame，列：date, symbol, holding_pct
    """
    if not _SNAPSHOT_PATH.exists():
        raise FileNotFoundError(
            f"北向持股历史文件不存在: {_SNAPSHOT_PATH}\n"
            "请先运行 snapshot_today() 积累至少 30 个交易日数据。"
        )
    return pd.read_parquet(_SNAPSHOT_PATH)


def build_holding_wide(
    symbols: list = None,
    start: str = None,
    end: str = None,
) -> pd.DataFrame:
    """
    构建北向持股比例宽表（date × symbol）

    参数
    ----
    symbols : 股票代码列表（None = 全部）
    start   : 开始日期（None = 全部）
    end     : 结束日期（None = 全部）

    返回
    ----
    DataFrame，index=date，columns=symbol，值=持股比例（%）
    """
    hist = load_holding_history()
    if symbols is not None:
        hist = hist[hist["symbol"].isin(symbols)]
    if start is not None:
        hist = hist[hist["date"] >= pd.Timestamp(start)]
    if end is not None:
        hist = hist[hist["date"] <= pd.Timestamp(end)]

    wide = hist.pivot(index="date", columns="symbol", values="holding_pct")
    wide = wide.sort_index()
    return wide


def compute_northbound_flow(
    holding_wide: pd.DataFrame,
    lookback: int = 20,
) -> pd.DataFrame:
    """
    计算北向持股变化因子（日均持股比例变化量）

    因子 = (持股比例_t - 持股比例_{t-lookback}) / lookback

    参数
    ----
    holding_wide : 北向持股比例宽表 (date × symbol)，来自 build_holding_wide()
    lookback     : 回看窗口（交易日），建议 5 / 20 / 60

    返回
    ----
    宽表 (date × symbol)，值为日均持股比例变化（单位：%/日）
    正值 = 北向净增持，负值 = 净减持
    """
    delta = holding_wide - holding_wide.shift(lookback)
    flow = delta / lookback
    return flow


def compute_northbound_zscore(
    holding_wide: pd.DataFrame,
    window: int = 60,
) -> pd.DataFrame:
    """
    计算北向持股比例的滚动 Z-score（相对历史水平的偏离程度）

    因子 = (持股比例_t - 滚动均值) / 滚动标准差

    适合捕捉"相对历史异常高/低的北向仓位"，而非单纯方向变化。

    参数
    ----
    holding_wide : 北向持股比例宽表 (date × symbol)
    window       : 滚动窗口（交易日）

    返回
    ----
    宽表 (date × symbol)，值为 Z-score
    正值 = 北向仓位处于历史高位（持续买入后），负值 = 历史低位
    """
    roll_mean = holding_wide.rolling(window, min_periods=window // 2).mean()
    roll_std = holding_wide.rolling(window, min_periods=window // 2).std()
    roll_std = roll_std.replace(0, np.nan)
    return (holding_wide - roll_mean) / roll_std


def compute_northbound_composite(
    holding_wide: pd.DataFrame,
    short_window: int = 20,
    long_window: int = 60,
    weights: tuple = (0.5, 0.5),
) -> pd.DataFrame:
    """
    合成北向资金因子（短期流量 + 长期 Z-score）

    short_window 捕捉近期动态变化，long_window 捕捉结构性持仓水平，
    两者截面 z-score 后加权合成。

    参数
    ----
    holding_wide : 北向持股比例宽表 (date × symbol)
    short_window : 短期流量窗口（默认 20 日）
    long_window  : Z-score 窗口（默认 60 日）
    weights      : (w_flow, w_zscore)，合计须为 1

    返回
    ----
    宽表 (date × symbol)，合成因子值
    """
    assert abs(sum(weights) - 1.0) < 1e-9, "权重之和必须为 1"
    w_f, w_z = weights

    flow = compute_northbound_flow(holding_wide, lookback=short_window)
    zscore = compute_northbound_zscore(holding_wide, window=long_window)

    def _cross_zscore(df: pd.DataFrame) -> pd.DataFrame:
        mean = df.mean(axis=1)
        std = df.std(axis=1).replace(0, np.nan)
        return df.sub(mean, axis=0).div(std, axis=0)

    flow_z = _cross_zscore(flow)
    zscore_z = _cross_zscore(zscore)

    common_idx = flow_z.index.intersection(zscore_z.index)
    common_col = flow_z.columns.intersection(zscore_z.columns)

    composite = (
        w_f * flow_z.loc[common_idx, common_col]
        + w_z * zscore_z.loc[common_idx, common_col]
    )
    return _cross_zscore(composite)


# ─────────────────────────────────────────────
# 最小验证（mock 数据）
# ─────────────────────────────────────────────

if __name__ == "__main__":
    np.random.seed(42)

    print("验证 northbound_flow_factor 模块（mock 数据）...")

    # 构造模拟持股宽表（100 个交易日 × 20 只股票）
    dates = pd.bdate_range("2024-01-01", periods=100)
    symbols = [f"{i:06d}" for i in range(1, 21)]

    # 模拟：持股比例在 0%~5% 之间随机游走
    np.random.seed(42)
    noise = np.random.randn(100, 20) * 0.05
    level = np.abs(np.random.randn(20) * 2 + 1)  # 初始持股比例
    holding_raw = level + noise.cumsum(axis=0)
    holding_raw = np.clip(holding_raw, 0, 10)  # 持股比例不超过 10%

    holding_wide = pd.DataFrame(holding_raw, index=dates, columns=symbols)

    # 测试流量因子
    flow_20 = compute_northbound_flow(holding_wide, lookback=20)
    assert flow_20.shape == holding_wide.shape
    assert flow_20.iloc[:20].isna().all().all()  # 前 20 行应为 NaN
    print(f"✅ northbound_flow(20日)  形状: {flow_20.shape} | 非空比例: {flow_20.notna().mean().mean():.1%}")

    # 测试 Z-score 因子
    zs = compute_northbound_zscore(holding_wide, window=60)
    assert zs.shape == holding_wide.shape
    print(f"✅ northbound_zscore(60日) 形状: {zs.shape} | 非空比例: {zs.notna().mean().mean():.1%}")

    # 测试合成
    comp = compute_northbound_composite(holding_wide)
    assert comp.shape[1] == len(symbols)
    print(f"✅ northbound_composite  形状: {comp.shape} | 非空比例: {comp.notna().mean().mean():.1%}")

    print("✅ northbound_flow_factor 验证通过")
    print()
    print("⚠️  回测前提：需先通过 snapshot_today() 积累至少 30 个交易日的真实数据")
    print("   建议在 scripts/daily_run.sh 中加入: python -c 'from research.factors.northbound_flow.northbound_flow_factor import snapshot_today; snapshot_today()'")
