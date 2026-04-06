"""
backtest/report.py — 回测 HTML 报告生成

生成自包含的 HTML 报告，包含:
  - NAV 曲线 + 回撤图
  - 月度收益热力图
  - 绩效指标表
  - 因子 IC 统计表
  - 回测配置摘要

输出: live/runs/{run_id}_report.html
"""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING

import numpy as np
import pandas as pd

if TYPE_CHECKING:
    from backtest.standardized import BacktestResult

RUNS_DIR = Path(__file__).parent.parent / "live" / "runs"


def generate_html_report(result: "BacktestResult") -> Path:
    """
    生成自包含 HTML 回测报告。

    参数:
        result: BacktestResult 实例

    返回:
        报告文件路径
    """
    config = result.config
    metrics = result.metrics
    equity = result.equity_curve
    factor_stats = result.factor_stats

    # NAV 序列
    if equity is not None and "portfolio_return" in equity.columns:
        nav = (1 + equity["portfolio_return"]).cumprod()
        dates_json = json.dumps([d.strftime("%Y-%m-%d") for d in nav.index])
        nav_json = json.dumps([round(float(v), 4) for v in nav.values])

        # 回撤序列
        peak = np.maximum.accumulate(nav.values)
        dd = ((nav.values - peak) / peak)
        dd_json = json.dumps([round(float(v), 4) for v in dd])

        # 月度收益热力图数据
        monthly = _compute_monthly_returns(equity["portfolio_return"])
        monthly_html = _render_monthly_heatmap(monthly)
    else:
        dates_json = "[]"
        nav_json = "[]"
        dd_json = "[]"
        monthly_html = "<p>无数据</p>"

    # 指标表
    metrics_html = _render_metrics_table(metrics)

    # 因子统计表
    factor_html = _render_factor_table(factor_stats)

    # 配置摘要
    config_html = _render_config_table(config)

    html = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>回测报告 — {config.strategy} | {config.start} ~ {config.end}</title>
<style>
* {{ margin: 0; padding: 0; box-sizing: border-box; }}
body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; background: #f5f6fa; color: #2d3436; padding: 20px; }}
.container {{ max-width: 1200px; margin: 0 auto; }}
h1 {{ font-size: 24px; margin-bottom: 8px; color: #2d3436; }}
h2 {{ font-size: 18px; margin: 24px 0 12px; color: #636e72; border-bottom: 2px solid #dfe6e9; padding-bottom: 6px; }}
.subtitle {{ color: #636e72; font-size: 14px; margin-bottom: 20px; }}
.card {{ background: white; border-radius: 8px; padding: 20px; margin-bottom: 16px; box-shadow: 0 1px 3px rgba(0,0,0,0.1); }}
.metrics-grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 12px; }}
.metric-box {{ background: #f8f9fa; border-radius: 6px; padding: 14px; text-align: center; }}
.metric-box .value {{ font-size: 22px; font-weight: 700; color: #2d3436; }}
.metric-box .label {{ font-size: 12px; color: #636e72; margin-top: 4px; }}
.positive {{ color: #00b894 !important; }}
.negative {{ color: #d63031 !important; }}
table {{ width: 100%; border-collapse: collapse; font-size: 14px; }}
th, td {{ padding: 8px 12px; text-align: left; border-bottom: 1px solid #dfe6e9; }}
th {{ background: #f8f9fa; font-weight: 600; color: #636e72; }}
canvas {{ width: 100% !important; }}
.chart-container {{ position: relative; height: 300px; }}
.heatmap-table td {{ text-align: center; font-size: 13px; font-weight: 500; padding: 6px 10px; }}
.footer {{ text-align: center; color: #b2bec3; font-size: 12px; margin-top: 24px; padding: 12px; }}
</style>
<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.0/dist/chart.umd.min.js"></script>
</head>
<body>
<div class="container">

<h1>回测报告 — {config.strategy.upper()}</h1>
<p class="subtitle">{config.start} ~ {config.end} | 生成于 {datetime.now().strftime('%Y-%m-%d %H:%M')}</p>

<div class="card">
<h2>绩效概览</h2>
{metrics_html}
</div>

<div class="card">
<h2>NAV 曲线</h2>
<div class="chart-container">
<canvas id="navChart"></canvas>
</div>
</div>

<div class="card">
<h2>回撤</h2>
<div class="chart-container">
<canvas id="ddChart"></canvas>
</div>
</div>

<div class="card">
<h2>月度收益</h2>
{monthly_html}
</div>

<div class="card">
<h2>因子统计</h2>
{factor_html}
</div>

<div class="card">
<h2>回测配置</h2>
{config_html}
</div>

<div class="footer">
quant-dojo standardized backtest | run_id: {result.run_id or 'N/A'}
</div>

</div>

<script>
const dates = {dates_json};
const navData = {nav_json};
const ddData = {dd_json};

// NAV Chart
new Chart(document.getElementById('navChart'), {{
    type: 'line',
    data: {{
        labels: dates,
        datasets: [{{
            label: 'NAV',
            data: navData,
            borderColor: '#0984e3',
            backgroundColor: 'rgba(9, 132, 227, 0.1)',
            fill: true,
            borderWidth: 2,
            pointRadius: 0,
            tension: 0.1,
        }}]
    }},
    options: {{
        responsive: true,
        maintainAspectRatio: false,
        plugins: {{ legend: {{ display: false }} }},
        scales: {{
            x: {{ display: true, ticks: {{ maxTicksLimit: 10 }} }},
            y: {{ display: true }}
        }}
    }}
}});

// Drawdown Chart
new Chart(document.getElementById('ddChart'), {{
    type: 'line',
    data: {{
        labels: dates,
        datasets: [{{
            label: 'Drawdown',
            data: ddData,
            borderColor: '#d63031',
            backgroundColor: 'rgba(214, 48, 49, 0.15)',
            fill: true,
            borderWidth: 2,
            pointRadius: 0,
            tension: 0.1,
        }}]
    }},
    options: {{
        responsive: true,
        maintainAspectRatio: false,
        plugins: {{ legend: {{ display: false }} }},
        scales: {{
            x: {{ display: true, ticks: {{ maxTicksLimit: 10 }} }},
            y: {{ display: true, ticks: {{ callback: v => (v * 100).toFixed(1) + '%' }} }}
        }}
    }}
}});
</script>
</body>
</html>"""

    # 保存
    RUNS_DIR.mkdir(parents=True, exist_ok=True)
    filename = f"{result.run_id}_report.html" if result.run_id else "backtest_report.html"
    report_path = RUNS_DIR / filename
    report_path.write_text(html, encoding="utf-8")

    print(f"  HTML 报告已生成: {report_path}")
    return report_path


def _render_metrics_table(metrics: dict) -> str:
    """渲染绩效指标网格"""
    if not metrics:
        return "<p>无指标数据</p>"

    items = [
        ("总收益", metrics.get("total_return", 0), True),
        ("年化收益", metrics.get("annualized_return", 0), True),
        ("夏普比率", metrics.get("sharpe", 0), False),
        ("最大回撤", metrics.get("max_drawdown", 0), True),
        ("年化波动", metrics.get("annualized_volatility", 0), True),
        ("卡玛比率", metrics.get("calmar", 0), False),
        ("胜率", metrics.get("win_rate", 0), True),
        ("盈亏比", metrics.get("profit_loss_ratio", 0), False),
    ]

    boxes = []
    for label, value, is_pct in items:
        if is_pct:
            formatted = f"{value:.2%}"
        else:
            formatted = f"{value:.2f}"

        css_class = ""
        if label in ("总收益", "年化收益"):
            css_class = "positive" if value > 0 else "negative"
        elif label == "最大回撤":
            css_class = "negative"

        boxes.append(
            f'<div class="metric-box">'
            f'<div class="value {css_class}">{formatted}</div>'
            f'<div class="label">{label}</div>'
            f'</div>'
        )

    return f'<div class="metrics-grid">{"".join(boxes)}</div>'


def _render_factor_table(factor_stats: dict) -> str:
    """渲染因子统计表"""
    if not factor_stats:
        return "<p>无因子数据</p>"

    rows = []
    for name, stats in factor_stats.items():
        ic_mean = stats.get("ic_mean", 0)
        ic_std = stats.get("ic_std", 0)
        icir = stats.get("icir", 0)
        direction = stats.get("direction", 1)
        dir_label = "正向" if direction == 1 else "反向"
        rows.append(
            f"<tr><td>{name}</td><td>{ic_mean:.4f}</td>"
            f"<td>{ic_std:.4f}</td><td>{icir:.4f}</td>"
            f"<td>{dir_label}</td></tr>"
        )

    return (
        "<table><thead><tr>"
        "<th>因子</th><th>IC 均值</th><th>IC 标准差</th><th>ICIR</th><th>方向</th>"
        "</tr></thead><tbody>"
        + "".join(rows) +
        "</tbody></table>"
    )


def _render_config_table(config) -> str:
    """渲染配置表"""
    items = [
        ("策略", config.strategy),
        ("回测区间", f"{config.start} ~ {config.end}"),
        ("选股数量", config.n_stocks),
        ("手续费率", f"{config.commission:.4f}"),
        ("初始资金", f"{config.initial_capital:,.0f}"),
        ("行业中性化", "是" if config.neutralize else "否"),
        ("最低股价", f"{config.min_price:.1f}"),
        ("最短上市天数", config.min_listing_days),
    ]

    rows = "".join(f"<tr><td>{k}</td><td>{v}</td></tr>" for k, v in items)
    return f"<table><tbody>{rows}</tbody></table>"


def _compute_monthly_returns(returns: pd.Series) -> pd.DataFrame:
    """计算月度收益表（年 x 月）"""
    monthly = returns.resample("ME").apply(lambda x: (1 + x).prod() - 1)
    df = pd.DataFrame({
        "year": monthly.index.year,
        "month": monthly.index.month,
        "return": monthly.values,
    })
    pivot = df.pivot_table(index="year", columns="month", values="return")
    pivot.columns = [f"{m}月" for m in pivot.columns]
    return pivot


def _render_monthly_heatmap(monthly: pd.DataFrame) -> str:
    """渲染月度收益热力图 HTML"""
    if monthly.empty:
        return "<p>无月度数据</p>"

    header = "<tr><th>年</th>" + "".join(f"<th>{c}</th>" for c in monthly.columns) + "<th>全年</th></tr>"

    rows = []
    for year in monthly.index:
        cells = []
        year_vals = []
        for col in monthly.columns:
            val = monthly.loc[year, col]
            if pd.isna(val):
                cells.append("<td>-</td>")
            else:
                year_vals.append(val)
                color = _heatmap_color(val)
                cells.append(f'<td style="background:{color}">{val:.2%}</td>')

        # 全年收益
        if year_vals:
            annual = float(np.prod([1 + v for v in year_vals]) - 1)
            color = _heatmap_color(annual)
            cells.append(f'<td style="background:{color};font-weight:700">{annual:.2%}</td>')
        else:
            cells.append("<td>-</td>")

        rows.append(f"<tr><td><strong>{year}</strong></td>{''.join(cells)}</tr>")

    return f'<table class="heatmap-table"><thead>{header}</thead><tbody>{"".join(rows)}</tbody></table>'


def _heatmap_color(value: float) -> str:
    """返回热力图颜色"""
    if value > 0.05:
        return "#00b894"
    elif value > 0.02:
        return "#55efc4"
    elif value > 0:
        return "#dfe6e9"
    elif value > -0.02:
        return "#fab1a0"
    elif value > -0.05:
        return "#ff7675"
    else:
        return "#d63031"
