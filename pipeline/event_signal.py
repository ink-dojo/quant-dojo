"""DSR #30 主板 rescaled — causal daily signal generator for paper-trade.

在 T (today) 决定在 T+1 (next trading day) 开仓的新 event 列表.

### 和 backtest 的关键差别

Backtest (`research/event_driven/dsr30_mainboard_recal.py`) 用 monthly groupby
+ top 30% by signal. 这个选股逻辑有轻微 look-ahead (月内第 3 天的 event 的
admission 依赖于当月剩余事件). Live 必须 causal, 我们用 **trailing 60 calendar
days 30th-percentile 阈值**:

- 在日期 T, 对 leg ∈ {bb, pv}, 计算过去 60 天 (event_date ∈ [T-60, T-1]) 所有 events
  的 signal 的 70th-percentile 值作为阈值 (因为 "top 30%" = signal >= 70th percentile)
- 今日候选: event_date == T-1 (上个交易日) 的 events
- 若 signal >= 阈值 → 合格, 在 T+1 (today's trading date) 开仓

这样保证 causal, 不泄漏未来. Smoke test 会对比此 causal rule 与 backtest 的 NAV
差异 (`scripts/paper_trade_smoke_test.py`).

### Weight 模型

DSR #30 = 50/50 ensemble. 两条 leg 各自独立 UNIT:
- BB: UNIT_BASE=1/15, SCALE=0.8/0.403=1.985 → per-position weight = 0.1323
- PV: UNIT_BASE=1/75, SCALE=0.8/0.350=2.286 → per-position weight = 0.03048

Portfolio weight per position = 0.5 × (leg-capped weight).
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, asdict
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Literal

import pandas as pd

logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).parent.parent

BB_EVENTS_PATH = PROJECT_ROOT / "data" / "raw" / "events" / "_all_buyback.parquet"
PV_EVENTS_PATH = PROJECT_ROOT / "data" / "raw" / "events" / "_all_earnings_preview_2018_2025.parquet"
LISTING_PATH = PROJECT_ROOT / "data" / "raw" / "listing_metadata.parquet"

# Strategy parameters (locked, see journal/paper_trade_spec_v2_20260421.md)
HOLD_DAYS = 20
POST_OFFSET = 1
TOP_PCT = 0.30  # admit events with signal >= (1-TOP_PCT) percentile
THRESHOLD_WINDOW_DAYS = 60  # trailing calendar days for percentile computation
BB_UNIT_BASE = 1.0 / 15
BB_SCALE = 0.8 / 0.403  # ≈ 1.985
PV_UNIT_BASE = 1.0 / 75
PV_SCALE = 0.8 / 0.350  # ≈ 2.286
BB_UNIT_WEIGHT = BB_UNIT_BASE * BB_SCALE
PV_UNIT_WEIGHT = PV_UNIT_BASE * PV_SCALE
ENSEMBLE_MIX = 0.5  # default 50/50 (spec v2); v3 overrides via config.json

Leg = Literal["bb", "pv"]


@dataclass
class EventEntry:
    """Single event admitted for paper-trade entry."""
    symbol: str
    leg: Leg
    event_date: str  # YYYY-MM-DD, when event fired
    entry_date: str  # YYYY-MM-DD, when we open (event_date + POST_OFFSET trading days)
    exit_date: str   # YYYY-MM-DD, when we close (entry_date + HOLD_DAYS trading days)
    unit_weight: float  # leg-level weight (before ensemble 0.5 and before gross cap)
    signal: float
    threshold: float  # admission threshold that was applied


@dataclass
class DailySignal:
    """Output of one call to generate_daily_signal()."""
    as_of_date: str  # YYYY-MM-DD, the trading day we're generating for (entry happens today)
    new_entries: list[EventEntry]
    stats: dict

    def to_dict(self) -> dict:
        return {
            "as_of_date": self.as_of_date,
            "new_entries": [asdict(e) for e in self.new_entries],
            "stats": self.stats,
        }


def _load_main_board_set() -> set[str]:
    df = pd.read_parquet(LISTING_PATH)
    return set(df[df["board"] == "主板"]["symbol"].tolist())


def _load_bb_events() -> pd.DataFrame:
    """Raw buyback events, filtered to valid signal/state but NOT main-board yet."""
    df = pd.read_parquet(BB_EVENTS_PATH)
    df["event_date"] = pd.to_datetime(df["回购起始时间"], errors="coerce")
    df = df.dropna(subset=["event_date", "占公告前一日总股本比例-上限", "股票代码"])
    df = df.rename(columns={"股票代码": "symbol"})
    df = df[df["实施进度"] != "股东大会否决"]
    df["signal"] = df["占公告前一日总股本比例-上限"].astype(float)
    df = df[(df["signal"] > 0) & (df["signal"] < 50)]
    return df[["symbol", "event_date", "signal"]].sort_values("event_date").reset_index(drop=True)


def _load_pv_events() -> pd.DataFrame:
    """Raw earnings preview events, filtered to positive types."""
    df = pd.read_parquet(PV_EVENTS_PATH)
    df["event_date"] = pd.to_datetime(df["公告日期"], errors="coerce")
    df = df.dropna(subset=["event_date", "业绩变动幅度", "股票代码"])
    df = df.rename(columns={"股票代码": "symbol"})
    df = df[df["预测指标"] == "归属于上市公司股东的净利润"]
    df = df[df["预告类型"].isin(["预增", "略增"])]
    df["signal"] = df["业绩变动幅度"].astype(float)
    df = df[(df["signal"] > 0) & (df["signal"] < 500)]
    df = df.sort_values("signal", ascending=False).drop_duplicates(
        subset=["symbol", "event_date"], keep="first"
    )
    return df[["symbol", "event_date", "signal"]].sort_values("event_date").reset_index(drop=True)


def _compute_threshold(events: pd.DataFrame, as_of: pd.Timestamp, window_days: int) -> float | None:
    """70th-percentile of signals in [as_of - window_days, as_of - 1day].

    Returns None if insufficient history (< 10 events in window).
    """
    lo = as_of - pd.Timedelta(days=window_days)
    hi = as_of - pd.Timedelta(days=1)
    window = events[(events["event_date"] >= lo) & (events["event_date"] <= hi)]
    if len(window) < 10:
        return None
    return float(window["signal"].quantile(1.0 - TOP_PCT))


def _shift_trading_day(trading_days: pd.DatetimeIndex, from_date: pd.Timestamp, offset: int) -> pd.Timestamp | None:
    """Return the trading day at `offset` positions after `from_date` (can be negative).

    `from_date` must be on a trading day. Returns None if out of range.
    """
    arr = trading_days.values
    idx = int(pd.Series(arr).searchsorted(from_date.to_datetime64(), side="left"))
    if idx >= len(arr) or pd.Timestamp(arr[idx]) != from_date:
        # from_date not a trading day; snap to next trading day
        if idx >= len(arr):
            return None
    target = idx + offset
    if target < 0 or target >= len(arr):
        return None
    return pd.Timestamp(arr[target])


def _previous_trading_day(trading_days: pd.DatetimeIndex, as_of: pd.Timestamp) -> pd.Timestamp | None:
    """Largest trading day strictly less than as_of."""
    arr = trading_days.values
    idx = int(pd.Series(arr).searchsorted(as_of.to_datetime64(), side="left"))
    if idx == 0:
        return None
    return pd.Timestamp(arr[idx - 1])


def generate_daily_signal(
    as_of_date: str | date | datetime,
    trading_days: pd.DatetimeIndex,
    bb_events: pd.DataFrame | None = None,
    pv_events: pd.DataFrame | None = None,
    main_board_symbols: set[str] | None = None,
    legs_enabled: dict[str, bool] | None = None,
) -> DailySignal:
    """Generate entry signals for opening at today (as_of_date) T+1-style.

    On day T (as_of_date, a trading day), we process events with event_date == T-1
    (last trading day). Each event is admitted if its signal >= trailing 60d 70th
    percentile and its symbol is main-board.

    Args:
        as_of_date: today's trading date.
        trading_days: sorted DatetimeIndex of all trading days (e.g. from price data).
        bb_events, pv_events, main_board_symbols: optional overrides for tests.
        legs_enabled: {"bb": bool, "pv": bool}. None = both enabled (spec v2 default).
            spec v3 passes {"bb": True, "pv": False} from paper_trade/config.json.

    Returns:
        DailySignal with list of admitted EventEntry and stats.
    """
    as_of = pd.Timestamp(as_of_date).normalize()
    if as_of not in trading_days:
        raise ValueError(f"as_of_date {as_of.date()} is not a trading day")

    prev_td = _previous_trading_day(trading_days, as_of)
    if prev_td is None:
        raise ValueError(f"No prior trading day before {as_of.date()}")

    if bb_events is None:
        bb_events = _load_bb_events()
    if pv_events is None:
        pv_events = _load_pv_events()
    if main_board_symbols is None:
        main_board_symbols = _load_main_board_set()

    # Apply main-board filter once (we do NOT include non-main-board events in threshold
    # calc because they can't trade anyway — matches backtest which calls
    # filter_mainboard before build_weights.)
    bb_events = bb_events[bb_events["symbol"].isin(main_board_symbols)]
    pv_events = pv_events[pv_events["symbol"].isin(main_board_symbols)]

    entries: list[EventEntry] = []
    stats = {"bb_candidates": 0, "bb_admitted": 0, "pv_candidates": 0, "pv_admitted": 0,
             "bb_threshold": None, "pv_threshold": None}

    exit_td = _shift_trading_day(trading_days, as_of, HOLD_DAYS)
    exit_date_str = exit_td.strftime("%Y-%m-%d") if exit_td is not None else ""

    if legs_enabled is None:
        legs_enabled = {"bb": True, "pv": True}

    for leg, events_df, unit_weight in [
        ("bb", bb_events, BB_UNIT_WEIGHT),
        ("pv", pv_events, PV_UNIT_WEIGHT),
    ]:
        if not legs_enabled.get(leg, True):
            stats[f"{leg}_candidates"] = 0
            stats[f"{leg}_admitted"] = 0
            stats[f"{leg}_threshold"] = None
            continue
        threshold = _compute_threshold(events_df, as_of, THRESHOLD_WINDOW_DAYS)
        stats[f"{leg}_threshold"] = threshold
        # Candidates: events that fired on the previous trading day
        candidates = events_df[events_df["event_date"] == prev_td]
        stats[f"{leg}_candidates"] = int(len(candidates))
        if threshold is None or len(candidates) == 0:
            continue
        admitted = candidates[candidates["signal"] >= threshold]
        # De-dup by symbol (keep best signal per symbol on same day)
        admitted = admitted.sort_values("signal", ascending=False).drop_duplicates(
            subset=["symbol"], keep="first"
        )
        stats[f"{leg}_admitted"] = int(len(admitted))
        for _, row in admitted.iterrows():
            entries.append(EventEntry(
                symbol=row["symbol"],
                leg=leg,
                event_date=row["event_date"].strftime("%Y-%m-%d"),
                entry_date=as_of.strftime("%Y-%m-%d"),
                exit_date=exit_date_str,
                unit_weight=unit_weight,
                signal=float(row["signal"]),
                threshold=float(threshold),
            ))

    return DailySignal(
        as_of_date=as_of.strftime("%Y-%m-%d"),
        new_entries=entries,
        stats=stats,
    )


def generate_strict_match_signal(
    as_of_date: str | date | datetime,
    trading_days: pd.DatetimeIndex,
    bb_events: pd.DataFrame | None = None,
    pv_events: pd.DataFrame | None = None,
    main_board_symbols: set[str] | None = None,
) -> DailySignal:
    """Non-causal variant that EXACTLY matches the backtest's monthly top-30% rule.

    Used ONLY for smoke test to isolate signal-logic divergence from trader-logic
    divergence. DO NOT USE IN PRODUCTION — it peeks at future events in the month.
    """
    as_of = pd.Timestamp(as_of_date).normalize()
    if as_of not in trading_days:
        raise ValueError(f"as_of_date {as_of.date()} is not a trading day")

    prev_td = _previous_trading_day(trading_days, as_of)
    if prev_td is None:
        raise ValueError(f"No prior trading day before {as_of.date()}")

    if bb_events is None:
        bb_events = _load_bb_events()
    if pv_events is None:
        pv_events = _load_pv_events()
    if main_board_symbols is None:
        main_board_symbols = _load_main_board_set()

    bb_events = bb_events[bb_events["symbol"].isin(main_board_symbols)]
    pv_events = pv_events[pv_events["symbol"].isin(main_board_symbols)]

    entries: list[EventEntry] = []
    stats = {"bb_candidates": 0, "bb_admitted": 0, "pv_candidates": 0, "pv_admitted": 0}

    exit_td = _shift_trading_day(trading_days, as_of, HOLD_DAYS)
    exit_date_str = exit_td.strftime("%Y-%m-%d") if exit_td is not None else ""

    for leg, events_df, unit_weight in [
        ("bb", bb_events, BB_UNIT_WEIGHT),
        ("pv", pv_events, PV_UNIT_WEIGHT),
    ]:
        if len(events_df) == 0:
            continue
        # Use full month including future events (non-causal — for test only)
        month = prev_td.to_period("M")
        month_events = events_df[events_df["event_date"].dt.to_period("M") == month]
        if len(month_events) < 10:
            continue
        month_events_sorted = month_events.sort_values("signal", ascending=False)
        n_top = max(1, int(len(month_events_sorted) * TOP_PCT))
        top = month_events_sorted.iloc[:n_top]
        # Candidates: events that fired on prev_td AND are in month's top
        admitted = top[top["event_date"] == prev_td]
        # De-dup by symbol
        admitted = admitted.sort_values("signal", ascending=False).drop_duplicates(
            subset=["symbol"], keep="first"
        )
        stats[f"{leg}_candidates"] = int((events_df["event_date"] == prev_td).sum())
        stats[f"{leg}_admitted"] = int(len(admitted))
        for _, row in admitted.iterrows():
            entries.append(EventEntry(
                symbol=row["symbol"],
                leg=leg,
                event_date=row["event_date"].strftime("%Y-%m-%d"),
                entry_date=as_of.strftime("%Y-%m-%d"),
                exit_date=exit_date_str,
                unit_weight=unit_weight,
                signal=float(row["signal"]),
                threshold=0.0,  # not applicable
            ))

    return DailySignal(
        as_of_date=as_of.strftime("%Y-%m-%d"),
        new_entries=entries,
        stats=stats,
    )


if __name__ == "__main__":
    import pandas as pd
    from utils.local_data_loader import load_adj_price_wide

    # Self-test: load a trading calendar, run signal on a recent date
    prices = load_adj_price_wide(["600000"], start="2025-01-01", end="2025-12-31")
    td = prices.index

    # Pick a date with likely events — use a Monday in mid 2025
    test_date = pd.Timestamp("2025-06-16")
    if test_date not in td:
        test_date = td[len(td) // 2]

    sig = generate_daily_signal(test_date, td)
    print(f"Signal for {sig.as_of_date}:")
    print(f"  BB: {sig.stats['bb_candidates']} candidates, {sig.stats['bb_admitted']} admitted, "
          f"threshold={sig.stats['bb_threshold']}")
    print(f"  PV: {sig.stats['pv_candidates']} candidates, {sig.stats['pv_admitted']} admitted, "
          f"threshold={sig.stats['pv_threshold']}")
    for e in sig.new_entries[:10]:
        print(f"    {e.leg} {e.symbol} signal={e.signal:.2f} entry={e.entry_date} exit={e.exit_date}")
    print(f"  ✅ total: {len(sig.new_entries)} entries")
