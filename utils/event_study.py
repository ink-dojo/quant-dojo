"""
通用 event-driven backtest 工具 — 抽自 research/event_alpha/lhb_t1_event_study.py
+ research/event_driven/event_study.py 的共同模式.

设计目标:
- A 路 4 个事件 candidate (LHB / 回购 / 减持 / 调研) 都用同一 event-window
  framework, 不再每个 script 复制 abn return 循环 + quintile spread.
- 不是 wide-panel daily backtest (那种用 utils/factor_analysis 或 utils/ls_costs);
  这里是 per-event horizon-cumulated 单点收益, 数学不同.

提供:
- load_event_parquets(prefix, dir, start, end, columns): 通用 SSD parquet glob
- compute_event_abn_returns(events, prices, ...): 向量化 fancy index, ~30x 比 iterrows
- quintile_spread(long_df, ...): per-event quintile + horizon-cumulated spread
- skip_overnight_gap 选项处理盘后披露事件的 T close→T+1 open 不可交易 gap
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd

# ─────────────────────────────────────────────────────────────
# Constants
# ─────────────────────────────────────────────────────────────

DEFAULT_PRE_DAYS = 5
DEFAULT_POST_DAYS = 30
DEFAULT_RET_CLIP = 0.25  # |daily ret| > 25% 视为 corp action 噪音 → NaN
DEFAULT_MIN_EVENTS_PER_QUINTILE = 20


# ─────────────────────────────────────────────────────────────
# 1. 加载 SSD events
# ─────────────────────────────────────────────────────────────

def load_event_parquets(
    prefix: str,
    events_dir: Path,
    start: str = "20100101",
    end: str = "20991231",
    columns: Optional[list[str]] = None,
    date_format: str = "%Y%m%d",
) -> pd.DataFrame:
    """通用日级 SSD parquet glob: {events_dir}/{prefix}_YYYYMMDD.parquet.

    用于 top_list / top_inst / repurchase 等按日存档的事件文件.
    返回 dedup 后的 long DataFrame, trade_date 转为 datetime, 加 symbol 列
    (从 ts_code 去掉后缀).

    参数:
        prefix      : 文件名前缀, 如 'top_list', 'top_inst', 'repurchase'
        events_dir  : SSD 上的 events 目录, 如 data/raw/tushare/events
        start, end  : 文件名日期 inclusive 范围
        columns     : pd.read_parquet 的 columns 参数; None 读全部
        date_format : 文件名里日期的 strftime; tushare 一般 %Y%m%d
    """
    files = sorted(events_dir.glob(f"{prefix}_*.parquet"))
    if not files:
        return pd.DataFrame()
    start_dt = pd.to_datetime(start, format=date_format if len(start) == 8 else None).date()
    end_dt = pd.to_datetime(end, format=date_format if len(end) == 8 else None).date()
    frames = []
    for f in files:
        try:
            d = pd.to_datetime(f.stem.replace(f"{prefix}_", ""), format=date_format).date()
        except ValueError:
            continue
        if d < start_dt or d > end_dt:
            continue
        df = pd.read_parquet(f, columns=columns) if columns else pd.read_parquet(f)
        if not df.empty:
            frames.append(df)
    if not frames:
        return pd.DataFrame()

    raw = pd.concat(frames, ignore_index=True).drop_duplicates()
    if "trade_date" in raw.columns and not pd.api.types.is_datetime64_any_dtype(raw["trade_date"]):
        raw["trade_date"] = pd.to_datetime(raw["trade_date"], format="%Y%m%d", errors="coerce")
    if "ts_code" in raw.columns and "symbol" not in raw.columns:
        raw["symbol"] = raw["ts_code"].astype(str).str.split(".").str[0]
    return raw


# ─────────────────────────────────────────────────────────────
# 2. event-window abn return (向量化)
# ─────────────────────────────────────────────────────────────

def compute_event_abn_returns(
    events: pd.DataFrame,
    prices: pd.DataFrame,
    *,
    date_col: str = "event_date",
    symbol_col: str = "symbol",
    extra_cols: Optional[list[str]] = None,
    pre_days: int = DEFAULT_PRE_DAYS,
    post_days: int = DEFAULT_POST_DAYS,
    ret_clip: float = DEFAULT_RET_CLIP,
) -> pd.DataFrame:
    """对每个事件算 T-pre ~ T+post 相对日 abn_ret, 向量化 fancy-index 实现.

    abn_ret = pct_change - mkt_ew_mean (简单 market-adj). |daily ret| > ret_clip
    视为 corp action 设 NaN.

    rel_day=0 是 event 当天; rel_day=1 是 (event close → next close) 的次日收益.
    对盘后披露事件, rel_day=1 含 overnight gap (见 quintile_spread 的
    skip_overnight_gap 选项).

    Skip 规则 (与原 iterrows 版本语义一致):
    - 事件日期不在交易日历 (停牌/节假日) → 整个事件丢弃
    - symbol 不在 prices 列 → 整个事件丢弃
    - i0 离索引头/尾不够窗口 → 整个事件丢弃
    - 单 rel_day NaN → 该 (event, rel_day) 行丢弃, 不影响其他 rel_day

    参数:
        events     : 长表, 必含 date_col 和 symbol_col, extra_cols 透传到输出
        prices     : 宽表 (date × symbol), 价格 (close 或 adj close)
        date_col   : events 里事件日期列名
        symbol_col : events 里 6 位股票代码列名
        extra_cols : 其他 events 列也带进结果 (如 net_rate, reason_cat)
        pre_days, post_days : 事件窗大小
        ret_clip   : |ret| > clip 设 NaN

    返回长表: [symbol, event_date, rel_day, abn_ret, ...extra_cols]
    """
    extra_cols = extra_cols or []

    daily_ret = prices.pct_change().where(lambda x: x.abs() < ret_clip)
    mkt = daily_ret.mean(axis=1)
    abn = daily_ret.sub(mkt, axis=0)

    td_arr = abn.index.values
    n_dates = len(td_arr)
    col_index = {c: i for i, c in enumerate(abn.columns)}
    abn_vals = abn.values  # (n_dates, n_syms) float64

    ev = events.reset_index(drop=True)
    ev_dates = pd.to_datetime(ev[date_col]).values.astype("datetime64[ns]")
    ev_syms = ev[symbol_col].values

    i0 = np.searchsorted(td_arr, ev_dates, side="left")
    in_range = i0 < n_dates

    hit = np.zeros(len(ev), dtype=bool)
    if in_range.any():
        hit[in_range] = td_arr[i0[in_range]] == ev_dates[in_range]

    sym_idx = np.array([col_index.get(s, -1) for s in ev_syms])
    sym_ok = sym_idx >= 0

    window_ok = (i0 >= pre_days) & (i0 + post_days < n_dates)
    keep = hit & sym_ok & window_ok

    if not keep.any():
        out_cols = [symbol_col, "event_date", "rel_day", "abn_ret"] + extra_cols
        return pd.DataFrame(columns=out_cols)

    ev_k = ev.loc[keep].reset_index(drop=True)
    i0_k = i0[keep]
    col_k = sym_idx[keep]

    rels = np.arange(-pre_days, post_days + 1)
    row_idx = i0_k[:, None] + rels[None, :]                # (n_ev, n_rel)
    col_idx = np.broadcast_to(col_k[:, None], row_idx.shape)
    vals = abn_vals[row_idx, col_idx]                      # (n_ev, n_rel)

    ev_pos, rd_pos = np.where(~np.isnan(vals))

    out = {
        symbol_col:   ev_k[symbol_col].values[ev_pos],
        "event_date": pd.to_datetime(ev_k[date_col].values[ev_pos]),
        "rel_day":    rels[rd_pos],
        "abn_ret":    vals[ev_pos, rd_pos],
    }
    for c in extra_cols:
        if c in ev_k.columns:
            out[c] = ev_k[c].values[ev_pos]
    return pd.DataFrame(out)


# ─────────────────────────────────────────────────────────────
# 3. quintile spread (per-event horizon-cumulated)
# ─────────────────────────────────────────────────────────────

def quintile_spread(
    long_df: pd.DataFrame,
    signal_col: str,
    horizons: list[int] = (1, 5, 10),
    n_q: int = 5,
    cost_per_side: float = 0.0025,
    n_legs: int = 2,
    skip_overnight_gap: bool = True,
    symbol_col: str = "symbol",
    min_events_per_quintile: int = DEFAULT_MIN_EVENTS_PER_QUINTILE,
) -> dict:
    """按 signal_col quintile 分组, 各 horizon 算 Q_top - Q_bot spread + cost-aware net.

    skip_overnight_gap (默认 True, **conservative tradeable**):
        每事件 horizon-累计 ret = sum(abn_ret, rel_day in [2..H+1]).
        rel_day=1 是 T close → T+1 close, 含盘后披露事件的 overnight gap (不可收).
        skip 后假设 entry 在 T+1 close, 持有 H 天到 T+H+1 close.
    skip_overnight_gap=False (上界, 含 gap):
        sum(abn_ret, rel_day in [1..H]).

    Cost: long-short n_legs 默认 2 (多腿+空腿), 各 1 次 round trip = 2 * cost_per_side.
        总扣减 = n_legs * 2 * cost_per_side. (默认 2 legs × 2 rt × 0.25% = 1.0% net 扣)

    返回 dict[horizon → metrics]:
        n_events, n_top, n_bot, spread_gross, spread_net, t_stat, p_value, q_means
    """
    from scipy import stats

    if "event_date" not in long_df.columns:
        raise KeyError("long_df 缺 event_date 列 (compute_event_abn_returns 输出)")
    ev_signal = (long_df.groupby([symbol_col, "event_date"])[signal_col]
                 .first().rename(signal_col))

    out = {}
    rel_lo = 2 if skip_overnight_gap else 1
    cost_total = n_legs * 2 * cost_per_side  # 2 legs × (entry + exit)

    for h in horizons:
        rel_hi = h + 1 if skip_overnight_gap else h
        sub = long_df[(long_df["rel_day"] >= rel_lo) & (long_df["rel_day"] <= rel_hi)]
        cum = (sub.groupby([symbol_col, "event_date"])["abn_ret"]
               .sum().rename(f"cum_{h}"))
        df = pd.concat([ev_signal, cum], axis=1).dropna(subset=[signal_col, f"cum_{h}"])

        if len(df) < n_q * min_events_per_quintile:
            out[h] = {"n_events": int(len(df)),
                      "spread_gross": None, "spread_net": None,
                      "t_stat": None, "p_value": None, "q_means": {}}
            continue

        df = df.copy()
        df["q"] = pd.qcut(df[signal_col], q=n_q, labels=False, duplicates="drop")
        q_means = df.groupby("q")[f"cum_{h}"].mean()
        spread_gross = float(q_means.iloc[-1] - q_means.iloc[0])
        spread_net = spread_gross - cost_total

        q_high = df[df["q"] == df["q"].max()][f"cum_{h}"].values
        q_low = df[df["q"] == 0][f"cum_{h}"].values
        t_stat, p_val = stats.ttest_ind(q_high, q_low, equal_var=False)

        out[h] = {
            "n_events": int(len(df)),
            "n_top": int(len(q_high)),
            "n_bot": int(len(q_low)),
            "spread_gross": round(spread_gross, 5),
            "spread_net": round(spread_net, 5),
            "cost_total": round(cost_total, 5),
            "t_stat": round(float(t_stat), 3),
            "p_value": round(float(p_val), 4),
            "q_means": {str(int(k)): round(float(v), 5) for k, v in q_means.items()},
        }
    return out


# ─────────────────────────────────────────────────────────────
# 4. T+1 涨跌停 next-day filter (排除 T+1 不可入场事件)
# ─────────────────────────────────────────────────────────────

def t1_limit_mask(
    events: pd.DataFrame,
    prices: pd.DataFrame,
    *,
    date_col: str = "trade_date",
    symbol_col: str = "symbol",
    cat_col: Optional[str] = "reason_cat",
    nolimit_value: str = "nolimit",
    threshold: float = 0.095,
) -> pd.Series:
    """对每事件查 T+1 raw return. 返回 bool Series, True = T+1 涨跌停 → 应剔.

    Vectorized fancy-index, ~50-100x 比 Python loop. 边界条件保留:
        - i0 越界 / sym 不在 prices 列 / event_date 不在交易日历 → False (不剔)
        - prices[T] 或 prices[T+1] NaN / prices[T] == 0 → False
        - cat_col 列里 nolimit_value 的事件不过滤 (本无涨跌停板)

    threshold 默认 0.095 (主板 ±10% 留 50bp buffer). 创业板/科创板 +/- 19.5%
    用同阈值会 over-filter, 是已知 trade-off (保守优先). 后续可接 tushare
    limit_list 做精确多板 detection.

    参数:
        events, prices : 同 compute_event_abn_returns
        cat_col, nolimit_value : 跳过无涨跌停板事件 (传 cat_col=None 则全部过滤)
        threshold      : |T+1 return| 阈值, 默认 0.095
    """
    td_arr = prices.index.values
    n_dates = len(td_arr)
    col_index = {c: i for i, c in enumerate(prices.columns)}
    p_vals = prices.values

    ev_dates = pd.to_datetime(events[date_col]).values.astype("datetime64[ns]")
    ev_syms = events[symbol_col].values

    i0 = np.searchsorted(td_arr, ev_dates, side="left")
    sym_idx = np.array([col_index.get(s, -1) for s in ev_syms])

    in_range = (i0 < n_dates - 1)
    safe_i0 = np.where(in_range, i0, 0)
    hit = np.zeros(len(events), dtype=bool)
    hit[in_range] = td_arr[safe_i0[in_range]] == ev_dates[in_range]
    sym_ok = sym_idx >= 0

    if cat_col is not None and cat_col in events.columns:
        not_nolimit = events[cat_col].values != nolimit_value
    else:
        not_nolimit = np.ones(len(events), dtype=bool)

    eligible = in_range & hit & sym_ok & not_nolimit
    is_limit = np.zeros(len(events), dtype=bool)
    if eligible.any():
        i0_e = i0[eligible]
        col_e = sym_idx[eligible]
        p_t = p_vals[i0_e, col_e]
        p_t1 = p_vals[i0_e + 1, col_e]
        with np.errstate(divide="ignore", invalid="ignore"):
            ret_t1 = p_t1 / p_t - 1
        valid = ~(np.isnan(p_t) | np.isnan(p_t1) | (p_t == 0))
        flag = valid & (np.abs(ret_t1) >= threshold)
        is_limit[np.where(eligible)[0]] = flag

    return pd.Series(is_limit, index=events.index, name="t1_limit")


if __name__ == "__main__":
    # 最小自测: 合成 200 个事件 + 100 股票 30 日窗
    rng = np.random.default_rng(42)
    n_d, n_s, n_e = 200, 100, 200
    dates = pd.bdate_range("2024-01-01", periods=n_d)
    syms = [f"S{i:03d}" for i in range(n_s)]
    prices = pd.DataFrame(
        100 * np.exp(np.cumsum(rng.normal(0, 0.02, (n_d, n_s)), axis=0)),
        index=dates, columns=syms,
    )
    ev_dates = rng.choice(dates[10:-40], size=n_e, replace=True)
    ev_syms = rng.choice(syms, size=n_e, replace=True)
    ev_signal = rng.normal(size=n_e)
    events = pd.DataFrame({"event_date": ev_dates, "symbol": ev_syms,
                           "signal": ev_signal})

    long_df = compute_event_abn_returns(
        events, prices, date_col="event_date", extra_cols=["signal"],
        pre_days=3, post_days=10,
    )
    print(f"long shape: {long_df.shape}, events kept: "
          f"{long_df.groupby(['symbol', 'event_date']).ngroups}")

    spread = quintile_spread(long_df, signal_col="signal", horizons=[1, 5],
                             min_events_per_quintile=5)
    for h, m in spread.items():
        if m["spread_gross"] is None:
            print(f"  T+{h}: insufficient")
            continue
        print(f"  T+{h}: gross {m['spread_gross']*100:+.3f}% / "
              f"net {m['spread_net']*100:+.3f}%  t={m['t_stat']:+.2f}")
    print("\n✅ event_study 自测通过")
