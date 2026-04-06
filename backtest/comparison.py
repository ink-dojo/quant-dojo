"""
backtest/comparison.py — 多策略对比报告

生成自包含 HTML，叠加多个策略的 NAV 曲线和绩效指标。

用法:
    from backtest.comparison import generate_comparison_report
    report_path = generate_comparison_report(results, title="v7 vs v8")
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

# 调色板
COLORS = ["#0984e3", "#d63031", "#00b894", "#fdcb6e", "#6c5ce7", "#e17055", "#00cec9", "#fab1a0"]


def generate_comparison_report(
    results: list["BacktestResult"],
    title: str = "策略对比",
) -> Path:
    """
    生成多策略对比 HTML 报告。

    参数:
        results: BacktestResult 列表（只使用 status=success 的结果）
        title: 报告标题

    返回:
        报告文件路径
    """
    # 过滤成功的结果
    valid = [r for r in results if r.status == "success" and r.equity_curve is not None]
    if not valid:
        raise ValueError("无有效回测结果可用于对比")

    # NAV 序列
    nav_datasets = []
    for i, r in enumerate(valid):
        nav = (1 + r.equity_curve["portfolio_return"]).cumprod()
        label = f"{r.config.strategy} (n={r.config.n_stocks})"
        color = COLORS[i % len(COLORS)]
        nav_datasets.append({
            "label": label,
            "dates": [d.strftime("%Y-%m-%d") for d in nav.index],
            "values": [round(float(v), 4) for v in nav.values],
            "color": color,
        })

    # 统一日期轴（取并集）
    all_dates = sorted(set(d for ds in nav_datasets for d in ds["dates"]))
    dates_json = json.dumps(all_dates)

    # 构建 chart.js datasets
    chart_datasets = []
    for ds in nav_datasets:
        # 对齐到统一日期轴
        date_val_map = dict(zip(ds["dates"], ds["values"]))
        aligned = [date_val_map.get(d, None) for d in all_dates]
        chart_datasets.append({
            "label": ds["label"],
            "data": aligned,
            "borderColor": ds["color"],
            "borderWidth": 2,
            "pointRadius": 0,
            "tension": 0.1,
            "fill": False,
            "spanGaps": True,
        })
    datasets_json = json.dumps(chart_datasets)

    # 指标对比表
    metrics_rows = []
    for i, r in enumerate(valid):
        m = r.metrics
        color = COLORS[i % len(COLORS)]
        label = f"{r.config.strategy} (n={r.config.n_stocks})"
        metrics_rows.append(
            f'<tr>'
            f'<td><span style="display:inline-block;width:12px;height:12px;'
            f'background:{color};border-radius:2px;margin-right:6px"></span>{label}</td>'
            f'<td>{m.get("total_return", 0):.2%}</td>'
            f'<td>{m.get("annualized_return", 0):.2%}</td>'
            f'<td>{m.get("sharpe", 0):.2f}</td>'
            f'<td>{m.get("max_drawdown", 0):.2%}</td>'
            f'<td>{m.get("calmar", 0):.2f}</td>'
            f'<td>{m.get("win_rate", 0):.2%}</td>'
            f'<td>{m.get("n_trading_days", 0)}</td>'
            f'</tr>'
        )
    metrics_table = (
        '<table><thead><tr>'
        '<th>策略</th><th>总收益</th><th>年化收益</th><th>夏普</th>'
        '<th>最大回撤</th><th>卡玛</th><th>胜率</th><th>天数</th>'
        '</tr></thead><tbody>'
        + "".join(metrics_rows) +
        '</tbody></table>'
    )

    html = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{title}</title>
<style>
* {{ margin: 0; padding: 0; box-sizing: border-box; }}
body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; background: #f5f6fa; color: #2d3436; padding: 20px; }}
.container {{ max-width: 1200px; margin: 0 auto; }}
h1 {{ font-size: 24px; margin-bottom: 8px; }}
h2 {{ font-size: 18px; margin: 24px 0 12px; color: #636e72; border-bottom: 2px solid #dfe6e9; padding-bottom: 6px; }}
.subtitle {{ color: #636e72; font-size: 14px; margin-bottom: 20px; }}
.card {{ background: white; border-radius: 8px; padding: 20px; margin-bottom: 16px; box-shadow: 0 1px 3px rgba(0,0,0,0.1); }}
table {{ width: 100%; border-collapse: collapse; font-size: 14px; }}
th, td {{ padding: 8px 12px; text-align: left; border-bottom: 1px solid #dfe6e9; }}
th {{ background: #f8f9fa; font-weight: 600; }}
.chart-container {{ position: relative; height: 400px; }}
.footer {{ text-align: center; color: #b2bec3; font-size: 12px; margin-top: 24px; }}
</style>
<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.0/dist/chart.umd.min.js"></script>
</head>
<body>
<div class="container">

<h1>{title}</h1>
<p class="subtitle">对比 {len(valid)} 个回测 | 生成于 {datetime.now().strftime('%Y-%m-%d %H:%M')}</p>

<div class="card">
<h2>NAV 曲线对比</h2>
<div class="chart-container">
<canvas id="compareChart"></canvas>
</div>
</div>

<div class="card">
<h2>绩效指标对比</h2>
{metrics_table}
</div>

<div class="footer">quant-dojo strategy comparison</div>
</div>

<script>
new Chart(document.getElementById('compareChart'), {{
    type: 'line',
    data: {{
        labels: {dates_json},
        datasets: {datasets_json},
    }},
    options: {{
        responsive: true,
        maintainAspectRatio: false,
        plugins: {{
            legend: {{ display: true, position: 'top' }},
        }},
        scales: {{
            x: {{ display: true, ticks: {{ maxTicksLimit: 12 }} }},
            y: {{ display: true, title: {{ display: true, text: 'NAV' }} }},
        }},
    }}
}});
</script>
</body>
</html>"""

    RUNS_DIR.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    report_path = RUNS_DIR / f"comparison_{ts}.html"
    report_path.write_text(html, encoding="utf-8")

    print(f"  对比报告已生成: {report_path}")
    return report_path
