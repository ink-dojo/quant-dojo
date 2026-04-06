"""
quant_dojo run — 每日全流程自动化

一个命令完成：
  1. 数据更新（增量）
  2. 信号生成（因子计算 → 选股）
  3. 模拟调仓（买入/卖出）
  4. 风控检查（回撤/集中度/因子健康）
  5. 状态报告（持仓/绩效/告警）

全部串联，中间任何 critical 步骤失败则停止。
"""
import logging
import sys
import time
from datetime import datetime
from pathlib import Path

logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).parent.parent.parent


def run_daily(date: str = None, strategy: str = None, dry_run: bool = False):
    """执行每日全流程"""
    t0 = time.time()

    # 读取配置
    sys.path.insert(0, str(PROJECT_ROOT))
    from utils.runtime_config import get_config, get_pipeline_param

    cfg = get_config()
    if strategy is None:
        try:
            from pipeline.active_strategy import get_active_strategy
            strategy = get_active_strategy()
        except Exception:
            strategy = get_pipeline_param("default_strategy", "v7")

    print("╔═══════════════════════════════════════════════╗")
    print("║  quant-dojo 每日全流程                        ║")
    print("╚═══════════════════════════════════════════════╝")
    print(f"  策略: {strategy}")
    print(f"  模式: {'空跑' if dry_run else '实盘模拟'}")

    # ── Step 1: 确定日期 ──
    if date is None:
        date = _detect_latest_date()
    print(f"  日期: {date}")
    print(f"  时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print()

    results = {}
    halted = False

    # ── Step 2: 数据更新 ──
    print("━━━ Step 1/6: 数据更新 ━━━")
    try:
        result = _step_data_update(dry_run=dry_run)
        results["data_update"] = result
        print(f"  [OK] {result.get('summary', '完成')}")
    except Exception as e:
        print(f"  [跳过] 数据更新失败: {e}")
        print("         继续使用现有数据")
        results["data_update"] = {"status": "skipped", "error": str(e)}

    # ── Step 3: 信号生成 ──
    print("\n━━━ Step 2/6: 信号生成 ━━━")
    try:
        result = _step_signal(date=date, strategy=strategy, dry_run=dry_run)
        results["signal"] = result
        n_picks = result.get("n_picks", 0)
        print(f"  [OK] 选出 {n_picks} 只股票")
        top = result.get("top_picks", [])
        if top:
            print(f"  Top 5: {', '.join(top[:5])}")
    except Exception as e:
        print(f"  [失败] 信号生成失败: {e}")
        results["signal"] = {"status": "failed", "error": str(e)}
        halted = True
        logger.error("信号生成失败", exc_info=True)

    # ── Step 4: 模拟调仓 ──
    signal_picks = results.get("signal", {}).get("top_picks", [])
    if not halted:
        print("\n━━━ Step 3/6: 模拟调仓 ━━━")
        try:
            result = _step_rebalance(date=date, strategy=strategy, dry_run=dry_run, picks=signal_picks)
            results["rebalance"] = result
            print(f"  [OK] 买入 {result.get('n_buys', 0)} / 卖出 {result.get('n_sells', 0)}")
        except Exception as e:
            print(f"  [失败] 调仓失败: {e}")
            results["rebalance"] = {"status": "failed", "error": str(e)}
            logger.error("调仓失败", exc_info=True)
    else:
        print("\n━━━ Step 3/6: 模拟调仓 ━━━")
        print("  [跳过] 信号生成失败，无法调仓")
        results["rebalance"] = {"status": "skipped"}

    # ── Step 5: 风控检查 ──
    print("\n━━━ Step 4/6: 风控检查 ━━━")
    try:
        result = _step_risk_check()
        results["risk"] = result
        level = result.get("level", "unknown")
        print(f"  [{'OK' if level == 'ok' else '注意'}] 风险等级: {level}")
        for alert in result.get("alerts", []):
            print(f"    - [{alert.get('level', '?')}] {alert.get('msg', '')}")
    except Exception as e:
        print(f"  [跳过] 风控检查失败: {e}")
        results["risk"] = {"status": "skipped", "error": str(e)}

    # ── Step 6: Dashboard 数据导出 ──
    print("\n━━━ Step 5/6: Dashboard 数据导出 ━━━")
    try:
        _step_export_dashboard()
        print("  [OK] Dashboard 数据已更新")
    except Exception as e:
        print(f"  [跳过] 导出失败: {e}")

    # ── Step 7: 状态报告 ──
    print("\n━━━ Step 6/6: 状态报告 ━━━")
    try:
        _step_show_summary(date, strategy)
    except Exception as e:
        print(f"  [跳过] 状态报告失败: {e}")

    # ── 完成 ──
    elapsed = time.time() - t0
    n_ok = sum(1 for r in results.values() if r.get("status") != "failed")
    n_fail = sum(1 for r in results.values() if r.get("status") == "failed")

    print(f"\n{'='*50}")
    print(f"  全流程完成 — {elapsed:.1f}s")
    print(f"  成功: {n_ok} | 失败: {n_fail}")
    if halted:
        print("  [注意] 流水线因关键步骤失败提前停止")
    print(f"{'='*50}")

    # 保存运行日志
    _save_run_log(date, results, elapsed)

    if n_fail > 0:
        sys.exit(1)


def _detect_latest_date() -> str:
    """自动检测最新可用交易日"""
    try:
        from utils.local_data_loader import load_price_wide, get_all_symbols
        symbols = get_all_symbols()[:10]
        pw = load_price_wide(symbols, "2020-01-01", "2099-12-31", field="close")
        if not pw.empty:
            return pw.index[-1].strftime("%Y-%m-%d")
    except Exception:
        pass

    # 降级到今天
    return datetime.now().strftime("%Y-%m-%d")


def _step_data_update(dry_run: bool = False) -> dict:
    """Step 1: 数据更新"""
    from pipeline.data_checker import check_data_freshness

    freshness = check_data_freshness()
    days_stale = freshness.get("days_stale", 0)

    if days_stale <= 1 or dry_run:
        return {
            "status": "ok",
            "summary": f"数据新鲜（延迟 {days_stale} 天）",
            "days_stale": days_stale,
        }

    # 尝试更新
    try:
        from pipeline.data_update import run_update
        result = run_update()
        n_updated = len(result.get("updated", []))
        return {
            "status": "ok",
            "summary": f"更新了 {n_updated} 只股票",
            "n_updated": n_updated,
        }
    except Exception as e:
        return {
            "status": "ok",
            "summary": f"更新失败但数据可用（延迟 {days_stale} 天）: {e}",
            "days_stale": days_stale,
        }


def _step_signal(date: str, strategy: str, dry_run: bool = False) -> dict:
    """Step 2: 信号生成"""
    if dry_run:
        return {"status": "ok", "n_picks": 0, "top_picks": [], "dry_run": True}

    from pipeline.daily_signal import run_daily_pipeline

    result = run_daily_pipeline(date=date, strategy=strategy)

    if "error" in result:
        raise RuntimeError(result["error"])

    picks = result.get("picks", [])
    return {
        "status": "ok",
        "n_picks": len(picks),
        "top_picks": picks,  # full list, used by rebalance
        "scores": result.get("scores", {}),
    }


def _step_rebalance(date: str, strategy: str, dry_run: bool = False, picks: list = None) -> dict:
    """Step 3: 模拟调仓"""
    if dry_run:
        return {"status": "ok", "n_buys": 0, "n_sells": 0, "dry_run": True}

    from live.paper_trader import PaperTrader
    from utils.local_data_loader import load_price_wide
    import json

    # 优先使用内存传递的 picks，降级到文件
    if not picks:
        signal_path = PROJECT_ROOT / "live" / "signals" / f"{date}.json"
        if not signal_path.exists():
            raise FileNotFoundError(f"信号文件不存在: {signal_path}")

        with open(signal_path) as f:
            signal = json.load(f)
        picks = signal.get("picks", [])

    if not picks:
        return {"status": "ok", "n_buys": 0, "n_sells": 0, "note": "无选股信号"}

    # 获取价格
    price_df = load_price_wide(picks, date, date, field="close")
    if price_df.empty:
        raise ValueError("无法获取当日价格")

    prices = price_df.iloc[-1].to_dict()

    # 执行调仓
    trader = PaperTrader()
    result = trader.rebalance(picks, prices, date)

    return {
        "status": "ok",
        "n_buys": result.get("n_buys", 0),
        "n_sells": result.get("n_sells", 0),
    }


def _step_risk_check() -> dict:
    """Step 4: 风控检查"""
    try:
        from live.risk_monitor import check_risk_alerts
        from live.paper_trader import PaperTrader
        import pandas as pd

        trader = PaperTrader()
        positions = trader.get_current_positions()

        if positions.empty:
            return {"status": "ok", "level": "ok", "alerts": [], "note": "无持仓"}

        alerts = check_risk_alerts()
        level = "ok"
        if any(a.get("level") == "critical" for a in alerts):
            level = "critical"
        elif any(a.get("level") == "warning" for a in alerts):
            level = "warning"

        return {"status": "ok", "level": level, "alerts": alerts}
    except Exception as e:
        return {"status": "ok", "level": "unknown", "alerts": [], "note": str(e)}


def _step_export_dashboard():
    """Step 5: 导出 Dashboard 数据"""
    from pipeline.dashboard_export import export_dashboard
    import json

    data = export_dashboard(include_ic=False)

    out_dir = PROJECT_ROOT / "live" / "dashboard"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "dashboard_data.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, default=str)


def _step_show_summary(date: str, strategy: str):
    """Step 5: 简要状态"""
    try:
        from live.paper_trader import PaperTrader
        trader = PaperTrader()
        positions = trader.get_current_positions()

        if positions.empty:
            print("  持仓: 空")
            return

        n_holdings = len(positions)
        total_value = positions.get("market_value", positions.get("value", 0))
        if hasattr(total_value, "sum"):
            total_value = total_value.sum()

        print(f"  持仓: {n_holdings} 只")
        if total_value > 0:
            print(f"  市值: ¥{total_value:,.0f}")

        # NAV
        nav_path = PROJECT_ROOT / "live" / "portfolio" / "nav.csv"
        if nav_path.exists():
            import pandas as pd
            nav_df = pd.read_csv(nav_path)
            if not nav_df.empty and "nav" in nav_df.columns:
                latest_nav = nav_df["nav"].iloc[-1]
                initial = nav_df["nav"].iloc[0]
                ret = (latest_nav / initial - 1) if initial > 0 else 0
                print(f"  NAV: ¥{latest_nav:,.0f} ({ret:+.2%})")
    except Exception as e:
        print(f"  状态获取失败: {e}")


def _save_run_log(date: str, results: dict, elapsed: float):
    """保存运行日志"""
    import json

    log_dir = PROJECT_ROOT / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)

    log = {
        "date": date,
        "timestamp": datetime.now().isoformat(),
        "elapsed_sec": round(elapsed, 2),
        "steps": {},
    }
    for step_name, result in results.items():
        log["steps"][step_name] = {
            "status": result.get("status", "unknown"),
            "error": result.get("error"),
        }

    log_path = log_dir / f"quant_dojo_run_{date}.json"
    with open(log_path, "w", encoding="utf-8") as f:
        json.dump(log, f, ensure_ascii=False, indent=2)
