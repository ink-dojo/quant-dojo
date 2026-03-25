"""
portfolio_service.py — 持仓服务层

封装 PaperTrader 的持仓和绩效查询，所有函数捕获异常并返回含 error 字段的 dict。
"""

from datetime import date

from dashboard.services.data_loader import load_nav_csv


def get_portfolio_summary() -> dict:
    """
    获取模拟盘当前持仓和绩效摘要。

    调用 PaperTrader().get_current_positions() 和 get_performance()，
    失败时返回含 error 字段的 dict。

    返回:
        dict，包含:
          - as_of_date: str，查询日期
          - summary: dict，净值/收益率/夏普/最大回撤
          - positions: list[dict]，当前每只持仓的明细
          - error: str（仅在失败时存在）
    """
    try:
        from live.paper_trader import PaperTrader

        trader = PaperTrader()
        positions_df = trader.get_current_positions()
        perf = trader.get_performance()
        cash = trader._get_cash()

        # 取最新净值
        nav_records = load_nav_csv()
        latest_nav = nav_records[-1]["nav"] if nav_records else cash

        summary = {
            "nav": round(latest_nav, 2),
            "cash": round(cash, 2),
            "return_pct": perf.get("total_return", 0.0),
            "annualized_return": perf.get("annualized_return", 0.0),
            "sharpe": perf.get("sharpe", 0.0),
            "max_drawdown": perf.get("max_drawdown", 0.0),
            "n_trades": perf.get("n_trades", 0),
            "running_days": perf.get("running_days", 0),
        }

        positions = positions_df.to_dict(orient="records") if not positions_df.empty else []

        return {
            "as_of_date": str(date.today()),
            "summary": summary,
            "positions": positions,
        }
    except Exception:
        return {
            "as_of_date": str(date.today()),
            "summary": {},
            "positions": [],
            "error": "Internal server error",
        }


def get_nav_history() -> list[dict]:
    """
    读取净值历史，返回日期和净值列表。

    返回:
        list[dict]，格式为 [{"date": "2026-03-20", "nav": 1050000.0}, ...]
        读取失败时返回 []
    """
    try:
        return load_nav_csv()
    except Exception:
        return []


if __name__ == "__main__":
    print("=== portfolio summary ===")
    summary = get_portfolio_summary()
    if "error" in summary:
        print(f"⚠️  error: {summary['error']}")
    else:
        print(f"持仓数: {len(summary['positions'])}")
        print(f"绩效: {summary['summary']}")

    print("\n=== nav history ===")
    nav = get_nav_history()
    print(f"共 {len(nav)} 条净值记录")

    print("\n✅ portfolio_service 检查完毕")
