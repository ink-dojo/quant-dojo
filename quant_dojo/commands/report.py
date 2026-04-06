"""
quant_dojo report — 生成报告

用法:
  python -m quant_dojo report                  # 最新一周的周报
  python -m quant_dojo report --week 2026-W13  # 指定周
  python -m quant_dojo report --backtest       # 最近回测的 HTML 报告
"""
import sys
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent.parent


def generate_report(week: str = None, backtest: bool = False):
    """生成报告"""
    sys.path.insert(0, str(PROJECT_ROOT))

    if backtest:
        _generate_backtest_report()
        return

    _generate_weekly_report(week)


def _generate_weekly_report(week: str = None):
    """生成周报"""
    if week is None:
        # 自动计算当前 ISO 周
        now = datetime.now()
        week = now.strftime("%G-W%V")

    print(f"╔═══════════════════════════════════════════════╗")
    print(f"║  quant-dojo 周报生成                          ║")
    print(f"╚═══════════════════════════════════════════════╝")
    print(f"  周次: {week}\n")

    try:
        from pipeline.weekly_report import generate_weekly_report
        report = generate_weekly_report(week)
        if isinstance(report, dict):
            path = report.get("path", "")
            print(f"  [OK] 周报已生成: {path}")
        elif isinstance(report, str):
            print(f"  [OK] 周报已生成: {report}")
        else:
            print(f"  [OK] 周报已生成")
    except ImportError:
        # 如果 weekly_report 模块不可用，用 pipeline.cli 的实现
        try:
            from pipeline.cli import cmd_report_weekly
            import argparse
            args = argparse.Namespace(week=week)
            cmd_report_weekly(args)
        except Exception as e:
            print(f"  [失败] 周报生成失败: {e}")
    except Exception as e:
        print(f"  [失败] 周报生成失败: {e}")


def _generate_backtest_report():
    """为最近的回测生成 HTML 报告"""
    print("╔═══════════════════════════════════════════════╗")
    print("║  quant-dojo 回测报告生成                       ║")
    print("╚═══════════════════════════════════════════════╝\n")

    try:
        from pipeline.run_store import list_runs
        runs = list_runs(status="success", limit=1)
        if not runs:
            print("  [错误] 没有成功的回测记录")
            print("         先运行: python -m quant_dojo backtest")
            sys.exit(1)

        latest = runs[0]
        print(f"  回测记录: {latest.run_id[:30]}")
        print(f"  策略: {latest.strategy_id}")

        metrics = latest.metrics or {}
        print(f"  收益: {metrics.get('total_return', 0):.2%}")
        print(f"  夏普: {metrics.get('sharpe', 0):.2f}")

        # 尝试重新生成 HTML 报告
        from backtest.standardized import BacktestConfig, BacktestResult
        import pandas as pd

        # 加载 equity curve
        runs_dir = PROJECT_ROOT / "live" / "runs"
        equity_path = runs_dir / f"{latest.run_id}_equity.csv"

        config = BacktestConfig(
            strategy=latest.strategy_id,
            start=latest.start_date,
            end=latest.end_date,
        )

        result = BacktestResult(
            config=config,
            metrics=metrics,
            run_id=latest.run_id,
            status="success",
        )

        if equity_path.exists():
            eq_df = pd.read_csv(equity_path, index_col=0, parse_dates=True)
            result.equity_curve = eq_df

        from backtest.report import generate_html_report
        path = generate_html_report(result)
        print(f"\n  [OK] HTML 报告: {path}")

    except Exception as e:
        print(f"  [失败] 报告生成失败: {e}")
        sys.exit(1)
