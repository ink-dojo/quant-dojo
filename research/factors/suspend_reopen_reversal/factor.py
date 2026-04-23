"""
SRR — Suspend-Reopen Reversal 因子

核心假设:
    A 股停牌原因多元 (资产重组 / 澄清公告 / 监管关注 / ST 检核).
    停牌复牌时有显著的 1-N 日 "信息重新 price-in" 过程:
      - 短停牌 (3~10 日) 常为澄清或小事件, 市场 overreact → 复牌 T+1~T+5 反转
      - 长停牌 (>10 日) 常为资产重组, 跳升 → 不是 clean 反转信号
    本 factor 用停牌 duration 做 cross-section signal, 让 IC 自己判断方向.

数据依赖:
    data/raw/tushare/suspend/suspend_YYYYMMDD.parquet
        cols: [ts_code, trade_date, suspend_timing, suspend_type]
        suspend_type: 'S' = 停牌, 'R' = 复牌

计算逻辑:
    1. 扫描所有 suspend_YYYYMMDD.parquet (按日期 date), 汇总 long 表
    2. 对每只 ts_code, 按 trade_date 排序, 相邻 'S' → 'R' 配对
    3. 每个复牌事件 (R 日): duration = (R_date - S_date).days
    4. Wide panel: index=trade_date, cols=ts_code
        - 在复牌日 D, value = log1p(duration)  (长尾 dampen)
        - 其他日 NaN (稀疏 event factor)

因子方向: auto (runner 用 IC 判断)
样本期: 2019+ (suspend 数据覆盖)
Caveats:
    - 稀疏事件 factor, 每日只有 ~5-20 个股票有值
    - 复牌当日不一定能实际交易 (涨跌停 + 排队), 后续配 tradability filter
    - 假设检验必须用 shift 1 (复牌日尾部 signal 可用, 最早 T+1 开盘交易)
"""
from __future__ import annotations

import logging
from pathlib import Path

import numpy as np
import pandas as pd

log = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parents[3]
SUSPEND_DIR = ROOT / "data" / "raw" / "tushare" / "suspend"


def load_suspend_long(start: str, end: str) -> pd.DataFrame:
    """
    汇总所有 suspend_YYYYMMDD.parquet 为 long 表.

    Returns:
        DataFrame with cols [ts_code, trade_date, suspend_type]
    """
    start_i = int(start.replace("-", ""))
    end_i = int(end.replace("-", ""))
    frames = []
    for f in sorted(SUSPEND_DIR.glob("*.parquet")):
        try:
            date_i = int(f.stem.split("_")[-1])
        except ValueError:
            continue
        if date_i < start_i or date_i > end_i:
            continue
        try:
            df = pd.read_parquet(f, columns=["ts_code", "trade_date", "suspend_type"])
        except Exception:
            continue
        if df.empty:
            continue
        frames.append(df)
    if not frames:
        return pd.DataFrame(columns=["ts_code", "trade_date", "suspend_type"])
    raw = pd.concat(frames, ignore_index=True)
    raw["trade_date"] = pd.to_datetime(
        raw["trade_date"].astype(str).str.strip(), format="%Y%m%d"
    )
    return raw.sort_values(["ts_code", "trade_date"]).reset_index(drop=True)


def pair_suspend_resume(
    long: pd.DataFrame,
    trading_cal: pd.DatetimeIndex | None = None,
) -> pd.DataFrame:
    """
    tushare suspend 数据主要记录 S (停牌) 事件, R (复牌) 稀疏, 所以用
    "连续 S 结束" 推导复牌日:
        一个 ts_code 的 S 事件按日期排序, 若 S_i 和 S_{i+1} 之间 >1 交易日,
        则前一段连续 S 结束; resume_date = 最后一个 S 日的下一交易日.
        最后一段 S (无后续) 也要处理 (若 S_last 之后下一交易日存在则视为复牌).

    Args:
        long: [ts_code, trade_date, suspend_type] 长表
        trading_cal: 交易日历 DatetimeIndex, 不传则用日历日 +1

    Returns:
        DataFrame with [ts_code, resume_date, suspend_first, duration_days]
    """
    records = []
    # 只取 S 记录 (R 稀疏, 不依赖)
    s_only = long[long["suspend_type"] == "S"]
    cal_sorted = trading_cal.sort_values() if trading_cal is not None else None

    def _next_trading_day(d: pd.Timestamp) -> pd.Timestamp | None:
        if cal_sorted is None:
            return d + pd.Timedelta(days=1)
        pos = cal_sorted.searchsorted(d, side="right")
        return cal_sorted[pos] if pos < len(cal_sorted) else None

    for code, grp in s_only.groupby("ts_code"):
        dates = grp["trade_date"].sort_values().tolist()
        if not dates:
            continue
        start = dates[0]
        for i in range(len(dates)):
            # 判断是否为当前连续段的结尾
            is_last_of_group = False
            if i == len(dates) - 1:
                is_last_of_group = True
            else:
                nxt = dates[i + 1]
                if cal_sorted is not None:
                    # 当前 S 日在交易日历的 index
                    cur_pos = cal_sorted.searchsorted(dates[i], side="left")
                    nxt_cal = cal_sorted[cur_pos + 1] if cur_pos + 1 < len(cal_sorted) else None
                    if nxt_cal is None or nxt > nxt_cal:
                        is_last_of_group = True
                else:
                    if (nxt - dates[i]).days > 1:
                        is_last_of_group = True

            if is_last_of_group:
                resume = _next_trading_day(dates[i])
                if resume is not None:
                    duration = (dates[i] - start).days + 1  # S 到 S_end 长度 (含首日)
                    records.append({
                        "ts_code": code,
                        "resume_date": resume,
                        "suspend_first": start,
                        "duration_days": int(duration),
                    })
                # 重置下一段 start
                if i + 1 < len(dates):
                    start = dates[i + 1]

    return pd.DataFrame(records)


PRICE_PATH = ROOT / "data" / "processed" / "price_wide_close_2014-01-01_2025-12-31_qfq_5477stocks.parquet"


def compute_factor(
    start: str,
    end: str,
    min_duration: int = 3,
    hold_days: int = 5,
) -> pd.DataFrame:
    """
    SRR 因子宽表.

    Args:
        start, end: YYYY-MM-DD. 用 [start - 60d, end] 扫 S 事件避免跨文件截断.
        min_duration: 停牌至少多少天才计入事件 (默认 3, 低于视为技术性停牌噪音)
        hold_days: 复牌后 factor 保留天数 (默认 5, 让每日截面有足够样本做 IC)

    Returns:
        wide DataFrame (index=trade_date, cols=ts_code, values=log1p(duration_days))
        复牌日 D 到 D + hold_days - 1 期间, factor 值保持; 其他日 NaN.
        若同一只股在 D+k 有新复牌, 取最新的 (last wins).
    """
    # 往前扩 60 日防止事件跨边界被截断
    start_ext = (pd.Timestamp(start) - pd.Timedelta(days=60)).strftime("%Y-%m-%d")
    long = load_suspend_long(start_ext, end)
    if long.empty:
        return pd.DataFrame()

    price = pd.read_parquet(PRICE_PATH)
    cal = price.index

    events = pair_suspend_resume(long, trading_cal=cal)
    if events.empty:
        return pd.DataFrame()

    events = events[events["duration_days"] >= min_duration]
    if events.empty:
        return pd.DataFrame()

    events["score"] = np.log1p(events["duration_days"].astype(float))
    cal_sub = cal[(cal >= start) & (cal <= end)]
    if len(cal_sub) == 0:
        return pd.DataFrame()

    # 对每个事件, 生成 hold_days 天的 forward fill
    # 先构造 long-format: (date, ts_code, score)
    expanded = []
    cal_pos_map = {d: i for i, d in enumerate(cal)}
    for _, r in events.iterrows():
        rd = r["resume_date"]
        if rd not in cal_pos_map:
            continue
        start_i = cal_pos_map[rd]
        end_i = min(start_i + hold_days, len(cal))
        for i in range(start_i, end_i):
            d = cal[i]
            if d in cal_sub:
                expanded.append({"trade_date": d, "ts_code": r["ts_code"], "score": r["score"]})

    if not expanded:
        return pd.DataFrame()

    exp_df = pd.DataFrame(expanded)
    # 同股同日多事件 → 取最新 (latest resume_date 的 score)
    exp_df = exp_df.sort_values("trade_date").drop_duplicates(
        subset=["trade_date", "ts_code"], keep="last"
    )
    wide = exp_df.pivot_table(
        index="trade_date", columns="ts_code", values="score", aggfunc="last"
    )
    return wide.reindex(cal_sub).sort_index()


if __name__ == "__main__":
    print("=== SRR 最小验证 (2025 H1) ===")
    df = compute_factor("2025-01-01", "2025-06-30")
    print(f"shape: {df.shape}")
    if not df.empty:
        print(f"复牌事件日数: {df.notna().any(axis=1).sum()}")
        print(f"每个复牌日平均股数: {df.notna().sum(axis=1).replace(0, np.nan).mean():.1f}")
        all_vals = df.stack()
        print(f"log1p(duration) 分位: "
              f"p10={all_vals.quantile(0.1):.2f} p50={all_vals.quantile(0.5):.2f} p90={all_vals.quantile(0.9):.2f}")
        # 原始 duration days
        raw_dur = np.expm1(all_vals)
        print(f"duration_days 分位: "
              f"p10={raw_dur.quantile(0.1):.0f} p50={raw_dur.quantile(0.5):.0f} p90={raw_dur.quantile(0.9):.0f}")
        print("最近复牌事件 (top 5 duration):")
        print(all_vals.nlargest(5).apply(lambda x: f"{np.expm1(x):.0f} days").to_string())
    print("✅ 最小验证通过")
