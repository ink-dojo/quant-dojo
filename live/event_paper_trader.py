"""DSR #30 主板 rescaled — event-driven paper trader.

和 cross-sectional PaperTrader 的差别
------------------------------------
1. 每 entry 有固定 UNIT (BB=0.1323, PV=0.03048), 不等权
2. 每 entry 有 scheduled exit_date, 到期自动平仓
3. 50/50 ensemble: BB leg 和 PV leg 各自 gross cap 1.0, 合成 weight =
   0.5 × w_bb + 0.5 × w_pv, 合成再 cap 一次
4. 同一 symbol 可同时有 BB 和 PV entry; 合计持仓 = 两腿目标的和
5. 每日 process_day(date, new_entries, prices): 踢出到期 → 登记新入 → 重新按
   target-weight rebalance (不 equal-weight)

持久化
------
- 主: SQLite ledger.db (复用 live/ledger.py, 事务 + WAL)
- 辅: open_entries.json (atomic write, 记录未到期 entries 的 metadata,
  ledger 里没有这张表)
- NAV / trades / positions: 同 paper_trader.py 惯例
"""
from __future__ import annotations

import json
import logging
import math
import threading
from dataclasses import asdict, dataclass
from datetime import date as date_cls
from pathlib import Path
from typing import Literal

import pandas as pd

from live.ledger import Ledger
from pipeline.event_signal import (
    BB_UNIT_WEIGHT,
    ENSEMBLE_MIX,
    EventEntry,
    PV_UNIT_WEIGHT,
)

logger = logging.getLogger(__name__)

Leg = Literal["bb", "pv"]

DEFAULT_COST_RATE = 0.0015  # 单边 15 bps (spec v2 §4, 与 backtest 一致)

_REBALANCE_LOCK = threading.Lock()


@dataclass
class OpenEntry:
    """未到期的 entry state (一条 entry = 一次 event admission)."""
    symbol: str
    leg: Leg
    entry_date: str
    exit_date: str
    unit_weight: float
    signal: float
    entry_price: float  # actual fill price at entry (for PnL attribution / audit)

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "OpenEntry":
        return cls(**d)


class EventPaperTrader:
    """Event-driven paper trader for DSR #30 (BB+PV main-board rescaled 50/50)."""

    def __init__(self, initial_capital: float, portfolio_dir: Path | str,
                 cost_rate: float = DEFAULT_COST_RATE,
                 ensemble_mix: dict[str, float] | None = None):
        """
        Args:
            initial_capital: 初始资金 (元)
            portfolio_dir: 持仓 / trades / nav / ledger 的存储目录
            cost_rate: 单边交易成本 (默认 15 bps)
            ensemble_mix: {"bb": float, "pv": float} 两腿合并系数. None = spec v2 默认
                {bb:0.5, pv:0.5}. spec v3 BB-only 传 {bb:1.0, pv:0.0}.
        """
        self.initial_capital = float(initial_capital)
        self.cost_rate = float(cost_rate)
        if ensemble_mix is None:
            ensemble_mix = {"bb": ENSEMBLE_MIX, "pv": ENSEMBLE_MIX}
        self.ensemble_mix = {"bb": float(ensemble_mix.get("bb", 0.0)),
                             "pv": float(ensemble_mix.get("pv", 0.0))}
        self.portfolio_dir = Path(portfolio_dir)
        self.portfolio_dir.mkdir(parents=True, exist_ok=True)

        self._ledger_file = self.portfolio_dir / "ledger.db"
        self._open_entries_file = self.portfolio_dir / "open_entries.json"
        self._positions_file = self.portfolio_dir / "positions.json"
        self._trades_file = self.portfolio_dir / "trades.json"
        self._nav_file = self.portfolio_dir / "nav.csv"

        self._ledger = Ledger(self._ledger_file, initial_capital=initial_capital)

        self._load_state()

    # ------------------------------------------------------------------
    # State I/O
    # ------------------------------------------------------------------
    def _load_state(self) -> None:
        """Load state from ledger + open_entries JSON."""
        # Positions (shares etc.) from ledger
        self.positions: dict = self._ledger.read_positions()
        if "__cash__" not in self.positions:
            self.positions["__cash__"] = self.initial_capital
        # Trades from ledger (source of truth)
        self.trades: list[dict] = self._ledger.read_trades()

        # Open entries from JSON
        if self._open_entries_file.exists():
            try:
                with open(self._open_entries_file, "r", encoding="utf-8") as f:
                    raw = json.load(f)
                self.open_entries: list[OpenEntry] = [OpenEntry.from_dict(d) for d in raw]
            except (json.JSONDecodeError, OSError) as exc:
                logger.warning("open_entries.json 损坏, 重置为空: %s", exc)
                self.open_entries = []
        else:
            self.open_entries = []

    def _save_state(self) -> None:
        """Atomic write of open_entries; ledger already persisted transactionally."""
        # 1. open_entries.json
        tmp = self._open_entries_file.with_suffix(".json.tmp")
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump([e.to_dict() for e in self.open_entries], f,
                      ensure_ascii=False, indent=2)
        tmp.replace(self._open_entries_file)

        # 2. positions.json (read cache)
        tmp = self._positions_file.with_suffix(".json.tmp")
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(self.positions, f, ensure_ascii=False, indent=2)
        tmp.replace(self._positions_file)

        # 3. trades.json (read cache)
        tmp = self._trades_file.with_suffix(".json.tmp")
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(self.trades, f, ensure_ascii=False, indent=2)
        tmp.replace(self._trades_file)

    def close(self) -> None:
        self._ledger.close()

    # ------------------------------------------------------------------
    # NAV / valuation
    # ------------------------------------------------------------------
    def _cash(self) -> float:
        return float(self.positions.get("__cash__", 0.0))

    def _set_cash(self, v: float) -> None:
        self.positions["__cash__"] = float(v)

    def _nav(self, prices: dict) -> float:
        """Cash + mark-to-market of open stock positions."""
        cash = self._cash()
        stock_value = 0.0
        for sym, info in self.positions.items():
            if sym == "__cash__":
                continue
            px = prices.get(sym, info.get("current_price", 0.0))
            stock_value += info["shares"] * px
        return cash + stock_value

    # ------------------------------------------------------------------
    # Target-weight computation (核心)
    # ------------------------------------------------------------------
    def _compute_target_weights(self) -> dict[str, float]:
        """
        从 open_entries 推 target per-symbol portfolio weight.

        流程 (match backtest):
          leg_bb = sum per-sym of bb entries' unit_weight
          leg_bb gross cap to 1.0 (scale if > 1.0)
          leg_pv similar
          portfolio = 0.5 × leg_bb + 0.5 × leg_pv (per sym)
          portfolio gross cap to 1.0
        """
        bb_sym: dict[str, float] = {}
        pv_sym: dict[str, float] = {}
        for e in self.open_entries:
            if e.leg == "bb":
                bb_sym[e.symbol] = bb_sym.get(e.symbol, 0.0) + e.unit_weight
            else:
                pv_sym[e.symbol] = pv_sym.get(e.symbol, 0.0) + e.unit_weight

        bb_gross = sum(bb_sym.values())
        if bb_gross > 1.0:
            bb_sym = {s: w / bb_gross for s, w in bb_sym.items()}

        pv_gross = sum(pv_sym.values())
        if pv_gross > 1.0:
            pv_sym = {s: w / pv_gross for s, w in pv_sym.items()}

        all_syms = set(bb_sym) | set(pv_sym)
        mix_bb = self.ensemble_mix["bb"]
        mix_pv = self.ensemble_mix["pv"]
        portfolio = {
            s: mix_bb * bb_sym.get(s, 0.0) + mix_pv * pv_sym.get(s, 0.0)
            for s in all_syms
        }
        port_gross = sum(portfolio.values())
        if port_gross > 1.0:
            portfolio = {s: w / port_gross for s, w in portfolio.items()}

        return portfolio

    # ------------------------------------------------------------------
    # Rebalance
    # ------------------------------------------------------------------
    def process_day(
        self,
        trade_date: str,
        new_entries: list[EventEntry],
        prices: dict[str, float],
    ) -> dict:
        """
        每日一次 EOD pipeline:
          1. 踢出已到期的 entries (exit_date < trade_date)
          2. 登记 new_entries 到 open_entries (entry_date == trade_date)
          3. 重算 target-weights
          4. 下单: 买/卖 使 positions 匹配 target_w × NAV
          5. 记 NAV → SQLite + csv, 持久化所有 state

        Args:
            trade_date: YYYY-MM-DD, 当日交易日
            new_entries: pipeline.event_signal 返回的 entries (应是当日新信号)
            prices: {symbol: price_close} 当日收盘 (元)

        Returns:
            {"date", "n_buys", "n_sells", "turnover", "cash_after",
             "nav_after", "n_open_entries", "gross_weight"}
        """
        with _REBALANCE_LOCK:
            return self._process_day_locked(trade_date, new_entries, prices)

    def _process_day_locked(
        self,
        trade_date: str,
        new_entries: list[EventEntry],
        prices: dict[str, float],
    ) -> dict:
        # Mark-to-market open positions with today's prices FIRST so NAV
        # calculations use current prices
        for sym, info in self.positions.items():
            if sym == "__cash__":
                continue
            if sym in prices and prices[sym]:
                info["current_price"] = float(prices[sym])

        nav_before = self._nav(prices)
        n_trades_before = len(self.trades)

        # 1. Drop expired entries (exit_date < trade_date means they should
        #    have been closed by the trade_date's open; we close "on" exit_date)
        self.open_entries = [e for e in self.open_entries if e.exit_date > trade_date]

        # 2. Add new entries (filter for entry_date == trade_date).
        #    Idempotency guard: if (symbol, leg, entry_date) already in
        #    open_entries, skip — the daily script may be retried by cron after a
        #    transient failure; re-registering the same entry doubles target weight.
        existing_keys = {(e.symbol, e.leg, e.entry_date) for e in self.open_entries}
        dropped_no_price: list[str] = []
        duplicate_skipped: list[str] = []
        for e in new_entries:
            if e.entry_date != trade_date:
                continue
            key = (e.symbol, e.leg, e.entry_date)
            if key in existing_keys:
                duplicate_skipped.append(f"{e.leg}:{e.symbol}")
                continue
            price = prices.get(e.symbol)
            if price is None or price <= 0:
                dropped_no_price.append(e.symbol)
                continue  # can't fill, drop
            self.open_entries.append(OpenEntry(
                symbol=e.symbol,
                leg=e.leg,
                entry_date=e.entry_date,
                exit_date=e.exit_date,
                unit_weight=e.unit_weight,
                signal=e.signal,
                entry_price=float(price),
            ))
            existing_keys.add(key)

        # 3. Compute target weights
        target_weights = self._compute_target_weights()

        # 4. Rebalance to target_w × NAV
        nav = self._nav(prices)
        # 4a. Sell phase: anything at lower target than current (or not in target)
        current_syms = {sym for sym in self.positions if sym != "__cash__"}
        target_syms = set(target_weights.keys())
        to_remove: list[str] = []

        for sym in current_syms:
            info = self.positions[sym]
            price = prices.get(sym, info["current_price"])
            if price <= 0:
                continue
            target_value = target_weights.get(sym, 0.0) * nav
            current_value = info["shares"] * price
            excess = current_value - target_value
            if excess <= price:
                continue
            shares_to_sell = min(info["shares"], math.floor(excess / price))
            if shares_to_sell <= 0:
                continue
            proceeds = shares_to_sell * price * (1 - self.cost_rate)
            self._set_cash(self._cash() + proceeds)
            info["shares"] -= shares_to_sell
            info["current_price"] = price
            self._record_trade(trade_date, sym, "sell", shares_to_sell, price)
            if info["shares"] <= 0:
                to_remove.append(sym)
        for sym in to_remove:
            del self.positions[sym]

        # Recompute NAV after sells (cash changed)
        nav = self._nav(prices)

        # 4b. Buy phase
        skipped = []
        # Order buys by target weight descending to prioritize biggest entries
        # when cash is tight
        buy_order = sorted(target_syms, key=lambda s: target_weights[s], reverse=True)
        for sym in buy_order:
            price = prices.get(sym)
            if price is None or price <= 0:
                continue
            target_value = target_weights[sym] * nav
            info = self.positions.get(sym)
            current_shares = int(info["shares"]) if info else 0
            current_value = current_shares * price
            gap = target_value - current_value
            if gap <= price:
                if info is not None:
                    info["current_price"] = price
                continue
            cash = self._cash()
            if cash <= 0:
                skipped.append(sym)
                continue
            max_affordable = math.floor(cash / (price * (1 + self.cost_rate)))
            target_shares_add = math.floor(gap / price)
            shares_to_buy = min(target_shares_add, max_affordable)
            if shares_to_buy <= 0:
                skipped.append(sym)
                continue
            actual_cost = shares_to_buy * price * (1 + self.cost_rate)
            if actual_cost > cash:
                skipped.append(sym)
                continue
            self._set_cash(cash - actual_cost)
            if info is None:
                self.positions[sym] = {
                    "shares": shares_to_buy,
                    "cost_price": float(price),
                    "current_price": float(price),
                }
            else:
                total_shares = info["shares"] + shares_to_buy
                info["cost_price"] = (
                    info["cost_price"] * info["shares"] + shares_to_buy * price
                ) / total_shares
                info["shares"] = total_shares
                info["current_price"] = float(price)
            self._record_trade(trade_date, sym, "buy", shares_to_buy, price)

        if self._cash() < -1e-6:
            raise RuntimeError(f"现金为负 {self._cash()} — rebalance 出错")

        # 5. Record NAV + persist state
        nav_after = self._nav(prices)
        self._ledger.upsert_nav(trade_date, nav_after)
        self._ledger.replace_positions(self.positions)
        self._save_state()
        self._rehydrate_nav_csv(trade_date, nav_after)

        new_trades = self.trades[n_trades_before:]
        n_buys = sum(1 for t in new_trades if t["action"] == "buy")
        n_sells = sum(1 for t in new_trades if t["action"] == "sell")
        trade_volume = sum(t["shares"] * t["price"] for t in new_trades)
        turnover = trade_volume / nav_before if nav_before > 0 else 0.0

        return {
            "date": trade_date,
            "n_buys": n_buys,
            "n_sells": n_sells,
            "turnover": round(turnover, 4),
            "cash_after": round(self._cash(), 2),
            "nav_after": round(nav_after, 2),
            "n_open_entries": len(self.open_entries),
            "gross_weight": round(sum(target_weights.values()), 4),
            "skipped_buys": skipped,
            "dropped_no_price": dropped_no_price,
            "duplicate_skipped": duplicate_skipped,
        }

    def _record_trade(self, trade_date: str, symbol: str, action: str,
                      shares: int, price: float) -> None:
        trade = {
            "date": trade_date,
            "symbol": symbol,
            "action": action,
            "shares": int(shares),
            "price": float(price),
            "cost": float(shares * price * self.cost_rate),
        }
        # Ledger is source of truth (spec v2 §7). If SQLite write fails we must
        # not let the in-memory list diverge — raise so the daily pipeline halts
        # and the operator investigates instead of silently piling up stale trades.
        self._ledger.append_trade(trade)
        self.trades.append(trade)

    def _rehydrate_nav_csv(self, trade_date: str, nav: float) -> None:
        """刷新 nav.csv 读缓存 (atomic, 覆盖当日)."""
        if self._nav_file.exists():
            nav_df = pd.read_csv(self._nav_file, dtype={"nav": float})
        else:
            nav_df = pd.DataFrame(columns=["date", "nav"])

        if trade_date in nav_df["date"].astype(str).values:
            nav_df.loc[nav_df["date"].astype(str) == trade_date, "nav"] = nav
        else:
            nav_df = pd.concat([nav_df, pd.DataFrame([{"date": trade_date, "nav": nav}])],
                               ignore_index=True)
        nav_df = nav_df.sort_values("date").reset_index(drop=True)
        tmp = self._nav_file.with_suffix(".csv.tmp")
        nav_df.to_csv(tmp, index=False)
        tmp.replace(self._nav_file)

    # ------------------------------------------------------------------
    # Observability
    # ------------------------------------------------------------------
    def nav_series(self) -> pd.Series:
        rows = self._ledger.read_nav()
        if not rows:
            return pd.Series(dtype=float, name="nav")
        s = pd.Series({pd.Timestamp(d): v for d, v in rows}, name="nav").sort_index()
        return s

    def active_positions_df(self) -> pd.DataFrame:
        rows = []
        for sym, info in self.positions.items():
            if sym == "__cash__":
                continue
            rows.append({
                "symbol": sym,
                "shares": info["shares"],
                "cost_price": info["cost_price"],
                "current_price": info["current_price"],
                "pnl_pct": round(info["current_price"] / info["cost_price"] - 1, 4)
                           if info["cost_price"] > 0 else 0.0,
            })
        return pd.DataFrame(rows)


if __name__ == "__main__":
    import tempfile
    logging.basicConfig(level=logging.INFO)

    with tempfile.TemporaryDirectory() as tmp:
        trader = EventPaperTrader(initial_capital=1_000_000, portfolio_dir=Path(tmp))
        # Manually construct a few entries for smoke test
        entries = [
            EventEntry(symbol="600000", leg="bb", event_date="2025-06-13",
                       entry_date="2025-06-16", exit_date="2025-07-14",
                       unit_weight=BB_UNIT_WEIGHT, signal=5.0, threshold=3.0),
            EventEntry(symbol="600036", leg="pv", event_date="2025-06-13",
                       entry_date="2025-06-16", exit_date="2025-07-14",
                       unit_weight=PV_UNIT_WEIGHT, signal=60.0, threshold=25.0),
        ]
        prices = {"600000": 9.8, "600036": 45.5}
        summary = trader.process_day("2025-06-16", entries, prices)
        print("Day 1 summary:", summary)
        print("Open entries:", len(trader.open_entries))
        print("Positions:", trader.active_positions_df())
        print("NAV:", trader._nav(prices))

        # Next day: no new entries, prices move
        prices2 = {"600000": 10.0, "600036": 46.0}
        summary2 = trader.process_day("2025-06-17", [], prices2)
        print("\nDay 2 summary:", summary2)

        trader.close()
        print("\n✅ EventPaperTrader smoke test ok")
