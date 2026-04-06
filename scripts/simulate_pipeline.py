#!/usr/bin/env python3
"""
scripts/simulate_pipeline.py — 多日流水线回放模拟

在历史日期范围上逐日运行流水线，验证：
  1. 信号连续性（相邻日重叠率）
  2. NAV 曲线合理性
  3. 因子选股是否稳定

用法:
  # 模拟最近 5 个交易日
  python scripts/simulate_pipeline.py --start 2026-03-28 --end 2026-04-03

  # 只跑信号+调仓（跳过风控和报告）
  python scripts/simulate_pipeline.py --start 2026-03-28 --end 2026-04-03 --fast

  # 干跑（不执行调仓）
  python scripts/simulate_pipeline.py --start 2026-03-28 --end 2026-04-03 --dry-run
"""

import argparse
import json
import sys
import os
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
os.chdir(PROJECT_ROOT)


def get_trade_dates(start: str, end: str) -> list:
    """
    获取日期范围内的交易日列表。

    使用本地数据中的实际日期（从任意一只股票的 CSV 中提取）。
    """
    import pandas as pd
    from utils.local_data_loader import get_all_symbols, load_local_stock

    # 取一只股票的日期作为交易日历
    symbols = get_all_symbols()
    if not symbols:
        print("无本地数据")
        return []

    # 尝试几只股票（避免某只股票数据不全）
    for sym in symbols[:5]:
        try:
            df = load_local_stock(sym)
            dates = df.index[(df.index >= start) & (df.index <= end)]
            if len(dates) > 0:
                return [d.strftime("%Y-%m-%d") for d in sorted(dates)]
        except Exception:
            continue

    return []


def main():
    parser = argparse.ArgumentParser(description="多日流水线回放模拟")
    parser.add_argument("--start", type=str, required=True, help="起始日期 YYYY-MM-DD")
    parser.add_argument("--end", type=str, required=True, help="结束日期 YYYY-MM-DD")
    parser.add_argument("--fast", action="store_true",
                        help="快速模式（只跑 signal + execute，跳过风控和报告）")
    parser.add_argument("--dry-run", dest="dry_run", action="store_true",
                        help="干跑模式")
    args = parser.parse_args()

    # 获取交易日
    print(f"获取 {args.start} 到 {args.end} 的交易日...")
    trade_dates = get_trade_dates(args.start, args.end)
    if not trade_dates:
        print("无交易日数据")
        sys.exit(1)

    print(f"共 {len(trade_dates)} 个交易日: {trade_dates[0]} → {trade_dates[-1]}\n")

    # 构建流水线
    from pipeline.orchestrator import build_default_pipeline

    # 记录每日结果
    daily_results = []
    prev_picks = []

    for i, date in enumerate(trade_dates):
        print(f"\n{'#'*60}")
        print(f"# Day {i+1}/{len(trade_dates)}: {date}")
        print(f"{'#'*60}")

        orch = build_default_pipeline()

        if args.fast:
            # 快速模式：只保留 data_check, signal, execute
            orch.stages = [
                s for s in orch.stages
                if s.name in ("data_check", "signal", "execute")
            ]

        ctx = orch.execute(date=date, mode="daily", dry_run=args.dry_run)

        # 收集统计
        picks = ctx.get("signal_picks", [])
        nav = ctx.get("nav_after", 0)
        rebalance = ctx.get("rebalance_summary", {})

        # 计算与前日重叠率
        if prev_picks and picks:
            overlap = set(picks) & set(prev_picks)
            overlap_rate = len(overlap) / max(len(picks), 1)
        else:
            overlap_rate = None

        daily_results.append({
            "date": date,
            "n_picks": len(picks),
            "nav": nav,
            "n_buys": rebalance.get("n_buys", 0),
            "n_sells": rebalance.get("n_sells", 0),
            "turnover": rebalance.get("turnover", 0),
            "overlap_rate": overlap_rate,
            "n_failed": sum(1 for r in ctx.stage_results if r.status.value == "failed"),
        })

        prev_picks = picks

    # ── 汇总报告 ──────────────────────────────────────────────
    print(f"\n\n{'='*70}")
    print(f"  多日模拟汇总 | {args.start} → {args.end}")
    print(f"{'='*70}\n")

    print(f"{'日期':<12} {'选股':>4} {'买':>4} {'卖':>4} {'换手率':>8} {'重叠率':>8} {'NAV':>14} {'状态':>6}")
    print(f"{'-'*70}")

    for r in daily_results:
        overlap = f"{r['overlap_rate']:.1%}" if r['overlap_rate'] is not None else "—"
        status = "FAIL" if r['n_failed'] > 0 else "OK"
        nav_str = f"{r['nav']:>14,.2f}" if r['nav'] else f"{'—':>14}"
        print(
            f"{r['date']:<12} {r['n_picks']:>4} {r['n_buys']:>4} {r['n_sells']:>4} "
            f"{r['turnover']:>7.1%} {overlap:>8} {nav_str} {status:>6}"
        )

    # 统计
    navs = [r["nav"] for r in daily_results if r["nav"]]
    overlaps = [r["overlap_rate"] for r in daily_results if r["overlap_rate"] is not None]
    turnovers = [r["turnover"] for r in daily_results if r["turnover"]]

    print(f"\n  NAV: {navs[0]:,.0f} → {navs[-1]:,.0f}" if len(navs) >= 2 else "")
    if navs and navs[0] > 0:
        total_ret = navs[-1] / navs[0] - 1
        print(f"  总收益: {total_ret:+.2%}")
    if overlaps:
        print(f"  平均重叠率: {sum(overlaps)/len(overlaps):.1%}")
    if turnovers:
        print(f"  平均换手率: {sum(turnovers)/len(turnovers):.1%}")

    # 保存结果
    result_path = PROJECT_ROOT / "journal" / f"simulation_{args.start}_{args.end}.json"
    result_path.parent.mkdir(parents=True, exist_ok=True)
    with open(result_path, "w", encoding="utf-8") as f:
        json.dump(daily_results, f, ensure_ascii=False, indent=2)
    print(f"\n  结果已保存: {result_path}")


if __name__ == "__main__":
    main()
