"""
broker_adapter.py — 券商适配器抽象接口 + 模拟盘实现

提供统一的下单/撤单/查询接口，将信号层与执行层解耦。
PaperAdapter 实现模拟执行，内置 A 股 T+1、涨跌停、成交量等约束。

本模块完全自包含，不依赖 quant-dojo 其他模块，避免循环导入。
"""

from __future__ import annotations

import json
import logging
import os
import uuid
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, date
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


# ====================================================================
# 数据类
# ====================================================================

@dataclass
class Fill:
    """
    成交回报。

    字段:
        order_id: 订单编号
        symbol: 股票代码（如 '600519.SH'）
        qty: 成交数量，正数=买入，负数=卖出
        price: 成交价格
        filled_at: 成交时间，ISO 格式字符串
        status: 成交状态 ("filled" | "partial" | "rejected" | "cancelled")
        note: 附加说明（如截量警告、拒绝原因等）
    """
    order_id: str
    symbol: str
    qty: int
    price: float
    filled_at: str
    status: str
    note: str = ""


@dataclass
class OrderRequest:
    """
    下单请求。

    字段:
        symbol: 股票代码
        qty: 委托数量，正数=买入，负数=卖出
        side: 方向 ("buy" | "sell")
        order_type: 订单类型 ("market" | "limit")
        limit_price: 限价单价格，市价单可不填
    """
    symbol: str
    qty: int
    side: str          # "buy" | "sell"
    order_type: str    # "market" | "limit"
    limit_price: Optional[float] = None


# ====================================================================
# 抽象基类
# ====================================================================

class BrokerAdapter(ABC):
    """
    券商适配器抽象接口。

    所有具体券商（模拟盘、实盘接口）都必须实现这些方法。
    """

    @abstractmethod
    def send_order(self, req: OrderRequest) -> str:
        """
        发送委托，返回 order_id。

        参数:
            req: 下单请求
        返回:
            str: 订单编号
        """
        ...

    @abstractmethod
    def cancel_order(self, order_id: str) -> bool:
        """
        撤单。

        参数:
            order_id: 要撤销的订单编号
        返回:
            bool: 是否成功撤单
        """
        ...

    @abstractmethod
    def get_positions(self) -> dict[str, int]:
        """
        获取当前持仓。

        返回:
            dict: {symbol: qty}，qty 为持股数量
        """
        ...

    @abstractmethod
    def get_fills(self, since: Optional[str] = None) -> list[Fill]:
        """
        获取成交回报列表。

        参数:
            since: 起始时间（ISO 格式），None 表示获取全部
        返回:
            list[Fill]: 成交回报列表
        """
        ...

    @abstractmethod
    def get_account_value(self) -> float:
        """
        获取账户总市值（含现金），单位：人民币元。

        返回:
            float: 总资产
        """
        ...


# ====================================================================
# 模拟盘实现
# ====================================================================

class PaperAdapter(BrokerAdapter):
    """
    模拟盘券商适配器。

    模拟 A 股交易执行，内置以下约束:
      - T+1：当日买入不可当日卖出
      - 涨停板：价格 >= prev_close * 1.095 时无法买入
      - 跌停板：价格 <= prev_close * 0.905 时无法卖出
      - 成交量限制：单笔不超过 20 日均量的 10%

    参数:
        initial_cash: 初始资金，默认 100 万
        prev_close_prices: {symbol: float} 前收盘价，用于涨跌停判断
        adv_20d: {symbol: float} 20 日平均成交量（股数），用于单笔上限
        state_file: 状态持久化文件路径，默认 live/portfolio/paper_fills.json
    """

    def __init__(
        self,
        initial_cash: float = 1_000_000,
        prev_close_prices: Optional[dict[str, float]] = None,
        adv_20d: Optional[dict[str, float]] = None,
        state_file: Optional[str] = None,
    ):
        self._cash: float = initial_cash
        self._initial_cash: float = initial_cash
        self._positions: dict[str, int] = {}          # symbol -> qty
        self._fills: list[Fill] = []
        self._buy_dates: dict[str, str] = {}           # symbol -> 买入日期 (YYYY-MM-DD)
        self._current_prices: dict[str, float] = {}    # symbol -> 最新价

        # 外部参考数据
        self._prev_close_prices: dict[str, float] = prev_close_prices or {}
        self._adv_20d: dict[str, float] = adv_20d or {}

        # 持久化路径
        if state_file is None:
            self._state_file = Path(__file__).parent / "portfolio" / "paper_fills.json"
        else:
            self._state_file = Path(state_file)

        # 尝试从文件恢复状态
        self._load_state()

    # ------------------------------------------------------------------
    # 价格更新
    # ------------------------------------------------------------------

    def update_prices(self, prices: dict[str, float]) -> None:
        """
        批量更新最新价格。

        参数:
            prices: {symbol: price} 字典
        """
        self._current_prices.update(prices)

    # ------------------------------------------------------------------
    # BrokerAdapter 接口实现
    # ------------------------------------------------------------------

    def send_order(self, req: OrderRequest) -> str:
        """
        发送委托并模拟执行。

        对 market 单立即按 current_price 成交。
        对 limit 单按 limit_price 成交（简化处理，不模拟排队）。

        内置 A 股合规检查:
          1. T+1 约束
          2. 涨跌停约束
          3. ADV 10% 单笔上限

        参数:
            req: 下单请求
        返回:
            str: 订单编号
        """
        order_id = uuid.uuid4().hex[:12]
        now_str = datetime.now().isoformat(timespec="seconds")
        today_str = date.today().isoformat()
        note_parts: list[str] = []

        # --- 确定成交价 ---
        if req.order_type == "limit" and req.limit_price is not None:
            exec_price = req.limit_price
        else:
            # 市价单：取 current_prices 中的价格
            exec_price = self._current_prices.get(req.symbol)
            if exec_price is None:
                # 没有价格数据，无法执行市价单
                fill = Fill(
                    order_id=order_id,
                    symbol=req.symbol,
                    qty=0,
                    price=0.0,
                    filled_at=now_str,
                    status="rejected",
                    note="无可用价格数据，无法执行市价单",
                )
                self._fills.append(fill)
                self._save_state()
                logger.warning("订单 %s 被拒: 无价格数据 (%s)", order_id, req.symbol)
                return order_id

        # --- T+1 约束检查（仅卖出） ---
        if req.side == "sell":
            buy_date = self._buy_dates.get(req.symbol)
            if buy_date == today_str:
                fill = Fill(
                    order_id=order_id,
                    symbol=req.symbol,
                    qty=0,
                    price=exec_price,
                    filled_at=now_str,
                    status="rejected",
                    note="T+1: 当日买入不可当日卖出",
                )
                self._fills.append(fill)
                self._save_state()
                logger.warning("订单 %s 被拒: T+1 约束 (%s)", order_id, req.symbol)
                return order_id

        # --- 涨跌停检查 ---
        prev_close = self._prev_close_prices.get(req.symbol)
        if prev_close is not None and prev_close > 0:
            if req.side == "buy" and exec_price >= prev_close * 1.095:
                fill = Fill(
                    order_id=order_id,
                    symbol=req.symbol,
                    qty=0,
                    price=exec_price,
                    filled_at=now_str,
                    status="rejected",
                    note=f"涨停，无法买入 (价格 {exec_price:.2f} >= 涨停价 {prev_close * 1.095:.2f})",
                )
                self._fills.append(fill)
                self._save_state()
                logger.warning("订单 %s 被拒: 涨停 (%s @ %.2f)", order_id, req.symbol, exec_price)
                return order_id

            if req.side == "sell" and exec_price <= prev_close * 0.905:
                fill = Fill(
                    order_id=order_id,
                    symbol=req.symbol,
                    qty=0,
                    price=exec_price,
                    filled_at=now_str,
                    status="rejected",
                    note=f"跌停，无法卖出 (价格 {exec_price:.2f} <= 跌停价 {prev_close * 0.905:.2f})",
                )
                self._fills.append(fill)
                self._save_state()
                logger.warning("订单 %s 被拒: 跌停 (%s @ %.2f)", order_id, req.symbol, exec_price)
                return order_id

        # --- ADV 10% 单笔上限 ---
        exec_qty = abs(req.qty)
        adv = self._adv_20d.get(req.symbol)
        if adv is not None and adv > 0:
            cap = int(adv * 0.10)
            if exec_qty > cap:
                note_parts.append(
                    f"ADV 截量: 原始 {exec_qty} 股 -> 截至 {cap} 股 "
                    f"(20 日均量 {adv:.0f} 的 10%)"
                )
                exec_qty = cap

        # --- 持仓/现金校验 ---
        if req.side == "sell":
            current_holding = self._positions.get(req.symbol, 0)
            if current_holding <= 0:
                fill = Fill(
                    order_id=order_id,
                    symbol=req.symbol,
                    qty=0,
                    price=exec_price,
                    filled_at=now_str,
                    status="rejected",
                    note="无持仓可卖",
                )
                self._fills.append(fill)
                self._save_state()
                return order_id
            # 卖出数量不超过持仓
            exec_qty = min(exec_qty, current_holding)
            # 更新持仓
            self._positions[req.symbol] = current_holding - exec_qty
            if self._positions[req.symbol] == 0:
                del self._positions[req.symbol]
            # 回收现金
            self._cash += exec_qty * exec_price
            signed_qty = -exec_qty  # 卖出用负数

        else:  # buy
            total_cost = exec_qty * exec_price
            if total_cost > self._cash:
                # 现金不足，截量到可买数量
                affordable = int(self._cash / exec_price) if exec_price > 0 else 0
                if affordable <= 0:
                    fill = Fill(
                        order_id=order_id,
                        symbol=req.symbol,
                        qty=0,
                        price=exec_price,
                        filled_at=now_str,
                        status="rejected",
                        note=f"现金不足 (需要 {total_cost:,.2f}，可用 {self._cash:,.2f})",
                    )
                    self._fills.append(fill)
                    self._save_state()
                    return order_id
                note_parts.append(
                    f"现金不足截量: {exec_qty} -> {affordable} 股"
                )
                exec_qty = affordable
                total_cost = exec_qty * exec_price

            # 扣减现金、增加持仓
            self._cash -= total_cost
            self._positions[req.symbol] = self._positions.get(req.symbol, 0) + exec_qty
            # 记录买入日期（T+1 用）
            self._buy_dates[req.symbol] = today_str
            signed_qty = exec_qty  # 买入用正数

        # --- 生成成交回报 ---
        status = "filled" if exec_qty == abs(req.qty) else "partial"
        fill = Fill(
            order_id=order_id,
            symbol=req.symbol,
            qty=signed_qty,
            price=exec_price,
            filled_at=now_str,
            status=status,
            note="; ".join(note_parts) if note_parts else "",
        )
        self._fills.append(fill)
        self._save_state()

        logger.info(
            "订单 %s 成交: %s %s %d 股 @ %.2f | 状态=%s",
            order_id, req.side, req.symbol, exec_qty, exec_price, status,
        )
        return order_id

    def cancel_order(self, order_id: str) -> bool:
        """
        撤单。模拟盘中订单立即成交，撤单总是返回 False。

        参数:
            order_id: 订单编号
        返回:
            bool: 永远返回 False（模拟盘无法撤单，因为订单已即时成交）
        """
        # 模拟盘下单即成交，无法撤销
        logger.info("模拟盘: 订单 %s 已即时成交，无法撤单", order_id)
        return False

    def get_positions(self) -> dict[str, int]:
        """
        获取当前持仓。

        返回:
            dict: {symbol: qty}
        """
        return dict(self._positions)

    def get_fills(self, since: Optional[str] = None) -> list[Fill]:
        """
        获取成交回报。

        参数:
            since: 起始时间（ISO 格式），None 返回全部
        返回:
            list[Fill]: 成交回报列表
        """
        if since is None:
            return list(self._fills)
        return [f for f in self._fills if f.filled_at >= since]

    def get_account_value(self) -> float:
        """
        获取账户总资产（现金 + 持仓市值），单位：人民币元。

        持仓市值按 _current_prices 中的最新价计算；
        若某个持仓无最新价，该持仓市值按 0 计算。

        返回:
            float: 总资产
        """
        stock_value = sum(
            qty * self._current_prices.get(symbol, 0.0)
            for symbol, qty in self._positions.items()
        )
        return self._cash + stock_value

    # ------------------------------------------------------------------
    # 状态持久化
    # ------------------------------------------------------------------

    def _save_state(self) -> None:
        """将持仓和成交记录持久化到 JSON 文件。"""
        try:
            self._state_file.parent.mkdir(parents=True, exist_ok=True)
            state = {
                "cash": self._cash,
                "initial_cash": self._initial_cash,
                "positions": self._positions,
                "buy_dates": self._buy_dates,
                "fills": [
                    {
                        "order_id": f.order_id,
                        "symbol": f.symbol,
                        "qty": f.qty,
                        "price": f.price,
                        "filled_at": f.filled_at,
                        "status": f.status,
                        "note": f.note,
                    }
                    for f in self._fills
                ],
            }
            with open(self._state_file, "w", encoding="utf-8") as fp:
                json.dump(state, fp, ensure_ascii=False, indent=2)
        except Exception as exc:
            logger.error("状态持久化失败: %s", exc)

    def _load_state(self) -> None:
        """从 JSON 文件恢复状态。文件不存在则跳过。"""
        if not self._state_file.exists():
            return
        try:
            with open(self._state_file, "r", encoding="utf-8") as fp:
                state = json.load(fp)
            self._cash = state.get("cash", self._cash)
            self._initial_cash = state.get("initial_cash", self._initial_cash)
            self._positions = state.get("positions", {})
            self._buy_dates = state.get("buy_dates", {})
            self._fills = [
                Fill(
                    order_id=f["order_id"],
                    symbol=f["symbol"],
                    qty=f["qty"],
                    price=f["price"],
                    filled_at=f["filled_at"],
                    status=f["status"],
                    note=f.get("note", ""),
                )
                for f in state.get("fills", [])
            ]
            logger.info("已从 %s 恢复状态: 现金=%.2f, 持仓=%d 只", self._state_file, self._cash, len(self._positions))
        except Exception as exc:
            logger.warning("状态恢复失败，使用初始状态: %s", exc)


# ====================================================================
# 工厂函数
# ====================================================================

def make_paper_adapter(
    initial_cash: float = 1_000_000,
    prev_close_prices: Optional[dict] = None,
    adv_20d: Optional[dict] = None,
    state_file: Optional[str] = None,
) -> PaperAdapter:
    """
    工厂函数：创建配置好的模拟券商适配器。

    参数:
        initial_cash: 初始资金，默认 100 万
        prev_close_prices: {symbol: float} 前收盘价，用于涨跌停判断
        adv_20d: {symbol: float} 20 日均量（股数），用于单笔上限
        state_file: 持久化文件路径，None 使用默认路径
    返回:
        PaperAdapter: 配置好的模拟盘适配器实例
    """
    return PaperAdapter(
        initial_cash=initial_cash,
        prev_close_prices=prev_close_prices or {},
        adv_20d=adv_20d or {},
        state_file=state_file,
    )


# ====================================================================
# 最小验证
# ====================================================================

if __name__ == "__main__":
    import tempfile

    print("=" * 60)
    print("模拟盘适配器验证")
    print("=" * 60)

    # 使用临时文件避免污染 live/portfolio/
    with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as tmp:
        tmp_path = tmp.name

    try:
        adapter = make_paper_adapter(
            initial_cash=1_000_000,
            prev_close_prices={"600519.SH": 1800.0},
            adv_20d={"600519.SH": 50000.0},
            state_file=tmp_path,
        )

        # 更新价格
        adapter.update_prices({"600519.SH": 1850.0})

        print(f"\n初始资金: {adapter._cash:,.2f}")
        print(f"账户总值: {adapter.get_account_value():,.2f}")

        # --- 测试 1: 买入 ---
        print("\n--- 测试 1: 买入 600519.SH 100 股 ---")
        buy_req = OrderRequest(
            symbol="600519.SH",
            qty=100,
            side="buy",
            order_type="market",
        )
        buy_id = adapter.send_order(buy_req)
        buy_fill = [f for f in adapter.get_fills() if f.order_id == buy_id][0]
        print(f"订单号: {buy_id}")
        print(f"状态: {buy_fill.status}")
        print(f"成交: {buy_fill.qty} 股 @ {buy_fill.price:.2f}")
        print(f"剩余现金: {adapter._cash:,.2f}")
        print(f"持仓: {adapter.get_positions()}")

        # --- 测试 2: 当日卖出（应被 T+1 拒绝） ---
        print("\n--- 测试 2: 当日卖出（T+1 应拒绝） ---")
        sell_req = OrderRequest(
            symbol="600519.SH",
            qty=50,
            side="sell",
            order_type="market",
        )
        sell_id = adapter.send_order(sell_req)
        sell_fill = [f for f in adapter.get_fills() if f.order_id == sell_id][0]
        print(f"订单号: {sell_id}")
        print(f"状态: {sell_fill.status}")
        print(f"拒绝原因: {sell_fill.note}")
        assert sell_fill.status == "rejected", "T+1 检查应拒绝当日卖出"
        assert "T+1" in sell_fill.note, "拒绝原因应包含 T+1"

        # --- 测试 3: 验证持仓未变 ---
        positions = adapter.get_positions()
        print(f"\n持仓确认（应不变）: {positions}")
        assert positions.get("600519.SH") == 100, f"持仓应为 100 股，实际 {positions.get('600519.SH')}"

        # --- 测试 4: 涨停拒绝 ---
        print("\n--- 测试 3: 涨停买入测试 ---")
        adapter.update_prices({"600519.SH": 1980.0})  # > 1800 * 1.095 = 1971
        limit_up_req = OrderRequest(
            symbol="600519.SH",
            qty=10,
            side="buy",
            order_type="market",
        )
        limit_up_id = adapter.send_order(limit_up_req)
        limit_up_fill = [f for f in adapter.get_fills() if f.order_id == limit_up_id][0]
        print(f"状态: {limit_up_fill.status}")
        print(f"原因: {limit_up_fill.note}")
        assert limit_up_fill.status == "rejected", "涨停应拒绝买入"

        # --- 测试 5: 账户总值 ---
        print(f"\n账户总值: {adapter.get_account_value():,.2f}")

        print("\n" + "=" * 60)
        print("所有测试通过")
        print("=" * 60)

    finally:
        # 清理临时文件
        if os.path.exists(tmp_path):
            os.unlink(tmp_path)
