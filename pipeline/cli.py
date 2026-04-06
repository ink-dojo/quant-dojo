"""
quant-dojo 控制面 CLI — 统一的操作命令入口

命令树：
  backtest run <strategy> [--start] [--end] [--param key=val ...]
  backtest list [--strategy] [--limit]
  backtest compare <run_id> <run_id> [...]
  signal run [--date]
  rebalance run --date
  risk check
  report weekly [--week]
  data status
  data update [--end-date] [--symbols] [--dry-run]
  positions
  performance
  factor-health
  doctor
  strategies

使用方式：
  python -m pipeline.cli --help
  python -m pipeline.cli backtest run multi_factor --start 2023-01-01 --end 2024-12-31
  python -m pipeline.cli backtest list
  python -m pipeline.cli signal run --date 2026-03-20
"""

import argparse
import datetime
import sys


# ══════════════════════════════════════════════════════════════
# 启动警告
# ══════════════════════════════════════════════════════════════

def _check_data_freshness_warning():
    """在 CLI 启动时检查数据新鲜度，如果数据过时则打印警告。"""
    try:
        import importlib
        data_checker = importlib.import_module("pipeline.data_checker")
        result = data_checker.check_data_freshness()
        days_stale = result.get("days_stale", 0)
        status = result.get("status", "ok")
        if status in ("stale", "missing") or days_stale >= 3:
            latest = result.get("latest_date", "未知")
            missing_count = len(result.get("missing_symbols", []))
            print(f"⚠️  [数据警告] 本地数据已 {days_stale} 个交易日未更新（最新：{latest}）", file=sys.stderr)
            if missing_count:
                print(f"⚠️  [数据警告] 有 {missing_count} 只股票数据缺失", file=sys.stderr)
    except Exception as e:
        print(f"⚠️  [数据警告] 数据新鲜度检查本身失败: {e}", file=sys.stderr)


# ══════════════════════════════════════════════════════════════
# backtest 命令组
# ══════════════════════════════════════════════════════════════

def cmd_backtest_run(args):
    """
    运行指定策略的回测，统一走 control_surface.execute

    参数:
        args: argparse 命名空间，包含 strategy, start, end, param
    """
    from pipeline.control_surface import execute

    strategy_id = args.strategy
    start = args.start
    end = args.end

    # 解析 --param key=val
    params = {}
    for pstr in (args.param or []):
        if "=" not in pstr:
            print(f"❌ 参数格式错误：'{pstr}'，应为 key=value", file=sys.stderr)
            sys.exit(1)
        k, v = pstr.split("=", 1)
        # 自动类型转换
        try:
            v = int(v)
        except ValueError:
            try:
                v = float(v)
            except ValueError:
                pass
        params[k] = v

    print(f"正在运行回测：{strategy_id}")
    print(f"  区间：{start} ~ {end}")
    if params:
        print(f"  参数：{params}")
    print()

    # 统一走控制面执行，共享审批门和持久化逻辑
    result = execute(
        "backtest.run",
        approved=True,
        strategy_id=strategy_id,
        start=start,
        end=end,
        params=params or None,
    )

    if result["status"] == "error":
        print(f"❌ 回测失败：{result['error']}", file=sys.stderr)
        sys.exit(1)

    data = result.get("data", {})
    run_id = data.get("run_id", "未知")
    metrics = data.get("metrics", {})

    # 打印结果
    print(f"{'='*55}")
    print(f"  回测完成：{strategy_id}")
    print(f"{'='*55}")
    print(f"  运行 ID ：{run_id}")
    print(f"  年化收益：{metrics.get('annualized_return', 0)*100:+.2f}%")
    print(f"  夏普比率：{metrics.get('sharpe', 0):.4f}")
    print(f"  最大回撤：{metrics.get('max_drawdown', 0)*100:.2f}%")
    print(f"  总收益率：{metrics.get('total_return', 0)*100:+.2f}%")
    print(f"  胜率    ：{metrics.get('win_rate', 0)*100:.1f}%")
    print(f"  交易天数：{metrics.get('n_trading_days', 0)}")
    print(f"{'='*55}")


def cmd_backtest_list(args):
    """
    列出历史回测运行记录

    参数:
        args: argparse 命名空间，包含可选的 strategy, limit
    """
    import importlib
    run_store = importlib.import_module("pipeline.run_store")

    strategy_id = getattr(args, "strategy", None)
    limit = getattr(args, "limit", 20)

    runs = run_store.list_runs(strategy_id=strategy_id, limit=limit)

    if not runs:
        print("暂无回测记录。使用 'backtest run <策略>' 开始第一次回测。")
        return

    print(f"\n{'运行ID':<35} {'策略':<15} {'区间':<25} {'夏普':>6} {'年化':>8} {'回撤':>8} {'状态':>6}")
    print("-" * 110)
    for r in runs:
        m = r.metrics or {}
        sharpe = f"{m.get('sharpe', 0):.2f}" if m else "-"
        ann_ret = f"{m.get('annualized_return', 0)*100:+.1f}%" if m else "-"
        mdd = f"{m.get('max_drawdown', 0)*100:.1f}%" if m else "-"
        date_range = f"{r.start_date} ~ {r.end_date}"
        status_icon = "✅" if r.status == "success" else "❌"
        print(f"{r.run_id:<35} {r.strategy_id:<15} {date_range:<25} {sharpe:>6} {ann_ret:>8} {mdd:>8} {status_icon:>6}")

    print(f"\n共 {len(runs)} 条记录")


def cmd_backtest_compare(args):
    """
    对比多个回测运行的绩效指标

    参数:
        args: argparse 命名空间，包含 run_ids 列表
    """
    import importlib
    run_store = importlib.import_module("pipeline.run_store")

    run_ids = args.run_ids
    if len(run_ids) < 2:
        print("❌ 至少需要两个运行 ID 来对比", file=sys.stderr)
        sys.exit(1)

    comparison = run_store.compare_runs(run_ids)
    runs = comparison["runs"]
    metric_names = comparison["metric_names"]

    # 过滤展示用指标
    display_metrics = [
        ("total_return", "总收益", lambda v: f"{v*100:+.2f}%"),
        ("annualized_return", "年化收益", lambda v: f"{v*100:+.2f}%"),
        ("sharpe", "夏普", lambda v: f"{v:.4f}"),
        ("max_drawdown", "最大回撤", lambda v: f"{v*100:.2f}%"),
        ("volatility", "波动率", lambda v: f"{v*100:.2f}%"),
        ("win_rate", "胜率", lambda v: f"{v*100:.1f}%"),
        ("n_trading_days", "交易天数", lambda v: f"{int(v)}"),
    ]

    # 表头
    col_width = max(25, max(len(r.get("run_id", "")) for r in runs) + 2)
    header = f"{'指标':<12}" + "".join(f"{r.get('run_id', '?'):<{col_width}}" for r in runs)
    print(f"\n{header}")
    print("-" * len(header))

    # 策略名
    row = f"{'策略':<12}" + "".join(
        f"{r.get('strategy_name', r.get('strategy_id', '?')):<{col_width}}" for r in runs
    )
    print(row)

    # 区间
    row = f"{'区间':<12}" + "".join(
        f"{r.get('start_date', '?')}~{r.get('end_date', '?'):<{col_width - len(r.get('start_date', '?')) - 1}}" for r in runs
    )
    print(row)

    print("-" * len(header))

    # 指标行
    for key, label, fmt in display_metrics:
        row = f"{label:<12}"
        for r in runs:
            metrics = r.get("metrics", {})
            if "error" in r:
                row += f"{'N/A':<{col_width}}"
            elif key in metrics:
                row += f"{fmt(metrics[key]):<{col_width}}"
            else:
                row += f"{'-':<{col_width}}"
        print(row)

    print()


# ══════════════════════════════════════════════════════════════
# signal 命令组
# ══════════════════════════════════════════════════════════════

def cmd_signal_run(args):
    """
    运行每日信号生成管道，输出选股摘要

    参数:
        args: argparse 命名空间，包含可选的 date 字段
    """
    import importlib
    daily_signal = importlib.import_module("pipeline.daily_signal")

    date = getattr(args, "date", None)
    if date is None:
        date = datetime.date.today().strftime("%Y-%m-%d")

    strategy = getattr(args, "strategy", "v7")
    print(f"正在生成 {date} 的选股信号 (strategy={strategy})...")
    result = daily_signal.run_daily_pipeline(date, strategy=strategy)

    picks = result.get("picks", [])
    scores = result.get("scores", {})
    excluded = result.get("excluded", {})

    print(f"\n{'='*50}")
    print(f"日期：{result.get('date', date)}")
    print(f"选股数量：{len(picks)} 只")
    print(f"{'='*50}")

    if picks:
        print(f"\n{'股票代码':<12} {'综合评分':>10}")
        print("-" * 25)
        for code in picks[:30]:
            score = scores.get(code, 0.0)
            print(f"{code:<12} {score:>10.4f}")

    if excluded:
        print(f"\n过滤统计：")
        for reason, count in excluded.items():
            print(f"  - {reason}：{count} 只")

    signal_path = f"live/signals/{date}.json"
    print(f"\n✅ 信号已保存到 {signal_path}")


# ══════════════════════════════════════════════════════════════
# rebalance 命令组
# ══════════════════════════════════════════════════════════════

def cmd_rebalance_run(args):
    """
    执行调仓：先生成信号，再调用 paper_trader 执行

    参数:
        args: argparse 命名空间，包含必需的 date 字段
    """
    import importlib
    import pandas as pd

    date = args.date
    print(f"正在执行 {date} 调仓...")

    # 1. 生成信号
    daily_signal = importlib.import_module("pipeline.daily_signal")
    result = daily_signal.run_daily_pipeline(date)
    picks = result.get("picks", [])
    if result.get("error"):
        raise RuntimeError(result["error"])

    local_loader = importlib.import_module("utils.local_data_loader")
    load_price_wide = local_loader.load_price_wide
    price_wide = load_price_wide(picks, date, date, field="close")
    if price_wide.empty:
        raise RuntimeError(f"无法加载 {date} 的收盘价，调仓中止")
    prices = {
        symbol: float(price_wide.iloc[-1][symbol])
        for symbol in price_wide.columns
        if pd.notna(price_wide.iloc[-1][symbol])
    }

    # 2. 执行调仓
    paper_trader_mod = importlib.import_module("live.paper_trader")
    PaperTrader = paper_trader_mod.PaperTrader
    trader = PaperTrader()
    summary = trader.rebalance(picks, prices, date)

    print(f"\n{'='*50}")
    print(f"调仓完成 | {date}")
    print(f"{'='*50}")
    print(f"  买入数量：{summary.get('n_buys', 0)} 笔")
    print(f"  卖出数量：{summary.get('n_sells', 0)} 笔")
    print(f"  换手率：{summary.get('turnover', 0)*100:.2f}%")
    print(f"  剩余现金：¥ {summary.get('cash_after', 0):,.2f}")
    print(f"  净值：¥ {summary.get('nav_after', 0):,.2f}")


# ══════════════════════════════════════════════════════════════
# risk 命令组
# ══════════════════════════════════════════════════════════════

def cmd_risk_check(args):
    """
    运行风险检查并打印预警报告

    参数:
        args: argparse 命名空间
    """
    import importlib
    paper_trader_mod = importlib.import_module("live.paper_trader")
    risk_monitor_mod = importlib.import_module("live.risk_monitor")
    PaperTrader = paper_trader_mod.PaperTrader

    trader = PaperTrader()
    alerts = risk_monitor_mod.check_risk_alerts(trader)

    print(f"\n{'='*50}")
    print("风险检查报告")
    print(f"{'='*50}\n")

    if isinstance(alerts, list):
        if not alerts:
            print("✅ 当前无风险预警")
        else:
            for alert in alerts:
                level = str(alert.get("level", "info")).lower()
                msg = alert.get("msg", str(alert))
                icon = "🔴" if level == "critical" else "🟡" if level == "warning" else "ℹ️"
                print(f"{icon} [{level}] {msg}")
    elif isinstance(alerts, dict):
        for key, val in alerts.items():
            print(f"  {key}: {val}")
    elif isinstance(alerts, str):
        print(alerts)
    else:
        print(alerts)


# ══════════════════════════════════════════════════════════════
# report 命令组
# ══════════════════════════════════════════════════════════════

def cmd_report_weekly(args):
    """
    生成每周周报

    参数:
        args: argparse 命名空间，包含可选的 week 字段
    """
    import importlib
    weekly_report_mod = importlib.import_module("pipeline.weekly_report")

    week = getattr(args, "week", None)
    report = weekly_report_mod.generate_weekly_report(week)
    print(report)


# ══════════════════════════════════════════════════════════════
# data 命令组
# ══════════════════════════════════════════════════════════════

def cmd_data_status(args):
    """
    查看本地数据 freshness 状态

    参数:
        args: argparse 命名空间
    """
    from pipeline.data_checker import check_data_freshness

    result = check_data_freshness()
    status = result.get("status", "unknown")
    latest_date = result.get("latest_date", "未知")
    days_stale = result.get("days_stale")
    missing_count = result.get("missing_count", 0)

    # 颜色 ANSI 码
    GREEN = "\033[32m"
    YELLOW = "\033[33m"
    RED = "\033[31m"
    RESET = "\033[0m"

    if status == "ok":
        color = GREEN
        icon = "✅"
    elif status == "stale":
        color = YELLOW
        icon = "⚠️ "
    else:
        color = RED
        icon = "❌"

    print(f"\n{'='*50}")
    print("数据状态检查")
    print(f"{'='*50}")
    print(f"  状态      ：{color}{icon} {status.upper()}{RESET}")
    print(f"  最新日期  ：{latest_date}")
    if days_stale is not None:
        print(f"  陈旧天数  ：{days_stale} 天")
    print(f"  缺失股票数：{missing_count}")
    print(f"{'='*50}\n")

    if status != "ok":
        sys.exit(1)


def cmd_data_update(args):
    """
    更新本地 A 股日线数据

    参数:
        args: argparse 命名空间，包含 end_date, symbols, dry_run
    """
    try:
        from pipeline.data_update import run_update
    except ImportError as e:
        print(f"❌ pipeline.data_update 模块未找到：{e}", file=sys.stderr)
        print("请先实现 pipeline/data_update.py 并提供 run_update() 函数", file=sys.stderr)
        sys.exit(1)

    end_date = getattr(args, "end_date", None)
    symbols_str = getattr(args, "symbols", None)
    dry_run = getattr(args, "dry_run", False)

    symbol_list = symbols_str.split(",") if symbols_str else None

    if dry_run:
        print("[dry-run] 模拟更新，不写文件")
    print(f"正在更新数据...")
    if end_date:
        print(f"  截止日期：{end_date}")
    if symbol_list:
        print(f"  股票范围：{len(symbol_list)} 只")
    print()

    result = run_update(symbols=symbol_list, end_date=end_date, dry_run=dry_run)

    updated = result.get("updated", [])
    skipped = result.get("skipped", [])
    failed = result.get("failed", [])

    print(f"{'='*50}")
    print(f"数据更新完成")
    print(f"{'='*50}")
    print(f"  已更新：{len(updated)} 只")
    print(f"  已跳过：{len(skipped)} 只")
    print(f"  失败  ：{len(failed)} 只")
    print(f"{'='*50}\n")

    if len(failed) > 0:
        sys.exit(1)


# ══════════════════════════════════════════════════════════════
# 独立命令
# ══════════════════════════════════════════════════════════════

def cmd_positions(args):
    """查询当前模拟盘持仓"""
    import importlib
    paper_trader_mod = importlib.import_module("live.paper_trader")
    PaperTrader = paper_trader_mod.PaperTrader

    trader = PaperTrader()
    positions = trader.get_current_positions()

    print(f"\n{'='*50}")
    print("当前持仓")
    print(f"{'='*50}")

    if positions is None or (hasattr(positions, "__len__") and len(positions) == 0):
        print("当前无持仓（模拟盘尚未开始调仓）")
        return

    try:
        import pandas as pd
        if isinstance(positions, pd.DataFrame):
            print(positions.to_string(index=True))
        elif isinstance(positions, dict):
            print(f"{'股票代码':<12} {'持仓数量':>12} {'成本价':>10} {'当前价':>10}")
            print("-" * 48)
            for code, info in positions.items():
                qty = info.get("quantity", 0)
                cost = info.get("cost_price", 0)
                current = info.get("current_price", 0)
                print(f"{code:<12} {qty:>12} {cost:>10.2f} {current:>10.2f}")
        else:
            print(positions)
    except ImportError:
        print(positions)


def cmd_performance(args):
    """查询模拟盘绩效指标"""
    import importlib
    paper_trader_mod = importlib.import_module("live.paper_trader")
    PaperTrader = paper_trader_mod.PaperTrader

    trader = PaperTrader()
    perf = trader.get_performance()

    print(f"\n{'='*50}")
    print("模拟盘绩效")
    print(f"{'='*50}")

    if isinstance(perf, dict):
        label_map = {
            "total_return": "总收益率",
            "annualized_return": "年化收益率",
            "sharpe": "夏普比率",
            "max_drawdown": "最大回撤",
            "n_trades": "交易笔数",
            "running_days": "运行天数",
        }
        for key, val in perf.items():
            label = label_map.get(key, key)
            if isinstance(val, float):
                if key in ("total_return", "annualized_return", "max_drawdown"):
                    print(f"  {label:<12}: {val*100:+.2f}%")
                elif key in ("sharpe",):
                    print(f"  {label:<12}: {val:.4f}")
                else:
                    print(f"  {label:<12}: {val:,.2f}")
            else:
                print(f"  {label:<12}: {val}")
    else:
        print(perf)


def cmd_factor_health(args):
    """运行因子健康度检查"""
    import importlib
    factor_monitor = importlib.import_module("pipeline.factor_monitor")

    preset = getattr(args, "preset", "legacy")
    preset_label = "v7（team_coin/low_vol_20d/cgo_simple/enhanced_mom_60/bp）" if preset == "v7" else "legacy（momentum_20/ep/low_vol/turnover_rev）"

    print(f"\n{'='*50}")
    print(f"因子健康度报告  [preset={preset_label}]")
    print(f"{'='*50}\n")

    factors = factor_monitor.FACTOR_PRESETS.get(preset)
    report = factor_monitor.factor_health_report(factors=factors)

    if isinstance(report, dict):
        print(f"{'因子':<20} {'近期IC均值':>12} {'状态':>10}")
        print("-" * 45)
        for factor, metrics in report.items():
            ic_mean = metrics.get("rolling_ic", 0)
            status = metrics.get("status", "-")
            ic_display = f"{ic_mean:.4f}" if ic_mean == ic_mean else "nan"
            print(f"{factor:<20} {ic_display:>12} {status:>10}")
    elif isinstance(report, str):
        print(report)
    else:
        print(report)


def cmd_strategies(args):
    """列出所有已注册策略"""
    import importlib
    strategy_reg = importlib.import_module("pipeline.strategy_registry")

    entries = strategy_reg.list_strategies()
    if not entries:
        print("暂无注册策略")
        return

    print(f"\n已注册策略 ({len(entries)} 个)：\n")
    for e in entries:
        print(f"  {e.id}")
        print(f"    名称：{e.name}")
        print(f"    描述：{e.description}")
        if e.params:
            print(f"    参数：")
            for p in e.params:
                print(f"      --param {p.name}={p.default}  ({p.type_hint}) {p.description}")
        print()


def cmd_doctor(args):
    """系统诊断 — 检查环境、数据、模块是否可用"""
    print(f"\n{'='*50}")
    print("quant-dojo 系统诊断")
    print(f"{'='*50}\n")

    checks = []

    # 1. 核心模块
    modules = [
        ("utils", "工具函数"),
        ("strategies", "策略模块"),
        ("backtest.engine", "回测引擎"),
        ("pipeline.daily_signal", "信号管道"),
        ("pipeline.strategy_registry", "策略注册表"),
        ("pipeline.run_store", "运行记录存储"),
        ("live.paper_trader", "模拟盘"),
        ("live.risk_monitor", "风险监控"),
        ("agents", "AI Agent"),
    ]

    print("模块检查：")
    for mod_name, label in modules:
        try:
            __import__(mod_name)
            print(f"  ✅ {label} ({mod_name})")
            checks.append(True)
        except Exception as e:
            print(f"  ❌ {label} ({mod_name}): {e}")
            checks.append(False)

    # 2. 策略注册表
    print("\n策略注册表：")
    try:
        import importlib
        reg = importlib.import_module("pipeline.strategy_registry")
        entries = reg.list_strategies()
        for e in entries:
            print(f"  ✅ {e.id}: {e.name}")
        checks.append(True)
    except Exception as e:
        print(f"  ❌ 策略注册表加载失败: {e}")
        checks.append(False)

    # 3. 数据新鲜度
    print("\n数据状态：")
    try:
        import importlib
        dc = importlib.import_module("pipeline.data_checker")
        result = dc.check_data_freshness()
        status = result.get("status", "unknown")
        latest = result.get("latest_date", "未知")
        icon = "✅" if status == "ok" else "⚠️"
        print(f"  {icon} 最新数据日期：{latest}（状态：{status}）")
        checks.append(status == "ok")
    except Exception as e:
        print(f"  ⚠️  数据检查跳过: {e}")

    # 4. 运行记录
    print("\n运行记录：")
    try:
        import importlib
        rs = importlib.import_module("pipeline.run_store")
        runs = rs.list_runs(limit=5)
        print(f"  ℹ️  历史运行：{len(runs)} 条")
    except Exception as e:
        print(f"  ⚠️  运行记录检查跳过: {e}")

    # 汇总
    ok = sum(1 for c in checks if c)
    total = len(checks)
    print(f"\n{'='*50}")
    print(f"诊断结果：{ok}/{total} 项通过")
    if ok == total:
        print("✅ 系统状态正常")
    else:
        print("⚠️  部分组件异常，请检查上方详情")
    print(f"{'='*50}")


# ══════════════════════════════════════════════════════════════
# CLI 主入口
# ══════════════════════════════════════════════════════════════

def main():
    """CLI 主入口，构建层级命令树并分发"""
    parser = argparse.ArgumentParser(
        prog="pipeline.cli",
        description="quant-dojo 控制面 — 统一的量化策略操作命令",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  %(prog)s strategies                              列出可用策略
  %(prog)s backtest run multi_factor --start 2023-01-01 --end 2024-12-31
  %(prog)s backtest list                           查看历史回测
  %(prog)s backtest compare RUN_ID_1 RUN_ID_2      对比两次回测
  %(prog)s signal run --date 2026-03-20 --strategy v7  生成选股信号
  %(prog)s rebalance run --date 2026-03-20         执行调仓
  %(prog)s risk check                              风险检查
  %(prog)s report weekly --week 2026-W12           生成周报
  %(prog)s data status                             查看数据新鲜度
  %(prog)s data update --end-date 2026-03-24       更新数据
  %(prog)s doctor                                  系统诊断
""",
    )
    subparsers = parser.add_subparsers(dest="command", help="命令组")

    # ── backtest ─────────────────────────────────────────────
    p_bt = subparsers.add_parser("backtest", help="回测管理（运行/列表/对比）")
    bt_sub = p_bt.add_subparsers(dest="bt_action")

    # backtest run
    p_bt_run = bt_sub.add_parser("run", help="运行策略回测")
    p_bt_run.add_argument("strategy", type=str, help="策略 ID（用 'strategies' 命令查看可用策略）")
    p_bt_run.add_argument("--start", type=str, required=True, help="开始日期 YYYY-MM-DD")
    p_bt_run.add_argument("--end", type=str, required=True, help="结束日期 YYYY-MM-DD")
    p_bt_run.add_argument("--param", type=str, nargs="*", help="策略参数 key=value（可多个）")

    # backtest list
    p_bt_list = bt_sub.add_parser("list", help="列出历史回测记录")
    p_bt_list.add_argument("--strategy", type=str, default=None, help="按策略 ID 过滤")
    p_bt_list.add_argument("--limit", type=int, default=20, help="返回条数（默认 20）")

    # backtest compare
    p_bt_cmp = bt_sub.add_parser("compare", help="对比多次回测")
    p_bt_cmp.add_argument("run_ids", type=str, nargs="+", help="运行 ID（至少两个）")

    # ── signal ───────────────────────────────────────────────
    # 同时支持 `signal --date` (旧) 和 `signal run --date` (新)
    p_sig = subparsers.add_parser("signal", help="信号生成")
    p_sig.add_argument("--date", type=str, default=None, help="日期 YYYY-MM-DD（默认今日）")
    sig_sub = p_sig.add_subparsers(dest="sig_action")

    p_sig_run = sig_sub.add_parser("run", help="运行每日选股信号生成")
    p_sig_run.add_argument("--date", type=str, default=None, help="日期 YYYY-MM-DD（默认今日）")
    p_sig_run.add_argument("--strategy", type=str, choices=["ad_hoc", "v7"], default="v7",
                           help="因子策略（默认 v7）")

    # ── rebalance ────────────────────────────────────────────
    # 同时支持 `rebalance --date` (旧) 和 `rebalance run --date` (新)
    p_reb = subparsers.add_parser("rebalance", help="调仓操作")
    p_reb.add_argument("--date", type=str, default=None, help="调仓日期 YYYY-MM-DD")
    reb_sub = p_reb.add_subparsers(dest="reb_action")

    p_reb_run = reb_sub.add_parser("run", help="执行调仓")
    p_reb_run.add_argument("--date", type=str, required=True, help="调仓日期 YYYY-MM-DD")

    # ── risk ─────────────────────────────────────────────────
    p_risk = subparsers.add_parser("risk", help="风险管理")
    risk_sub = p_risk.add_subparsers(dest="risk_action")

    risk_sub.add_parser("check", help="运行风险预警检查")

    # ── report ───────────────────────────────────────────────
    p_rep = subparsers.add_parser("report", help="报告生成")
    rep_sub = p_rep.add_subparsers(dest="rep_action")

    p_rep_weekly = rep_sub.add_parser("weekly", help="生成每周周报")
    p_rep_weekly.add_argument("--week", type=str, default=None, help="周 YYYY-Www（默认当周）")

    # ── data ─────────────────────────────────────────────────
    p_data = subparsers.add_parser("data", help="数据管理（状态/更新）")
    data_sub = p_data.add_subparsers(dest="data_action")

    data_sub.add_parser("status", help="查看本地数据 freshness 状态")

    p_data_update = data_sub.add_parser("update", help="更新本地 A 股日线数据")
    p_data_update.add_argument("--end-date", dest="end_date", type=str, default=None,
                               help="更新截止日期 YYYY-MM-DD")
    p_data_update.add_argument("--symbols", type=str, default=None,
                               help="逗号分隔的股票代码，不填则全量")
    p_data_update.add_argument("--dry-run", dest="dry_run", action="store_true",
                               help="只打印，不写文件")

    # ── live ─────────────────────────────────────────────────
    p_live = subparsers.add_parser("live", help="实时数据服务")
    live_sub = p_live.add_subparsers(dest="live_action")

    p_live_quote = live_sub.add_parser("quote", help="查看实时行情")
    p_live_quote.add_argument("symbols", nargs="*", help="股票代码（不填则用持仓）")

    p_live_poll = live_sub.add_parser("poll", help="盘中实时轮询")
    p_live_poll.add_argument("--interval", type=int, default=5, help="间隔秒数")

    live_sub.add_parser("eod", help="执行收盘后 EOD 更新")

    # ── 独立命令 ─────────────────────────────────────────────
    subparsers.add_parser("positions", help="查看当前模拟盘持仓")
    subparsers.add_parser("performance", help="查看模拟盘绩效指标")
    p_fh = subparsers.add_parser("factor-health", help="因子健康度检查")
    p_fh.add_argument(
        "--preset",
        type=str,
        choices=["legacy", "v7"],
        default="legacy",
        help="因子集预设：legacy（momentum_20/ep/low_vol/turnover_rev）或 v7（team_coin/low_vol_20d/cgo_simple/enhanced_mom_60/bp）",
    )
    subparsers.add_parser("strategies", help="列出所有已注册策略")
    subparsers.add_parser("doctor", help="系统诊断")

    # ── 兼容旧命令 ─────────────────────────────────────────
    # weekly-report 和 risk-check 保留为独立子命令（旧脚本直接用）
    _p_wr_compat = subparsers.add_parser("weekly-report", help="生成每周周报（兼容旧命令）")
    _p_wr_compat.add_argument("--week", type=str, default=None)

    _p_rc_compat = subparsers.add_parser("risk-check", help="风险检查（兼容旧命令）")

    # ── 解析 ─────────────────────────────────────────────────
    args = parser.parse_args()

    if args.command is None:
        parser.print_help()
        sys.exit(0)

    # 启动时检查数据新鲜度
    _check_data_freshness_warning()

    # ── 分发 ─────────────────────────────────────────────────
    dispatch = {
        # 独立命令
        "positions": cmd_positions,
        "performance": cmd_performance,
        "factor-health": cmd_factor_health,
        "strategies": cmd_strategies,
        "doctor": cmd_doctor,
        # 兼容旧命令
        "weekly-report": cmd_report_weekly,
        "risk-check": cmd_risk_check,
    }

    # 先检查独立命令
    handler = dispatch.get(args.command)
    if handler:
        try:
            handler(args)
        except Exception as e:
            print(f"❌ 执行失败：{e}", file=sys.stderr)
            sys.exit(1)
        return

    # 层级命令分发
    if args.command == "backtest":
        bt_dispatch = {
            "run": cmd_backtest_run,
            "list": cmd_backtest_list,
            "compare": cmd_backtest_compare,
        }
        action = getattr(args, "bt_action", None)
        if action is None:
            p_bt.print_help()
            sys.exit(0)
        handler = bt_dispatch.get(action)
    elif args.command == "signal":
        action = getattr(args, "sig_action", None)
        if action is None:
            # 兼容旧用法：`signal --date YYYY-MM-DD` 等价于 `signal run --date`
            handler = cmd_signal_run
        else:
            handler = {"run": cmd_signal_run}.get(action)
    elif args.command == "rebalance":
        action = getattr(args, "reb_action", None)
        if action is None:
            # 兼容旧用法：`rebalance --date YYYY-MM-DD` 等价于 `rebalance run --date`
            if getattr(args, "date", None):
                handler = cmd_rebalance_run
            else:
                p_reb.print_help()
                sys.exit(0)
        else:
            handler = {"run": cmd_rebalance_run}.get(action)
    elif args.command == "risk":
        action = getattr(args, "risk_action", None)
        if action is None:
            p_risk.print_help()
            sys.exit(0)
        handler = {"check": cmd_risk_check}.get(action)
    elif args.command == "report":
        action = getattr(args, "rep_action", None)
        if action is None:
            p_rep.print_help()
            sys.exit(0)
        handler = {"weekly": cmd_report_weekly}.get(action)
    elif args.command == "data":
        action = getattr(args, "data_action", None)
        if action is None:
            p_data.print_help()
            sys.exit(0)
        handler = {
            "status": cmd_data_status,
            "update": cmd_data_update,
        }.get(action)
    elif args.command == "live":
        action = getattr(args, "live_action", None)
        if action is None:
            p_live.print_help()
            sys.exit(0)
        if action == "quote":
            def _live_quote(a):
                try:
                    from providers.sina_provider import fetch_realtime_quotes
                except ImportError:
                    print("❌ providers.sina_provider 不可用，请确认 providers/ 目录完整", file=sys.stderr)
                    sys.exit(1)
                syms = a.symbols if a.symbols else ["600000", "000001", "600519"]
                quotes = fetch_realtime_quotes(syms)
                print(f"\n{'代码':<8} {'名称':<10} {'现价':>8} {'涨跌':>8} {'成交额':>10}")
                print("-" * 50)
                for s, q in quotes.items():
                    pnl = (q['price']/q['prev_close']-1)*100 if q['prev_close']>0 else 0
                    print(f"{s:<8} {q['name']:<10} {q['price']:>8.2f} {pnl:>+7.2f}% {q['amount']/1e8:>9.1f}亿")
            handler = _live_quote
        elif action == "poll":
            def _live_poll(a):
                try:
                    from pipeline.live_data_service import poll_realtime
                except ImportError:
                    print("❌ pipeline.live_data_service 不可用", file=sys.stderr)
                    sys.exit(1)
                poll_realtime(interval=a.interval)
            handler = _live_poll
        elif action == "eod":
            def _live_eod(a):
                try:
                    from pipeline.live_data_service import run_eod_update
                except ImportError:
                    print("❌ pipeline.live_data_service 不可用", file=sys.stderr)
                    sys.exit(1)
                run_eod_update()
            handler = _live_eod
        else:
            handler = None
    else:
        handler = None

    if handler is None:
        print(f"未知命令：{args.command}", file=sys.stderr)
        parser.print_help()
        sys.exit(1)

    try:
        handler(args)
    except Exception as e:
        print(f"❌ 执行失败：{e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
