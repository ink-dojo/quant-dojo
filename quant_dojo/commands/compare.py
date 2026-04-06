"""
quant_dojo compare — 策略对比

用法:
  python -m quant_dojo compare v7 v8           # 对比两个策略
  python -m quant_dojo compare v7 v8 ad_hoc    # 对比三个策略
  python -m quant_dojo compare v7 v8 --start 2024-01-01 --end 2025-12-31
"""
import sys
from datetime import datetime, timedelta
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent.parent


def run_compare(
    strategies: list[str],
    start: str = None,
    end: str = None,
    n_stocks: int = 30,
):
    """运行多策略对比"""
    sys.path.insert(0, str(PROJECT_ROOT))

    if len(strategies) < 2:
        print("  [错误] 至少需要 2 个策略进行对比")
        sys.exit(1)

    # 智能默认日期
    if end is None:
        end = datetime.now().strftime("%Y-%m-%d")
    if start is None:
        start_dt = datetime.strptime(end, "%Y-%m-%d") - timedelta(days=730)
        start = start_dt.strftime("%Y-%m-%d")

    print("╔═══════════════════════════════════════════════╗")
    print("║  quant-dojo 策略对比                           ║")
    print("╚═══════════════════════════════════════════════╝")
    print(f"  策略: {', '.join(strategies)}")
    print(f"  区间: {start} ~ {end}")
    print(f"  选股: {n_stocks}")
    print()

    # 前置检查
    try:
        from utils.local_data_loader import get_all_symbols
        symbols = get_all_symbols()
        if not symbols:
            print("  [错误] 未找到股票数据")
            print("         请先运行: python -m quant_dojo init --download")
            sys.exit(1)
        print(f"  数据: {len(symbols)} 只股票\n")
    except Exception as e:
        print(f"  [错误] 数据检查失败: {e}")
        sys.exit(1)

    from backtest.standardized import run_backtest, BacktestConfig

    results = []
    for strat in strategies:
        print(f"━━━ 运行回测: {strat} ━━━")
        config = BacktestConfig(
            strategy=strat,
            start=start,
            end=end,
            n_stocks=n_stocks,
        )
        result = run_backtest(config)
        if result.status == "success":
            results.append(result)
            m = result.metrics
            print(f"  收益 {m.get('total_return', 0):+.2%} | 夏普 {m.get('sharpe', 0):.2f} | 回撤 {m.get('max_drawdown', 0):.2%}")
        else:
            print(f"  [失败] {result.error}")
        print()

    if len(results) < 2:
        print("  [错误] 成功的回测不足 2 个，无法对比")
        sys.exit(1)

    # 生成对比报告
    try:
        from backtest.comparison import generate_comparison_report
        report_path = generate_comparison_report(results, title="策略对比")
        print(f"  对比报告: {report_path}")
    except Exception as e:
        print(f"  报告生成失败: {e}")

    # 打印对比摘要
    print(f"\n{'='*60}")
    print(f"  {'策略':<8} {'总收益':>10} {'年化':>10} {'夏普':>8} {'回撤':>10}")
    print(f"  {'─'*6:<8} {'─'*8:>10} {'─'*8:>10} {'─'*6:>8} {'─'*8:>10}")

    best_sharpe = max(r.metrics.get("sharpe", 0) for r in results)

    for r in results:
        m = r.metrics
        sharpe = m.get("sharpe", 0)
        marker = " <-- 最优" if sharpe == best_sharpe else ""
        print(
            f"  {r.config.strategy:<8} "
            f"{m.get('total_return', 0):>+9.2%} "
            f"{m.get('annualized_return', 0):>+9.2%} "
            f"{sharpe:>7.2f} "
            f"{m.get('max_drawdown', 0):>9.2%}"
            f"{marker}"
        )
    print(f"{'='*60}")

    # 推荐
    best = max(results, key=lambda r: r.metrics.get("sharpe", 0))
    print(f"\n  推荐: {best.config.strategy} (夏普 {best.metrics.get('sharpe', 0):.2f})")
    print(f"  激活: python -m quant_dojo activate {best.config.strategy}")
