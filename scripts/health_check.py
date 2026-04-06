#!/usr/bin/env python3
"""
scripts/health_check.py — 轻量健康检查（适合 cron 定时运行）

检查因子健康、数据新鲜度、NAV 状态，发现问题时发送告警。
不运行完整流水线，几秒内完成。

用法:
  # 手动运行
  python scripts/health_check.py

  # cron 每 4 小时运行一次
  0 */4 * * * cd /path/to/quant-dojo && python scripts/health_check.py >> logs/health_check.log 2>&1

  # 只检查因子
  python scripts/health_check.py --only factors

  # 静默模式（只在有问题时输出）
  python scripts/health_check.py --quiet
"""

import argparse
import sys
import os
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
os.chdir(PROJECT_ROOT)


def check_data_freshness(quiet: bool = False) -> list:
    """检查数据新鲜度"""
    issues = []
    try:
        from pipeline.data_checker import check_data_freshness as _check
        result = _check()
        days_stale = result.get("days_stale", 999)
        latest = result.get("latest_date", "unknown")

        if days_stale > 5:
            issues.append(f"数据严重过期: {latest} ({days_stale} 天前)")
        elif days_stale > 3:
            issues.append(f"数据过期: {latest} ({days_stale} 天前)")

        if not quiet:
            status = "OK" if days_stale <= 3 else "STALE"
            print(f"  数据: {latest} ({days_stale} 天前) [{status}]")

    except Exception as e:
        issues.append(f"数据检查失败: {e}")
    return issues


def check_factor_health(quiet: bool = False) -> list:
    """检查因子健康度"""
    issues = []
    try:
        from pipeline.factor_monitor import factor_health_report, FACTOR_PRESETS
        from pipeline.active_strategy import get_active_strategy

        active = get_active_strategy()
        preset_key = active if active in FACTOR_PRESETS else "v7"
        health = factor_health_report(factors=FACTOR_PRESETS[preset_key])

        dead_factors = []
        degraded_factors = []

        for name, info in health.items():
            status = info.get("status", "no_data")
            if status == "dead":
                dead_factors.append(name)
            elif status == "degraded":
                degraded_factors.append(name)

            if not quiet:
                ic = info.get("rolling_ic")
                ic_str = f"{ic:.4f}" if ic is not None and ic == ic else "N/A"
                icon = {"healthy": "OK", "degraded": "WARN", "dead": "DEAD", "no_data": "N/A"}.get(status, "?")
                print(f"  因子 {name:20s} IC: {ic_str:>8s} [{icon}]")

        if dead_factors:
            issues.append(f"因子失效: {', '.join(dead_factors)}")
        if degraded_factors:
            issues.append(f"因子衰减: {', '.join(degraded_factors)}")

    except Exception as e:
        issues.append(f"因子检查失败: {e}")
    return issues


def check_nav(quiet: bool = False) -> list:
    """检查 NAV 状态"""
    issues = []
    try:
        from live.paper_trader import PaperTrader
        trader = PaperTrader()
        perf = trader.get_performance()

        if perf:
            total_ret = perf.get("total_return", 0)
            max_dd = perf.get("max_drawdown", 0)
            sharpe = perf.get("sharpe", 0)

            if max_dd < -0.10:
                issues.append(f"最大回撤超过 10%: {max_dd:.2%}")
            if total_ret < -0.15:
                issues.append(f"总亏损超过 15%: {total_ret:.2%}")

            if not quiet:
                from live.paper_trader import NAV_FILE
                import pandas as pd
                nav_df = pd.read_csv(NAV_FILE) if NAV_FILE.exists() else pd.DataFrame()
                latest_nav = nav_df["nav"].iloc[-1] if not nav_df.empty else 0
                print(f"  NAV: {latest_nav:,.2f} | 收益: {total_ret:.2%} | 夏普: {sharpe:.2f} | 回撤: {max_dd:.2%}")
        else:
            if not quiet:
                print("  NAV: 无数据")

    except Exception as e:
        issues.append(f"NAV 检查失败: {e}")
    return issues


def check_pipeline_runs(quiet: bool = False) -> list:
    """检查最近流水线运行"""
    issues = []
    journal_dir = PROJECT_ROOT / "journal"
    files = sorted(journal_dir.glob("pipeline_*.json"), reverse=True)[:3]

    if not files:
        issues.append("无流水线运行记录")
        return issues

    import json
    latest = json.loads(files[0].read_text(encoding="utf-8"))
    latest_date = latest.get("date", "?")
    halted = latest.get("halted", False)
    n_fail = sum(1 for s in latest.get("stages", []) if s["status"] == "failed")

    if halted:
        issues.append(f"最近一次流水线被中止: {latest_date}")
    if n_fail > 0:
        issues.append(f"最近一次流水线有 {n_fail} 个阶段失败: {latest_date}")

    if not quiet:
        status = "HALTED" if halted else ("FAIL" if n_fail else "OK")
        print(f"  最近运行: {latest_date} [{status}]")

    return issues


def main():
    parser = argparse.ArgumentParser(description="量化系统健康检查")
    parser.add_argument("--quiet", action="store_true", help="静默模式（只在有问题时输出）")
    parser.add_argument("--only", type=str, choices=["data", "factors", "nav", "pipeline"],
                        help="只运行指定检查")
    args = parser.parse_args()

    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    all_issues = []

    if not args.quiet:
        print(f"\n  量化系统健康检查 | {now}")
        print(f"  {'─' * 40}")

    checks = {
        "data": check_data_freshness,
        "factors": check_factor_health,
        "nav": check_nav,
        "pipeline": check_pipeline_runs,
    }

    if args.only:
        checks = {args.only: checks[args.only]}

    for name, fn in checks.items():
        issues = fn(quiet=args.quiet)
        all_issues.extend(issues)

    # 发送告警
    if all_issues:
        if not args.quiet:
            print(f"\n  发现 {len(all_issues)} 个问题:")
            for issue in all_issues:
                print(f"    - {issue}")

        try:
            from pipeline.alert_notifier import send_alert, AlertLevel
            for issue in all_issues:
                level = AlertLevel.CRITICAL if any(
                    kw in issue for kw in ["失效", "中止", "严重", "超过 10%", "超过 15%"]
                ) else AlertLevel.WARNING
                send_alert(level=level, title=issue, source="health_check")
        except Exception:
            pass

        if not args.quiet:
            print(f"\n  告警已发送到 logs/alerts.log")
    else:
        if not args.quiet:
            print(f"\n  所有检查通过")

    if not args.quiet:
        print()

    # 退出码：有问题返回 1
    sys.exit(1 if all_issues else 0)


if __name__ == "__main__":
    main()
