"""
事件驱动数据加载模块
提供 A 股公司财报披露日 + 业绩 surprise 代理变量.

数据源 (Phase 1 实装):
  - akshare `stock_report_disclosure`: 实际披露日 (首次正式公告, PEAD 事件锚点)
  - akshare `stock_yjbb_em`: 业绩快报 (EPS, 营收同比, 净利润同比 — 直接给)

设计约束 (来自 research/event_driven/README.md 预注册):
  - 零未来函数: announce_date 用"实际披露"字段, 严格晚于 report_period_end_date
  - 零 look-ahead: 不用任何"最新修订"日期, 只用首次公告
  - 缓存: data/raw/events/{disclosure,financials}_{period}.parquet 分文件

调用节奏:
  - stock_yjbb_em 每次约 30s (12-13 次分页), stock_report_disclosure 约 5s
  - 一个季度 ~35s. 2017Q1 ~ 2025Q4 共 36 个季度 → 首次全量 ~20 分钟
  - 有 parquet 缓存, 次次增量只拉最新季度
"""
from __future__ import annotations

import logging
import time
from pathlib import Path
from typing import Optional

import pandas as pd

logger = logging.getLogger(__name__)

RAW_DIR = Path(__file__).parent.parent / "data" / "raw" / "events"

# 报告期 → akshare period 字符串映射
_PERIOD_MAP = {
    "0331": "一季报",
    "0630": "半年报",
    "0930": "三季报",
    "1231": "年报",
}


def _ymd_to_period_str(yyyymmdd: str) -> str:
    """20240930 → '2024三季报'"""
    year = yyyymmdd[:4]
    mmdd = yyyymmdd[4:]
    if mmdd not in _PERIOD_MAP:
        raise ValueError(f"yyyymmdd={yyyymmdd}: 仅支持 0331/0630/0930/1231")
    return f"{year}{_PERIOD_MAP[mmdd]}"


def _enumerate_quarters(start: str, end: str) -> list[str]:
    """列出 [start, end] 覆盖的所有报告期 yyyymmdd (仅 0331/0630/0930/1231)."""
    s = pd.Timestamp(start)
    e = pd.Timestamp(end)
    periods = []
    for year in range(s.year, e.year + 1):
        for mmdd in ["0331", "0630", "0930", "1231"]:
            d = pd.Timestamp(f"{year}-{mmdd[:2]}-{mmdd[2:]}")
            if s <= d <= e:
                periods.append(f"{year}{mmdd}")
    return periods


# ─────────────────────────────────────────────
# 披露日历 (实际披露日 = PEAD 事件锚点)
# ─────────────────────────────────────────────

def _fetch_disclosure_single(period_yyyymmdd: str, use_cache: bool = True) -> pd.DataFrame:
    """拉一个季度的披露日历 (带 parquet 缓存)."""
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    cache_path = RAW_DIR / f"disclosure_{period_yyyymmdd}.parquet"

    if use_cache and cache_path.exists():
        return pd.read_parquet(cache_path)

    import akshare as ak
    period_str = _ymd_to_period_str(period_yyyymmdd)
    logger.info(f"拉披露日历 {period_str}...")
    df = ak.stock_report_disclosure(market="沪深京", period=period_str)

    keep = df[["股票代码", "股票简称", "首次预约", "实际披露"]].copy()
    keep.columns = ["symbol", "name", "scheduled_date", "announce_date"]
    keep["report_period"] = pd.Timestamp(
        f"{period_yyyymmdd[:4]}-{period_yyyymmdd[4:6]}-{period_yyyymmdd[6:]}"
    )
    keep["scheduled_date"] = pd.to_datetime(keep["scheduled_date"], errors="coerce")
    keep["announce_date"] = pd.to_datetime(keep["announce_date"], errors="coerce")
    # 未披露的行 announce_date = NaT, 这些事件尚未发生, PEAD 用不到

    keep.to_parquet(cache_path, index=False)
    logger.info(f"  {period_str}: {len(keep)} 行 → {cache_path.name}")
    return keep


# ─────────────────────────────────────────────
# 业绩快报 (EPS + 同比)
# ─────────────────────────────────────────────

def _fetch_financials_single(period_yyyymmdd: str, use_cache: bool = True) -> pd.DataFrame:
    """拉一个季度的业绩快报 (带 parquet 缓存). ~30s 首次."""
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    cache_path = RAW_DIR / f"financials_{period_yyyymmdd}.parquet"

    if use_cache and cache_path.exists():
        return pd.read_parquet(cache_path)

    import akshare as ak
    logger.info(f"拉业绩快报 {period_yyyymmdd}... (约 30s)")
    t0 = time.time()
    df = ak.stock_yjbb_em(date=period_yyyymmdd)

    keep = df[[
        "股票代码", "股票简称", "每股收益",
        "营业总收入-营业总收入", "营业总收入-同比增长",
        "净利润-净利润", "净利润-同比增长",
        "每股净资产", "净资产收益率",
    ]].copy()
    keep.columns = [
        "symbol", "name", "eps_basic",
        "revenue", "revenue_yoy",
        "net_profit", "net_profit_yoy",
        "bps", "roe",
    ]
    keep["report_period"] = pd.Timestamp(
        f"{period_yyyymmdd[:4]}-{period_yyyymmdd[4:6]}-{period_yyyymmdd[6:]}"
    )
    # 注: 忽略 akshare "最新公告日期" 字段 — 它是该公司最新任一公告, 非本期公告, 噪声.

    keep.to_parquet(cache_path, index=False)
    logger.info(f"  {period_yyyymmdd}: {len(keep)} 行, 耗时 {time.time()-t0:.1f}s")
    return keep


# ─────────────────────────────────────────────
# 公开 API
# ─────────────────────────────────────────────

def get_disclosure_calendar(
    start: str,
    end: str,
    quarter: Optional[str] = None,
    use_cache: bool = True,
) -> pd.DataFrame:
    """
    获取区间内的 A 股财报披露日历.

    参数:
        start    : 报告期范围开始, 如 '2022-01-01'
        end      : 报告期范围结束, 如 '2025-12-31'
        quarter  : 可选过滤 {'annual', 'Q1', 'Q2', 'Q3'}; None = 全部
        use_cache: parquet 缓存

    返回:
        DataFrame, columns: [symbol, name, scheduled_date, announce_date, report_period]
    """
    periods = _enumerate_quarters(start, end)
    if quarter == "annual":
        periods = [p for p in periods if p.endswith("1231")]
    elif quarter == "Q3":
        periods = [p for p in periods if p.endswith("0930")]
    elif quarter == "Q2":
        periods = [p for p in periods if p.endswith("0630")]
    elif quarter == "Q1":
        periods = [p for p in periods if p.endswith("0331")]

    frames = [_fetch_disclosure_single(p, use_cache=use_cache) for p in periods]
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()


def get_earning_announcements(
    symbols: Optional[list[str]] = None,
    start: str = "2018-01-01",
    end: str = "2025-12-31",
    use_cache: bool = True,
) -> pd.DataFrame:
    """
    获取多只股票的财报披露日 + 业绩 surprise 代理.

    参数:
        symbols  : 股票代码列表; None = 全 A 股
        start    : 区间开始 (按 announce_date 过滤)
        end      : 区间结束 (按 announce_date 过滤)
        use_cache: parquet 缓存

    返回:
        DataFrame, columns:
          - symbol          : str, 6 位代码
          - name            : str, 股票简称
          - report_period   : Timestamp, 报告期末 (2024-09-30 等)
          - announce_date   : Timestamp, 实际披露日 (PEAD 事件锚点)
          - eps_basic       : float, 基本每股收益 (本期)
          - revenue_yoy     : float %, 营收同比 (akshare 直接给, 不手算)
          - net_profit_yoy  : float %, 净利润同比 — **PEAD primary surprise 代理**
          - roe             : float %, 净资产收益率

    验收契约:
        - announce_date > report_period (未来函数红线, 100% 行成立)
        - announce_date ∈ [start, end] (过滤后)
    """
    periods = _enumerate_quarters(start, end)

    # 跨年事件: announce_date 可能落在 report_period 的下一季, 所以 report_period
    # 往后延一年作为 buffer (例: 2025 年报可能 2026-04 公告, 若 end=2025-12-31,
    # 相关报告期只到 2025-09-30 = Q3 2025, 避免漏 Q3)
    # 此处从简: 只拉 [start, end] 的报告期, announce_date 过滤在下方做.
    disc = get_disclosure_calendar(
        start=(pd.Timestamp(start) - pd.DateOffset(months=6)).strftime("%Y-%m-%d"),
        end=end, use_cache=use_cache,
    )
    fin_frames = [_fetch_financials_single(p, use_cache=use_cache) for p in periods]
    fin = pd.concat(fin_frames, ignore_index=True) if fin_frames else pd.DataFrame()

    if disc.empty or fin.empty:
        return pd.DataFrame()

    merged = disc.merge(
        fin[["symbol", "report_period", "eps_basic", "revenue_yoy", "net_profit_yoy", "roe"]],
        on=["symbol", "report_period"], how="left",
    )

    # 过滤: 已实际披露 + 落在 [start, end]
    merged = merged[merged["announce_date"].notna()]
    merged = merged[
        (merged["announce_date"] >= pd.Timestamp(start))
        & (merged["announce_date"] <= pd.Timestamp(end))
    ]

    if symbols is not None:
        merged = merged[merged["symbol"].isin(set(symbols))]

    _quality_gate(merged)
    return merged.sort_values(["symbol", "announce_date"]).reset_index(drop=True)


def build_eps_surprise_signal(
    anns: pd.DataFrame,
    holding_window: int = 20,
    surprise_col: str = "net_profit_yoy",
) -> pd.DataFrame:
    """
    从披露数据构造日频 surprise 信号矩阵 (T+1 ~ T+window 持仓).

    参数:
        anns            : get_earning_announcements() 输出
        holding_window  : 公告后持仓天数 (默认 20, 即 T+1 ~ T+20)
        surprise_col    : 用哪列做 surprise; 默认 net_profit_yoy (预注册 primary)

    返回:
        DataFrame, index=日历日 (date, DatetimeIndex), columns=symbol
        value: 若该日处于 (announce_date+1) ~ (announce_date+holding_window) 区间,
               value = surprise; 否则 NaN.
        同一 symbol 持仓窗口内若发生新公告, 取最晚 (更新信号).

    上层使用: backtest engine 做 cross-section top/bottom 30% 选股时, 读此矩阵.
    """
    if anns.empty:
        return pd.DataFrame()

    df = anns.dropna(subset=["announce_date", surprise_col]).copy()
    df["announce_date"] = pd.to_datetime(df["announce_date"])

    start = df["announce_date"].min()
    end = df["announce_date"].max() + pd.Timedelta(days=holding_window + 10)
    cal = pd.bdate_range(start, end)

    signal = pd.DataFrame(index=cal, columns=sorted(df["symbol"].unique()), dtype=float)

    for _, row in df.iterrows():
        ad = row["announce_date"]
        entry = ad + pd.Timedelta(days=1)
        exit_ = ad + pd.Timedelta(days=holding_window * 2)  # 历日 buffer 覆盖交易日
        window = cal[(cal >= entry) & (cal <= exit_)][:holding_window]
        # 取最晚公告: 若已有 non-NaN 且公告日更早, 新值覆盖
        signal.loc[window, row["symbol"]] = row[surprise_col]

    return signal.dropna(axis=0, how="all")


# ─────────────────────────────────────────────
# 数据质量门
# ─────────────────────────────────────────────

def _quality_gate(anns: pd.DataFrame) -> None:
    """
    质量检查, 每次 load 末尾调用.
    发现问题时 logger.warning, 但不 raise (让上层决定如何处理).
    """
    if anns.empty:
        logger.warning("quality_gate: 空 DataFrame")
        return

    # 1. 未来函数红线
    future_leak = anns["announce_date"] <= anns["report_period"]
    if future_leak.any():
        n = int(future_leak.sum())
        raise ValueError(
            f"质量门 FAIL: {n} 行的 announce_date ≤ report_period (未来函数). "
            f"样本: {anns[future_leak].head(3).to_dict('records')}"
        )

    # 2. 覆盖率
    pct_na_surprise = anns["net_profit_yoy"].isna().mean()
    if pct_na_surprise > 0.30:
        logger.warning(f"quality_gate: net_profit_yoy 缺失率 {pct_na_surprise:.1%} > 30%")

    # 3. 极值 (> 500% 或 < -500% 同比, 可能是数据异常)
    extreme = (anns["net_profit_yoy"].abs() > 500).sum()
    if extreme > 0:
        logger.info(f"quality_gate: net_profit_yoy |value|>500% 共 {extreme} 行 (可能 IPO 次年/扭亏)")

    logger.info(
        f"quality_gate OK: {len(anns)} 事件, "
        f"cov(net_profit_yoy)={1-pct_na_surprise:.1%}, "
        f"unique_symbols={anns['symbol'].nunique()}"
    )


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    # 最小验证: 拉 2024 年报 披露日历 (应该 ~5000 行)
    print("=== 验证: 2024 年年报披露日历 ===")
    disc = _fetch_disclosure_single("20241231", use_cache=True)
    print(f"行数: {len(disc)}")
    print(f"列: {disc.columns.tolist()}")
    print(f"announce_date 范围: {disc['announce_date'].min()} ~ {disc['announce_date'].max()}")
    print(disc.head(3))
