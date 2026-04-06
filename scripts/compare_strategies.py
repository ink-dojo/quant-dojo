#!/usr/bin/env python3
"""
scripts/compare_strategies.py — v7 vs v8 策略对比

对同一日期范围分别运行 v7 和 v8 策略信号，比较：
  1. 选股重叠率（v7 ∩ v8 / v7）
  2. 因子覆盖度差异
  3. 评分分布差异
  4. 排除统计差异

用法:
  # 对比单日
  python scripts/compare_strategies.py --date 2026-04-03

  # 对比多日
  python scripts/compare_strategies.py --start 2026-03-28 --end 2026-04-03
"""

import argparse
import json
import sys
import os
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
os.chdir(PROJECT_ROOT)

import numpy as np


def run_signal_for_strategy(date: str, strategy: str) -> dict:
    """运行指定策略的信号生成"""
    from pipeline.daily_signal import run_daily_pipeline
    try:
        return run_daily_pipeline(date=date, strategy=strategy)
    except Exception as e:
        return {"error": str(e), "picks": [], "scores": {}}


def compare_single_day(date: str) -> dict:
    """对比单日 v7 vs v8"""
    print(f"\n  {date}: 运行 v7...")
    v7 = run_signal_for_strategy(date, "v7")
    print(f"  {date}: 运行 v8...")
    v8 = run_signal_for_strategy(date, "v8")

    v7_picks = set(v7.get("picks", []))
    v8_picks = set(v8.get("picks", []))

    overlap = v7_picks & v8_picks
    only_v7 = v7_picks - v8_picks
    only_v8 = v8_picks - v7_picks

    # 评分对比（交集股票）
    v7_scores = v7.get("scores", {})
    v8_scores = v8.get("scores", {})
    score_corr = None
    if overlap and v7_scores and v8_scores:
        common_scores_v7 = []
        common_scores_v8 = []
        for sym in overlap:
            if sym in v7_scores and sym in v8_scores:
                common_scores_v7.append(v7_scores[sym])
                common_scores_v8.append(v8_scores[sym])
        if len(common_scores_v7) > 5:
            from scipy import stats
            corr, _ = stats.spearmanr(common_scores_v7, common_scores_v8)
            score_corr = round(corr, 4)

    result = {
        "date": date,
        "v7_n": len(v7_picks),
        "v8_n": len(v8_picks),
        "overlap_n": len(overlap),
        "overlap_rate": round(len(overlap) / max(len(v7_picks), 1), 4),
        "only_v7": sorted(only_v7)[:5],
        "only_v8": sorted(only_v8)[:5],
        "score_rank_corr": score_corr,
        "v7_excluded": v7.get("excluded", {}),
        "v8_excluded": v8.get("excluded", {}),
    }

    # 因子覆盖度对比
    v7_factors = v7.get("factor_values", {})
    v8_factors = v8.get("factor_values", {})
    if v7_factors and v8_factors:
        v7_fnames = set(v7_factors.keys())
        v8_fnames = set(v8_factors.keys())
        result["v7_factors"] = sorted(v7_fnames)
        result["v8_factors"] = sorted(v8_fnames)
        result["new_in_v8"] = sorted(v8_fnames - v7_fnames)

    return result


def get_trade_dates(start: str, end: str) -> list:
    """获取交易日列表"""
    import pandas as pd
    from utils.local_data_loader import get_all_symbols, load_local_stock

    symbols = get_all_symbols()
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
    parser = argparse.ArgumentParser(description="v7 vs v8 策略对比")
    parser.add_argument("--date", type=str, help="单日对比")
    parser.add_argument("--start", type=str, help="多日对比起始日期")
    parser.add_argument("--end", type=str, help="多日对比结束日期")
    args = parser.parse_args()

    if args.date:
        dates = [args.date]
    elif args.start and args.end:
        dates = get_trade_dates(args.start, args.end)
        if not dates:
            print("无交易日数据")
            sys.exit(1)
    else:
        parser.error("必须指定 --date 或 --start/--end")

    print(f"\n{'='*70}")
    print(f"  v7 vs v8 策略对比 | {dates[0]} → {dates[-1]} ({len(dates)} 天)")
    print(f"{'='*70}")

    results = []
    for date in dates:
        r = compare_single_day(date)
        results.append(r)

    # 汇总表
    print(f"\n{'='*70}")
    print(f"  对比汇总")
    print(f"{'='*70}\n")

    print(f"{'日期':<12} {'v7选股':>6} {'v8选股':>6} {'重叠':>6} {'重叠率':>8} {'评分相关':>8}")
    print(f"{'-'*52}")

    for r in results:
        corr_str = f"{r['score_rank_corr']:.4f}" if r['score_rank_corr'] is not None else "—"
        print(
            f"{r['date']:<12} {r['v7_n']:>6} {r['v8_n']:>6} {r['overlap_n']:>6} "
            f"{r['overlap_rate']:>7.1%} {corr_str:>8}"
        )

    # 平均值
    if len(results) > 1:
        avg_overlap = np.mean([r['overlap_rate'] for r in results])
        corrs = [r['score_rank_corr'] for r in results if r['score_rank_corr'] is not None]
        avg_corr = np.mean(corrs) if corrs else None
        print(f"{'-'*52}")
        corr_avg_str = f"{avg_corr:.4f}" if avg_corr is not None else "—"
        print(f"{'平均':<12} {'':>6} {'':>6} {'':>6} {avg_overlap:>7.1%} {corr_avg_str:>8}")

    # v8 新增因子
    if results and results[0].get("new_in_v8"):
        print(f"\n  v8 新增因子: {', '.join(results[0]['new_in_v8'])}")

    # v8 独有股票样例
    if results:
        all_only_v8 = set()
        for r in results:
            all_only_v8.update(r.get("only_v8", []))
        if all_only_v8:
            print(f"  v8 独有选股样例: {', '.join(sorted(all_only_v8)[:10])}")

    # 保存
    output_path = PROJECT_ROOT / "journal" / f"strategy_compare_{dates[0]}_{dates[-1]}.json"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)
    print(f"\n  结果已保存: {output_path}")


if __name__ == "__main__":
    main()
