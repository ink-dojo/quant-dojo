"""DSR #30 paper-trade — EOD daily pipeline (spec v2 §2).

每交易日 15:00 后跑一次:
  1. 拉 BB/PV 当日事件
  2. generate_daily_signal(as_of=today, ...) → new EventEntries
  3. EventPaperTrader.process_day(...) → 买卖成交 + NAV
  4. kill_switch.evaluate(...) → 风控判定
  5. 写 paper_trade/orders_YYYYMMDD.csv + paper_trade/daily_report_YYYYMMDD.md
  6. 若 action != OK → 推送告警 (stub: print + write)

用法:
  python scripts/paper_trade_daily.py                 # 用 today
  python scripts/paper_trade_daily.py --date 2025-06-16
  python scripts/paper_trade_daily.py --dry-run       # 不落盘
"""
from __future__ import annotations

import argparse
import csv
import json
import logging
import sys
from datetime import date, datetime, timezone
from pathlib import Path

import pandas as pd

from live.event_kill_switch import KillAction, KillReport, evaluate as eval_kill
from live.event_paper_trader import EventPaperTrader
from pipeline.event_signal import generate_daily_signal
from utils.local_data_loader import load_adj_price_wide

logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).parent.parent
PAPER_TRADE_DIR = PROJECT_ROOT / "paper_trade"
CONFIG_PATH = PAPER_TRADE_DIR / "config.json"
DEFAULT_INITIAL_CAPITAL = 1_000_000.0  # spec v3 §3: phase 1 = 5% of total; trader itself sees absolute


def _load_config() -> dict:
    """Load paper_trade/config.json with defaults for missing fields."""
    if not CONFIG_PATH.exists():
        return {"legs_enabled": {"bb": True, "pv": True},
                "ensemble_mix": {"bb": 0.5, "pv": 0.5}}
    cfg = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    cfg.setdefault("legs_enabled", {"bb": True, "pv": True})
    cfg.setdefault("ensemble_mix", {"bb": 0.5, "pv": 0.5})
    return cfg


def _today_trading_day(trading_days: pd.DatetimeIndex,
                       as_of: pd.Timestamp) -> pd.Timestamp | None:
    """Returns as_of if trading day, else None (caller should skip)."""
    as_of = as_of.normalize()
    if as_of in trading_days:
        return as_of
    return None


def _build_prices_dict(prices_df: pd.DataFrame,
                       as_of: pd.Timestamp) -> dict[str, float]:
    """Return {symbol: close_price} for as_of."""
    if as_of not in prices_df.index:
        return {}
    row = prices_df.loc[as_of]
    return {sym: float(p) for sym, p in row.items() if pd.notna(p) and p > 0}


def _write_orders_csv(path: Path, trader: EventPaperTrader,
                       as_of: pd.Timestamp, summary: dict) -> None:
    """Write today's orders (trades that happened during process_day) to CSV."""
    today_str = as_of.strftime("%Y-%m-%d")
    today_trades = [t for t in trader.trades if t["date"] == today_str]
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(
            f, fieldnames=["date", "symbol", "action", "shares", "price",
                           "cost", "reason"])
        writer.writeheader()
        for t in today_trades:
            reason = "exit" if t["action"] == "sell" else "entry"
            writer.writerow({**t, "reason": reason})


def _write_daily_report(path: Path, as_of: pd.Timestamp,
                        summary: dict, kill: KillReport,
                        trader: EventPaperTrader) -> None:
    """Write Markdown daily report per spec v2 §6."""
    today = as_of.strftime("%Y-%m-%d")
    nav_series = trader.nav_series()
    pnl_today = 0.0
    cum_pnl = 0.0
    if len(nav_series) >= 1:
        today_nav = nav_series.iloc[-1]
        cum_pnl = today_nav - DEFAULT_INITIAL_CAPITAL
        if len(nav_series) >= 2:
            pnl_today = today_nav - nav_series.iloc[-2]

    active = trader.active_positions_df()
    open_entries = trader.open_entries

    # Header reflects current config (v3 BB-only or v2 ensemble)
    cfg = _load_config()
    legs_on = [k for k, v in cfg.get("legs_enabled", {}).items() if v]
    legs_label = " + ".join(legs_on).upper() or "NONE"
    spec_ver = cfg.get("spec_version", "?")
    lines = [
        f"# Paper-Trade Daily Report — {today}",
        "",
        f"_{cfg.get('strategy_id', 'paper-trade')} — legs={legs_label}, spec {spec_ver}_",
        "",
        "## 当日 PnL",
        "",
        f"- 当日 PnL: **{pnl_today:+,.2f}** 元",
        f"- 累计 PnL: **{cum_pnl:+,.2f}** 元 (self NAV, relative initial)",
        f"- NAV: {summary['nav_after']:,.2f}",
        f"- Cash: {summary['cash_after']:,.2f}",
        f"- Gross weight: {summary['gross_weight']:.3f}",
        "",
        "## 交易",
        "",
        f"- 新开仓: {summary['n_buys']}",
        f"- 到期平仓: {summary['n_sells']}",
        f"- Turnover: {summary['turnover']:.2%}",
        f"- 跳过 (现金不足): {', '.join(summary.get('skipped_buys', [])) or '无'}",
        f"- 缺价格 (事件有信号但无价): {', '.join(summary.get('dropped_no_price', [])) or '无'}",
        f"- 重复 (cron 重试去重): {', '.join(summary.get('duplicate_skipped', [])) or '无'}",
        "",
        "## 活仓",
        "",
        f"共 {len(active)} 个持仓, {len(open_entries)} 个未到期 entries",
        "",
    ]
    if not active.empty:
        lines.append(active.to_markdown(index=False))
        lines.append("")

    lines.extend([
        "## 风控 / Kill switch",
        "",
        f"- Action: **{kill.action.value.upper()}** (position_scale={kill.position_scale():.1f})",
        f"- 30d rolling SR: {kill.rolling_sr_30d:.2f}" if kill.rolling_sr_30d is not None
          else "- 30d rolling SR: n/a",
        f"- Live Sharpe: {kill.live_sharpe:.2f}" if kill.live_sharpe is not None
          else "- Live Sharpe: n/a",
        f"- Cum DD: {kill.cum_drawdown:.2%}" if kill.cum_drawdown is not None
          else "- Cum DD: n/a",
        f"- Monthly MDD: {kill.monthly_mdd:.2%}" if kill.monthly_mdd is not None
          else "- Monthly MDD: n/a",
        f"- Running days: {kill.running_days}",
        "",
    ])
    if kill.reasons:
        lines.append("### Kill reasons")
        for r in kill.reasons:
            lines.append(f"- {r}")
        lines.append("")
    if kill.warnings:
        lines.append("### Soft warnings")
        for w in kill.warnings:
            lines.append(f"- {w}")
        lines.append("")

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines), encoding="utf-8")


def _push_alert(kill: KillReport, alert_file: Path) -> None:
    """Spec v3 §9: alert push. stderr 行 + alerts.log 持久化 + macOS 本地通知
    (osascript display notification). Slack/邮件若未来配置可在这里接入."""
    if kill.action == KillAction.OK:
        return
    line = (f"[{kill.as_of}] {kill.action.value.upper()} — "
            f"{'; '.join(kill.reasons)}")
    print(f"[ALERT] {line}", file=sys.stderr)
    alert_file.parent.mkdir(parents=True, exist_ok=True)
    with open(alert_file, "a", encoding="utf-8") as f:
        f.write(line + "\n")
    # macOS 本地通知 (darwin); 其他 OS 跳过
    try:
        import platform, shlex, subprocess
        if platform.system() == "Darwin":
            title = f"Paper-trade {kill.action.value.upper()}"
            body = "; ".join(kill.reasons)[:120] or str(kill.as_of)
            script = (f'display notification {shlex.quote(body)} '
                      f'with title {shlex.quote(title)}')
            subprocess.run(["osascript", "-e", script], check=False,
                            capture_output=True, timeout=5)
    except Exception as e:
        logger.warning("macOS notification failed: %s", e)


def _write_portfolio_state(state_path: Path, trader: EventPaperTrader,
                            summary: dict, kill: KillReport,
                            cfg: dict, as_of: pd.Timestamp) -> None:
    """Write portfolio/public/data/paper_trade/state.json — 供可视化页面消费.

    包含: 最近 90 日 NAV 曲线 + 全量 NAV / 活仓 / 当日 trades / kill 状态 /
    phase / started_at / last run 时间. 设计为 self-contained, 页面无需再算任何指标.
    """
    nav = trader.nav_series()
    nav_records = [{"date": idx.strftime("%Y-%m-%d"), "nav": float(v)}
                   for idx, v in nav.items()]

    active = trader.active_positions_df()
    positions = []
    if not active.empty:
        for _, r in active.iterrows():
            positions.append({
                "symbol": str(r["symbol"]),
                "shares": int(r["shares"]) if r["shares"] == r["shares"] else 0,
                "cost_price": float(r["cost_price"]),
                "current_price": float(r["current_price"]),
                "pnl_pct": float(r["pnl_pct"]),
            })

    today_str = as_of.strftime("%Y-%m-%d")
    today_trades = [t for t in trader.trades if t["date"] == today_str]

    # NAV derived metrics — 让页面直接显示, 不重算
    init_cap = trader.initial_capital
    last_nav = float(nav.iloc[-1]) if len(nav) else init_cap
    cum_ret = last_nav / init_cap - 1 if init_cap > 0 else 0.0
    pnl_today = 0.0
    if len(nav) >= 2:
        pnl_today = float(nav.iloc[-1] - nav.iloc[-2])

    open_entries = [e.to_dict() for e in trader.open_entries]

    state = {
        "spec_version": cfg.get("spec_version", "v3"),
        "strategy_id": cfg.get("strategy_id"),
        "phase": cfg.get("phase"),
        "started_at": cfg.get("started_at"),
        "enabled": cfg.get("enabled", False),
        "initial_capital": init_cap,
        "initial_capital_pct_of_total": cfg.get("initial_capital_pct_of_total"),
        "legs_enabled": cfg.get("legs_enabled"),
        "ensemble_mix": cfg.get("ensemble_mix"),
        "last_run_ts": pd.Timestamp.now(tz="Asia/Shanghai").isoformat(),
        "last_trading_day": today_str,
        "nav_series": nav_records,
        "last_nav": last_nav,
        "cum_return": cum_ret,
        "pnl_today": pnl_today,
        "daily_summary": {
            "n_buys": int(summary.get("n_buys", 0)),
            "n_sells": int(summary.get("n_sells", 0)),
            "turnover": float(summary.get("turnover", 0.0)),
            "gross_weight": float(summary.get("gross_weight", 0.0)),
            "cash_after": float(summary.get("cash_after", 0.0)),
            "nav_after": float(summary.get("nav_after", last_nav)),
            "skipped_buys": summary.get("skipped_buys", []),
            "dropped_no_price": summary.get("dropped_no_price", []),
            "duplicate_skipped": summary.get("duplicate_skipped", []),
        },
        "today_trades": [
            {"symbol": str(t["symbol"]),
             "action": str(t["action"]),
             "shares": int(t["shares"]),
             "price": float(t["price"]),
             "cost": float(t["cost"])}
            for t in today_trades
        ],
        "positions": positions,
        "open_entries_count": len(open_entries),
        "open_entries": open_entries,
        "kill": {
            "action": kill.action.value,
            "position_scale": kill.position_scale(),
            "rolling_sr_30d": kill.rolling_sr_30d,
            "live_sharpe": kill.live_sharpe,
            "cum_drawdown": kill.cum_drawdown,
            "monthly_mdd": kill.monthly_mdd,
            "running_days": kill.running_days,
            "reasons": list(kill.reasons),
            "warnings": list(kill.warnings),
        },
    }
    state_path.parent.mkdir(parents=True, exist_ok=True)
    state_path.write_text(json.dumps(state, indent=2, ensure_ascii=False,
                                      default=float), encoding="utf-8")


def run_daily(as_of: pd.Timestamp | None = None,
              dry_run: bool = False,
              initial_capital: float = DEFAULT_INITIAL_CAPITAL) -> dict:
    """
    Main entry point for EOD paper-trade pipeline.

    Args:
        as_of: trading date (default = today in UTC+8)
        dry_run: if True, do not mutate trader state or write files
        initial_capital: starting capital for fresh trader

    Returns:
        dict with keys: date, summary, kill_action, orders_path, report_path
    """
    if as_of is None:
        as_of = pd.Timestamp.now(tz="Asia/Shanghai").normalize().tz_localize(None)
    else:
        as_of = pd.Timestamp(as_of).normalize()
    today_str = as_of.strftime("%Y-%m-%d")

    logger.info("Paper-trade daily pipeline for %s", today_str)

    # 1. Load prices (for as_of + a small history for NAV continuity)
    from pipeline.event_signal import _load_bb_events, _load_pv_events, _load_main_board_set
    bb = _load_bb_events()
    pv = _load_pv_events()
    main_board = _load_main_board_set()
    event_syms = set(bb["symbol"]).union(set(pv["symbol"])) & main_board
    # For today, we need prices for all open positions + new candidate symbols
    prices_df = load_adj_price_wide(sorted(event_syms),
                                    start="2018-01-01",
                                    end=today_str)
    if as_of not in prices_df.index:
        # 非交易日 (周末 / 中国节日 / 数据尚未就绪) — 优雅退出, 不污染 cron 日志
        logger.info("%s 不是交易日 (可能周末/节日/数据未就绪), skip", today_str)
        return {
            "date": today_str,
            "skipped": True,
            "reason": "not_a_trading_day",
            "kill_action": "ok",
            "kill_reasons": [],
            "n_signal_entries": 0,
        }
    trading_days = prices_df.index

    # Load config (spec v3: BB-only via legs_enabled.pv=false)
    cfg = _load_config()
    legs_enabled = cfg["legs_enabled"]
    ensemble_mix = cfg["ensemble_mix"]
    logger.info("  Config: legs_enabled=%s  ensemble_mix=%s", legs_enabled, ensemble_mix)

    # 2. Generate signal
    sig = generate_daily_signal(
        as_of_date=as_of,
        trading_days=trading_days,
        bb_events=bb,
        pv_events=pv,
        main_board_symbols=main_board,
        legs_enabled=legs_enabled,
    )
    logger.info("  Signal: %d new entries (BB %d adm / %d cand, PV %d adm / %d cand)",
                len(sig.new_entries),
                sig.stats["bb_admitted"], sig.stats["bb_candidates"],
                sig.stats["pv_admitted"], sig.stats["pv_candidates"])

    # 3. Load trader + process day
    portfolio_dir = PAPER_TRADE_DIR / "portfolio"
    dryrun_ctx = None
    if dry_run:
        import tempfile
        dryrun_ctx = tempfile.TemporaryDirectory(prefix="paper_dryrun_")
        portfolio_dir = Path(dryrun_ctx.name)

    trader = EventPaperTrader(initial_capital, portfolio_dir,
                               ensemble_mix=ensemble_mix)
    prices_today = _build_prices_dict(prices_df, as_of)
    summary = trader.process_day(today_str, sig.new_entries, prices_today)
    logger.info("  Summary: %s", summary)

    # 4. Kill switch
    kill = eval_kill(
        trader.nav_series(),
        as_of=as_of,
        n_positions_today=len(trader.active_positions_df()),
        turnover_today=summary["turnover"],
    )
    logger.info("  Kill: %s (%s)", kill.action.value, kill.reasons or "no triggers")

    # 5. Write reports / orders
    date_compact = today_str.replace("-", "")
    orders_path = PAPER_TRADE_DIR / f"orders_{date_compact}.csv"
    report_path = PAPER_TRADE_DIR / f"daily_report_{date_compact}.md"
    alerts_path = PAPER_TRADE_DIR / "alerts.log"
    state_path = PROJECT_ROOT / "portfolio" / "public" / "data" / "paper_trade" / "state.json"

    if not dry_run:
        _write_orders_csv(orders_path, trader, as_of, summary)
        _write_daily_report(report_path, as_of, summary, kill, trader)
        _push_alert(kill, alerts_path)
        _write_portfolio_state(state_path, trader, summary, kill, cfg, as_of)

    trader.close()
    if dryrun_ctx is not None:
        dryrun_ctx.cleanup()

    return {
        "date": today_str,
        "summary": summary,
        "kill_action": kill.action.value,
        "kill_reasons": kill.reasons,
        "orders_path": str(orders_path) if not dry_run else None,
        "report_path": str(report_path) if not dry_run else None,
        "n_signal_entries": len(sig.new_entries),
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--date", help="YYYY-MM-DD, defaults to today (Asia/Shanghai)")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--capital", type=float, default=DEFAULT_INITIAL_CAPITAL)
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    as_of = pd.Timestamp(args.date) if args.date else None
    out = run_daily(as_of, dry_run=args.dry_run, initial_capital=args.capital)

    print("\n=== Paper-trade daily result ===")
    print(json.dumps(out, indent=2, ensure_ascii=False, default=str))

    if out.get("skipped"):
        return 0  # 非交易日, 正常无事
    # 任何非 OK 都应让 cron 报警; HALVE / DO_NOT_UPGRADE / WARN 也要上浮
    return 0 if out["kill_action"] == "ok" else 1


if __name__ == "__main__":
    sys.exit(main())
