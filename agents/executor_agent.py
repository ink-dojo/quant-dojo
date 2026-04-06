"""
agents/executor_agent.py — 调仓执行 Agent

职责:
  1. 从信号中获取选股名单 + 价格
  2. 调用 PaperTrader.rebalance() 执行模拟调仓
  3. 验证调仓结果（持仓数匹配、NAV 合理）
  4. 记录交易成本分析
"""

import logging
from typing import Any

logger = logging.getLogger(__name__)


class ExecutorAgent:
    """
    调仓执行 Agent：将信号转化为模拟持仓变动。
    """

    # NAV 变动幅度预警阈值
    NAV_CHANGE_WARNING = 0.05  # 单次调仓 NAV 变动 > 5%

    def run(self, ctx: Any) -> dict:
        """
        执行模拟调仓。

        参数:
            ctx: PipelineContext（需要 signal_picks, signal_date）

        返回:
            dict: 调仓摘要
        """
        from live.paper_trader import PaperTrader
        from utils.local_data_loader import load_price_wide

        picks = ctx.get("signal_picks", [])
        signal_date = ctx.get("signal_date", ctx.date)

        if not picks:
            print("  无选股信号，跳过调仓")
            ctx.log_decision("ExecutorAgent", "跳过调仓: 无选股信号")
            return {"skipped": True, "reason": "无信号"}

        if ctx.dry_run:
            print(f"  [DRY RUN] 将调仓 {len(picks)} 只股票")
            ctx.log_decision("ExecutorAgent", f"[DRY RUN] 调仓 {len(picks)} 只")
            return {"dry_run": True, "n_picks": len(picks)}

        # ── 获取最新价格 ──────────────────────────────────────
        print(f"  加载 {len(picks)} 只股票价格...")
        try:
            # 加载最近几天的 close 价格，取最新一天
            end = ctx.date
            start_y = int(end[:4])
            start = f"{start_y}-{end[5:7]}-01"

            price_wide = load_price_wide(picks, start, end, field="close")
            if price_wide.empty:
                print("  价格数据为空，无法调仓")
                return {"error": "价格数据为空"}

            # 取最新一天的价格
            prices = price_wide.iloc[-1].dropna().to_dict()
        except Exception as e:
            print(f"  价格加载失败: {e}")
            return {"error": str(e)}

        tradable_picks = [sym for sym in picks if sym in prices and prices[sym] > 0]
        if not tradable_picks:
            print("  无可交易股票（全部无价格）")
            return {"error": "无可交易价格"}

        print(f"  可交易: {len(tradable_picks)}/{len(picks)} 只")

        # ── 执行调仓 ──────────────────────────────────────────
        trader = PaperTrader()
        nav_before = trader._portfolio_value(prices)

        summary = trader.rebalance(
            new_picks=tradable_picks,
            prices=prices,
            date=signal_date,
        )

        nav_after = summary.get("nav_after", nav_before)

        # ── 调仓后验证 ───────────────────────────────────────
        warnings = []

        # NAV 变动检查
        if nav_before > 0:
            nav_change = abs(nav_after - nav_before) / nav_before
            if nav_change > self.NAV_CHANGE_WARNING:
                warnings.append(
                    f"NAV 变动 {nav_change:.2%} 超过阈值 {self.NAV_CHANGE_WARNING:.0%}"
                )

        # 持仓数检查
        positions = trader.get_current_positions()
        n_positions = len(positions)
        if n_positions > 0 and abs(n_positions - len(tradable_picks)) > 5:
            warnings.append(
                f"持仓数 {n_positions} 与目标 {len(tradable_picks)} 差异较大"
            )

        if warnings:
            for w in warnings:
                print(f"  [调仓验证] {w}")

        ctx.set("rebalance_summary", summary)
        ctx.set("nav_after", nav_after)

        ctx.log_decision(
            "ExecutorAgent",
            f"调仓完成: 买 {summary.get('n_buys', 0)} 卖 {summary.get('n_sells', 0)}",
            f"换手率 {summary.get('turnover', 0):.1%}, NAV {nav_after:,.0f}",
        )

        print(f"  调仓完成: 买 {summary.get('n_buys', 0)} 卖 {summary.get('n_sells', 0)}")
        print(f"  换手率: {summary.get('turnover', 0):.1%}")
        print(f"  NAV: {nav_after:,.2f}")

        return {
            "summary": summary,
            "nav_before": round(nav_before, 2),
            "nav_after": round(nav_after, 2),
            "warnings": warnings,
        }
