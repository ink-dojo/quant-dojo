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


def _load_dotenv():
    """加载项目根目录的 .env 文件（若存在），将变量注入 os.environ。"""
    import os
    from pathlib import Path
    env_path = Path(__file__).parent.parent / ".env"
    if not env_path.exists():
        return
    try:
        import dotenv
        dotenv.load_dotenv(env_path)
        return
    except ImportError:
        pass
    # dotenv 未安装时手动解析
    with open(env_path) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, val = line.partition("=")
            key = key.strip()
            val = val.strip().strip('"').strip("'")
            if key and key not in os.environ:
                os.environ[key] = val


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
    # 若未指定 start/end，使用默认值：start = 三年前，end = 昨天
    today = datetime.date.today()
    if args.start:
        start = args.start
    else:
        # 安全处理闰年 2 月 29 日：回退到 2 月 28 日
        try:
            start = today.replace(year=today.year - 3).strftime("%Y-%m-%d")
        except ValueError:
            start = today.replace(year=today.year - 3, day=28).strftime("%Y-%m-%d")
    end = args.end or (today - datetime.timedelta(days=1)).strftime("%Y-%m-%d")

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

    # 记录当日 NAV 快照（即使未调仓也要追踪净值变化）
    try:
        paper_trader_mod = importlib.import_module("live.paper_trader")
        trader = paper_trader_mod.PaperTrader()
        nav_result = trader.record_nav(trade_date=date)
        print(f"  NAV 已记录: {nav_result['date']} -> ¥{nav_result['nav']:,.2f}")
    except Exception as e:
        print(f"⚠️  NAV 记录失败（不影响信号生成）: {e}", file=sys.stderr)


# ══════════════════════════════════════════════════════════════
# rebalance 命令组
# ══════════════════════════════════════════════════════════════

def _get_trade_calendar(year: int) -> set:
    """
    获取指定年份的 A 股交易日集合。

    策略（按优先级）：
    1. 从本地任意一只股票 CSV 中读取当年出现过的日期（最权威，无需网络）
    2. Tushare trade_cal（需高积分，通常不可用）
    3. 返回空集合，由调用方降级为纯周末过滤

    参数:
        year: 4 位年份整数

    返回:
        set[str]：该年所有交易日 YYYY-MM-DD 字符串，空集表示不可用
    """
    import logging as _log
    import pandas as _pd
    from pathlib import Path as _Path

    _logger = _log.getLogger(__name__)

    # ── 方案 1：本地 CSV 数据（最可靠）──────────────────────────
    # 支持中文列名（baostock: 交易所行情日期）和英文列名（tushare: date）
    try:
        from utils.runtime_config import get_local_data_dir
        data_dir = get_local_data_dir()
        for probe in ("sz.000001.csv", "sh.600000.csv", "sz.000002.csv"):
            csv_path = data_dir / probe
            if not csv_path.exists():
                continue
            raw = _pd.read_csv(csv_path, encoding="utf-8-sig", nrows=0)
            # 找日期列（兼容中英文）
            date_col = next(
                (c for c in raw.columns if c in ("date", "交易所行情日期")), None
            )
            if date_col is None:
                continue
            df = _pd.read_csv(csv_path, usecols=[date_col], encoding="utf-8-sig")
            df[date_col] = _pd.to_datetime(df[date_col], errors="coerce")
            year_dates = df[df[date_col].dt.year == year][date_col].dropna()
            if len(year_dates) >= 30:  # 至少 30 个交易日（约 1.5 个月）即可信
                return set(year_dates.dt.strftime("%Y-%m-%d").tolist())
    except Exception as e:
        _logger.debug("本地 CSV 交易日历读取失败: %s", e)

    # ── 方案 2：Tushare trade_cal（需高积分，通常降级）──────────
    try:
        _load_dotenv()
        import os
        import tushare as _ts
        token = os.environ.get("TUSHARE_TOKEN", "")
        if token:
            _ts.set_token(token)
            pro = _ts.pro_api()
            cal = pro.trade_cal(
                exchange="SSE",
                start_date=f"{year}0101",
                end_date=f"{year}1231",
                is_open="1",
            )
            if cal is not None and not cal.empty:
                dates = set()
                for raw in cal["cal_date"]:
                    dates.add(f"{raw[:4]}-{raw[4:6]}-{raw[6:]}")
                return dates
    except Exception as e:
        _logger.debug("Tushare trade_cal 不可用: %s", e)

    # ── 方案 3：无法获取，返回空集，由调用方降级 ─────────────────
    _logger.warning("无法获取 %d 年交易日历，节假日将被误判为交易日", year)
    return set()


def _prev_trading_date(date_str: str) -> str:
    """
    获取给定日期的前一个 A 股交易日。

    逻辑：
    1. 先尝试从交易日历中找到真正的前一交易日（处理节假日）
    2. 交易日历不可用时，退化为跳过周末

    参数:
        date_str: 日期字符串，格式 YYYY-MM-DD

    返回:
        前一交易日字符串，格式 YYYY-MM-DD
    """
    import datetime as _dt

    d = _dt.date.fromisoformat(date_str)

    # 往前最多查 14 天（覆盖 7 天节假日 + 2 个周末）
    for _ in range(14):
        d -= _dt.timedelta(days=1)
        d_str = d.isoformat()

        # 先跳过周末（最快路径）
        if d.weekday() >= 5:
            continue

        # 检查交易日历
        cal = _get_trade_calendar(d.year)
        if not cal:
            # fallback：周末已跳过，直接返回
            return d_str
        if d_str in cal:
            return d_str

    # 安全兜底（极端情况）
    return d.isoformat()


def cmd_prev_trading_date(args):
    """
    输出给定日期的前一个 A 股交易日，供 shell 脚本调用。

    用法:
        python -m pipeline.cli prev-trading-date 2026-04-13
        → 2026-04-10
    """
    import datetime as _dt
    date_str = args.date or _dt.date.today().isoformat()
    print(_prev_trading_date(date_str))


def cmd_rebalance_run(args):
    """
    执行调仓：读取前一交易日信号，用当日开盘价成交。

    正确的模拟盘时序：
      T 日收盘后：signal run --date T  →  保存信号到 live/signals/T.json
      T+1 日开盘后：rebalance run --date T+1  →  读 T 日信号，用 T+1 开盘价成交

    参数:
        args: argparse 命名空间，包含必需的 date 字段（T+1 交易日）
    """
    import importlib
    import json
    import pandas as pd
    from pathlib import Path

    # date = T+1 日（今天的交易日，开盘后执行）
    date = args.date
    print(f"正在执行 {date} 调仓（T+1 开盘成交模式）...")

    # 1. 计算前一交易日（信号日 = T 日）
    signal_date = _prev_trading_date(date)
    print(f"  信号日期：{signal_date}（前一交易日）")
    print(f"  成交日期：{date}（当日开盘价）")

    # 2. 读取 T 日信号文件（必须事先由 signal run --date T 生成）
    signal_dir = Path(__file__).parent.parent / "live" / "signals"
    signal_path = signal_dir / f"{signal_date}.json"
    if not signal_path.exists():
        raise RuntimeError(
            f"信号文件不存在：{signal_path}\n"
            f"请先运行：python -m pipeline.cli signal run --date {signal_date}"
        )

    with open(signal_path, "r", encoding="utf-8") as f:
        signal_data = json.load(f)

    picks = signal_data.get("picks", [])
    if not picks:
        raise RuntimeError(f"信号文件 {signal_path} 中 picks 为空，调仓中止")

    print(f"  读取信号：{len(picks)} 只股票")

    # 3. 加载 T+1 日开盘价（成交价）
    local_loader = importlib.import_module("utils.local_data_loader")
    load_price_wide = local_loader.load_price_wide

    # 优先用开盘价；如果开盘价不可用则回退到收盘价 * (1 + 0.002) 近似滑点
    price_wide = load_price_wide(picks, date, date, field="open")
    use_open = True
    if price_wide.empty:
        print(f"  ⚠ 开盘价不可用，回退到收盘价 × 1.002（近似开盘滑点）", file=sys.stderr)
        price_wide = load_price_wide(picks, date, date, field="close")
        use_open = False

    if price_wide.empty:
        raise RuntimeError(f"无法加载 {date} 的价格数据，调仓中止")

    prices = {
        symbol: float(price_wide.iloc[-1][symbol]) * (1.0 if use_open else 1.002)
        for symbol in price_wide.columns
        if pd.notna(price_wide.iloc[-1][symbol])
    }

    price_type = "open" if use_open else "close×1.002"
    print(f"  成交价格：{price_type}（共 {len(prices)} 只有效报价）")

    # 4. 执行调仓
    paper_trader_mod = importlib.import_module("live.paper_trader")
    PaperTrader = paper_trader_mod.PaperTrader
    trader = PaperTrader()
    summary = trader.rebalance(picks, prices, date)

    print(f"\n{'='*50}")
    print(f"调仓完成 | 成交日：{date} | 信号日：{signal_date}")
    print(f"{'='*50}")
    print(f"  成交价类型：{price_type}")
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
        args: argparse 命名空间，包含 end_date, symbols, dry_run, source
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
    source = getattr(args, "source", "auto")

    symbol_list = symbols_str.split(",") if symbols_str else None

    # ── 构造 provider ─────────────────────────────────────────
    provider = None
    if source == "tushare":
        # 先加载 .env（若存在）
        _load_dotenv()
        import os
        token = os.environ.get("TUSHARE_TOKEN", "")
        if not token:
            print("❌ 未找到 TUSHARE_TOKEN，请在 .env 中设置：", file=sys.stderr)
            print("   TUSHARE_TOKEN=你的token", file=sys.stderr)
            sys.exit(1)
        try:
            from providers.tushare_provider import TushareProvider
            provider = TushareProvider(token=token)
            print(f"✅ 使用 Tushare 批量模式（每天 1~3 次 API 调用）")
        except Exception as e:
            print(f"❌ Tushare 初始化失败: {e}", file=sys.stderr)
            sys.exit(1)

    if dry_run:
        print("[dry-run] 模拟更新，不写文件")
    print(f"正在更新数据...")
    if end_date:
        print(f"  截止日期：{end_date}")
    if symbol_list:
        print(f"  股票范围：{len(symbol_list)} 只")
    print()

    result = run_update(symbols=symbol_list, end_date=end_date,
                        dry_run=dry_run, provider=provider)

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


def cmd_pipeline_run(args):
    """执行 AI Agent 流水线"""
    from pipeline.orchestrator import build_default_pipeline

    date = getattr(args, "date", None)
    mode = getattr(args, "mode", "daily")
    dry_run = getattr(args, "dry_run", False)
    only = getattr(args, "only", None)

    orch = build_default_pipeline()

    if only:
        only_stages = set(only.split(","))
        orch.stages = [s for s in orch.stages if s.name in only_stages]

    ctx = orch.execute(date=date, mode=mode, dry_run=dry_run)

    n_failed = sum(1 for r in ctx.stage_results if r.status.value == "failed")
    if n_failed:
        sys.exit(1)


def cmd_pipeline_mine(args):
    """执行因子挖掘（快捷方式）"""
    from pipeline.orchestrator import build_default_pipeline

    date = getattr(args, "date", None)
    orch = build_default_pipeline()
    orch.stages = [s for s in orch.stages if s.name in ("factor_mine", "strategy_compose")]
    orch.execute(date=date, mode="full")


def cmd_pipeline_status(args):
    """查看流水线综合状态面板"""
    import json
    from pathlib import Path

    print(f"\n{'='*60}")
    print("  量化流水线状态面板")
    print(f"{'='*60}")

    # ── 1. 当前策略 ──────────────────────────────────────────
    try:
        from pipeline.active_strategy import get_active_strategy
        active = get_active_strategy()
        print(f"\n  当前策略: {active}")
    except Exception:
        print("\n  当前策略: v7 (默认)")

    # ── 2. NAV & 绩效 ────────────────────────────────────────
    try:
        from live.paper_trader import PaperTrader
        trader = PaperTrader()
        perf = trader.get_performance()
        if perf:
            nav_file = Path(__file__).parent.parent / "live" / "portfolio" / "nav.csv"
            import pandas as pd
            nav_df = pd.read_csv(nav_file)
            latest_nav = nav_df["nav"].iloc[-1] if not nav_df.empty else 0
            print(f"  NAV: {latest_nav:,.2f} | 收益: {perf.get('total_return', 0):.2%} | "
                  f"夏普: {perf.get('sharpe', 0):.2f} | 回撤: {perf.get('max_drawdown', 0):.2%}")
    except Exception:
        pass

    # ── 3. 最近运行 ──────────────────────────────────────────
    journal_dir = Path(__file__).parent.parent / "journal"
    files = sorted(journal_dir.glob("pipeline_*.json"), reverse=True)[:5]

    if files:
        print(f"\n  最近运行:")
        for f in files:
            try:
                data = json.loads(f.read_text(encoding="utf-8"))
                date = data.get("date", "?")
                mode = data.get("mode", "?")
                total_time = data.get("total_time_sec", 0)
                stages = data.get("stages", [])
                n_ok = sum(1 for s in stages if s["status"] == "success")
                n_fail = sum(1 for s in stages if s["status"] == "failed")
                halted = data.get("halted", False)
                status = "HALTED" if halted else "FAIL" if n_fail else "OK"
                print(f"    {date} [{mode:6s}] {status:4s} | {n_ok} ok, {n_fail} fail | {total_time:.0f}s")
            except Exception:
                pass
    else:
        print("\n  最近运行: 暂无记录")

    # ── 4. 因子健康 ──────────────────────────────────────────
    try:
        from pipeline.factor_monitor import factor_health_report, FACTOR_PRESETS
        from pipeline.active_strategy import get_active_strategy as _get
        _a = _get()
        _pk = _a if _a in FACTOR_PRESETS else "v7"
        health = factor_health_report(factors=FACTOR_PRESETS[_pk])
        if health:
            print(f"\n  因子健康 ({_pk}):")
            for name, info in health.items():
                ic = info.get("rolling_ic")
                status = info.get("status", "?")
                ic_str = f"{ic:.4f}" if ic is not None and not (isinstance(ic, float) and ic != ic) else "N/A"
                icon = {"healthy": "OK", "degraded": "WARN", "dead": "DEAD", "no_data": "N/A"}.get(status, "?")
                print(f"    {name:20s} | IC: {ic_str:>8s} | {icon}")
    except Exception:
        pass

    # ── 5. 最近告警 ──────────────────────────────────────────
    try:
        from pipeline.alert_notifier import get_recent_alerts
        alerts = get_recent_alerts(n=5)
        if alerts:
            print(f"\n  最近告警:")
            for a in alerts:
                level = a.get("level", "?").upper()
                title = a.get("title", "?")
                ts = a.get("timestamp", "")[:16]
                print(f"    [{level:8s}] {ts} {title}")
    except Exception:
        pass

    print(f"\n{'='*60}\n")


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
# research 命令组（Phase 7 AI 研究助理）
# ══════════════════════════════════════════════════════════════

def _collect_system_state():
    """
    读取当前因子健康度 / 风险告警 / 实盘回测偏差，作为 planner 输入。
    任一步失败都只打印警告并回退成空 dict，不让 CLI 整体挂掉。
    """
    factor_health = {}
    risk_alerts: list = []
    divergence = {}
    try:
        from pipeline.factor_monitor import factor_health_report
        factor_health = factor_health_report() or {}
    except Exception as e:
        print(f"⚠️  factor_health_report 不可用: {e}", file=sys.stderr)
    try:
        from live.paper_trader import PaperTrader
        from live.risk_monitor import check_risk_alerts
        risk_alerts = check_risk_alerts(PaperTrader()) or []
    except Exception as e:
        print(f"⚠️  risk_alerts 不可用: {e}", file=sys.stderr)
    try:
        from pipeline.live_vs_backtest import compute_divergence
        divergence = compute_divergence() or {}
    except Exception as e:
        print(f"⚠️  divergence 不可用: {e}", file=sys.stderr)
    return factor_health, risk_alerts, divergence


def cmd_research_propose(args):
    """扫描系统状态 → 生成 research plan（不落盘、不跑回测）。"""
    from pipeline.research_planner import plan_research, render_plan_markdown

    factor_health, risk_alerts, divergence = _collect_system_state()
    questions = plan_research(
        factor_health=factor_health,
        risk_alerts=risk_alerts,
        divergence=divergence,
    )
    print(render_plan_markdown(questions))


def cmd_research_run(args):
    """扫描系统状态 → plan → propose + run experiments（需 --approved 才真跑）。"""
    from pipeline.research_planner import plan_research
    from pipeline.experiment_runner import run_experiments, propose_experiment

    factor_health, risk_alerts, divergence = _collect_system_state()
    questions = plan_research(
        factor_health=factor_health,
        risk_alerts=risk_alerts,
        divergence=divergence,
    )
    print(f"plan 产出 {len(questions)} 条 research question")

    if not args.approved:
        # 未批准：只 propose，不调回测
        records = [propose_experiment(q) for q in questions]
        print("\n未 --approved，仅落 proposed 记录（未执行回测）：")
        for r in records:
            print(f"  {r.experiment_id}  {r.question_type:<20}  {r.status}")
        return

    records = run_experiments(
        questions,
        max_runs=args.max_runs,
    )
    print(f"\n执行完成，共 {len(records)} 条实验：")
    for r in records:
        line = f"  {r.experiment_id}  {r.status:<10}  {r.question_type}"
        if r.run_id:
            line += f"  run_id={r.run_id}"
        if r.error:
            line += f"  ({r.error})"
        print(line)


def cmd_research_list(args):
    """列出历史 experiment 记录。"""
    from pipeline.experiment_store import list_experiments

    records = list_experiments(
        status=args.status,
        question_type=args.type,
        limit=args.limit,
    )
    if not records:
        print("（无 experiment 记录）")
        return
    print(f"{'experiment_id':<32} {'status':<10} {'priority':<8} {'question_type':<22} run_id")
    print("-" * 100)
    for r in records:
        print(
            f"{r.experiment_id:<32} "
            f"{r.status:<10} "
            f"{r.priority:<8} "
            f"{r.question_type:<22} "
            f"{r.run_id or '-'}"
        )


def cmd_research_summarize(args):
    """对 experiment 做 baseline 对比汇总。"""
    from pipeline.experiment_store import list_experiments
    from pipeline.experiment_summarizer import (
        render_summary_markdown,
        summarize_experiments,
    )

    records = list_experiments(status=args.status, limit=args.limit)
    baseline = None
    if args.baseline_run:
        try:
            from pipeline.run_store import get_run
            baseline = get_run(args.baseline_run).metrics or None
        except Exception as e:
            print(f"⚠️  读取 baseline run 失败：{e}", file=sys.stderr)

    summary = summarize_experiments(records, baseline=baseline)
    print(render_summary_markdown(summary))


# ══════════════════════════════════════════════════════════════
# idea 命令（自然语言策略想法 → 自动回测）
# ══════════════════════════════════════════════════════════════

def cmd_idea(args):
    """
    自然语言策略想法 → 自动回测流水线（idea-to-strategy）。

    流程：
        1. 调用 IdeaParser 将用户输入的自然语言想法解析为因子规范
        2. 对选中因子做 IC 快速验证
        3. 将策略定义写入 strategies/generated/auto_gen_latest.json
        4. 通过 control_surface 运行 auto_gen 回测
        5. 调用 risk_gate 检查是否达标
        6. 打印 Markdown 格式的最终报告

    参数:
        args: argparse 命名空间，包含
              - text  : 策略想法字符串
              - start : 回测开始日期 YYYY-MM-DD
              - end   : 回测结束日期 YYYY-MM-DD
    """
    idea_text = args.text
    start = args.start
    end = args.end

    print(f"{'='*60}")
    print(f"  idea-to-strategy 流水线")
    print(f"{'='*60}")
    print(f"  想法  : {idea_text}")
    print(f"  区间  : {start} ~ {end}")
    print()

    # ── 步骤1：调用 IdeaParser ──────────────────────────────
    print("[1/3] 解析策略想法（LLM 解析中）...")
    try:
        from agents.base import LLMClient
        from agents.idea_parser import IdeaParser

        llm = LLMClient()
        if llm._backend == "none":
            print("❌ LLM 后端不可用，请安装 claude CLI 或启动 Ollama", file=sys.stderr)
            sys.exit(1)

        parser_agent = IdeaParser(llm)
        spec = parser_agent.analyze(idea_text=idea_text)
    except Exception as e:
        print(f"❌ IdeaParser 调用失败：{e}", file=sys.stderr)
        sys.exit(1)

    if not spec.get("parse_ok", False):
        print(f"❌ 想法解析失败：{spec.get('reason', '未知原因')}", file=sys.stderr)
        sys.exit(1)

    factor_names = [f["name"] for f in spec.get("selected_factors", [])]
    print(f"  已识别 {len(factor_names)} 个因子：{factor_names}")
    print(f"  策略假设：{spec.get('hypothesis', '')}")
    print()

    # ── 步骤2~6：运行主流水线 ────────────────────────────────
    print("[2/3] 运行 IC 验证、回测、风险门...")

    def _print_progress(stage: str, message: str):
        """进度回调：在终端打印各阶段进度"""
        stage_icons = {
            "validating": "   验证",
            "computing_ic": "   IC  ",
            "writing_spec": "   写入",
            "backtesting": "   回测",
            "risk_gate": "   风控",
            "done": "   完成",
        }
        icon = stage_icons.get(stage, f"  [{stage}]")
        print(f"{icon}: {message}")

    try:
        from pipeline.idea_to_strategy import run_idea_pipeline
        result = run_idea_pipeline(
            idea_text=idea_text,
            spec=spec,
            backtest_start=start,
            backtest_end=end,
            progress_callback=_print_progress,
        )
    except Exception as e:
        print(f"❌ 流水线执行异常：{e}", file=sys.stderr)
        sys.exit(1)

    # ── 步骤3：打印最终报告 ──────────────────────────────────
    print()
    print("[3/3] 最终报告")
    print("=" * 60)
    print(result.report_markdown)
    print("=" * 60)

    # 非零退出码：仅在解析或回测本身失败时退出1，风险门未通过仍视为"正常完成"
    if result.status in ("failed_parse", "failed_ic", "failed_backtest"):
        sys.exit(1)


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
    p_bt_run.add_argument("--start", type=str, default=None,
                          help="开始日期 YYYY-MM-DD（默认三年前）")
    p_bt_run.add_argument("--end", type=str, default=None,
                          help="结束日期 YYYY-MM-DD（默认昨天）")
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
    p_sig_run.add_argument("--strategy", type=str,
                           choices=["ad_hoc", "v7", "v8", "v9", "v10", "auto_gen"], default="v10",
                           help="因子策略（默认 v7）")

    # ── rebalance ────────────────────────────────────────────
    # 同时支持 `rebalance --date` (旧) 和 `rebalance run --date` (新)
    p_reb = subparsers.add_parser("rebalance", help="调仓操作")
    p_reb.add_argument("--date", type=str, default=None, help="调仓日期 YYYY-MM-DD")
    reb_sub = p_reb.add_subparsers(dest="reb_action")

    p_reb_run = reb_sub.add_parser("run", help="执行调仓")
    p_reb_run.add_argument("--date", type=str, required=True, help="调仓日期 YYYY-MM-DD")
    p_reb_run.add_argument("--strategy", type=str,
                           choices=["ad_hoc", "v7", "v8", "v9", "v10", "auto_gen"], default="v10",
                           help="因子策略（默认 v7）")

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
    p_data_update.add_argument(
        "--source",
        type=str,
        default="auto",
        choices=["auto", "tushare", "baostock"],
        help=(
            "数据源: tushare = 批量模式（需 TUSHARE_TOKEN, 秒级更新）; "
            "baostock = 逐只模式（免费但慢）; auto = 优先 baostock"
        ),
    )

    # ── live ─────────────────────────────────────────────────
    p_live = subparsers.add_parser("live", help="实时数据服务")
    live_sub = p_live.add_subparsers(dest="live_action")

    p_live_quote = live_sub.add_parser("quote", help="查看实时行情")
    p_live_quote.add_argument("symbols", nargs="*", help="股票代码（不填则用持仓）")

    p_live_poll = live_sub.add_parser("poll", help="盘中实时轮询")
    p_live_poll.add_argument("--interval", type=int, default=5, help="间隔秒数")

    live_sub.add_parser("eod", help="执行收盘后 EOD 更新")

    # ── pipeline ──────────────────────────────────────────────
    p_pipe = subparsers.add_parser("pipeline", help="AI Agent 流水线（运行/挖掘/状态）")
    pipe_sub = p_pipe.add_subparsers(dest="pipe_action")

    p_pipe_run = pipe_sub.add_parser("run", help="执行流水线")
    p_pipe_run.add_argument("--date", type=str, default=None, help="日期 YYYY-MM-DD")
    p_pipe_run.add_argument("--mode", type=str, default="daily",
                            choices=["daily", "weekly", "full"],
                            help="模式: daily/weekly/full")
    p_pipe_run.add_argument("--dry-run", dest="dry_run", action="store_true")
    p_pipe_run.add_argument("--only", type=str, default=None,
                            help="只执行指定阶段（逗号分隔）")

    p_pipe_mine = pipe_sub.add_parser("mine", help="执行因子挖掘")
    p_pipe_mine.add_argument("--date", type=str, default=None)

    p_pipe_status = pipe_sub.add_parser("status", help="查看最近流水线运行状态")

    # ── 独立命令 ─────────────────────────────────────────────
    # ── research 命令组（Phase 7 AI 研究助理）────────────────
    p_rs = subparsers.add_parser("research", help="AI 研究助理（提议/执行/列表/总结实验）")
    rs_sub = p_rs.add_subparsers(dest="rs_action")

    rs_sub.add_parser("propose", help="扫描系统状态并打印 research plan（不跑回测）")

    p_rs_run = rs_sub.add_parser("run", help="运行 research plan 对应的实验")
    p_rs_run.add_argument("--approved", action="store_true",
                          help="明确批准才真的拉起回测，否则只 propose")
    p_rs_run.add_argument("--max-runs", type=int, default=None,
                          help="最多执行多少条，超过的仅保留 proposed 状态")

    p_rs_list = rs_sub.add_parser("list", help="列出历史 experiment 记录")
    p_rs_list.add_argument("--status", type=str, default=None,
                           help="按 status 过滤 (proposed/running/success/failed/skipped)")
    p_rs_list.add_argument("--type", type=str, default=None,
                           help="按 question_type 过滤")
    p_rs_list.add_argument("--limit", type=int, default=20)

    p_rs_sum = rs_sub.add_parser("summarize", help="对 experiment 做 baseline 对比汇总")
    p_rs_sum.add_argument("--status", type=str, default="success",
                          help="只汇总指定 status 的实验，默认 success")
    p_rs_sum.add_argument("--limit", type=int, default=20)
    p_rs_sum.add_argument("--baseline-run", type=str, default=None,
                          help="对比的 baseline run_id")

    # ── idea ─────────────────────────────────────────────────
    p_idea = subparsers.add_parser(
        "idea",
        help="自然语言策略想法 → 自动回测（idea-to-strategy）",
        description=(
            "输入自然语言策略想法，自动完成：\n"
            "  1. LLM 解析 → 因子选择\n"
            "  2. IC 快速验证\n"
            "  3. 写入 strategies/generated/auto_gen_latest.json\n"
            "  4. 运行 auto_gen 回测\n"
            "  5. 风险门检查\n"
            "  6. 输出 Markdown 报告"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p_idea.add_argument("text", help="策略想法，如 '我想做基于ROE和低波动的选股策略'")
    p_idea.add_argument("--start", type=str, default="2022-01-01",
                        help="回测开始日期 YYYY-MM-DD（默认 2022-01-01）")
    p_idea.add_argument("--end", type=str, default="2025-12-31",
                        help="回测结束日期 YYYY-MM-DD（默认 2025-12-31）")

    p_ptd = subparsers.add_parser("prev-trading-date", help="输出前一个 A 股交易日（供 shell 脚本调用）")
    p_ptd.add_argument("date", nargs="?", default=None, help="日期 YYYY-MM-DD（默认今天）")

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
        "prev-trading-date": cmd_prev_trading_date,
        # idea-to-strategy 流水线
        "idea": cmd_idea,
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
    elif args.command == "pipeline":
        action = getattr(args, "pipe_action", None)
        if action is None:
            p_pipe.print_help()
            sys.exit(0)
        handler = {
            "run": cmd_pipeline_run,
            "mine": cmd_pipeline_mine,
            "status": cmd_pipeline_status,
        }.get(action)
    elif args.command == "research":
        action = getattr(args, "rs_action", None)
        if action is None:
            p_rs.print_help()
            sys.exit(0)
        handler = {
            "propose": cmd_research_propose,
            "run": cmd_research_run,
            "list": cmd_research_list,
            "summarize": cmd_research_summarize,
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
