"""
Streamlit Dashboard — 量化流水线全流程可视化

运行方式:
  streamlit run streamlit_dashboard/app.py

数据来源: live/dashboard/dashboard_data.json
         (由 pipeline/dashboard_export.py 生成)
"""

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import streamlit as st

# 项目路径
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

DASHBOARD_FILE = PROJECT_ROOT / "live" / "dashboard" / "dashboard_data.json"

# ──────────────────────────────────────────────────────────────
# Page config
# ──────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="Quant Dojo Dashboard",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="expanded",
)


@st.cache_data(ttl=60)
def load_data() -> dict:
    """加载仪表盘数据（60s 缓存）"""
    if not DASHBOARD_FILE.exists():
        return {}
    with open(DASHBOARD_FILE, encoding="utf-8") as f:
        return json.load(f)


def refresh_data():
    """手动刷新数据"""
    try:
        from pipeline.dashboard_export import export_dashboard
        export_dashboard(include_ic=False)
        load_data.clear()
    except Exception as e:
        st.error(f"刷新失败: {e}")


# ──────────────────────────────────────────────────────────────
# Sidebar
# ──────────────────────────────────────────────────────────────
with st.sidebar:
    st.title("Quant Dojo")

    data = load_data()
    if not data:
        st.error("无数据，请先运行流水线")
        st.stop()

    generated_at = data.get("generated_at", "unknown")
    st.caption(f"数据更新: {generated_at[:19]}")

    if st.button("刷新数据"):
        refresh_data()
        st.rerun()

    # 策略状态
    strategy = data.get("strategy", {})
    active = strategy.get("active", "v7")
    st.metric("当前策略", active)

    # 关键指标
    perf = data.get("performance", {})
    if perf:
        col1, col2 = st.columns(2)
        col1.metric("总收益", f"{perf.get('total_return', 0):.2%}")
        col2.metric("夏普", f"{perf.get('sharpe', 0):.2f}")
        col1.metric("最大回撤", f"{perf.get('max_drawdown', 0):.2%}")
        col2.metric("交易笔数", perf.get("n_trades", 0))

    # 页面导航
    page = st.radio(
        "页面",
        ["总览", "持仓分析", "因子健康", "信号历史", "告警中心"],
        label_visibility="collapsed",
    )


# ──────────────────────────────────────────────────────────────
# Page: 总览
# ──────────────────────────────────────────────────────────────
if page == "总览":
    st.header("总览")

    nav_data = data.get("nav", {})
    dates = nav_data.get("dates", [])
    values = nav_data.get("values", [])
    drawdown = nav_data.get("drawdown", [])

    if dates and values:
        # NAV 曲线 + 回撤
        fig = make_subplots(
            rows=2, cols=1,
            shared_xaxes=True,
            vertical_spacing=0.08,
            row_heights=[0.7, 0.3],
            subplot_titles=("净值曲线", "回撤"),
        )

        fig.add_trace(
            go.Scatter(
                x=dates, y=values,
                mode="lines+markers",
                name="NAV",
                line=dict(color="#2196F3", width=2),
                marker=dict(size=6),
            ),
            row=1, col=1,
        )

        # 基准线
        if values:
            fig.add_hline(
                y=values[0], line_dash="dash", line_color="gray",
                annotation_text=f"初始 {values[0]:,.0f}",
                row=1, col=1,
            )

        if drawdown:
            fig.add_trace(
                go.Bar(
                    x=dates, y=[d * 100 for d in drawdown],
                    name="回撤 %",
                    marker_color="#F44336",
                    opacity=0.6,
                ),
                row=2, col=1,
            )

        fig.update_layout(
            height=500,
            showlegend=False,
            margin=dict(l=50, r=20, t=40, b=20),
        )
        fig.update_yaxes(title_text="NAV", row=1, col=1)
        fig.update_yaxes(title_text="回撤 %", row=2, col=1)

        st.plotly_chart(fig, use_container_width=True)
    else:
        st.info("暂无 NAV 数据")

    # 绩效指标表格
    if perf:
        st.subheader("绩效指标")
        cols = st.columns(6)
        metrics = [
            ("总收益", f"{perf.get('total_return', 0):.2%}"),
            ("年化收益", f"{perf.get('annualized_return', 0):.2%}"),
            ("波动率", f"{perf.get('volatility', 0):.2%}" if "volatility" in perf else "---"),
            ("夏普比率", f"{perf.get('sharpe', 0):.2f}"),
            ("最大回撤", f"{perf.get('max_drawdown', 0):.2%}"),
            ("运行天数", f"{perf.get('running_days', 0)} 天"),
        ]
        for col, (label, value) in zip(cols, metrics):
            col.metric(label, value)

    # 两列布局：行业分布 + 换手率
    col_left, col_right = st.columns(2)

    # 行业分布
    industry = data.get("industry_distribution", [])
    if industry:
        with col_left:
            st.subheader("行业分布")
            ind_df = pd.DataFrame(industry)
            fig_ind = px.pie(
                ind_df, values="count", names="industry",
                hole=0.4,
                color_discrete_sequence=px.colors.qualitative.Set3,
            )
            fig_ind.update_layout(height=380, margin=dict(l=20, r=20, t=20, b=20))
            st.plotly_chart(fig_ind, use_container_width=True)

    # 换手率历史
    turnover = data.get("turnover_history", [])
    if turnover:
        with col_right:
            st.subheader("换手率历史")
            t_df = pd.DataFrame(turnover)
            fig_t = px.bar(
                t_df, x="date", y="turnover",
                labels={"turnover": "换手率", "date": "日期"},
                color_discrete_sequence=["#FF9800"],
            )
            fig_t.update_layout(height=380, margin=dict(l=50, r=20, t=20, b=20))
            fig_t.update_yaxes(tickformat=".0%")
            st.plotly_chart(fig_t, use_container_width=True)


# ──────────────────────────────────────────────────────────────
# Page: 持仓分析
# ──────────────────────────────────────────────────────────────
elif page == "持仓分析":
    st.header("持仓分析")

    positions = data.get("positions", [])
    if not positions:
        st.info("无持仓数据")
        st.stop()

    pos_df = pd.DataFrame(positions)

    # P&L 瀑布图
    if "pnl" in pos_df.columns:
        st.subheader("个股盈亏")
        pos_sorted = pos_df.sort_values("pnl", ascending=False)

        colors = ["#4CAF50" if p >= 0 else "#F44336" for p in pos_sorted["pnl"]]
        fig_pnl = go.Figure(go.Bar(
            x=pos_sorted["symbol"],
            y=pos_sorted["pnl"],
            marker_color=colors,
            text=[f"{p:+,.0f}" for p in pos_sorted["pnl"]],
            textposition="outside",
        ))
        fig_pnl.update_layout(
            height=400,
            xaxis_title="股票",
            yaxis_title="盈亏 (元)",
            margin=dict(l=50, r=20, t=20, b=60),
        )
        st.plotly_chart(fig_pnl, use_container_width=True)

    # 盈亏分布 + 贡献分布
    if "pnl_pct" in pos_df.columns and "contribution" in pos_df.columns:
        col_l, col_r = st.columns(2)
        with col_l:
            st.subheader("盈亏率分布")
            fig_dist = px.histogram(
                pos_df, x="pnl_pct", nbins=15,
                labels={"pnl_pct": "盈亏率"},
                color_discrete_sequence=["#2196F3"],
            )
            fig_dist.update_layout(height=300, margin=dict(l=50, r=20, t=20, b=20))
            fig_dist.update_xaxes(tickformat=".1%")
            st.plotly_chart(fig_dist, use_container_width=True)

        with col_r:
            st.subheader("贡献度分布")
            top5 = pos_df.nlargest(5, "contribution")
            bot5 = pos_df.nsmallest(5, "contribution")
            contrib = pd.concat([top5, bot5]).sort_values("contribution", ascending=True)
            colors_c = ["#4CAF50" if c >= 0 else "#F44336" for c in contrib["contribution"]]
            fig_c = go.Figure(go.Bar(
                y=contrib["symbol"],
                x=contrib["contribution"],
                orientation="h",
                marker_color=colors_c,
                text=[f"{c:.4%}" for c in contrib["contribution"]],
                textposition="outside",
            ))
            fig_c.update_layout(height=300, margin=dict(l=80, r=60, t=20, b=20))
            fig_c.update_xaxes(tickformat=".3%", title="对组合收益贡献")
            st.plotly_chart(fig_c, use_container_width=True)

    # 持仓明细表
    st.subheader("持仓明细")
    display_cols = [c for c in ["symbol", "shares", "cost_price", "current_price",
                                 "market_value", "pnl", "pnl_pct", "weight", "contribution"]
                    if c in pos_df.columns]

    format_dict = {}
    if "cost_price" in display_cols:
        format_dict["cost_price"] = "{:.2f}"
    if "current_price" in display_cols:
        format_dict["current_price"] = "{:.2f}"
    if "market_value" in display_cols:
        format_dict["market_value"] = "{:,.2f}"
    if "pnl" in display_cols:
        format_dict["pnl"] = "{:+,.2f}"
    if "pnl_pct" in display_cols:
        format_dict["pnl_pct"] = "{:.2%}"
    if "weight" in display_cols:
        format_dict["weight"] = "{:.2%}"
    if "contribution" in display_cols:
        format_dict["contribution"] = "{:.4%}"

    st.dataframe(
        pos_df[display_cols].style.format(format_dict),
        use_container_width=True,
        height=min(600, len(pos_df) * 35 + 50),
    )

    # 统计
    if "pnl" in pos_df.columns:
        col1, col2, col3, col4 = st.columns(4)
        col1.metric("盈利股数", int((pos_df["pnl"] > 0).sum()))
        col2.metric("亏损股数", int((pos_df["pnl"] < 0).sum()))
        col3.metric("最大盈利", f"{pos_df['pnl'].max():+,.0f}")
        col4.metric("最大亏损", f"{pos_df['pnl'].min():+,.0f}")


# ──────────────────────────────────────────────────────────────
# Page: 因子健康
# ──────────────────────────────────────────────────────────────
elif page == "因子健康":
    st.header("因子健康")

    factor_health = data.get("factor_health", {})
    factors = factor_health.get("factors", {})
    strategy_name = factor_health.get("strategy", "v7")

    st.caption(f"策略: {strategy_name}")

    if not factors:
        st.info("无因子健康数据")
        st.stop()

    # 因子状态卡片
    cols = st.columns(len(factors))
    status_colors = {
        "healthy": "green",
        "degraded": "orange",
        "dead": "red",
        "no_data": "gray",
    }

    for col, (name, info) in zip(cols, factors.items()):
        status = info.get("status", "no_data")
        ic = info.get("rolling_ic")
        ic_str = f"{ic:.4f}" if ic is not None else "N/A"
        color = status_colors.get(status, "gray")

        col.markdown(f"**{name}**")
        col.markdown(f"IC: `{ic_str}`")
        col.markdown(f":{color}[{status.upper()}]")

    # 因子 IC 柱状图
    st.subheader("因子 IC 对比")
    ic_data = []
    bar_colors_map = {
        "healthy": "#4CAF50",
        "degraded": "#FF9800",
        "dead": "#F44336",
        "no_data": "#9E9E9E",
    }
    for name, info in factors.items():
        ic = info.get("rolling_ic")
        status = info.get("status", "no_data")
        if ic is not None:
            ic_data.append({"factor": name, "IC": ic, "status": status})

    if ic_data:
        ic_df = pd.DataFrame(ic_data)
        bar_colors = [bar_colors_map.get(s, "gray") for s in ic_df["status"]]
        fig_ic = go.Figure(go.Bar(
            x=ic_df["factor"],
            y=ic_df["IC"],
            marker_color=bar_colors,
            text=[f"{v:.4f}" for v in ic_df["IC"]],
            textposition="outside",
        ))
        fig_ic.update_layout(
            height=350,
            yaxis_title="IC 均值",
            margin=dict(l=50, r=20, t=20, b=20),
        )
        fig_ic.add_hline(y=0.02, line_dash="dash", line_color="green",
                         annotation_text="healthy 阈值")
        fig_ic.add_hline(y=-0.02, line_dash="dash", line_color="green")
        st.plotly_chart(fig_ic, use_container_width=True)

    # 因子 IC 历史（如果有）
    factor_ic = data.get("factor_ic", {})
    if factor_ic and factor_ic.get("factors"):
        st.subheader("因子 IC 历史")
        ic_factors = factor_ic["factors"]
        selected = st.multiselect(
            "选择因子",
            list(ic_factors.keys()),
            default=list(ic_factors.keys())[:3],
        )
        if selected:
            fig_hist = go.Figure()
            for fname in selected:
                fdata = ic_factors.get(fname, {})
                if fdata.get("dates"):
                    fig_hist.add_trace(go.Scatter(
                        x=fdata["dates"], y=fdata["values"],
                        mode="lines", name=fname,
                    ))
            fig_hist.update_layout(
                height=350,
                yaxis_title="IC",
                margin=dict(l=50, r=20, t=20, b=20),
            )
            fig_hist.add_hline(y=0, line_dash="dash", line_color="gray")
            st.plotly_chart(fig_hist, use_container_width=True)


# ──────────────────────────────────────────────────────────────
# Page: 信号历史
# ──────────────────────────────────────────────────────────────
elif page == "信号历史":
    st.header("信号历史")

    signals = data.get("signal_history", [])
    if not signals:
        st.info("无信号历史")
        st.stop()

    sig_df = pd.DataFrame(signals)

    # 选股数量折线
    st.subheader("每日选股数量")
    fig_s = px.line(
        sig_df, x="date", y="n_picks",
        markers=True,
        labels={"n_picks": "选股数", "date": "日期"},
        color_discrete_sequence=["#2196F3"],
    )
    fig_s.update_layout(height=300, margin=dict(l=50, r=20, t=20, b=20))
    st.plotly_chart(fig_s, use_container_width=True)

    # 信号明细
    st.subheader("信号明细")
    st.dataframe(sig_df, use_container_width=True)

    # Top 股票频率统计
    all_top3 = []
    for sig in signals:
        all_top3.extend(sig.get("top_3", []))
    if all_top3:
        st.subheader("Top-3 高频出现股票")
        from collections import Counter
        freq = Counter(all_top3).most_common(10)
        freq_df = pd.DataFrame(freq, columns=["symbol", "出现次数"])
        fig_freq = px.bar(
            freq_df, x="symbol", y="出现次数",
            color_discrete_sequence=["#9C27B0"],
        )
        fig_freq.update_layout(height=300, margin=dict(l=50, r=20, t=20, b=20))
        st.plotly_chart(fig_freq, use_container_width=True)


# ──────────────────────────────────────────────────────────────
# Page: 告警中心
# ──────────────────────────────────────────────────────────────
elif page == "告警中心":
    st.header("告警中心")

    alerts = data.get("recent_alerts", [])
    if not alerts:
        st.success("无告警记录")
        st.stop()

    # 告警统计
    level_counts = {}
    for a in alerts:
        lvl = a.get("level", "unknown")
        level_counts[lvl] = level_counts.get(lvl, 0) + 1

    cols = st.columns(4)
    cols[0].metric("总告警数", len(alerts))
    cols[1].metric("CRITICAL", level_counts.get("critical", 0))
    cols[2].metric("WARNING", level_counts.get("warning", 0))
    cols[3].metric("INFO", level_counts.get("info", 0))

    # 告警列表
    st.subheader("告警时间线")
    for alert in alerts:
        level = alert.get("level", "info")
        title = alert.get("title", "")
        body = alert.get("body", "")
        ts = alert.get("timestamp", "")[:19]
        source = alert.get("source", "")

        if level == "critical":
            icon = "🔴"
        elif level == "warning":
            icon = "🟡"
        else:
            icon = "🔵"

        with st.expander(f"{icon} [{level.upper()}] {title}", expanded=(level == "critical")):
            st.caption(f"时间: {ts} | 来源: {source}")
            if body:
                st.write(body)


# ──────────────────────────────────────────────────────────────
# Footer
# ──────────────────────────────────────────────────────────────
st.divider()
st.caption("Quant Dojo Dashboard | 数据由 AI Agent 流水线自动生成")
