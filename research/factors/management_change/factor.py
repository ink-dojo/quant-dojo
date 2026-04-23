"""
MCHG — Management Change 因子

核心假设:
    A 股关键职位 (董事长 / 总经理 / 首席财务官 / 财务总监) 变动往往伴随:
      - 战略调整 (业绩压力)
      - 业绩披露问题 (监管关注)
      - 股权争夺 / 并购重组
    对未来 20 日股价有 cross-section 预测力. 方向先不设, 让 IC 判断.

数据依赖:
    data/raw/tushare/stk_managers/stk_managers_<symbol6>.parquet
    cols: ts_code, ann_date, name, title, begin_date, end_date, ...

因子构造:
    1. 加载每只股票的 stk_managers 记录
    2. 过滤 title 包含关键词: 董事长 / 总经理 / 首席执行官 / 首席财务官 / 财务总监
    3. 事件 = ann_date (公告日) 出现的 key-title 变动记录
       事件"强度" = 该 ann_date 同股出现的 key-title 独立 name 数 (越多 = 越集中变动)
    4. factor[D] = 过去 window=60 日该股累计事件强度 (log1p)
    5. Hold: 从第一个事件日起 60 日内 factor 值保持

因子方向: auto
样本期: 2018-01+ (stk_managers 数据从 ~2018 开始有意义)
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[3]
MGR_DIR = ROOT / "data" / "raw" / "tushare" / "stk_managers"
PRICE_PATH = ROOT / "data" / "processed" / "price_wide_close_2014-01-01_2025-12-31_qfq_5477stocks.parquet"

KEY_TITLES = ["董事长", "总经理", "首席执行官", "首席财务官", "财务总监"]


def _is_key_title(t) -> bool:
    s = str(t) if t is not None else ""
    return any(k in s for k in KEY_TITLES)


def _to_ts(sym: str) -> str:
    if sym.startswith(("60", "68")):
        return f"{sym}.SH"
    if sym.startswith(("00", "30")):
        return f"{sym}.SZ"
    return f"{sym}.SZ"


def load_key_events(start: str, end: str) -> pd.DataFrame:
    """
    扫描所有 stk_managers_*.parquet, 过滤 key titles, 按 (ts_code, ann_date) 聚合事件强度.

    Returns:
        DataFrame [ts_code, ann_date, event_strength] (long)
    """
    start_i = int(start.replace("-", ""))
    end_i = int(end.replace("-", ""))
    frames = []
    for f in sorted(MGR_DIR.glob("stk_managers_*.parquet")):
        try:
            df = pd.read_parquet(
                f, columns=["ts_code", "ann_date", "name", "title", "begin_date", "end_date"]
            )
        except Exception:
            continue
        if df.empty:
            continue
        df = df[df["title"].apply(_is_key_title)]
        if df.empty:
            continue
        df["ann_date_i"] = pd.to_numeric(df["ann_date"], errors="coerce").astype("Int64")
        df = df[df["ann_date_i"].between(start_i, end_i)]
        if df.empty:
            continue
        frames.append(df)
    if not frames:
        return pd.DataFrame(columns=["ts_code", "ann_date", "event_strength"])

    raw = pd.concat(frames, ignore_index=True)
    # 事件强度: 每个 (ts_code, ann_date) 独立 name×title 组合数
    raw["name_title"] = raw["name"].astype(str) + "@" + raw["title"].astype(str)
    raw = raw.drop_duplicates(subset=["ts_code", "ann_date", "name_title"])
    agg = (
        raw.groupby(["ts_code", "ann_date"])
        .agg(event_strength=("name_title", "count"))
        .reset_index()
    )
    agg["ann_date"] = pd.to_datetime(
        agg["ann_date"].astype(str).str.strip(), format="%Y%m%d", errors="coerce"
    )
    agg = agg.dropna(subset=["ann_date"])
    return agg[["ts_code", "ann_date", "event_strength"]]


def compute_factor(
    start: str,
    end: str,
    lookback_days: int = 60,
    hold_days: int = 60,
) -> pd.DataFrame:
    """
    MCHG 因子宽表.

    Args:
        start, end: YYYY-MM-DD
        lookback_days: 每日 factor 值 = 过去 N 日累计事件强度 (默认 60)
        hold_days: 首次 event 后 factor 保持 N 日 (默认 60, 与 lookback 一致)

    Returns:
        wide DataFrame (index=trade_date, cols=ts_code, values=log1p(rolling_sum_events))
        只有有事件的股票在事件窗口内非 NaN, 其他 NaN.
    """
    # 往前扩 lookback_days + buffer
    start_ext = (pd.Timestamp(start) - pd.Timedelta(days=lookback_days + 30)).strftime("%Y-%m-%d")
    events = load_key_events(start_ext, end)
    if events.empty:
        return pd.DataFrame()

    price = pd.read_parquet(PRICE_PATH)
    cal = price.index
    cal_sub = cal[(cal >= start) & (cal <= end)]
    if len(cal_sub) == 0:
        return pd.DataFrame()

    # 将事件日对齐到最近一个 >= ann_date 的交易日 (公告当日若非交易日往后对齐)
    def _align_to_cal(d: pd.Timestamp) -> pd.Timestamp | None:
        pos = cal.searchsorted(d, side="left")
        return cal[pos] if pos < len(cal) else None

    events["event_trade_date"] = events["ann_date"].apply(_align_to_cal)
    events = events.dropna(subset=["event_trade_date"])

    # 对每只股票, 在 cal_sub 上计算 rolling_sum_events_past_lookback
    # 简化: 构造 per-stock wide daily event strength, rolling sum.
    full_cal = cal[(cal >= pd.Timestamp(start_ext)) & (cal <= end)]

    event_wide = events.pivot_table(
        index="event_trade_date", columns="ts_code",
        values="event_strength", aggfunc="sum", fill_value=0,
    ).reindex(full_cal, fill_value=0.0)

    rolling_sum = event_wide.rolling(lookback_days, min_periods=1).sum()

    # 只在"过去 hold_days 有事件" 的位置保留 value, 其他 NaN
    has_recent_event = event_wide.rolling(hold_days, min_periods=1).sum() > 0
    factor = rolling_sum.where(has_recent_event, np.nan)
    factor = np.log1p(factor)

    factor = factor.loc[cal_sub]
    return factor


if __name__ == "__main__":
    print("=== MCHG 最小验证 (2024-2025) ===")
    df = compute_factor("2024-01-01", "2025-12-31")
    print(f"shape: {df.shape}")
    if not df.empty:
        daily_n = df.notna().sum(axis=1)
        print(f"日均有效股: {daily_n.mean():.0f}")
        print(f"最多一日有效股: {daily_n.max()} (date {daily_n.idxmax().date() if daily_n.max() else 'n/a'})")
        latest = df.iloc[-1].dropna()
        print(f"最新一日 {df.index[-1].date()}, 有效 {len(latest)}")
        if len(latest):
            all_vals = df.stack()
            print(f"因子分位 (非 NaN): p10={all_vals.quantile(0.1):.2f} p50={all_vals.quantile(0.5):.2f} p90={all_vals.quantile(0.9):.2f}")
            print("最强事件股 Top 5 (最新日):")
            print(latest.nlargest(5).to_string())
    print("✅ 最小验证通过")
