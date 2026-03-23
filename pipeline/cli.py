"""
量化策略管道 CLI 入口

使用方式：
  python -m pipeline.cli signal [--date YYYY-MM-DD]
  python -m pipeline.cli positions
  python -m pipeline.cli rebalance --date YYYY-MM-DD
  python -m pipeline.cli performance
  python -m pipeline.cli factor-health
  python -m pipeline.cli weekly-report [--week YYYY-Www]
  python -m pipeline.cli risk-check
"""

import argparse
import sys
import datetime


def _check_data_freshness_warning():
    """
    在 CLI 启动时检查数据新鲜度，如果数据过时则打印警告。
    使用懒加载避免依赖不可用时启动失败。
    """
    try:
        import importlib
        data_checker = importlib.import_module("pipeline.data_checker")
        result = data_checker.check_data_freshness()
        days_stale = result.get("days_stale", 0)
        status = result.get("status", "ok")
        if status in ("stale", "missing") or days_stale >= 3:
            latest = result.get("latest_date", "未知")
            missing_count = len(result.get("missing_symbols", []))
            print(f"⚠️  [数据警告] 本地数据已 {days_stale} 个交易日未更新（最新：{latest}）", file=sys.stderr)
            if missing_count:
                print(f"⚠️  [数据警告] 有 {missing_count} 只股票数据缺失", file=sys.stderr)
    except Exception:
        # 数据检查模块不可用时静默跳过
        pass


def cmd_signal(args):
    """
    运行每日信号生成管道，输出选股摘要表格。

    参数：
        args: argparse 命名空间，包含可选的 date 字段
    """
    import importlib
    daily_signal = importlib.import_module("pipeline.daily_signal")

    date = getattr(args, "date", None)
    if date is None:
        date = datetime.date.today().strftime("%Y-%m-%d")

    print(f"正在生成 {date} 的选股信号...")
    result = daily_signal.run_daily_pipeline(date)

    picks = result.get("picks", [])
    scores = result.get("scores", {})
    excluded = result.get("excluded", {})

    print(f"\n{'='*50}")
    print(f"日期：{result.get('date', date)}")
    print(f"选股数量：{len(picks)} 只")
    print(f"{'='*50}")

    if picks:
        print(f"\n{'股票代码':<12} {'综合评分':>10}")
        print("-" * 25)
        for code in picks[:30]:
            score = scores.get(code, 0.0)
            print(f"{code:<12} {score:>10.4f}")

    if excluded:
        print(f"\n过滤统计：")
        for reason, count in excluded.items():
            print(f"  - {reason}：{count} 只")

    signal_path = f"live/signals/{date}.json"
    print(f"\n✅ 信号已保存到 {signal_path}")


def cmd_positions(args):
    """
    查询并打印当前模拟盘持仓。

    参数：
        args: argparse 命名空间（无额外参数）
    """
    import importlib
    paper_trader_mod = importlib.import_module("live.paper_trader")
    PaperTrader = paper_trader_mod.PaperTrader

    trader = PaperTrader()
    positions = trader.get_current_positions()

    print(f"\n{'='*50}")
    print("当前持仓")
    print(f"{'='*50}")

    if positions is None or (hasattr(positions, "__len__") and len(positions) == 0):
        print("当前无持仓（模拟盘尚未开始调仓）")
        return

    # 支持 DataFrame 或 dict
    try:
        import pandas as pd
        if isinstance(positions, pd.DataFrame):
            print(positions.to_string(index=True))
        elif isinstance(positions, dict):
            print(f"{'股票代码':<12} {'持仓数量':>12} {'成本价':>10} {'当前价':>10}")
            print("-" * 48)
            for code, info in positions.items():
                qty = info.get("quantity", 0)
                cost = info.get("cost_price", 0)
                current = info.get("current_price", 0)
                print(f"{code:<12} {qty:>12} {cost:>10.2f} {current:>10.2f}")
        else:
            print(positions)
    except ImportError:
        print(positions)


def cmd_rebalance(args):
    """
    执行调仓：先生成信号，再调用 paper_trader 执行。

    参数：
        args: argparse 命名空间，包含必需的 date 字段
    """
    import importlib
    import pandas as pd

    date = args.date
    print(f"正在执行 {date} 调仓...")

    # 1. 生成信号
    daily_signal = importlib.import_module("pipeline.daily_signal")
    result = daily_signal.run_daily_pipeline(date)
    picks = result.get("picks", [])
    if result.get("error"):
        raise RuntimeError(result["error"])

    local_loader = importlib.import_module("utils.local_data_loader")
    load_price_wide = local_loader.load_price_wide
    price_wide = load_price_wide(picks, date, date, field="close")
    if price_wide.empty:
        raise RuntimeError(f"无法加载 {date} 的收盘价，调仓中止")
    prices = {
        symbol: float(price_wide.iloc[-1][symbol])
        for symbol in price_wide.columns
        if pd.notna(price_wide.iloc[-1][symbol])
    }

    # 2. 执行调仓
    paper_trader_mod = importlib.import_module("live.paper_trader")
    PaperTrader = paper_trader_mod.PaperTrader
    trader = PaperTrader()
    trader.rebalance(picks, prices, date)

    print(f"✅ 调仓完成：{len(picks)} 只股票，日期 {date}")


def cmd_performance(args):
    """
    查询并打印模拟盘绩效指标。

    参数：
        args: argparse 命名空间（无额外参数）
    """
    import importlib
    paper_trader_mod = importlib.import_module("live.paper_trader")
    PaperTrader = paper_trader_mod.PaperTrader

    trader = PaperTrader()
    perf = trader.get_performance()

    print(f"\n{'='*50}")
    print("模拟盘绩效")
    print(f"{'='*50}")

    if isinstance(perf, dict):
        label_map = {
            "total_return": "总收益率",
            "annualized_return": "年化收益率",
            "sharpe": "夏普比率",
            "max_drawdown": "最大回撤",
            "n_trades": "交易笔数",
            "running_days": "运行天数",
        }
        for key, val in perf.items():
            label = label_map.get(key, key)
            if isinstance(val, float):
                if key in ("total_return", "annualized_return", "max_drawdown"):
                    print(f"  {label:<12}: {val*100:+.2f}%")
                elif key in ("sharpe",):
                    print(f"  {label:<12}: {val:.4f}")
                else:
                    print(f"  {label:<12}: {val:,.2f}")
            else:
                print(f"  {label:<12}: {val}")
    else:
        print(perf)


def cmd_factor_health(args):
    """
    运行因子健康度检查并打印报告。

    参数：
        args: argparse 命名空间（无额外参数）
    """
    import importlib
    factor_monitor = importlib.import_module("pipeline.factor_monitor")

    print(f"\n{'='*50}")
    print("因子健康度报告")
    print(f"{'='*50}\n")

    report = factor_monitor.factor_health_report()

    if isinstance(report, dict):
        print(f"{'因子':<20} {'近期IC均值':>12} {'状态':>10}")
        print("-" * 45)
        for factor, metrics in report.items():
            ic_mean = metrics.get("rolling_ic", 0)
            status = metrics.get("status", "-")
            ic_display = f"{ic_mean:.4f}" if ic_mean == ic_mean else "nan"
            print(f"{factor:<20} {ic_display:>12} {status:>10}")
    elif isinstance(report, str):
        print(report)
    else:
        print(report)


def cmd_weekly_report(args):
    """
    生成并打印每周周报。

    参数：
        args: argparse 命名空间，包含可选的 week 字段（格式 YYYY-Www）
    """
    import importlib
    weekly_report_mod = importlib.import_module("pipeline.weekly_report")

    week = getattr(args, "week", None)
    report = weekly_report_mod.generate_weekly_report(week)
    print(report)


def cmd_risk_check(args):
    """
    运行风险检查并打印预警报告。

    参数：
        args: argparse 命名空间（无额外参数）
    """
    import importlib
    paper_trader_mod = importlib.import_module("live.paper_trader")
    risk_monitor_mod = importlib.import_module("live.risk_monitor")
    PaperTrader = paper_trader_mod.PaperTrader

    trader = PaperTrader()
    alerts = risk_monitor_mod.check_risk_alerts(trader)

    print(f"\n{'='*50}")
    print("风险检查报告")
    print(f"{'='*50}\n")

    if isinstance(alerts, list):
        if not alerts:
            print("✅ 当前无风险预警")
        else:
            for alert in alerts:
                level = str(alert.get("level", "info")).lower()
                msg = alert.get("msg", str(alert))
                icon = "🔴" if level == "critical" else "🟡" if level == "warning" else "ℹ️"
                print(f"{icon} [{level}] {msg}")
    elif isinstance(alerts, dict):
        for key, val in alerts.items():
            print(f"  {key}: {val}")
    elif isinstance(alerts, str):
        print(alerts)
    else:
        print(alerts)


def main():
    """
    CLI 主入口，解析参数并分发到对应子命令处理函数。
    """
    parser = argparse.ArgumentParser(
        prog="pipeline.cli",
        description="量化策略管道命令行工具"
    )
    subparsers = parser.add_subparsers(dest="command", help="子命令")

    # signal 子命令
    p_signal = subparsers.add_parser("signal", help="生成每日选股信号")
    p_signal.add_argument("--date", type=str, default=None, help="日期，格式 YYYY-MM-DD，默认今日")

    # positions 子命令
    subparsers.add_parser("positions", help="查看当前模拟盘持仓")

    # rebalance 子命令
    p_rebalance = subparsers.add_parser("rebalance", help="执行调仓操作")
    p_rebalance.add_argument("--date", type=str, required=True, help="调仓日期，格式 YYYY-MM-DD")

    # performance 子命令
    subparsers.add_parser("performance", help="查看模拟盘绩效指标")

    # factor-health 子命令
    subparsers.add_parser("factor-health", help="因子健康度检查")

    # weekly-report 子命令
    p_weekly = subparsers.add_parser("weekly-report", help="生成每周周报")
    p_weekly.add_argument("--week", type=str, default=None, help="周，格式 YYYY-Www，默认当前周")

    # risk-check 子命令
    subparsers.add_parser("risk-check", help="运行风险预警检查")

    args = parser.parse_args()

    if args.command is None:
        parser.print_help()
        sys.exit(0)

    # 启动时检查数据新鲜度
    _check_data_freshness_warning()

    # 分发到对应子命令
    dispatch = {
        "signal": cmd_signal,
        "positions": cmd_positions,
        "rebalance": cmd_rebalance,
        "performance": cmd_performance,
        "factor-health": cmd_factor_health,
        "weekly-report": cmd_weekly_report,
        "risk-check": cmd_risk_check,
    }

    handler = dispatch.get(args.command)
    if handler is None:
        print(f"未知命令：{args.command}", file=sys.stderr)
        sys.exit(1)

    try:
        handler(args)
    except Exception as e:
        print(f"❌ 执行失败：{e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
