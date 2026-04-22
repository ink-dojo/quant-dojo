"""DSR #30 paper-trade — 每月首个交易日 review (spec v2 §6).

汇总上月 live vs backtest 数据:
  - 月度 PnL / SR / DD / 交易次数 / 胜率
  - 与 backtest 同期对比
  - Regime 暴露 (HS300 < MA120 占比)
  - 集中度检查 (top 5 股票贡献)
  - 是否触及 kill switch 任何条款

用法:
  python scripts/paper_trade_monthly_review.py              # 自动取上月
  python scripts/paper_trade_monthly_review.py --month 2026-04
"""
from __future__ import annotations

import argparse
import logging
from pathlib import Path

import numpy as np
import pandas as pd

from live.event_kill_switch import evaluate as eval_kill
from live.event_paper_trader import EventPaperTrader

logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).parent.parent
PAPER_TRADE_DIR = PROJECT_ROOT / "paper_trade"
BACKTEST_PARQUET = PROJECT_ROOT / "research/event_driven/dsr30_mainboard_recal_ensemble_oos.parquet"


def _compute_monthly_stats(nav: pd.Series, month: str) -> dict:
    """month format: 'YYYY-MM'."""
    start = pd.Timestamp(month + "-01")
    end = (start + pd.offsets.MonthEnd(0)).normalize()
    period = nav.loc[(nav.index >= start) & (nav.index <= end)]
    if len(period) < 2:
        return {"n_days": len(period), "note": "insufficient data"}

    rets = period.pct_change().dropna()
    total_ret = period.iloc[-1] / period.iloc[0] - 1
    ann_sr = (rets.mean() / rets.std() * np.sqrt(252)) if rets.std() > 0 else 0.0
    peak = period.cummax()
    dd = (period / peak - 1).min()
    win_rate = (rets > 0).mean()

    return {
        "n_days": len(period),
        "total_return": total_ret,
        "sharpe_ann": ann_sr,
        "max_dd": dd,
        "win_rate": win_rate,
        "avg_daily_ret": rets.mean(),
        "vol_daily": rets.std(),
    }


def _concentration_check(trader: EventPaperTrader, month: str) -> dict:
    """Top 5 symbols by cumulative trade notional in the month."""
    start = pd.Timestamp(month + "-01")
    end = (start + pd.offsets.MonthEnd(0)).normalize()
    month_trades = [t for t in trader.trades
                    if start <= pd.Timestamp(t["date"]) <= end]
    if not month_trades:
        return {"top_5": [], "n_unique_symbols": 0}
    df = pd.DataFrame(month_trades)
    df["notional"] = df["shares"] * df["price"]
    by_sym = df.groupby("symbol")["notional"].sum().sort_values(ascending=False)
    top5 = by_sym.head(5)
    total = by_sym.sum()
    top5_pct = (top5.sum() / total) if total > 0 else 0.0
    return {
        "top_5": [(sym, round(notional, 2)) for sym, notional in top5.items()],
        "top_5_concentration": round(top5_pct, 3),
        "n_unique_symbols": int(by_sym.size),
        "total_trade_notional": round(total, 2),
    }


def _compare_vs_backtest(nav: pd.Series, month: str) -> dict:
    """Compare live NAV returns vs backtest net_return for same month."""
    if not BACKTEST_PARQUET.exists():
        return {"note": "backtest parquet missing"}
    bt = pd.read_parquet(BACKTEST_PARQUET)["net_return"]
    bt.index = pd.DatetimeIndex(bt.index).normalize()
    start = pd.Timestamp(month + "-01")
    end = (start + pd.offsets.MonthEnd(0)).normalize()

    live_rets = nav.pct_change().dropna()
    live_rets.index = pd.DatetimeIndex(live_rets.index).normalize()
    live_month = live_rets.loc[(live_rets.index >= start) & (live_rets.index <= end)]
    bt_month = bt.loc[(bt.index >= start) & (bt.index <= end)]
    joined = pd.concat([live_month.rename("live"), bt_month.rename("bt")],
                       axis=1, sort=True).dropna()
    if len(joined) < 2:
        return {"note": "insufficient overlap"}
    delta = joined["live"] - joined["bt"]
    return {
        "n_days": len(joined),
        "live_cum": (1 + joined["live"]).prod() - 1,
        "bt_cum": (1 + joined["bt"]).prod() - 1,
        "mean_abs_delta_bps": float(delta.abs().mean() * 1e4),
        "corr": float(joined["live"].corr(joined["bt"])),
    }


def run_review(month: str, portfolio_dir: Path = None) -> dict:
    """Generate monthly review report."""
    portfolio_dir = portfolio_dir or (PAPER_TRADE_DIR / "portfolio")
    if not portfolio_dir.exists():
        logger.warning("Portfolio dir %s does not exist — no live data yet", portfolio_dir)
        return {"month": month, "note": "no live data"}

    trader = EventPaperTrader(1_000_000.0, portfolio_dir)
    nav = trader.nav_series()
    if len(nav) == 0:
        return {"month": month, "note": "empty NAV history"}

    stats = _compute_monthly_stats(nav, month)
    conc = _concentration_check(trader, month)
    vs_bt = _compare_vs_backtest(nav, month)

    # Kill switch evaluation at end of month
    end = pd.Timestamp(month + "-01") + pd.offsets.MonthEnd(0)
    as_of = min(pd.Timestamp(nav.index[-1]), end)
    kill = eval_kill(nav, as_of=as_of)

    trader.close()

    return {
        "month": month,
        "stats": stats,
        "concentration": conc,
        "vs_backtest": vs_bt,
        "kill_at_month_end": kill.to_dict(),
    }


def _write_review_md(path: Path, review: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    m = review["month"]
    lines = [f"# Paper-Trade Monthly Review — {m}", "",
             "_DSR #30 主板 rescaled, spec v2_", ""]

    if "note" in review:
        lines.append(f"**NOTE**: {review['note']}")
        path.write_text("\n".join(lines), encoding="utf-8")
        return

    s = review["stats"]
    lines += [
        "## 当月统计",
        "",
        f"- 交易日: {s['n_days']}",
        f"- 月度收益: **{s['total_return']:+.2%}**" if "total_return" in s else "",
        f"- 年化 Sharpe: **{s['sharpe_ann']:.2f}**" if "sharpe_ann" in s else "",
        f"- 最大回撤: {s['max_dd']:.2%}" if "max_dd" in s else "",
        f"- 胜率 (日): {s['win_rate']:.1%}" if "win_rate" in s else "",
        f"- 日均收益: {s['avg_daily_ret'] * 1e4:+.1f} bps" if "avg_daily_ret" in s else "",
        "",
    ]

    c = review["concentration"]
    lines += [
        "## 集中度",
        "",
        f"- Top 5 贡献: {c.get('top_5_concentration', 0):.1%} of total trade notional",
        f"- 参与过的 symbol 数: {c.get('n_unique_symbols', 0)}",
        "",
        "### Top 5 symbols",
        "",
    ]
    for sym, notional in c.get("top_5", []):
        lines.append(f"- {sym}: {notional:,.0f}")
    lines.append("")

    vb = review["vs_backtest"]
    lines += [
        "## Live vs Backtest",
        "",
    ]
    if "note" in vb:
        lines.append(f"_{vb['note']}_")
    else:
        lines += [
            f"- 覆盖天数: {vb['n_days']}",
            f"- Live 累计收益: {vb['live_cum']:+.2%}",
            f"- Backtest 累计收益: {vb['bt_cum']:+.2%}",
            f"- 日均绝对偏差: {vb['mean_abs_delta_bps']:.2f} bps",
            f"- Corr(live, bt): {vb['corr']:.4f}",
        ]
    lines.append("")

    k = review["kill_at_month_end"]
    lines += [
        "## 月末 Kill Switch",
        "",
        f"- Action: **{k['action'].upper()}**",
        f"- Rolling SR: {k.get('rolling_sr_30d')}",
        f"- Live Sharpe: {k.get('live_sharpe')}",
        f"- Cum DD: {k.get('cum_drawdown')}",
    ]
    if k.get("reasons"):
        lines.append("")
        lines.append("### Reasons")
        for r in k["reasons"]:
            lines.append(f"- {r}")
    lines.append("")

    path.write_text("\n".join(lines), encoding="utf-8")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--month", help="YYYY-MM, default=previous calendar month")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    if args.month:
        month = args.month
    else:
        today = pd.Timestamp.now()
        prev = (today - pd.offsets.MonthBegin(1)).strftime("%Y-%m")
        month = prev

    review = run_review(month)
    out_path = PAPER_TRADE_DIR / f"monthly_review_{month}.md"
    _write_review_md(out_path, review)
    print(f"Review written: {out_path}")

    import json
    print(json.dumps(review, indent=2, ensure_ascii=False, default=str))


if __name__ == "__main__":
    main()
