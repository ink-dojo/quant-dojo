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

    # 基准 NAV
    benchmark_nav_json = "null"
    if result.benchmark_returns is not None and not result.benchmark_returns.empty:
        bm_nav = (1 + result.benchmark_returns).cumprod()
        benchmark_nav_json = json.dumps([round(float(v), 4) for v in bm_nav.values])

    # 滚动夏普数据
    rolling_sharpe_json = "null"
    if result.rolling_metrics is not None and "rolling_sharpe" in result.rolling_metrics.columns:
        rs = result.rolling_metrics["rolling_sharpe"].dropna()
        if not rs.empty:
            rolling_sharpe_json = json.dumps([round(float(v), 4) for v in rs.values])

    # 指标表
    metrics_html = _render_metrics_table(metrics, result.benchmark_metrics)

    # 因子统计表
    factor_html = _render_factor_table(factor_stats)

    # 因子相关性矩阵
    corr_html = _render_correlation_matrix(factor_stats.get("_correlation_matrix"))

    # 分层回测
    quintile_html = _render_quintile_table(getattr(result, "quintile_stats", {}))

    # 调仓日志
    trade_html = _render_trade_log(result.trade_log)

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
<h2>滚动夏普比率 (63日)</h2>
<div class="chart-container">
<canvas id="rsChart"></canvas>
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
<h2>因子相关性矩阵</h2>
{corr_html}
</div>

<div class="card">
<h2>分层回测（Quintile）</h2>
{quintile_html}
</div>

<div class="card">
<h2>调仓记录</h2>
{trade_html}
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
const benchmarkData = {benchmark_nav_json};

// NAV Chart
const navDatasets = [{{
    label: '策略',
    data: navData,
    borderColor: '#0984e3',
    backgroundColor: 'rgba(9, 132, 227, 0.1)',
    fill: true,
    borderWidth: 2,
    pointRadius: 0,
    tension: 0.1,
}}];
if (benchmarkData) {{
    navDatasets.push({{
        label: '基准 ({config.benchmark})',
        data: benchmarkData,
        borderColor: '#636e72',
        borderDash: [5, 5],
        borderWidth: 1.5,
        pointRadius: 0,
        fill: false,
        tension: 0.1,
    }});
}}
new Chart(document.getElementById('navChart'), {{
    type: 'line',
    data: {{
        labels: dates,
        datasets: navDatasets,
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

// Rolling Sharpe Chart
const rollingSharpeData = {rolling_sharpe_json};
if (rollingSharpeData) {{
    const rsLabels = dates.slice(dates.length - rollingSharpeData.length);
    new Chart(document.getElementById('rsChart'), {{
        type: 'line',
        data: {{
            labels: rsLabels,
            datasets: [{{
                label: 'Rolling Sharpe (63d)',
                data: rollingSharpeData,
                borderColor: '#6c5ce7',
                borderWidth: 2,
                pointRadius: 0,
                tension: 0.1,
                fill: false,
            }}]
        }},
        options: {{
            responsive: true,
            maintainAspectRatio: false,
            plugins: {{ legend: {{ display: false }} }},
            scales: {{
                x: {{ display: true, ticks: {{ maxTicksLimit: 10 }} }},
                y: {{
                    display: true,
                    title: {{ display: true, text: 'Sharpe Ratio' }},
                }},
            }},
        }}
    }});
}} else {{
    document.getElementById('rsChart').parentElement.innerHTML = '<p style="color:#636e72">数据不足，无法计算滚动夏普</p>';
}}
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


def _render_metrics_table(metrics: dict, benchmark_metrics: dict = None) -> str:
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

    # 超额指标（如果有基准）
    if metrics.get("excess_return") is not None:
        items.append(("超额收益", metrics["excess_return"], True))
    if metrics.get("excess_sharpe") is not None:
        items.append(("超额夏普", metrics["excess_sharpe"], False))

    boxes = []
    for label, value, is_pct in items:
        if is_pct:
            formatted = f"{value:.2%}"
        else:
            formatted = f"{value:.2f}"

        css_class = ""
        if label in ("总收益", "年化收益", "超额收益"):
            css_class = "positive" if value > 0 else "negative"
        elif label == "最大回撤":
            css_class = "negative"

        boxes.append(
            f'<div class="metric-box">'
            f'<div class="value {css_class}">{formatted}</div>'
            f'<div class="label">{label}</div>'
            f'</div>'
        )

    html = f'<div class="metrics-grid">{"".join(boxes)}</div>'

    # 基准指标对照
    if benchmark_metrics:
        bm_items = [
            ("基准总收益", benchmark_metrics.get("total_return", 0), True),
            ("基准夏普", benchmark_metrics.get("sharpe", 0), False),
            ("基准回撤", benchmark_metrics.get("max_drawdown", 0), True),
        ]
        bm_boxes = []
        for label, value, is_pct in bm_items:
            formatted = f"{value:.2%}" if is_pct else f"{value:.2f}"
            bm_boxes.append(
                f'<div class="metric-box">'
                f'<div class="value" style="color:#636e72">{formatted}</div>'
                f'<div class="label">{label}</div>'
                f'</div>'
            )
        html += f'<div class="metrics-grid" style="margin-top:8px">{"".join(bm_boxes)}</div>'

    return html


def _render_factor_table(factor_stats: dict) -> str:
    """渲染因子统计表"""
    if not factor_stats:
        return "<p>无因子数据</p>"

    rows = []
    for name, stats in factor_stats.items():
        if name.startswith("_"):
            continue
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


def _render_correlation_matrix(corr_data: dict | None) -> str:
    """渲染因子相关性矩阵"""
    if not corr_data:
        return "<p>无相关性数据</p>"

    factors = list(corr_data.keys())
    header = "<tr><th></th>" + "".join(f"<th>{f}</th>" for f in factors) + "</tr>"

    rows = []
    for f1 in factors:
        cells = []
        for f2 in factors:
            val = corr_data[f1].get(f2, 0)
            # 颜色：高相关性 = 红色警告
            abs_val = abs(val)
            if f1 == f2:
                bg = "#f8f9fa"
            elif abs_val > 0.7:
                bg = "#ff7675"
            elif abs_val > 0.5:
                bg = "#fab1a0"
            elif abs_val > 0.3:
                bg = "#ffeaa7"
            else:
                bg = "#dfe6e9"
            cells.append(f'<td style="background:{bg};text-align:center">{val:.2f}</td>')
        rows.append(f"<tr><td><strong>{f1}</strong></td>{''.join(cells)}</tr>")

    return (
        '<table class="heatmap-table"><thead>' + header + '</thead><tbody>'
        + "".join(rows) + '</tbody></table>'
    )


def _render_quintile_table(quintile_stats: dict) -> str:
    """渲染分层回测表格"""
    if not quintile_stats:
        return "<p>无分层数据</p>"

    rows = []
    for name, stats in quintile_stats.items():
        group_ret = stats.get("group_cum_return", {})
        group_cells = ""
        for q in ["Q1", "Q2", "Q3", "Q4", "Q5"]:
            val = group_ret.get(q, 0)
            color = "positive" if val > 0 else "negative" if val < 0 else ""
            group_cells += f'<td class="{color}">{val:.2%}</td>'

        ls_ret = stats.get("ls_annual_return", 0)
        ls_sharpe = stats.get("ls_sharpe", 0)
        mono = stats.get("monotonicity", "mixed")
        mono_label = {"increasing": "递增", "decreasing": "递减", "mixed": "混合"}.get(mono, mono)
        mono_color = "#00b894" if mono in ("increasing", "decreasing") else "#fdcb6e"

        rows.append(
            f"<tr><td><strong>{name}</strong></td>"
            f"{group_cells}"
            f'<td class="{"positive" if ls_ret > 0 else "negative"}">{ls_ret:.2%}</td>'
            f"<td>{ls_sharpe:.2f}</td>"
            f'<td style="color:{mono_color}">{mono_label}</td>'
            f"</tr>"
        )

    return (
        "<table><thead><tr>"
        "<th>因子</th><th>Q1</th><th>Q2</th><th>Q3</th><th>Q4</th><th>Q5</th>"
        "<th>多空年化</th><th>多空夏普</th><th>单调性</th>"
        "</tr></thead><tbody>"
        + "".join(rows)
        + "</tbody></table>"
    )


def _render_trade_log(trade_log: list) -> str:
    """渲染调仓记录表"""
    if not trade_log:
        return "<p>无调仓记录</p>"

    rows = []
    for t in trade_log:
        buys_str = ", ".join(t.get("buys", [])[:5])
        if len(t.get("buys", [])) > 5:
            buys_str += f" +{len(t['buys'])-5}"
        sells_str = ", ".join(t.get("sells", [])[:5])
        if len(t.get("sells", [])) > 5:
            sells_str += f" +{len(t['sells'])-5}"

        rows.append(
            f"<tr><td>{t['date']}</td><td>{t.get('n_holdings', 0)}</td>"
            f"<td>{t.get('n_buys', 0)}</td><td>{t.get('n_sells', 0)}</td>"
            f"<td>{t.get('turnover', 0):.1%}</td>"
            f"<td style='font-size:12px'>{buys_str}</td>"
            f"<td style='font-size:12px'>{sells_str}</td></tr>"
        )

    # 汇总行
    avg_turnover = np.mean([t.get("turnover", 0) for t in trade_log])
    total_buys = sum(t.get("n_buys", 0) for t in trade_log)
    total_sells = sum(t.get("n_sells", 0) for t in trade_log)
    rows.append(
        f"<tr style='font-weight:700;background:#f8f9fa'>"
        f"<td>合计 ({len(trade_log)} 次)</td><td>-</td>"
        f"<td>{total_buys}</td><td>{total_sells}</td>"
        f"<td>{avg_turnover:.1%} (均)</td><td>-</td><td>-</td></tr>"
    )

    return (
        "<table><thead><tr>"
        "<th>日期</th><th>持仓</th><th>买入</th><th>卖出</th>"
        "<th>换手率</th><th>买入标的</th><th>卖出标的</th>"
        "</tr></thead><tbody>"
        + "".join(rows) +
        "</tbody></table>"
    )


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
