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

# 投资组合数据存储目录
PORTFOLIO_DIR = Path(__file__).parent / "portfolio"
POSITIONS_FILE = PORTFOLIO_DIR / "positions.json"
TRADES_FILE = PORTFOLIO_DIR / "trades.json"
NAV_FILE = PORTFOLIO_DIR / "nav.csv"

# 交易成本（双边 0.3%，单边 0.15%）
TRANSACTION_COST_RATE = 0.003


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
            # 最新 NAV 中的现金要从 NAV 减去持仓市值推算
            # 直接从文件读取，cash 单独记录在 positions 里的 "__cash__" 键
            pass
        else:
            # 写入 nav.csv 表头和初始净值
            pd.DataFrame(columns=["date", "nav"]).to_csv(NAV_FILE, index=False)

        # 现金用 __cash__ 键存在 positions 里，方便序列化
        if "__cash__" not in self.positions:
            self.positions["__cash__"] = initial_capital

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
        追加一条净值记录到 nav.csv。

        参数:
            trade_date: 交易日期字符串，格式 YYYY-MM-DD
            nav: 当日净值
        """
        row = pd.DataFrame([{"date": trade_date, "nav": nav}])
        row.to_csv(NAV_FILE, mode="a", header=False, index=False)

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
        if not new_picks:
            return

        current_symbols = set(
            sym for sym in self.positions if sym != "__cash__"
        )
        target_symbols = set(new_picks)

        # --- 先卖出不在目标中的持仓 ---
        sells = current_symbols - target_symbols
        for sym in sells:
            info = self.positions[sym]
            sell_price = prices.get(sym, info["current_price"])
            proceeds = info["shares"] * sell_price * (1 - TRANSACTION_COST_RATE)
            self._set_cash(self._get_cash() + proceeds)

            self.trades.append({
                "date": date,
                "symbol": sym,
                "action": "sell",
                "shares": info["shares"],
                "price": sell_price,
                "cost": info["shares"] * sell_price * TRANSACTION_COST_RATE,
            })
            del self.positions[sym]

        # --- 计算每只股票的目标市值（等权） ---
        total_value = self._portfolio_value(prices)
        n_picks = len(new_picks)
        target_value_per_stock = total_value / n_picks

        # --- 买入不在当前持仓中的标的 ---
        buys = target_symbols - current_symbols
        for sym in buys:
            buy_price = prices.get(sym)
            if buy_price is None or buy_price <= 0:
                continue

            cash = self._get_cash()
            # 每只股票分配等权份额，但不超过当前现金
            alloc = min(target_value_per_stock, cash)
            if alloc <= 0:
                continue

            # 扣除交易成本后实际可买入的金额
            invest_amount = alloc / (1 + TRANSACTION_COST_RATE)
            shares = math.floor(invest_amount / buy_price)
            if shares <= 0:
                continue

            actual_cost = shares * buy_price * (1 + TRANSACTION_COST_RATE)
            self._set_cash(self._get_cash() - actual_cost)

            self.positions[sym] = {
                "shares": shares,
                "cost_price": buy_price,
                "current_price": buy_price,
            }

            self.trades.append({
                "date": date,
                "symbol": sym,
                "action": "buy",
                "shares": shares,
                "price": buy_price,
                "cost": shares * buy_price * TRANSACTION_COST_RATE,
            })

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
