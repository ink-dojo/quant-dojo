"""
每周周报生成模块

从 live/signals/、live/portfolio/nav.csv、live/factor_snapshot/ 读取数据，
生成 Markdown 格式的周报，保存到 journal/weekly/{week}.md。
"""

import os
import json
import glob
import datetime
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
    # ISO week 第1天是周一
    monday = datetime.date.fromisocalendar(year, week_num, 1)
    dates = []
    for i in range(5):  # 周一到周五
        dates.append((monday + datetime.timedelta(days=i)).strftime("%Y-%m-%d"))
    return dates


def _load_signals_for_week(signals_dir: str, dates: list) -> dict:
    """
    加载指定日期列表的信号文件。

    参数：
        signals_dir: live/signals/ 目录路径
        dates: 日期字符串列表

    返回：
        dict {date: signal_dict}，仅包含存在的日期
    """
    signals = {}
    for date in dates:
        fpath = os.path.join(signals_dir, f"{date}.json")
        if os.path.exists(fpath):
            try:
                with open(fpath, "r", encoding="utf-8") as f:
                    signals[date] = json.load(f)
            except Exception:
                pass
    return signals


def _load_nav_for_week(nav_path: str, dates: list) -> list:
    """
    从 nav.csv 中过滤出当周的净值数据。

    参数：
        nav_path: live/portfolio/nav.csv 路径
        dates: 当周日期列表

    返回：
        list of dict，每行包含 date/nav 字段
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
            if len(parts) > max(date_idx, nav_idx):
                if parts[date_idx] in date_set:
                    try:
                        rows.append({"date": parts[date_idx], "nav": float(parts[nav_idx])})
                    except ValueError:
                        pass
    except Exception:
        pass
    return rows


def _load_factor_snapshots_for_week(snapshot_dir: str, dates: list) -> dict:
    """
    加载当周的因子快照（.parquet 或 .json 格式）。

    参数：
        snapshot_dir: live/factor_snapshot/ 目录路径
        dates: 当周日期列表

    返回：
        dict {date: factor_data}
    """
    snapshots = {}
    for date in dates:
        # 尝试 parquet
        fpath_parquet = os.path.join(snapshot_dir, f"{date}.parquet")
        fpath_json = os.path.join(snapshot_dir, f"{date}.json")
        if os.path.exists(fpath_parquet):
            try:
                import pandas as pd
                df = pd.read_parquet(fpath_parquet)
                snapshots[date] = df.to_dict()
            except Exception:
                pass
        elif os.path.exists(fpath_json):
            try:
                with open(fpath_json, "r", encoding="utf-8") as f:
                    snapshots[date] = json.load(f)
            except Exception:
                pass
    return snapshots


def _compute_position_changes(signals: dict, dates: list) -> dict:
    """
    根据本周信号计算持仓变化（买入/卖出）。

    参数：
        signals: {date: signal_dict} 字典
        dates: 当周日期列表

    返回：
        dict with keys 'buys', 'sells', 'hold'
    """
    sorted_dates = sorted([d for d in dates if d in signals])
    if not sorted_dates:
        return {"buys": [], "sells": [], "hold": []}

    first_picks = set(signals[sorted_dates[0]].get("picks", []))
    last_picks = set(signals[sorted_dates[-1]].get("picks", []))

    if len(sorted_dates) >= 2:
        prev_picks = set(signals[sorted_dates[-2]].get("picks", []))
        buys = list(last_picks - prev_picks)
        sells = list(prev_picks - last_picks)
        hold = list(last_picks & prev_picks)
    else:
        buys = list(last_picks)
        sells = []
        hold = []

    return {"buys": buys, "sells": sells, "hold": hold}


def _compute_factor_ic_summary(snapshots: dict) -> dict:
    """
    汇总本周各因子的 IC 均值（简单占位实现）。

    参数：
        snapshots: {date: factor_data} 字典

    返回：
        dict {factor_name: avg_ic}
    """
    # 如果快照包含 ic 字段，取均值；否则返回空
    ic_accum: dict = {}
    ic_count: dict = {}
    for date, data in snapshots.items():
        if isinstance(data, dict) and "ic" in data:
            for factor, ic_val in data["ic"].items():
                ic_accum[factor] = ic_accum.get(factor, 0.0) + float(ic_val)
                ic_count[factor] = ic_count.get(factor, 0) + 1
    if not ic_accum:
        return {}
    return {f: ic_accum[f] / ic_count[f] for f in ic_accum}


def generate_weekly_report(week: Optional[str] = None) -> str:
    """
    生成指定周的量化策略周报。

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
    signals_dir = base_dir / "live" / "signals"
    nav_path = base_dir / "live" / "portfolio" / "nav.csv"
    snapshot_dir = base_dir / "live" / "factor_snapshot"
    journal_dir = base_dir / "journal" / "weekly"
    journal_dir.mkdir(parents=True, exist_ok=True)

    # 获取当周工作日
    dates = _get_week_dates(week)
    week_start, week_end = dates[0], dates[-1]

    # 加载数据
    signals = _load_signals_for_week(str(signals_dir), dates)
    nav_rows = _load_nav_for_week(str(nav_path), dates)
    snapshots = _load_factor_snapshots_for_week(str(snapshot_dir), dates)

    # 判断是否有任何真实数据
    has_data = bool(signals or nav_rows or snapshots)

    # 构建报告
    lines = []
    lines.append(f"# 周报：{week}（{week_start} ~ {week_end}）\n")
    lines.append(f"> 生成时间：{datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
    lines.append("")

    if not has_data:
        # 系统刚启动，无历史数据
        lines.append("## 系统状态\n")
        lines.append("系统刚启动，暂无历史数据。以下为占位报告，待积累真实运行数据后自动填充。\n")
        lines.append("")

        lines.append("## 持仓变化\n")
        lines.append("- 买入：暂无数据\n")
        lines.append("- 卖出：暂无数据\n")
        lines.append("")

        lines.append("## 本周净值 vs HS300\n")
        lines.append("| 指标 | 本策略 | 沪深300 |\n")
        lines.append("|------|--------|--------|\n")
        lines.append("| 本周收益 | - | 0（占位）|\n")
        lines.append("| 累计净值 | - | - |\n")
        lines.append("")

        lines.append("## 各因子本周 IC\n")
        lines.append("| 因子 | IC 均值 | 状态 |\n")
        lines.append("|------|---------|------|\n")
        lines.append("| momentum_20 | - | 待计算 |\n")
        lines.append("| ep | - | 待计算 |\n")
        lines.append("| low_volatility | - | 待计算 |\n")
        lines.append("| turnover | - | 待计算 |\n")
        lines.append("")

        lines.append("## 风险预警摘要\n")
        lines.append("暂无数据，系统未发现风险事件。\n")
        lines.append("")

        lines.append("## 下周调仓计划\n")
        lines.append("- 待系统积累数据后自动生成\n")
        lines.append("")

    else:
        # 1. 持仓变化
        position_changes = _compute_position_changes(signals, dates)
        lines.append("## 持仓变化\n")

        buys = position_changes["buys"]
        sells = position_changes["sells"]
        hold = position_changes["hold"]

        if buys:
            lines.append(f"**买入（{len(buys)} 只）：** {', '.join(buys[:10])}{'...' if len(buys) > 10 else ''}\n")
        else:
            lines.append("**买入：** 无新增持仓\n")

        if sells:
            lines.append(f"**卖出（{len(sells)} 只）：** {', '.join(sells[:10])}{'...' if len(sells) > 10 else ''}\n")
        else:
            lines.append("**卖出：** 无减仓操作\n")

        lines.append(f"**持仓不变：** {len(hold)} 只\n")
        lines.append("")

        # 2. 本周净值 vs HS300
        lines.append("## 本周净值 vs HS300\n")
        lines.append("| 日期 | 策略净值 | HS300（占位：0）|\n")
        lines.append("|------|----------|------------------|\n")
        if nav_rows:
            nav_sorted = sorted(nav_rows, key=lambda x: x["date"])
            start_nav = nav_sorted[0]["nav"]
            for row in nav_sorted:
                weekly_ret = (row["nav"] / start_nav - 1) * 100 if start_nav else 0
                lines.append(f"| {row['date']} | {row['nav']:.4f} | 0（暂无基准）|\n")
            # 本周收益
            if len(nav_sorted) >= 2:
                end_nav = nav_sorted[-1]["nav"]
                weekly_ret = (end_nav / start_nav - 1) * 100
                lines.append(f"\n**本周策略收益：** {weekly_ret:+.2f}%  |  **HS300 收益：** 0（占位）\n")
        else:
            lines.append("| - | 暂无净值数据 | 0（占位）|\n")
        lines.append("")

        # 3. 各因子本周 IC
        lines.append("## 各因子本周 IC\n")
        ic_summary = _compute_factor_ic_summary(snapshots)
        lines.append("| 因子 | IC 均值 | 状态 |\n")
        lines.append("|------|---------|------|\n")
        if ic_summary:
            for factor, ic_val in ic_summary.items():
                status = "✅ 有效" if abs(ic_val) >= 0.02 else "⚠️ 弱信号"
                lines.append(f"| {factor} | {ic_val:.4f} | {status} |\n")
        else:
            default_factors = ["momentum_20", "ep", "low_volatility", "turnover"]
            for f in default_factors:
                lines.append(f"| {f} | 暂无数据 | - |\n")
        lines.append("")

        # 4. 风险预警摘要
        lines.append("## 风险预警摘要\n")
        # 简单检查：是否有信号缺失的交易日
        missing_dates = [d for d in dates if d not in signals]
        if missing_dates:
            lines.append(f"⚠️ 以下日期缺少信号数据：{', '.join(missing_dates)}\n")
        if nav_rows:
            nav_vals = [r["nav"] for r in sorted(nav_rows, key=lambda x: x["date"])]
            if len(nav_vals) >= 2:
                max_nav = max(nav_vals)
                min_after_max = min(nav_vals[nav_vals.index(max_nav):])
                drawdown = (min_after_max / max_nav - 1) * 100
                if drawdown < -5:
                    lines.append(f"⚠️ 本周内最大回撤：{drawdown:.2f}%（已超过 -5% 警戒线）\n")
                else:
                    lines.append(f"✅ 本周最大回撤：{drawdown:.2f}%（正常范围）\n")
        if not missing_dates and not nav_rows:
            lines.append("✅ 本周未发现风险预警\n")
        lines.append("")

        # 5. 下周调仓计划
        lines.append("## 下周调仓计划\n")
        # 取最新一天的选股作为下周参考
        latest_signal_date = max(signals.keys()) if signals else None
        if latest_signal_date:
            latest_picks = signals[latest_signal_date].get("picks", [])
            excluded = signals[latest_signal_date].get("excluded", {})
            lines.append(f"基于 {latest_signal_date} 信号，下周持仓候选（前10）：\n")
            lines.append(f"{', '.join(latest_picks[:10])}{'...' if len(latest_picks) > 10 else ''}\n")
            lines.append("")
            if excluded:
                lines.append("**过滤统计：**\n")
                for reason, count in excluded.items():
                    lines.append(f"- {reason}：{count} 只\n")
        else:
            lines.append("- 待信号生成后更新\n")
        lines.append("")

    report = "\n".join(lines)

    # 保存到 journal/weekly/{week}.md（已存在则追加）
    output_path = journal_dir / f"{week}.md"
    separator = "\n\n---\n\n"
    if output_path.exists():
        with open(output_path, "a", encoding="utf-8") as f:
            f.write(separator)
            f.write(report)
    else:
        with open(output_path, "w", encoding="utf-8") as f:
            f.write(report)

    return report


if __name__ == "__main__":
    # 生成当前周的周报并打印
    report = generate_weekly_report()
    print(report)
