"""
运行 multi_factor_v23 单次 in-sample 回测，写入 live/runs/。

v23 = v16 九因子 + adaptive_half_position_stop 叠加层
（baseline=-0.10, vol_window=60, ref_vol=0.15）。纯仓位管理叠加，不改
因子。IS 扫描（sweep_v16_dd_overlay.py）结果：sharpe 0.74→0.84，
MDD -43%→-26%，年化 22.9%→18.2%。

⚠ 参数来自 IS 14 组扫描，存在 selection bias；admission 前需走 WF。

回测期：2022-01-01 ~ 2025-12-31（与 v16 同 IS 窗口，便于直接对比）。

运行：python scripts/run_v23_backtest.py
"""
from __future__ import annotations

import datetime
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import pandas as pd

from pipeline.strategy_registry import get_strategy
from pipeline.run_store import RunRecord, generate_run_id, save_run
from utils.data_fingerprint import compute_data_fingerprint
from utils.local_data_loader import get_all_symbols, load_price_wide
from utils.metrics import (
    annualized_return, annualized_volatility, sharpe_ratio,
    max_drawdown, win_rate,
)

START = "2022-01-01"
END = "2025-12-31"
WARMUP_START = "2019-01-01"
N_STOCKS = 30


def main():
    print(f"[1/4] 加载 price 宽表 {WARMUP_START} ~ {END} …")
    symbols = get_all_symbols()
    price = load_price_wide(symbols, WARMUP_START, END, field="close")
    valid = price.columns[price.notna().sum() > 500]
    price = price[valid]
    print(f"  股票: {len(valid)} | 交易日: {len(price)}")

    print("  计算数据指纹…")
    fingerprint = compute_data_fingerprint(
        list(valid), WARMUP_START, END, sample_price_hash=True, n_sample=10
    )
    print(f"  universe_hash={fingerprint['universe']['hash']}  "
          f"cache_mtime_max={fingerprint['cache_dir']['stats'].get('mtime_max')}")

    print("[2/4] 构建 v23 策略…")
    entry = get_strategy("multi_factor_v23")
    params = {"n_stocks": N_STOCKS}
    strategy = entry.factory(params)

    print("[3/4] 运行回测（v16 底层 + 叠加层，数分钟）…")
    result = strategy.run(price)
    print(f"  回测产出行数: {len(result)}")

    if "portfolio_return" in result.columns:
        r = result["portfolio_return"]
    elif "returns" in result.columns:
        r = result["returns"]
    else:
        raise RuntimeError(f"未找到 return 列: {result.columns.tolist()}")

    r_eval = r.loc[START:END].dropna()
    metrics = {
        "total_return": float((1 + r_eval).prod() - 1),
        "annualized_return": float(annualized_return(r_eval)),
        "sharpe": float(sharpe_ratio(r_eval)),
        "max_drawdown": float(max_drawdown(r_eval)),
        "volatility": float(annualized_volatility(r_eval)),
        "win_rate": float(win_rate(r_eval)),
        "n_trading_days": int(len(r_eval)),
        "start_date": str(r_eval.index[0].date()),
        "end_date": str(r_eval.index[-1].date()),
    }
    print(f"  sharpe={metrics['sharpe']:.4f}  ann={metrics['annualized_return']:.2%}  "
          f"mdd={metrics['max_drawdown']:.2%}  n={metrics['n_trading_days']}")

    print("[4/4] 保存到 live/runs/ …")
    run_id = generate_run_id("multi_factor_v23", START, END, params)
    equity_df = pd.DataFrame({
        "date": r.index,
        "portfolio_return": r.values,
        "cumulative_return": (1 + r).cumprod().values - 1,
    })
    equity_df = equity_df.set_index("date")

    record = RunRecord(
        run_id=run_id,
        strategy_id="multi_factor_v23",
        strategy_name=entry.name,
        params=params,
        start_date=START,
        end_date=END,
        status="success",
        metrics=metrics,
        created_at=datetime.datetime.now().isoformat(),
    )
    path = save_run(record, equity_df=equity_df, fingerprint=fingerprint)
    print(f"  写出 {path}")
    print(f"  run_id: {run_id}")


if __name__ == "__main__":
    main()
