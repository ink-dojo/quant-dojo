#!/usr/bin/env python3
"""
quant_dojo — 统一入口

用法:
    python -m quant_dojo init                  # 首次设置
    python -m quant_dojo run                   # 每日全流程
    python -m quant_dojo run --date 2026-04-03 # 指定日期
    python -m quant_dojo backtest              # 回测（默认 v7，最近2年）
    python -m quant_dojo backtest --strategy v8 --start 2024-01-01 --end 2026-03-31
    python -m quant_dojo status                # 一眼看全局
"""
import argparse
import sys
from pathlib import Path

# 确保项目根目录在 sys.path
ROOT = Path(__file__).parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def main():
    parser = argparse.ArgumentParser(
        prog="quant_dojo",
        description="quant-dojo 量化研究自动化 — 一个命令通到底",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  python -m quant_dojo init                       # 首次设置
  python -m quant_dojo run                        # 每日全流程
  python -m quant_dojo backtest                   # 快速回测
  python -m quant_dojo status                     # 系统状态
  python -m quant_dojo schedule                   # 设置定时自动运行
  python -m quant_dojo doctor                     # 诊断问题
        """,
    )

    sub = parser.add_subparsers(dest="command", help="命令")

    # ── init ──
    p_init = sub.add_parser("init", help="首次设置（配置数据目录）")
    p_init.add_argument("--data-dir", type=str, help="本地行情数据目录路径")
    p_init.add_argument("--download", action="store_true", help="自动下载 A 股日线数据")

    # ── run ──
    p_run = sub.add_parser("run", help="执行每日全流程（数据→信号→调仓→风控→报告）")
    p_run.add_argument("--date", type=str, help="交易日期 YYYY-MM-DD（默认自动检测）")
    p_run.add_argument("--strategy", type=str, default=None, help="策略名（默认从配置读取）")
    p_run.add_argument("--dry-run", action="store_true", help="空跑模式，不执行实际操作")

    # ── backtest ──
    p_bt = sub.add_parser("backtest", help="运行回测（自动生成报告）")
    p_bt.add_argument("--strategy", type=str, default="v7", help="策略名（默认 v7）")
    p_bt.add_argument("--start", type=str, help="开始日期（默认2年前）")
    p_bt.add_argument("--end", type=str, help="结束日期（默认今天）")
    p_bt.add_argument("--n-stocks", type=int, default=30, help="选股数量（默认30）")
    p_bt.add_argument("--no-report", action="store_true", help="不生成 HTML 报告")

    # ── status ──
    sub.add_parser("status", help="系统全局状态一览")

    # ── compare ──
    p_cmp = sub.add_parser("compare", help="多策略对比回测")
    p_cmp.add_argument("strategies", nargs="+", help="策略名列表 (如 v7 v8)")
    p_cmp.add_argument("--start", type=str, help="开始日期")
    p_cmp.add_argument("--end", type=str, help="结束日期")
    p_cmp.add_argument("--n-stocks", type=int, default=30, help="选股数量")

    # ── report ──
    p_rep = sub.add_parser("report", help="生成报告（周报/回测报告）")
    p_rep.add_argument("--week", type=str, help="ISO 周次 (如 2026-W13)")
    p_rep.add_argument("--backtest", action="store_true", help="重新生成最近回测的 HTML 报告")

    # ── dashboard ──
    p_dash = sub.add_parser("dashboard", help="启动可视化仪表盘")
    p_dash.add_argument("--port", type=int, default=8501, help="端口号（默认 8501）")

    # ── activate ──
    p_act = sub.add_parser("activate", help="切换 live 运行策略")
    p_act.add_argument("strategy", nargs="?", type=str, help="策略名 (v7/v8/ad_hoc)")
    p_act.add_argument("--reason", type=str, default="", help="切换原因")
    p_act.add_argument("--show", action="store_true", help="查看当前策略")

    # ── schedule ──
    p_sched = sub.add_parser("schedule", help="设置每日定时自动运行")
    p_sched.add_argument("--time", type=str, default="16:30", help="执行时间 HH:MM（默认 16:30）")
    p_sched.add_argument("--remove", action="store_true", help="移除定时任务")

    # ── doctor ──
    sub.add_parser("doctor", help="诊断系统问题")

    args = parser.parse_args()

    if args.command is None:
        parser.print_help()
        return

    dispatch = {
        "init": cmd_init,
        "run": cmd_run,
        "backtest": cmd_backtest,
        "status": cmd_status,
        "compare": cmd_compare,
        "report": cmd_report,
        "dashboard": cmd_dashboard,
        "activate": cmd_activate,
        "schedule": cmd_schedule,
        "doctor": cmd_doctor,
    }
    dispatch[args.command](args)


def cmd_init(args):
    """首次设置"""
    from quant_dojo.commands.init import run_init
    run_init(data_dir=args.data_dir, download=args.download)


def cmd_run(args):
    """每日全流程"""
    from quant_dojo.commands.run import run_daily
    run_daily(date=args.date, strategy=args.strategy, dry_run=args.dry_run)


def cmd_backtest(args):
    """运行回测"""
    from quant_dojo.commands.backtest import run_backtest_cmd
    run_backtest_cmd(
        strategy=args.strategy,
        start=args.start,
        end=args.end,
        n_stocks=args.n_stocks,
        report=not args.no_report,
    )


def cmd_status(args):
    """系统状态"""
    from quant_dojo.commands.status import show_status
    show_status()


def cmd_compare(args):
    """策略对比"""
    from quant_dojo.commands.compare import run_compare
    run_compare(
        strategies=args.strategies,
        start=args.start,
        end=args.end,
        n_stocks=args.n_stocks,
    )


def cmd_report(args):
    """生成报告"""
    from quant_dojo.commands.report import generate_report
    generate_report(week=args.week, backtest=args.backtest)


def cmd_dashboard(args):
    """启动仪表盘"""
    from quant_dojo.commands.dashboard import launch_dashboard
    launch_dashboard(port=args.port)


def cmd_activate(args):
    """策略激活"""
    from quant_dojo.commands.activate import run_activate
    run_activate(strategy=args.strategy, reason=args.reason, show=args.show)


def cmd_schedule(args):
    """定时任务"""
    from quant_dojo.commands.schedule import setup_schedule
    setup_schedule(time=args.time, remove=args.remove)


def cmd_doctor(args):
    """系统诊断"""
    from quant_dojo.commands.doctor import run_doctor
    run_doctor()


if __name__ == "__main__":
    main()
