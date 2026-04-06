"""
quant_dojo backtest — 一键回测

自动完成：
  1. 计算合理的日期范围（默认最近2年）
  2. 运行标准化回测
  3. 生成 HTML 报告
  4. 打印关键指标
"""
import sys
from datetime import datetime, timedelta
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent.parent


def run_backtest_cmd(
    strategy: str = "v7",
    start: str = None,
    end: str = None,
    n_stocks: int = 30,
    report: bool = True,
):
    """运行回测"""
    sys.path.insert(0, str(PROJECT_ROOT))

    # 智能默认日期
    if end is None:
        end = datetime.now().strftime("%Y-%m-%d")
    if start is None:
        start_dt = datetime.strptime(end, "%Y-%m-%d") - timedelta(days=730)  # ~2年
        start = start_dt.strftime("%Y-%m-%d")

    print("╔═══════════════════════════════════════════════╗")
    print("║  quant-dojo 回测                              ║")
    print("╚═══════════════════════════════════════════════╝")
    print(f"  策略: {strategy}")
    print(f"  区间: {start} ~ {end}")
    print(f"  选股: {n_stocks}")
    print()

    # 前置检查：数据是否可用
    try:
        from utils.local_data_loader import get_all_symbols
        symbols = get_all_symbols()
        if not symbols:
            print("  [错误] 未找到股票数据")
            print("         请先下载数据或运行: python -m quant_dojo init")
            sys.exit(1)
        print(f"  数据: {len(symbols)} 只股票")
    except Exception as e:
        print(f"  [错误] 数据加载失败: {e}")
        print("         请先运行: python -m quant_dojo init")
        sys.exit(1)

    from backtest.standardized import run_backtest, BacktestConfig

    config = BacktestConfig(
        strategy=strategy,
        start=start,
        end=end,
        n_stocks=n_stocks,
    )

    result = run_backtest(config)

    if result.status == "failed":
        print(f"\n回测失败: {result.error}")
        sys.exit(1)

    # 生成报告
    if report and result.equity_curve is not None:
        try:
            from backtest.report import generate_html_report
            report_path = generate_html_report(result)
            print(f"\nHTML 报告: {report_path}")
        except Exception as e:
            print(f"\n报告生成失败: {e}")

    # 简洁摘要
    m = result.metrics
    print(f"\n{'─'*40}")
    print(f"  结论:")
    sharpe = m.get("sharpe", 0)
    total = m.get("total_return", 0)
    mdd = m.get("max_drawdown", 0)

    if sharpe >= 1.0 and total > 0:
        verdict = "策略表现良好"
    elif sharpe >= 0.5 and total > 0:
        verdict = "策略表现中等，可优化"
    elif total > 0:
        verdict = "策略正收益但风险偏高"
    else:
        verdict = "策略表现不佳，建议调整"

    print(f"  {verdict}")
    print(f"  总收益 {total:+.2%} | 夏普 {sharpe:.2f} | 最大回撤 {mdd:.2%}")
    print(f"  Run ID: {result.run_id}")
    print(f"{'─'*40}")

    # 提示下一步
    if sharpe >= 0.5 and total > 0:
        print(f"\n  下一步:")
        print(f"    python -m quant_dojo activate {strategy}   # 激活此策略")
        print(f"    python -m quant_dojo run                   # 开始每日运行")

    return result
