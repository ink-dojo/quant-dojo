"""
paper_trader.py — 模拟盘持仓追踪

记录模拟交易的持仓、交易记录和净值曲线，不涉及真实资金。
数据持久化到 live/portfolio/ 目录下的 JSON/CSV 文件。
"""

import json
import math
import os
from datetime import datetime, date
from pathlib import Path

import numpy as np
import pandas as pd

from utils.runtime_config import get_transaction_cost_rate

# 投资组合数据存储目录
PORTFOLIO_DIR = Path(__file__).parent / "portfolio"
POSITIONS_FILE = PORTFOLIO_DIR / "positions.json"
TRADES_FILE = PORTFOLIO_DIR / "trades.json"
NAV_FILE = PORTFOLIO_DIR / "nav.csv"

class PaperTrader:
    """模拟盘交易类，用于追踪持仓、记录交易和计算净值。"""

    def __init__(self, initial_capital: float = 1_000_000):
        """
        初始化模拟盘交易器。

        参数:
            initial_capital: 初始资金，默认 100 万
        """
        self.initial_capital = initial_capital

        # 确保数据目录存在
        PORTFOLIO_DIR.mkdir(parents=True, exist_ok=True)

        # 加载已有数据或初始化空状态
        if POSITIONS_FILE.exists():
            with open(POSITIONS_FILE, "r", encoding="utf-8") as f:
                self.positions = json.load(f)
        else:
            self.positions = {}  # {symbol: {shares, cost_price, current_price}}

        if TRADES_FILE.exists():
            with open(TRADES_FILE, "r", encoding="utf-8") as f:
                self.trades = json.load(f)
        else:
            self.trades = []

        if NAV_FILE.exists():
            nav_df = pd.read_csv(NAV_FILE)
        else:
            # 写入 nav.csv 表头和初始净值
            nav_df = pd.DataFrame(columns=["date", "nav"])
            nav_df.to_csv(NAV_FILE, index=False)

        # 现金用 __cash__ 键存在 positions 里，方便序列化
        if "__cash__" not in self.positions:
            self.positions["__cash__"] = initial_capital

        # 加载后做状态校验，打印任何警告
        warnings = self._validate_state()
        for w in warnings:
            print(f"[PaperTrader WARNING] {w}")

        # 自一致性校验：用 current_price 推算 NAV，与 nav.csv 最后一行对比
        if not nav_df.empty:
            last_nav = float(nav_df["nav"].iloc[-1])
            expected_nav = self._get_cash() + sum(
                info["shares"] * info.get("current_price", 0)
                for sym, info in self.positions.items()
                if sym != "__cash__"
            )
            if last_nav > 0:
                diff_pct = abs(expected_nav - last_nav) / last_nav
                if diff_pct > 0.01:
                    print(
                        f"[PaperTrader WARNING] 状态不一致：持仓推算 NAV={expected_nav:,.2f}，"
                        f"csv 记录 NAV={last_nav:,.2f}，偏差={diff_pct:.2%}（可能来自上次运行的过时数据）"
                    )

    # ------------------------------------------------------------------
    # 内部辅助
    # ------------------------------------------------------------------

    def _get_cash(self) -> float:
        """获取当前现金余额。"""
        return self.positions.get("__cash__", 0.0)

    def _set_cash(self, value: float):
        """设置当前现金余额。"""
        self.positions["__cash__"] = value

    def _portfolio_value(self, prices: dict) -> float:
        """
        计算当前组合总市值（现金 + 持仓市值）。

        参数:
            prices: {symbol: price} 当前价格字典
        返回:
            总市值（浮点数）
        """
        cash = self._get_cash()
        stock_value = sum(
            info["shares"] * prices.get(sym, info["current_price"])
            for sym, info in self.positions.items()
            if sym != "__cash__"
        )
        return cash + stock_value

    def _save_positions(self):
        """将持仓数据持久化到磁盘。"""
        with open(POSITIONS_FILE, "w", encoding="utf-8") as f:
            json.dump(self.positions, f, ensure_ascii=False, indent=2)

    def _save_trades(self):
        """将交易记录持久化到磁盘。"""
        with open(TRADES_FILE, "w", encoding="utf-8") as f:
            json.dump(self.trades, f, ensure_ascii=False, indent=2)

    def _append_nav(self, trade_date: str, nav: float):
        """
        写入一条净值记录到 nav.csv，若该日期已存在则覆盖，避免重复行。

        参数:
            trade_date: 交易日期字符串，格式 YYYY-MM-DD
            nav: 当日净值
        """
        if NAV_FILE.exists():
            nav_df = pd.read_csv(NAV_FILE)
        else:
            nav_df = pd.DataFrame(columns=["date", "nav"])

        if trade_date in nav_df["date"].values:
            # 覆盖已有行，避免 NAV 重复记录
            nav_df.loc[nav_df["date"] == trade_date, "nav"] = nav
        else:
            new_row = pd.DataFrame([{"date": trade_date, "nav": nav}])
            nav_df = pd.concat([nav_df, new_row], ignore_index=True)

        nav_df.to_csv(NAV_FILE, index=False)

    def _validate_state(self) -> list:
        """
        校验持仓状态完整性，返回警告信息列表（空列表表示无异常）。

        检查项:
          - 现金余额不得为负
          - 每个持仓必须包含 shares、cost_price、current_price 三个键
        返回:
            list[str]: 警告信息列表，空列表表示状态正常
        """
        warnings = []
        cash = self._get_cash()
        if cash < 0:
            warnings.append(f"现金余额为负: {cash:,.2f}")

        required_keys = {"shares", "cost_price", "current_price"}
        for sym, info in self.positions.items():
            if sym == "__cash__":
                continue
            if not isinstance(info, dict):
                warnings.append(f"持仓 {sym} 数据格式异常（非字典）")
                continue
            missing = required_keys - info.keys()
            if missing:
                warnings.append(f"持仓 {sym} 缺少字段: {missing}")

        return warnings

    def _record_trade(self, trade_date: str, symbol: str, action: str, shares: int, price: float):
        """记录一笔交易。"""
        self.trades.append({
            "date": trade_date,
            "symbol": symbol,
            "action": action,
            "shares": int(shares),
            "price": float(price),
            "cost": float(shares * price * get_transaction_cost_rate()),
        })

    # ------------------------------------------------------------------
    # 核心接口
    # ------------------------------------------------------------------

    def rebalance(self, new_picks: list, prices: dict, date: str):
        """
        根据新的选股列表执行再平衡操作。

        等权分配资金：卖出不在新选股中的持仓，买入新选股中未持有的标的。
        扣除双边 0.3% 交易成本。

        参数:
            new_picks: 目标持仓股票代码列表
            prices: {symbol: price} 当日价格字典
            date: 交易日期字符串，格式 YYYY-MM-DD
        """
        # 记录调仓前组合价值（用于计算换手率）
        portfolio_value_before = self._portfolio_value(prices or {})
        # 记录本次调仓新增的交易笔数基准
        trades_before = len(self.trades)

        if not new_picks:
            nav = self._portfolio_value(prices or {})
            self._append_nav(date, nav)
            self._save_positions()
            self._save_trades()
            return {
                "date": date,
                "n_buys": 0,
                "n_sells": 0,
                "turnover": 0.0,
                "cash_after": self._get_cash(),
                "nav_after": nav,
            }

        current_symbols = set(
            sym for sym in self.positions if sym != "__cash__"
        )
        target_symbols = set(new_picks)

        tradable_symbols = [
            sym for sym in new_picks
            if prices.get(sym) is not None and prices.get(sym, 0) > 0
        ]
        if not tradable_symbols:
            nav = self._portfolio_value(prices)
            self._append_nav(date, nav)
            self._save_positions()
            self._save_trades()
            return {
                "date": date,
                "n_buys": 0,
                "n_sells": 0,
                "turnover": 0.0,
                "cash_after": self._get_cash(),
                "nav_after": nav,
            }

        # --- 先卖出不在目标中的持仓 ---
        sells = current_symbols - set(tradable_symbols)
        for sym in sells:
            info = self.positions[sym]
            sell_price = prices.get(sym, info["current_price"])
            shares_to_sell = int(info["shares"])
            if shares_to_sell <= 0 or sell_price <= 0:
                continue
            proceeds = shares_to_sell * sell_price * (1 - get_transaction_cost_rate())
            self._set_cash(self._get_cash() + proceeds)
            self._record_trade(date, sym, "sell", shares_to_sell, sell_price)
            del self.positions[sym]

        # --- 再把保留仓位降到目标等权以下 ---
        total_value = self._portfolio_value(prices)
        target_value_per_stock = total_value / len(tradable_symbols)

        for sym in list(current_symbols & set(tradable_symbols)):
            info = self.positions.get(sym)
            if info is None:
                continue
            price = prices.get(sym, info["current_price"])
            if price <= 0:
                continue
            current_value = info["shares"] * price
            excess_value = current_value - target_value_per_stock
            if excess_value <= price:
                continue
            shares_to_sell = min(info["shares"], math.floor(excess_value / price))
            if shares_to_sell <= 0:
                continue
            proceeds = shares_to_sell * price * (1 - get_transaction_cost_rate())
            self._set_cash(self._get_cash() + proceeds)
            info["shares"] -= shares_to_sell
            info["current_price"] = price
            self._record_trade(date, sym, "sell", shares_to_sell, price)
            if info["shares"] <= 0:
                del self.positions[sym]

        # --- 最后把所有目标仓位补到等权 ---
        for sym in tradable_symbols:
            price = prices[sym]
            if price <= 0:
                continue

            info = self.positions.get(sym)
            current_shares = int(info["shares"]) if info else 0
            current_value = current_shares * price
            gap_value = target_value_per_stock - current_value
            if gap_value <= price:
                if info is not None:
                    info["current_price"] = price
                continue

            cash = self._get_cash()
            max_affordable_shares = math.floor(cash / (price * (1 + get_transaction_cost_rate())))
            target_shares = math.floor(gap_value / price)
            shares_to_buy = min(target_shares, max_affordable_shares)
            if shares_to_buy <= 0:
                if info is not None:
                    info["current_price"] = price
                continue

            actual_cost = shares_to_buy * price * (1 + get_transaction_cost_rate())
            self._set_cash(self._get_cash() - actual_cost)

            if info is None:
                self.positions[sym] = {
                    "shares": shares_to_buy,
                    "cost_price": price,
                    "current_price": price,
                }
            else:
                total_shares = info["shares"] + shares_to_buy
                if total_shares > 0:
                    info["cost_price"] = (
                        info["cost_price"] * info["shares"] + shares_to_buy * price
                    ) / total_shares
                info["shares"] = total_shares
                info["current_price"] = price

            self._record_trade(date, sym, "buy", shares_to_buy, price)

        # --- 更新持仓的当前价格 ---
        for sym in list(self.positions.keys()):
            if sym == "__cash__":
                continue
            if sym in prices:
                self.positions[sym]["current_price"] = prices[sym]

        # --- 记录净值 ---
        nav = self._portfolio_value(prices)
        self._append_nav(date, nav)

        # --- 持久化 ---
        self._save_positions()
        self._save_trades()

        # --- 统计本次调仓摘要 ---
        new_trades = self.trades[trades_before:]
        n_buys = sum(1 for t in new_trades if t["action"] == "buy")
        n_sells = sum(1 for t in new_trades if t["action"] == "sell")
        trade_volume = sum(t["shares"] * t["price"] for t in new_trades)
        turnover = trade_volume / portfolio_value_before if portfolio_value_before > 0 else 0.0

        return {
            "date": date,
            "n_buys": n_buys,
            "n_sells": n_sells,
            "turnover": round(turnover, 4),
            "cash_after": round(self._get_cash(), 2),
            "nav_after": round(nav, 2),
        }

    def get_performance(self) -> dict:
        """
        计算模拟盘绩效指标。

        返回:
            包含以下指标的字典:
              - total_return: 总收益率
              - annualized_return: 年化收益率
              - sharpe: 夏普比率（无风险利率假设为 0）
              - max_drawdown: 最大回撤（负值）
              - n_trades: 总交易笔数
              - running_days: 运行天数
        """
        if not NAV_FILE.exists():
            return {}

        nav_df = pd.read_csv(NAV_FILE)
        if nav_df.empty:
            return {}

        nav_df["date"] = pd.to_datetime(nav_df["date"])
        nav_df = nav_df.sort_values("date").reset_index(drop=True)

        navs = nav_df["nav"].values
        running_days = (nav_df["date"].iloc[-1] - nav_df["date"].iloc[0]).days

        # 总收益率
        total_return = (navs[-1] / self.initial_capital) - 1

        # 年化收益率（实际天数）
        if running_days > 0:
            annualized_return = (1 + total_return) ** (365 / running_days) - 1
        else:
            annualized_return = 0.0

        # 夏普比率（日收益率标准差年化）
        daily_returns = pd.Series(navs).pct_change().dropna()
        if len(daily_returns) > 1 and daily_returns.std() > 0:
            sharpe = (daily_returns.mean() / daily_returns.std()) * np.sqrt(252)
        else:
            sharpe = 0.0

        # 最大回撤
        peak = np.maximum.accumulate(navs)
        drawdowns = (navs - peak) / peak
        max_drawdown = float(drawdowns.min())

        # 交易笔数
        n_trades = len(self.trades)

        return {
            "total_return": round(total_return, 4),
            "annualized_return": round(annualized_return, 4),
            "sharpe": round(sharpe, 4),
            "max_drawdown": round(max_drawdown, 4),
            "n_trades": n_trades,
            "running_days": running_days,
        }

    def get_current_positions(self) -> pd.DataFrame:
        """
        获取当前持仓的 DataFrame。

        返回:
            DataFrame，列为: symbol, shares, cost_price, current_price, pnl_pct
        """
        rows = []
        for sym, info in self.positions.items():
            if sym == "__cash__":
                continue
            pnl_pct = (info["current_price"] / info["cost_price"] - 1) if info["cost_price"] > 0 else 0.0
            rows.append({
                "symbol": sym,
                "shares": info["shares"],
                "cost_price": info["cost_price"],
                "current_price": info["current_price"],
                "pnl_pct": round(pnl_pct, 4),
            })

        if not rows:
            return pd.DataFrame(columns=["symbol", "shares", "cost_price", "current_price", "pnl_pct"])

        return pd.DataFrame(rows)


if __name__ == "__main__":
    # 最小验证：创建模拟盘并打印持仓
    trader = PaperTrader(initial_capital=1_000_000)
    print("当前持仓:")
    print(trader.get_current_positions())
    print(f"\n现金余额: {trader._get_cash():,.2f}")
    print(f"\n绩效指标: {trader.get_performance()}")
    print("✅ PaperTrader 初始化 ok")
