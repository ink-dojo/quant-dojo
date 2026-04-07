#!/usr/bin/env python3
"""
quant_dojo — 统一入口

新手入门（一个命令搞定一切）:
    python -m quant_dojo quickstart            # 自动: 初始化→下载→回测→激活→定时

日常使用:
    python -m quant_dojo run                   # 每日全流程
    python -m quant_dojo status                # 一眼看全局
    python -m quant_dojo backtest              # 回测（默认 v7，最近2年）

进阶:
    python -m quant_dojo compare v7 v8         # 策略对比
    python -m quant_dojo activate v8           # 切换策略
    python -m quant_dojo dashboard             # 可视化仪表盘
"""
import argparse
import sys
from pathlib import Path

# 确保项目根目录在 sys.path
ROOT = Path(__file__).parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def main():
    from quant_dojo import __version__

    parser = argparse.ArgumentParser(
        prog="quant_dojo",
        description="quant-dojo 量化研究自动化 — 一个命令通到底",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
新手入门:
  python -m quant_dojo quickstart                 # 一键完成所有设置

分步操作:
  python -m quant_dojo init --download            # 初始化 + 下载数据
  python -m quant_dojo backtest                   # 回测验证
  python -m quant_dojo activate v7                # 激活策略
  python -m quant_dojo run                        # 每日全流程
  python -m quant_dojo schedule                   # 设置定时自动运行

日常使用:
  python -m quant_dojo status                     # 系统状态
  python -m quant_dojo compare v7 v8              # 策略对比
  python -m quant_dojo dashboard                  # 可视化仪表盘
  python -m quant_dojo doctor                     # 诊断问题
        """,
    )
    parser.add_argument("--version", action="version", version=f"quant-dojo {__version__}")

    sub = parser.add_subparsers(dest="command", help="命令")

    # ── init ──
    p_init = sub.add_parser("init", help="首次设置（配置数据目录）")
    p_init.add_argument("--data-dir", type=str, help="本地行情数据目录路径")
    p_init.add_argument("--download", action="store_true", help="自动下载 A 股日线数据")

    # ── quickstart ──
    p_qs = sub.add_parser("quickstart", help="零配置一键启动（init→数据→回测→激活→定时）")
    p_qs.add_argument("--data-dir", type=str, help="本地行情数据目录路径")
    p_qs.add_argument("--skip-download", action="store_true", help="跳过数据下载")

    # ── update ──
    p_upd = sub.add_parser("update", help="增量更新本地行情数据")
    p_upd.add_argument("--dry-run", action="store_true", help="空跑模式，仅查看待更新范围")
    p_upd.add_argument("--full", action="store_true", help="全量重新下载")

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
    p_cmp.add_argument("strategies", nargs="*", help="策略名列表 (如 v7 v8)，不指定则对比全部")
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

    # ── signals ──
    p_sig = sub.add_parser("signals", help="查看选股信号历史")
    p_sig.add_argument("-n", type=int, default=5, help="显示天数（默认 5）")
    p_sig.add_argument("--date", type=str, help="查看指定日期的信号")

    # ── logs ──
    p_logs = sub.add_parser("logs", help="查看最近运行记录")
    p_logs.add_argument("-n", type=int, default=10, help="显示条数（默认 10）")
    p_logs.add_argument("--detail", action="store_true", help="显示步骤详情")

    # ── doctor ──
    sub.add_parser("doctor", help="诊断系统问题")

    args = parser.parse_args()

    if args.command is None:
        parser.print_help()
        return

    dispatch = {
        "init": cmd_init,
        "quickstart": cmd_quickstart,
        "update": cmd_update,
        "run": cmd_run,
        "backtest": cmd_backtest,
        "status": cmd_status,
        "compare": cmd_compare,
        "report": cmd_report,
        "dashboard": cmd_dashboard,
        "activate": cmd_activate,
        "schedule": cmd_schedule,
        "signals": cmd_signals,
        "logs": cmd_logs,
        "doctor": cmd_doctor,
    }
    dispatch[args.command](args)


def cmd_init(args):
    """首次设置"""
    from quant_dojo.commands.init import run_init
    run_init(data_dir=args.data_dir, download=args.download)


def cmd_quickstart(args):
    """零配置一键启动"""
    from quant_dojo.commands.quickstart import run_quickstart
    run_quickstart(data_dir=args.data_dir, skip_download=args.skip_download)


def cmd_update(args):
    """数据更新"""
    from quant_dojo.commands.update import run_update
    run_update(dry_run=args.dry_run, full=args.full)


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
    strategies = args.strategies
    if not strategies:
        # 无参数 → 对比所有已知策略
        from pipeline.active_strategy import VALID_STRATEGIES
        strategies = sorted(VALID_STRATEGIES)
    run_compare(
        strategies=strategies,
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


def cmd_signals(args):
    """查看信号历史"""
    from quant_dojo.commands.signals import show_signals
    show_signals(n=args.n, date=args.date)


def cmd_logs(args):
    """查看运行记录"""
    from quant_dojo.commands.logs import show_logs
    show_logs(n=args.n, detail=args.detail)


def cmd_doctor(args):
    """系统诊断"""
    from quant_dojo.commands.doctor import run_doctor
    run_doctor()


if __name__ == "__main__":
    main()
