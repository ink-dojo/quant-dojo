#!/usr/bin/env python3
"""
scripts/run_backtest.py — 标准化回测 CLI 入口

一行命令运行完整回测:
    python scripts/run_backtest.py --strategy v7 --start 2024-01-01 --end 2026-03-31
    python scripts/run_backtest.py --strategy v8 --start 2025-01-01 --end 2026-03-31 --n-stocks 50
    python scripts/run_backtest.py --strategy v7 --start 2024-01-01 --end 2026-03-31 --report

选项:
    --strategy   策略名 (v7/v8/ad_hoc)，默认 v7
    --start      回测开始日期 YYYY-MM-DD
    --end        回测结束日期 YYYY-MM-DD
    --n-stocks   每期选股数量，默认 30
    --commission  单边手续费率，默认 0.0003
    --no-neutralize  关闭行业中性化
    --report     生成 HTML 报告
    --compare    与指定 run_id 对比
"""
import argparse
import sys
from pathlib import Path

# 确保项目根目录在 sys.path 中
ROOT = Path(__file__).parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def main():
    parser = argparse.ArgumentParser(
        description="标准化回测 — 一行命令运行完整回测",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  %(prog)s --strategy v7 --start 2024-01-01 --end 2026-03-31
  %(prog)s --strategy v8 --start 2025-01-01 --end 2026-03-31 --n-stocks 50
  %(prog)s --strategy v7 --start 2024-01-01 --end 2026-03-31 --report
        """,
    )
    parser.add_argument(
        "--strategy", type=str, default="v7",
        choices=["v7", "v8", "ad_hoc"],
        help="策略名 (默认: v7)",
    )
    parser.add_argument("--start", type=str, required=True, help="回测开始日期 YYYY-MM-DD")
    parser.add_argument("--end", type=str, required=True, help="回测结束日期 YYYY-MM-DD")
    parser.add_argument("--n-stocks", type=int, default=30, help="每期选股数量 (默认: 30)")
    parser.add_argument("--commission", type=float, default=0.0003, help="单边手续费率 (默认: 0.0003)")
    parser.add_argument("--capital", type=float, default=1_000_000, help="初始资金 (默认: 1000000)")
    parser.add_argument("--no-neutralize", action="store_true", help="关闭行业中性化")
    parser.add_argument("--report", action="store_true", help="生成 HTML 报告")
    parser.add_argument(
        "--walk-forward", action="store_true",
        help="运行 Walk-Forward 滚动样本外验证（替代单次回测）",
    )
    parser.add_argument("--train-years", type=int, default=3, help="Walk-Forward 训练窗口（年，默认 3）")
    parser.add_argument("--test-months", type=int, default=6, help="Walk-Forward 测试窗口（月，默认 6）")
    parser.add_argument(
        "--sweep-n-stocks", type=int, nargs="*", metavar="N",
        help="参数扫描：选股数量列表 (如 --sweep-n-stocks 20 30 50)",
    )
    parser.add_argument(
        "--compare", type=str, nargs="*", metavar="RUN_ID",
        help="与指定 run_id 对比绩效",
    )

    args = parser.parse_args()

    from backtest.standardized import run_backtest, run_walk_forward, run_parameter_sweep, BacktestConfig

    config = BacktestConfig(
        strategy=args.strategy,
        start=args.start,
        end=args.end,
        n_stocks=args.n_stocks,
        commission=args.commission,
        initial_capital=args.capital,
        neutralize=not args.no_neutralize,
    )

    if args.walk_forward:
        wf = run_walk_forward(config, train_years=args.train_years, test_months=args.test_months)
        print(f"\n窗口结果:")
        print(wf["windows"].to_string())
        return

    if args.sweep_n_stocks:
        results = run_parameter_sweep(config, {"n_stocks": args.sweep_n_stocks})
        if results and args.report:
            try:
                from backtest.comparison import generate_comparison_report
                report_path = generate_comparison_report(results, title="参数扫描对比")
                print(f"\n对比报告: {report_path}")
            except Exception as e:
                print(f"\n对比报告生成失败: {e}")
        print(f"\n最优参数 run_id: {results[0].run_id if results else 'N/A'}")
        return

    result = run_backtest(config)

    if result.status == "failed":
        print(f"\n回测失败: {result.error}")
        sys.exit(1)

    # 生成 HTML 报告
    if args.report and result.equity_curve is not None:
        try:
            from backtest.report import generate_html_report
            report_path = generate_html_report(result)
            print(f"\nHTML 报告: {report_path}")
        except ImportError:
            print("\n报告生成模块不可用，跳过 HTML 报告")

    # 对比
    if args.compare and result.run_id:
        from pipeline.run_store import compare_runs
        all_ids = [result.run_id] + args.compare
        comparison = compare_runs(all_ids)
        print(f"\n{'='*60}")
        print("  策略对比")
        print(f"{'='*60}")
        for run in comparison["runs"]:
            m = run.get("metrics", {})
            print(f"  {run.get('run_id', '?')[:30]}")
            print(f"    策略: {run.get('strategy_id', '?')}")
            print(f"    总收益: {m.get('total_return', 0):.2%}")
            print(f"    夏普: {m.get('sharpe', 0):.2f}")
            print(f"    最大回撤: {m.get('max_drawdown', 0):.2%}")
            print()

    print(f"\n运行记录 ID: {result.run_id}")


if __name__ == "__main__":
    main()
