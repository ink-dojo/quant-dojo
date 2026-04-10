"""
quant_dojo status — 系统全局状态一览

一个命令看到：
  - 数据新鲜度
  - 当前持仓
  - 绩效指标
  - 最新信号
  - 风险等级
  - 最近回测
"""
import json
import sys
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent.parent


def show_status():
    """显示系统全局状态"""
    sys.path.insert(0, str(PROJECT_ROOT))

    print("╔═══════════════════════════════════════════════╗")
    print("║  quant-dojo 系统状态                          ║")
    print("╚═══════════════════════════════════════════════╝")
    print(f"  时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")

    _show_data_status()
    _show_strategy_status()
    _show_signal_status()
    _show_portfolio_status()
    _show_risk_status()
    _show_last_run()
    _show_recent_backtests()
    _show_backtest_divergence()

    print()


def _show_data_status():
    """数据新鲜度"""
    print("━━━ 数据 ━━━")
    try:
        from pipeline.data_checker import check_data_freshness
        info = check_data_freshness()
        latest = info.get("latest_date", "?")
        stale = info.get("days_stale")
        if stale is None:
            icon = "?"
        elif stale <= 1:
            icon = "OK"
        elif stale <= 3:
            icon = "注意"
        else:
            icon = "过期"
        stale_str = f"{stale} 天" if stale is not None else "未知"
        print(f"  [{icon}] 最新数据: {latest} (延迟 {stale_str})")
    except Exception as e:
        print(f"  [?] 无法检查数据状态: {e}")

    # 数据量
    try:
        from utils.local_data_loader import get_all_symbols
        symbols = get_all_symbols()
        print(f"  股票数: {len(symbols)}")
    except Exception:
        pass
    print()


def _show_strategy_status():
    """当前策略"""
    print("━━━ 策略 ━━━")
    try:
        from pipeline.active_strategy import get_active_strategy
        info = get_active_strategy()
        name = info.get("strategy", "v7") if isinstance(info, dict) else info
        print(f"  当前策略: {name}")
    except Exception:
        print("  当前策略: v7 (默认)")
    print()


def _show_signal_status():
    """最新信号"""
    print("━━━ 信号 ━━━")
    signal_dir = PROJECT_ROOT / "live" / "signals"
    if not signal_dir.exists():
        print("  无信号记录")
        print()
        return

    signal_files = sorted(signal_dir.glob("*.json"), reverse=True)
    if not signal_files:
        print("  无信号记录")
        print()
        return

    latest = signal_files[0]
    try:
        with open(latest) as f:
            sig = json.load(f)
        date = sig.get("date", latest.stem)
        picks = sig.get("picks", [])
        print(f"  最新信号: {date} ({len(picks)} 只)")
        if picks:
            print(f"  Top 5: {', '.join(picks[:5])}")
    except Exception as e:
        print(f"  信号读取失败: {e}")
    print()


def _show_portfolio_status():
    """持仓与绩效"""
    print("━━━ 持仓 ━━━")

    # 持仓
    pos_path = PROJECT_ROOT / "live" / "portfolio" / "positions.json"
    if pos_path.exists():
        try:
            with open(pos_path) as f:
                positions = json.load(f)
            # 排除 __cash__ 等 meta 字段
            holdings = {k: v for k, v in positions.items() if not k.startswith("_")}
            cash = positions.get("__cash__", 0)
            print(f"  持仓: {len(holdings)} 只")
            if cash:
                print(f"  现金: ¥{cash:,.0f}")
        except Exception:
            print("  持仓: 读取失败")
    else:
        print("  持仓: 空（未开始交易）")

    # NAV
    nav_path = PROJECT_ROOT / "live" / "portfolio" / "nav.csv"
    if nav_path.exists():
        try:
            import pandas as pd
            nav_df = pd.read_csv(nav_path)
            if not nav_df.empty and "nav" in nav_df.columns:
                latest = nav_df["nav"].iloc[-1]
                initial = nav_df["nav"].iloc[0]
                n_days = len(nav_df)
                ret = (latest / initial - 1) if initial > 0 else 0
                print(f"  NAV: ¥{latest:,.0f} ({ret:+.2%})")
                print(f"  交易天数: {n_days}")

                # 简单回撤
                peak = nav_df["nav"].cummax()
                dd = ((nav_df["nav"] - peak) / peak).min()
                print(f"  最大回撤: {dd:.2%}")
        except Exception:
            pass
    print()


def _show_risk_status():
    """风险等级"""
    print("━━━ 风控 ━━━")
    try:
        from live.risk_monitor import check_risk_alerts
        from live.paper_trader import PaperTrader

        trader = PaperTrader()
        positions = trader.get_current_positions()

        if positions.empty:
            print("  [OK] 无持仓，无风险")
            print()
            return

        alerts = check_risk_alerts(trader)
        if not alerts:
            print("  [OK] 无告警")
        else:
            for a in alerts:
                level = a.get("level", "info").upper()
                msg = a.get("msg", "")
                print(f"  [{level}] {msg}")
    except Exception as e:
        print(f"  [?] 风控检查失败: {e}")
    print()


def _show_last_run():
    """最近一次运行"""
    print("━━━ 最近运行 ━━━")
    log_dir = PROJECT_ROOT / "logs"
    if not log_dir.exists():
        print("  尚无运行记录")
        print()
        return

    log_files = sorted(log_dir.glob("quant_dojo_run_*.json"), reverse=True)
    if not log_files:
        print("  尚无运行记录")
        print()
        return

    try:
        data = json.loads(log_files[0].read_text(encoding="utf-8"))
        date = data.get("date", "?")
        ts = data.get("timestamp", "")[:19]
        elapsed = data.get("elapsed_sec", 0)
        steps = data.get("steps", {})
        n_fail = sum(1 for s in steps.values() if s.get("status") == "failed")
        mark = "OK" if n_fail == 0 else f"FAIL ({n_fail})"
        print(f"  [{mark}] {date}  {ts}  {elapsed:.1f}s")
    except Exception:
        print("  日志读取失败")
    print()


def _show_recent_backtests():
    """最近回测记录 — 复用 history._load_backtest_runs 作为单一真相源"""
    print("━━━ 回测 ━━━")
    try:
        from quant_dojo.commands.history import _load_backtest_runs
    except Exception:
        print("  [?] 无法加载 history 模块")
        return

    all_rows = _load_backtest_runs()
    if not all_rows:
        print("  无回测记录")
        return

    success = [r for r in all_rows if r.get("status") == "success"]
    n_failed = sum(1 for r in all_rows if r.get("status") == "failed")

    if not success:
        print("  无成功的回测记录")
        if n_failed > 0:
            print(f"  ({n_failed} 个失败记录已隐藏)")
        return

    # 按 created_at 倒序，取前 3 条
    success.sort(key=lambda r: r.get("created_at") or r.get("run_id", ""), reverse=True)
    for r in success[:3]:
        rid = (r.get("run_id") or "?")[:30]
        strategy = r.get("strategy") or "?"
        ret = r.get("total_return") or 0
        sharpe = r.get("sharpe") or 0
        print(f"  {rid} | {strategy} | 收益 {ret:+.2%} | 夏普 {sharpe:.2f}")

    if n_failed > 0:
        print(f"  ({n_failed} 个失败记录已隐藏)")


def _show_backtest_divergence():
    """实盘 vs 最近一次成功回测 的 NAV 偏差（摘要）"""
    print()
    print("━━━ 偏差 (live vs backtest) ━━━")

    runs_dir = PROJECT_ROOT / "live" / "runs"
    nav_path = PROJECT_ROOT / "live" / "portfolio" / "nav.csv"
    if not runs_dir.exists() or not nav_path.exists():
        print("  无可用数据")
        return

    # 找到最新的成功回测 run（必须带 equity_csv）
    latest = None
    for p in sorted(runs_dir.glob("*.json"),
                    key=lambda f: f.stat().st_mtime, reverse=True):
        try:
            with open(p) as f:
                data = json.load(f)
        except Exception:
            continue
        if data.get("status") != "success":
            continue
        if not data.get("artifacts", {}).get("equity_csv"):
            continue
        latest = p
        break

    if latest is None:
        print("  无成功的回测记录")
        return

    try:
        from pipeline.live_vs_backtest import compute_divergence
        div = compute_divergence(live_nav_path=nav_path, backtest_run_path=latest)
    except Exception as e:
        print(f"  [?] 计算失败: {e}")
        return

    if div.get("status") != "ok":
        print(f"  [?] 无法对照: {div.get('reason', div.get('status'))}")
        return

    s = div["summary"]
    n = s["n_overlap_days"]
    gap = s["total_delta"]
    std_dd = s["std_daily_delta"]

    if abs(gap) < 0.005:
        tag = "跟踪良好"
    elif abs(s["mean_daily_delta"]) < 1e-4 and std_dd > 0.005:
        tag = "纯噪声（无漂移）"
    elif gap < 0:
        tag = f"系统性少赚 {abs(gap):.2%}"
    else:
        tag = f"系统性多赚 {abs(gap):.2%}"

    print(f"  基于 {latest.stem} ({n} 天共同窗口)")
    print(f"  live {s['live_total_return']:+.2%}  bt {s['backtest_total_return']:+.2%}  "
          f"gap {gap:+.2%}  σ {std_dd:.2%}")
    print(f"  结论: {tag}")
    print(f"  详情: python -m quant_dojo diff {latest.stem}")
