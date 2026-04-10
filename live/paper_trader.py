"""
paper_trader.py — 模拟盘持仓追踪

记录模拟交易的持仓、交易记录和净值曲线，不涉及真实资金。
数据持久化到 live/portfolio/ 目录下的 JSON/CSV 文件。
"""

import json
import logging
import math
import os
import threading
from datetime import datetime, date
from pathlib import Path

import numpy as np
import pandas as pd

from utils.runtime_config import get_transaction_cost_rate

_REBALANCE_LOCK = threading.Lock()

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
        self._log = logging.getLogger(__name__)

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

        has_positions = POSITIONS_FILE.exists()
        has_nav = NAV_FILE.exists()

        if has_positions and not has_nav:
            # 持仓在但净值丢失 — 从持仓重建 nav.csv
            nav_df = self._reconstruct_nav_from_positions()
            self._log.info("nav.csv 缺失，已从 positions.json 重建")
        elif not has_positions and has_nav:
            # 净值在但持仓丢失 — 从净值重建空持仓（只恢复现金 = 最后 NAV）
            nav_df = pd.read_csv(NAV_FILE)
            if not nav_df.empty:
                last_nav = float(nav_df["nav"].iloc[-1])
                self.positions = {"__cash__": last_nav}
                self._save_positions()
                self._log.info("positions.json 缺失，已从 nav.csv 末行重建（现金=%,.2f）", last_nav)
            else:
                nav_df = pd.DataFrame(columns=["date", "nav"])
        elif has_nav:
            nav_df = pd.read_csv(NAV_FILE)
        else:
            # 两者都不存在 — 全新启动
            nav_df = pd.DataFrame(columns=["date", "nav"])
            nav_df.to_csv(NAV_FILE, index=False)

        # 现金用 __cash__ 键存在 positions 里，方便序列化
        if "__cash__" not in self.positions:
            self.positions["__cash__"] = initial_capital

        # 加载后做状态校验，打印任何警告
        warnings = self._validate_state()
        for w in warnings:
            self._log.info("[PaperTrader WARNING] %s", w)

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
                    self._log.info(
                        "状态不一致：持仓推算 NAV=%,.2f，csv 记录 NAV=%,.2f，偏差=%.2f%%（可能来自上次运行的过时数据）",
                        expected_nav, last_nav, diff_pct * 100,
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
            # dtype 强制 float，防止全整数列被推断为 int64 导致后续赋值报错
            nav_df = pd.read_csv(NAV_FILE, dtype={"nav": float})
        else:
            nav_df = pd.DataFrame(columns=["date", "nav"])

        if trade_date in nav_df["date"].values:
            # 覆盖已有行，避免 NAV 重复记录
            old_nav = float(nav_df.loc[nav_df["date"] == trade_date, "nav"].iloc[0])
            if abs(old_nav - nav) > 0.01:
                print(f"[PaperTrader] NAV 覆盖: {trade_date} {old_nav:,.2f} -> {nav:,.2f}")
            nav_df.loc[nav_df["date"] == trade_date, "nav"] = nav
        else:
            new_row = pd.DataFrame([{"date": trade_date, "nav": nav}])
            nav_df = pd.concat([nav_df, new_row], ignore_index=True)

        # 按日期排序，避免乱序写入导致下游读取最后一行 != 最新日期
        nav_df = nav_df.sort_values("date").reset_index(drop=True)
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

    def _reconstruct_nav_from_positions(self) -> pd.DataFrame:
        """从 positions.json 重建 nav.csv。日期取最后交易记录的日期，若无交易记录则取今天。"""
        nav_value = self._get_cash() + sum(
            info["shares"] * info.get("current_price", 0)
            for sym, info in self.positions.items()
            if sym != "__cash__"
        )
        # 优先用最后一笔交易的日期，避免持仓是 3 天前但 NAV 标今天
        if self.trades:
            last_trade_date = max(t.get("date", "") for t in self.trades)
            nav_date = last_trade_date if last_trade_date else date.today().isoformat()
        else:
            nav_date = date.today().isoformat()
        nav_df = pd.DataFrame([{"date": nav_date, "nav": nav_value}])
        nav_df.to_csv(NAV_FILE, index=False)
        print(f"[PaperTrader] nav.csv 重建: date={nav_date}, nav={nav_value:,.2f}")
        return nav_df

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

        等权分配资金：先卖出不在新选股中的持仓及超额部分，再买入新选股至等权目标。
        扣除双边 0.3% 交易成本。若当日已执行过调仓，跳过重复执行并返回已有摘要。

        参数:
            new_picks: 目标持仓股票代码列表
            prices: {symbol: price} 当日价格字典
            date: 交易日期字符串，格式 YYYY-MM-DD
        返回:
            dict: 调仓摘要，含 date/n_buys/n_sells/turnover/cash_after/nav_after
        """
        with _REBALANCE_LOCK:
            return self._rebalance_locked(new_picks, prices, date)

    def _rebalance_locked(self, new_picks: list, prices: dict, date: str) -> dict:
        """rebalance() 的实际实现，调用方必须持有 _REBALANCE_LOCK。"""
        # --- 同日防重 ---
        existing_today = [t for t in self.trades if t.get("date") == date]
        if existing_today:
            print(f"⚠ 当日已执行过调仓 ({date})，跳过重复执行")
            # 用当日最新价格 mark-to-market 持仓，避免 positions.json 与 nav.csv 不一致
            for sym in list(self.positions.keys()):
                if sym == "__cash__":
                    continue
                if sym in prices and prices[sym]:
                    self.positions[sym]["current_price"] = prices[sym]

            nav = self._portfolio_value(prices or {})
            n_buys = sum(1 for t in existing_today if t["action"] == "buy")
            n_sells = sum(1 for t in existing_today if t["action"] == "sell")
            # 计算已执行调仓的真实换手率
            trade_volume = sum(t["shares"] * t["price"] for t in existing_today)
            actual_turnover = trade_volume / nav if nav > 0 else 0.0

            # 持久化 mark-to-market 后的 NAV/positions（覆盖当日 NAV 行）
            self._append_nav(date, nav)
            self._save_positions()

            return {
                "date": date,
                "n_buys": n_buys,
                "n_sells": n_sells,
                "turnover": round(actual_turnover, 4),
                "cash_after": round(self._get_cash(), 2),
                "nav_after": round(nav, 2),
            }

        # --- 前置状态快照 ---
        portfolio_value_before = self._portfolio_value(prices or {})
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

        # --- 计算 tradable symbol 集合 ---
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

        total_value = self._portfolio_value(prices)
        target_value_per_stock = total_value / len(tradable_symbols)

        # --- 卖出阶段 ---
        self._sell_phase(tradable_symbols, prices, target_value_per_stock, date)

        # --- 买入阶段 ---
        skipped_symbols = self._buy_phase(tradable_symbols, prices, target_value_per_stock, date)

        if skipped_symbols:
            print(f"[PaperTrader] 现金不足，跳过买入: {skipped_symbols}")

        # --- 现金保护断言 ---
        assert self._get_cash() >= 0, (
            f"调仓后现金为负 ({self._get_cash():,.2f})，逻辑异常"
        )

        # --- 更新持仓的当前价格 ---
        for sym in list(self.positions.keys()):
            if sym == "__cash__":
                continue
            if sym in prices:
                self.positions[sym]["current_price"] = prices[sym]

        # --- 记录净值并持久化 ---
        nav = self._portfolio_value(prices)
        self._append_nav(date, nav)
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

    def _sell_phase(self, tradable_symbols: list, prices: dict, target_value_per_stock: float, date: str):
        """
        卖出阶段：清仓不在目标中的持仓，并将保留持仓降至等权目标以下。

        参数:
            tradable_symbols: 当日可交易的目标股票列表
            prices: {symbol: price} 当日价格字典
            target_value_per_stock: 每个仓位的目标市值
            date: 交易日期字符串
        """
        tradable_set = set(tradable_symbols)
        current_symbols = {sym for sym in self.positions if sym != "__cash__"}

        # 子阶段 1：清仓不在目标中的持仓
        for sym in current_symbols - tradable_set:
            info = self.positions[sym]
            sell_price = prices.get(sym, info["current_price"])
            shares_to_sell = int(info["shares"])
            if shares_to_sell <= 0 or sell_price <= 0:
                continue
            proceeds = shares_to_sell * sell_price * (1 - get_transaction_cost_rate())
            self._set_cash(self._get_cash() + proceeds)
            self._record_trade(date, sym, "sell", shares_to_sell, sell_price)
            del self.positions[sym]

        # 子阶段 2：把保留仓位降到等权目标以下
        for sym in list(current_symbols & tradable_set):
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

    def _buy_phase(self, tradable_symbols: list, prices: dict, target_value_per_stock: float, date: str) -> list:
        """
        买入阶段：把目标持仓补到等权目标（现金不足时跳过部分标的）。

        参数:
            tradable_symbols: 当日可交易的目标股票列表
            prices: {symbol: price} 当日价格字典
            target_value_per_stock: 每个仓位的目标市值
            date: 交易日期字符串

        返回:
            list: 因现金不足而跳过的股票代码列表
        """
        skipped_symbols = []
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
            if cash <= 0:
                skipped_symbols.append(sym)
                continue

            max_affordable_shares = math.floor(cash / (price * (1 + get_transaction_cost_rate())))
            target_shares = math.floor(gap_value / price)
            shares_to_buy = min(target_shares, max_affordable_shares)
            if shares_to_buy <= 0:
                skipped_symbols.append(sym)
                if info is not None:
                    info["current_price"] = price
                continue

            actual_cost = shares_to_buy * price * (1 + get_transaction_cost_rate())
            if self._get_cash() - actual_cost < 0:
                skipped_symbols.append(sym)
                if info is not None:
                    info["current_price"] = price
                continue

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

        return skipped_symbols

    def record_nav(self, trade_date: str = None, prices: dict = None):
        """
        计算当前组合 NAV 并追加到 nav.csv。

        用于非调仓场景（如 signal run），记录当日净值快照。
        若该日期已有记录则覆盖（与 _append_nav 行为一致）。

        参数:
            trade_date: 日期字符串 YYYY-MM-DD，默认今天
            prices: 可选的最新价格字典 {symbol: price}，用于 mark-to-market
        """
        if trade_date is None:
            trade_date = date.today().isoformat()

        # 用最新价格更新持仓市值（如果提供了 prices）
        if prices:
            for sym in list(self.positions.keys()):
                if sym == "__cash__":
                    continue
                if sym in prices and prices[sym]:
                    self.positions[sym]["current_price"] = prices[sym]

        nav = self._portfolio_value(prices or {})
        self._append_nav(trade_date, nav)
        self._save_positions()
        return {"date": trade_date, "nav": round(nav, 2)}

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

        # Calmar 比率：年化收益 / 最大回撤绝对值
        calmar_ratio = round(annualized_return / abs(max_drawdown), 4) if max_drawdown != 0 else None

        return {
            "total_return": round(total_return, 4),
            "annualized_return": round(annualized_return, 4),
            "sharpe": round(sharpe, 4),
            "max_drawdown": round(max_drawdown, 4),
            "calmar_ratio": calmar_ratio,
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


    def get_position_attribution(self) -> pd.DataFrame:
        """
        计算持仓级别的盈亏归因。

        返回:
            DataFrame with columns:
              - symbol: 股票代码
              - shares: 持股数
              - cost_price: 成本价
              - current_price: 现价
              - market_value: 市值
              - pnl: 绝对盈亏（元）
              - pnl_pct: 盈亏百分比
              - weight: 仓位占比
              - contribution: 对组合收益的贡献
        """
        positions_df = self.get_current_positions()
        if positions_df.empty:
            return pd.DataFrame(columns=[
                "symbol", "shares", "cost_price", "current_price",
                "market_value", "pnl", "pnl_pct", "weight", "contribution",
            ])

        # 计算市值和绝对盈亏
        positions_df["market_value"] = positions_df["shares"] * positions_df["current_price"]
        positions_df["cost_value"] = positions_df["shares"] * positions_df["cost_price"]
        positions_df["pnl"] = positions_df["market_value"] - positions_df["cost_value"]

        # 组合总市值
        total_mv = positions_df["market_value"].sum()
        total_cost = positions_df["cost_value"].sum()

        # 仓位权重
        positions_df["weight"] = (
            positions_df["market_value"] / total_mv if total_mv > 0
            else 0.0
        )

        # 对组合收益的贡献 = weight * pnl_pct
        positions_df["contribution"] = positions_df["weight"] * positions_df["pnl_pct"]

        # 排序：按贡献降序
        positions_df = positions_df.sort_values("contribution", ascending=False)

        # 清理列
        result = positions_df[[
            "symbol", "shares", "cost_price", "current_price",
            "market_value", "pnl", "pnl_pct", "weight", "contribution",
        ]].copy()

        # 四舍五入
        for col in ["market_value", "pnl"]:
            result[col] = result[col].round(2)
        for col in ["pnl_pct", "weight", "contribution"]:
            result[col] = result[col].round(6)

        return result.reset_index(drop=True)


    def get_performance_vs_benchmark(self, benchmark_ret: pd.Series = None) -> dict:
        """
        计算策略相对基准的超额收益指标。

        参数:
            benchmark_ret: 基准日收益率 Series（如沪深300），index 为 DatetimeIndex。
                           None 时尝试从本地数据自动加载 sh000300。

        返回:
            包含以下键的字典:
              - excess_total_return: 累计超额收益
              - information_ratio: IR = 年化超额收益均值 / 跟踪误差
              - tracking_error: 跟踪误差（年化，基于日收益率）
              - beta: 策略对基准的 beta
              - alpha_annualized: Jensen's alpha（年化）
              - benchmark_total_return: 基准累计收益
        """
        if not NAV_FILE.exists():
            return {}

        nav_df = pd.read_csv(NAV_FILE)
        if nav_df.empty or len(nav_df) < 2:
            return {}

        nav_df["date"] = pd.to_datetime(nav_df["date"])
        nav_df = nav_df.sort_values("date").reset_index(drop=True)

        # 策略日收益率
        strategy_ret = nav_df.set_index("date")["nav"].pct_change().dropna()

        # 加载基准收益率
        if benchmark_ret is None:
            try:
                from utils.data_loader import get_index_history
                start = strategy_ret.index[0].strftime("%Y-%m-%d")
                end = strategy_ret.index[-1].strftime("%Y-%m-%d")
                bm_df = get_index_history("sh000300", start=start, end=end)
                benchmark_ret = bm_df["close"].pct_change().dropna()
                benchmark_ret.index = pd.to_datetime(benchmark_ret.index)
            except Exception as exc:
                self._log.warning("自动加载 sh000300 失败，无法计算 benchmark 指标: %s", exc)
                return {}

        # 对齐日期 index
        common_idx = strategy_ret.index.intersection(benchmark_ret.index)
        if len(common_idx) < 2:
            self._log.warning("策略与基准的重叠日期不足 2 个交易日，无法计算指标")
            return {}

        s_ret = strategy_ret.loc[common_idx]
        b_ret = benchmark_ret.loc[common_idx]

        # 累计收益
        strategy_total = (1 + s_ret).prod() - 1
        benchmark_total = (1 + b_ret).prod() - 1
        excess_total = strategy_total - benchmark_total

        # 超额日收益
        excess = s_ret - b_ret

        # 年化超额收益 / 跟踪误差 / IR
        tracking_error = float(excess.std() * np.sqrt(252))
        ann_excess = float(excess.mean() * 252)
        ir = ann_excess / tracking_error if tracking_error > 0 else 0.0

        # beta = cov(strategy, benchmark) / var(benchmark)
        cov_matrix = np.cov(s_ret.values, b_ret.values)
        beta = cov_matrix[0, 1] / cov_matrix[1, 1] if cov_matrix[1, 1] > 0 else 0.0

        # 年化收益（实际天数）
        n_days = (common_idx[-1] - common_idx[0]).days
        if n_days > 0:
            ann_strategy = (1 + strategy_total) ** (365 / n_days) - 1
            ann_benchmark = (1 + benchmark_total) ** (365 / n_days) - 1
        else:
            ann_strategy = 0.0
            ann_benchmark = 0.0

        # Jensen's alpha（年化）
        alpha_annualized = ann_strategy - beta * ann_benchmark

        return {
            "excess_total_return": round(float(excess_total), 4),
            "information_ratio": round(ir, 4),
            "tracking_error": round(tracking_error, 4),
            "beta": round(float(beta), 4),
            "alpha_annualized": round(float(alpha_annualized), 4),
            "benchmark_total_return": round(float(benchmark_total), 4),
        }


if __name__ == "__main__":
    # 最小验证：创建模拟盘并打印持仓
    trader = PaperTrader(initial_capital=1_000_000)
    print("当前持仓:")
    print(trader.get_current_positions())
    print(f"\n现金余额: {trader._get_cash():,.2f}")
    perf = trader.get_performance()
    print(f"\n绩效指标: {perf}")
    calmar = perf.get("calmar_ratio")
    if calmar is not None:
        print(f"  Calmar比率: {calmar:.2f}（年化收益/最大回撤）")
    print("✅ PaperTrader 初始化 ok")
