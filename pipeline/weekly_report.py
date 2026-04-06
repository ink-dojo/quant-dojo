"""
每周周报生成模块（结构化审计文档）

从 live/portfolio/ 目录读取交易、持仓、净值数据，
调用风险监控和因子健康度模块，生成 Markdown 格式的周报，
保存到 journal/weekly/{YYYY-Www}.md。
"""

import datetime
import json
import os
from pathlib import Path
from typing import Optional


def _get_week_dates(week: str) -> list:
    """
    根据 ISO 周字符串返回该周的工作日列表（周一到周五）。

    参数：
        week: "2026-W13" 格式的 ISO 周字符串

    返回：
        list of str, 格式 "YYYY-MM-DD"
    """
    year, week_num = week.split("-W")
    year, week_num = int(year), int(week_num)
    monday = datetime.date.fromisocalendar(year, week_num, 1)
    return [(monday + datetime.timedelta(days=i)).strftime("%Y-%m-%d") for i in range(5)]


def _load_trades(trades_path: str, dates: list) -> list:
    """
    从 trades.json 中加载指定日期范围内的调仓记录。

    参数：
        trades_path: trades.json 文件路径
        dates: 当周工作日列表

    返回：
        list of dict，每条记录包含 date/symbol/action/shares/price/cost
    """
    if not os.path.exists(trades_path):
        return []
    try:
        with open(trades_path, "r", encoding="utf-8") as f:
            all_trades = json.load(f)
    except Exception:
        return []
    if not isinstance(all_trades, list):
        return []
    date_set = set(dates)
    return [t for t in all_trades if t.get("date") in date_set]


def _load_positions(positions_path: str) -> dict:
    """
    从 positions.json 中加载当前持仓快照。

    参数：
        positions_path: positions.json 文件路径

    返回：
        dict，键为股票代码（或 "__cash__"），值为持仓详情
    """
    if not os.path.exists(positions_path):
        return {}
    try:
        with open(positions_path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def _load_nav(nav_path: str, dates: list) -> list:
    """
    从 nav.csv 中过滤出当周的净值数据。

    参数：
        nav_path: nav.csv 文件路径
        dates: 当周日期列表

    返回：
        list of dict，每行包含 date/nav 字段，按日期排序
    """
    if not os.path.exists(nav_path):
        return []
    rows = []
    try:
        with open(nav_path, "r", encoding="utf-8") as f:
            lines = f.readlines()
        if not lines:
            return []
        header = [h.strip() for h in lines[0].split(",")]
        date_idx = header.index("date") if "date" in header else 0
        nav_idx = header.index("nav") if "nav" in header else 1
        date_set = set(dates)
        for line in lines[1:]:
            parts = [p.strip() for p in line.split(",")]
            if len(parts) > max(date_idx, nav_idx) and parts[date_idx] in date_set:
                try:
                    rows.append({"date": parts[date_idx], "nav": float(parts[nav_idx])})
                except ValueError:
                    pass
    except Exception:
        pass
    return sorted(rows, key=lambda x: x["date"])


def _load_all_nav(nav_path: str) -> list:
    """
    从 nav.csv 加载全部净值数据（用于计算周前净值基准）。

    参数：
        nav_path: nav.csv 文件路径

    返回：
        list of dict，按日期排序，每行包含 date/nav
    """
    if not os.path.exists(nav_path):
        return []
    rows = []
    try:
        with open(nav_path, "r", encoding="utf-8") as f:
            lines = f.readlines()
        if not lines:
            return []
        header = [h.strip() for h in lines[0].split(",")]
        date_idx = header.index("date") if "date" in header else 0
        nav_idx = header.index("nav") if "nav" in header else 1
        for line in lines[1:]:
            parts = [p.strip() for p in line.split(",")]
            if len(parts) > max(date_idx, nav_idx):
                try:
                    rows.append({"date": parts[date_idx], "nav": float(parts[nav_idx])})
                except ValueError:
                    pass
    except Exception:
        pass
    return sorted(rows, key=lambda x: x["date"])


def _try_risk_alerts() -> Optional[list]:
    """
    尝试调用 live.risk_monitor.check_risk_alerts 获取风险预警。

    如果模块不可用或调用失败，返回 None。

    返回：
        预警列表或 None
    """
    try:
        from live.risk_monitor import check_risk_alerts
        from live.paper_trader import PaperTrader
        # PaperTrader 使用模块级 portfolio 路径；这里只需要实例化当前组合状态。
        trader = PaperTrader()
        return check_risk_alerts(trader)
    except Exception:
        return None


def _try_factor_health() -> Optional[dict]:
    """
    尝试调用 pipeline.factor_monitor.factor_health_report 获取因子健康度。

    如果模块不可用或调用失败，返回 None。

    返回：
        因子健康度字典或 None
    """
    try:
        from pipeline.factor_monitor import factor_health_report, FACTOR_PRESETS
        return factor_health_report(factors=FACTOR_PRESETS["v7"])
    except Exception:
        return None


# ---------------------------------------------------------------------------
# 各报告段落的渲染函数
# ---------------------------------------------------------------------------

def _render_trades_section(trades: list) -> str:
    """
    渲染「本周调仓记录」段落。

    参数：
        trades: 过滤后的当周交易列表

    返回：
        Markdown 字符串
    """
    lines = ["## 本周调仓记录\n"]
    if not trades:
        lines.append("本周无调仓记录。\n")
        return "\n".join(lines)

    buys = [t for t in trades if t.get("action") == "buy"]
    sells = [t for t in trades if t.get("action") == "sell"]

    if buys:
        lines.append(f"### 买入（{len(buys)} 笔）\n")
        lines.append("| 日期 | 代码 | 股数 | 价格 | 成本 |")
        lines.append("|------|------|-----:|-----:|-----:|")
        for t in buys:
            lines.append(
                f"| {t['date']} | {t['symbol']} | {t['shares']} "
                f"| {t['price']:.2f} | {t['cost']:.2f} |"
            )
        lines.append("")

    if sells:
        lines.append(f"### 卖出（{len(sells)} 笔）\n")
        lines.append("| 日期 | 代码 | 股数 | 价格 | 成本 |")
        lines.append("|------|------|-----:|-----:|-----:|")
        for t in sells:
            lines.append(
                f"| {t['date']} | {t['symbol']} | {t['shares']} "
                f"| {t['price']:.2f} | {t['cost']:.2f} |"
            )
        lines.append("")

    total_buy_cost = sum(t.get("cost", 0) for t in buys)
    total_sell_cost = sum(t.get("cost", 0) for t in sells)
    lines.append(f"**汇总：** 买入总额 {total_buy_cost:,.2f} 元，卖出总额 {total_sell_cost:,.2f} 元\n")
    return "\n".join(lines)


def _render_positions_section(positions: dict) -> str:
    """
    渲染「周末持仓概览」段落。

    参数：
        positions: positions.json 的内容

    返回：
        Markdown 字符串
    """
    lines = ["## 周末持仓概览\n"]

    # 分离现金与股票持仓
    cash = positions.get("__cash__", 0)
    stock_positions = {k: v for k, v in positions.items() if k != "__cash__"}

    if not stock_positions:
        lines.append("当前无股票持仓。\n")
        lines.append(f"**现金余额：** {cash:,.2f} 元\n")
        return "\n".join(lines)

    # 计算总市值
    total_market_value = sum(
        p.get("shares", 0) * p.get("current_price", p.get("cost_price", 0))
        for p in stock_positions.values()
    )
    total_value = total_market_value + cash

    lines.append(f"**持仓数量：** {len(stock_positions)} 只 | "
                 f"**总市值：** {total_market_value:,.2f} 元 | "
                 f"**现金：** {cash:,.2f} 元 | "
                 f"**总资产：** {total_value:,.2f} 元\n")

    lines.append("| 代码 | 股数 | 成本价 | 现价 | 市值 | 盈亏% |")
    lines.append("|------|-----:|-------:|-----:|-----:|------:|")

    # 按市值降序
    sorted_stocks = sorted(
        stock_positions.items(),
        key=lambda kv: kv[1].get("shares", 0) * kv[1].get("current_price", 0),
        reverse=True,
    )
    for symbol, info in sorted_stocks:
        shares = info.get("shares", 0)
        cost_price = info.get("cost_price", 0)
        cur_price = info.get("current_price", cost_price)
        mkt_val = shares * cur_price
        pnl_pct = ((cur_price / cost_price) - 1) * 100 if cost_price else 0
        lines.append(
            f"| {symbol} | {shares} | {cost_price:.2f} | {cur_price:.2f} "
            f"| {mkt_val:,.2f} | {pnl_pct:+.2f}% |"
        )
    lines.append("")
    return "\n".join(lines)


def _render_nav_section(nav_rows: list, all_nav: list, week_start: str) -> str:
    """
    渲染「本周 NAV 表现」段落，计算周收益率。

    参数：
        nav_rows: 当周净值数据
        all_nav: 全部历史净值数据（用于找上周末基准）
        week_start: 当周周一日期字符串

    返回：
        Markdown 字符串
    """
    lines = ["## 本周 NAV 表现\n"]

    if not nav_rows:
        lines.append("本周无净值数据。\n")
        return "\n".join(lines)

    # 找上周末（week_start 之前最近的净值）作为基准
    prev_nav = None
    for row in all_nav:
        if row["date"] < week_start:
            prev_nav = row["nav"]
        else:
            break

    lines.append("| 日期 | 净值 |")
    lines.append("|------|-----:|")
    for row in nav_rows:
        lines.append(f"| {row['date']} | {row['nav']:,.2f} |")
    lines.append("")

    end_nav = nav_rows[-1]["nav"]
    start_nav = nav_rows[0]["nav"]

    # 周内收益
    if len(nav_rows) >= 2:
        intra_ret = (end_nav / start_nav - 1) * 100
        lines.append(f"**周内收益（首日到末日）：** {intra_ret:+.4f}%\n")

    # 相对上周末
    if prev_nav is not None and prev_nav > 0:
        weekly_ret = (end_nav / prev_nav - 1) * 100
        lines.append(f"**周收益（vs 上周末）：** {weekly_ret:+.4f}%\n")
    else:
        lines.append("**周收益：** 无上周基准，无法计算\n")

    return "\n".join(lines)


def _render_risk_section(alerts: Optional[list]) -> str:
    """
    渲染「本周风险预警摘要」段落。

    参数：
        alerts: check_risk_alerts 返回的预警列表，或 None

    返回：
        Markdown 字符串
    """
    lines = ["## 本周风险预警摘要\n"]

    if alerts is None:
        lines.append("无持仓/无数据，风险监控模块未能加载。\n")
        return "\n".join(lines)

    if not alerts:
        lines.append("本周未触发任何风险预警。\n")
        return "\n".join(lines)

    lines.append("| 级别 | 预警内容 | 相关标的 |")
    lines.append("|------|----------|----------|")
    for alert in alerts:
        level = alert.get("level", "info")
        msg = alert.get("msg", "")
        symbol = alert.get("symbol", "-")
        if level == "critical":
            level_label = "CRITICAL"
        elif level == "warning":
            level_label = "WARNING"
        else:
            level_label = "INFO"
        lines.append(f"| {level_label} | {msg} | {symbol} |")
    lines.append("")
    return "\n".join(lines)


def _render_factor_health_section(health: Optional[dict]) -> str:
    """
    渲染「因子健康度摘要」段落。

    参数：
        health: factor_health_report 返回的字典，或 None

    返回：
        Markdown 字符串
    """
    lines = ["## 因子健康度摘要\n"]

    if health is None:
        lines.append("无数据，因子监控模块未能加载。\n")
        return "\n".join(lines)

    if not health:
        lines.append("无因子快照数据。\n")
        return "\n".join(lines)

    lines.append("| 因子 | IC 均值 | 状态 |")
    lines.append("|------|--------:|------|")
    status_map = {
        "healthy": "健康",
        "degraded": "衰减",
        "dead": "失效",
        "no_data": "无数据",
    }
    for factor, info in health.items():
        if isinstance(info, dict):
            # factor_monitor 返回 "rolling_ic"，兼容旧版 "ic_mean"
            ic_mean = info.get("rolling_ic", info.get("ic_mean"))
            status = info.get("status", "no_data")
            ic_str = f"{ic_mean:.4f}" if ic_mean is not None and not (isinstance(ic_mean, float) and ic_mean != ic_mean) else "-"
            status_str = status_map.get(status, status)
        else:
            ic_str = "-"
            status_str = str(info)
        lines.append(f"| {factor} | {ic_str} | {status_str} |")
    lines.append("")
    return "\n".join(lines)


def _render_factor_research_section() -> str:
    """
    渲染「因子研究」段落：从最近一次 FactorMiner 结果生成。

    返回:
        Markdown 字符串
    """
    lines = ["## 因子研究（最近一次挖掘）\n"]

    research_dir = Path(__file__).parent.parent / "live" / "factor_research"
    if not research_dir.exists():
        lines.append("无因子挖掘记录。\n")
        return "\n".join(lines)

    # 找最近的 mining 结果
    mining_files = sorted(research_dir.glob("mining_*.json"), reverse=True)
    if not mining_files:
        lines.append("无因子挖掘记录。\n")
        return "\n".join(lines)

    try:
        with open(mining_files[0], "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception:
        lines.append("因子挖掘结果读取失败。\n")
        return "\n".join(lines)

    mining_date = data.get("date", "?")
    rankings = data.get("rankings", [])
    recommended = data.get("recommended", [])

    lines.append(f"挖掘日期: {mining_date}\n")

    if rankings:
        lines.append("| 排名 | 因子 | IC均值 | ICIR | t统计量 | L/S夏普 | 类别 |")
        lines.append("|------|------|--------|------|---------|---------|------|")
        for i, r in enumerate(rankings[:10], 1):
            lines.append(
                f"| {i} | {r['name']} | {r['IC_mean']:.4f} | "
                f"{r['ICIR']:.4f} | {r['t_stat']:.4f} | "
                f"{r['ls_sharpe']:.4f} | {r['category']} |"
            )
        lines.append("")

    if recommended:
        lines.append(f"**推荐因子组合**: {', '.join(recommended)}\n")

    # 策略建议
    strategy_files = sorted(research_dir.glob("strategy_*.json"), reverse=True)
    if strategy_files:
        try:
            with open(strategy_files[0], "r", encoding="utf-8") as f:
                strategy = json.load(f)
            rec = strategy.get("recommendation", "keep")
            reason = strategy.get("reason", "")
            lines.append(f"**策略建议**: {rec.upper()} — {reason}\n")
        except Exception:
            pass

    return "\n".join(lines)


def _render_todo_section() -> str:
    """
    渲染「下周待确认事项」段落（静态清单）。

    返回：
        Markdown 字符串
    """
    lines = [
        "## 下周待确认事项\n",
        "- [ ] 数据更新：确认行情数据源正常拉取",
        "- [ ] 信号生成：运行因子计算与选股流程",
        "- [ ] 调仓执行：核对信号并完成调仓操作",
        "",
    ]
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# 主入口
# ---------------------------------------------------------------------------

def generate_weekly_report(week: Optional[str] = None) -> str:
    """
    生成指定周的量化策略周报（结构化审计文档）。

    报告包含六个段落：
      1. 本周调仓记录
      2. 周末持仓概览
      3. 本周 NAV 表现
      4. 本周风险预警摘要
      5. 因子健康度摘要
      6. 下周待确认事项

    参数：
        week: ISO 周字符串，如 "2026-W13"。默认为当前周。

    返回：
        Markdown 格式的周报字符串，同时保存到 journal/weekly/{week}.md。
    """
    # 确定目标周
    if week is None:
        today = datetime.date.today()
        iso_cal = today.isocalendar()
        week = f"{iso_cal[0]}-W{iso_cal[1]:02d}"

    # 路径配置
    base_dir = Path(__file__).parent.parent
    portfolio_dir = base_dir / "live" / "portfolio"
    trades_path = portfolio_dir / "trades.json"
    positions_path = portfolio_dir / "positions.json"
    nav_path = portfolio_dir / "nav.csv"
    journal_dir = base_dir / "journal" / "weekly"
    journal_dir.mkdir(parents=True, exist_ok=True)

    # 获取当周工作日
    dates = _get_week_dates(week)
    week_start, week_end = dates[0], dates[-1]

    # 加载数据
    trades = _load_trades(str(trades_path), dates)
    positions = _load_positions(str(positions_path))
    nav_rows = _load_nav(str(nav_path), dates)
    all_nav = _load_all_nav(str(nav_path))

    # 尝试加载风险预警和因子健康度
    risk_alerts = _try_risk_alerts()
    factor_health = _try_factor_health()

    # 构建报告
    sections = []

    # 数据覆盖度评估
    has_trades = bool(trades)
    has_positions = bool(positions) and any(k != "__cash__" for k in positions)
    has_nav = bool(nav_rows)
    coverage_items = [
        ("调仓记录", has_trades),
        ("持仓数据", has_positions),
        ("净值数据", has_nav),
    ]
    coverage_count = sum(1 for _, v in coverage_items if v)
    if coverage_count == 0:
        coverage_label = "空周（无任何交易数据）"
    elif coverage_count < len(coverage_items):
        missing = [name for name, v in coverage_items if not v]
        coverage_label = f"部分数据缺失（缺：{', '.join(missing)}）"
    else:
        coverage_label = "数据完整"

    # 标题与元信息
    sections.append(f"# 周报：{week}（{week_start} ~ {week_end}）\n")
    sections.append(f"> 生成时间：{datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
    sections.append(f"> **数据覆盖度：{coverage_label}**\n")

    # 六个结构化段落
    sections.append(_render_trades_section(trades))
    sections.append(_render_positions_section(positions))
    sections.append(_render_nav_section(nav_rows, all_nav, week_start))
    sections.append(_render_risk_section(risk_alerts))
    sections.append(_render_factor_health_section(factor_health))
    sections.append(_render_factor_research_section())
    sections.append(_render_todo_section())

    report = "\n".join(sections)

    # 保存到 journal/weekly/{week}.md（覆盖写入）
    output_path = journal_dir / f"{week}.md"
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(report)

    return report


if __name__ == "__main__":
    report = generate_weekly_report()
    print(report)
