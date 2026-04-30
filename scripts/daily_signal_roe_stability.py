"""
roe_stability daily signal generator (D 路, Issue #51 kickoff).

每日跑一次, 产出 roe_stability 中性化后 Q5 (top 30 多头) signal,
schema 跟现有 live/signals/YYYY-MM-DD.json 一致, 写到 live/signals/.

复用 Issue #44 / #47 的中性化路径:
  build_roe_stability → neutralize_factor (size + SW-L1) → cross_section_rank
  → 当日 top 30 stocks by rank.

执行:
    python scripts/daily_signal_roe_stability.py [--date YYYY-MM-DD]

后续: 接 Makefile target, 接 cron / launchd 每天盘后 16:30 跑.
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
import warnings
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from research.factors.tushare_factors.factor_research import (  # noqa: E402
    build_roe_stability,
)
from research.factors.tushare_factors.neutralize_and_cost import (  # noqa: E402
    build_df_info,
    build_price_panel,
    build_size_panel,
    load_industry_l1,
    resolve_stock_pools,
)
from utils.factor_analysis import (  # noqa: E402
    cross_section_rank,
    neutralize_factor,
)

warnings.filterwarnings("ignore")

SIGNALS_DIR = ROOT / "live" / "signals"
TOP_N = 30  # 与现有 v16 picks 数量一致
LOOKBACK_DAYS = 60  # 价格面板回溯 60d (足够算 ranking)


def generate_signal(target_date: pd.Timestamp) -> dict:
    """对 target_date 产出 roe_stability top N 多头 picks.

    流程: 加载价格 + roe_stability factor + 中性化 + rank → 取 target_date 当日
    rank top N stocks. 如果 target_date 不是交易日, 取最近交易日.
    """
    pools = resolve_stock_pools()
    quality_stocks = pools["quality"]
    print(f"[signal] quality stocks pool: {len(quality_stocks)}")

    start_date = (target_date - pd.Timedelta(days=LOOKBACK_DAYS)).date()
    end_date = target_date.date()
    price_wide = build_price_panel(pools["core"], str(start_date), str(end_date))
    if price_wide.empty:
        raise RuntimeError(f"price_wide 空, 区间 {start_date} ~ {end_date}")
    print(f"[signal] price shape: {price_wide.shape}")

    size_panel = build_size_panel(pools["core"], price_wide.index)
    industry_l1 = load_industry_l1()
    df_info = build_df_info(size_panel, industry_l1)

    f_roe = build_roe_stability(quality_stocks, price_wide.index).reindex(price_wide.index)
    f_neutral = neutralize_factor(f_roe, df_info, n_sigma=3.0)
    r_neutral = cross_section_rank(f_neutral)

    # 找 target_date 的最近 ≤ trading day
    trading_dates = r_neutral.index
    tradable_dates = trading_dates[trading_dates <= target_date]
    if len(tradable_dates) == 0:
        raise RuntimeError(f"target_date {target_date.date()} 之前没有交易日数据")
    use_date = tradable_dates[-1]
    print(f"[signal] target_date={target_date.date()}, 用最近交易日={use_date.date()}")

    today_rank = r_neutral.loc[use_date].dropna().sort_values(ascending=False)
    picks = today_rank.head(TOP_N).index.tolist()
    scores = {sym: round(float(today_rank[sym]), 4) for sym in picks}
    factor_values = {sym: round(float(f_neutral.loc[use_date, sym]), 6)
                     for sym in picks}

    payload = {
        "date": str(use_date.date()),
        "strategy": "roe_stability_neutral_q5",
        "picks": picks,
        "scores": scores,
        "factor_values": factor_values,
        "excluded": [],
        "metadata": {
            "target_date_input": str(target_date.date()),
            "n_picks": len(picks),
            "n_stocks_ranked": int(today_rank.shape[0]),
            "n_quality_stocks": len(quality_stocks),
            "neutralize": "size_log + SW_L1",
            "rank_method": "cross_section_pct_rank",
            "tier": "Live-Tier 0 (paper-only, Issue #51)",
            "issue": "#51",
        },
    }
    return payload


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", type=str, default=None,
                    help="YYYY-MM-DD; 默认今天")
    ap.add_argument("--force", action="store_true",
                    help="即使文件已存在也覆盖")
    args = ap.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    target = pd.Timestamp(args.date) if args.date else pd.Timestamp.today().normalize()
    print(f"[signal] target_date = {target.date()}")

    payload = generate_signal(target)

    SIGNALS_DIR.mkdir(parents=True, exist_ok=True)
    out_path = SIGNALS_DIR / f"roe_stability_{payload['date']}.json"
    if out_path.exists() and not args.force:
        print(f"[signal] {out_path} 已存在, 不覆盖 (用 --force 覆盖)")
        return
    out_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False, default=str))
    print(f"\n✅ {out_path} ({len(payload['picks'])} picks)")
    print(f"   top 5: {payload['picks'][:5]}")


if __name__ == "__main__":
    main()
