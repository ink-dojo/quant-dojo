"""
agents/reporter.py — 日报/周报生成 Agent

职责:
  1. 汇总当日流水线各阶段结果
  2. 生成结构化日报（Markdown）
  3. 周报时附加因子研究和策略建议
  4. 保存到 journal/ 目录
"""

import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

REPORT_DIR = Path(__file__).parent.parent / "journal"


class Reporter:
    """
    报告生成 Agent：汇总流水线结果为可读报告。
    """

    def run(self, ctx: Any) -> dict:
        """
        生成当日报告。

        返回:
            dict: {report_path: str, sections: [...]}
        """
        report_lines = []
        date = ctx.date

        # ── 标题 ──────────────────────────────────────────────
        report_lines.append(f"# 量化流水线日报 | {date}")
        report_lines.append(f"")
        report_lines.append(f"生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        report_lines.append(f"模式: {ctx.mode}")
        report_lines.append("")

        # ── 流水线概览 ────────────────────────────────────────
        report_lines.append("## 流水线概览")
        report_lines.append("")
        report_lines.append(f"| 阶段 | 状态 | 耗时 |")
        report_lines.append(f"|------|------|------|")
        for sr in ctx.stage_results:
            status_icon = {
                "success": "OK",
                "failed": "FAIL",
                "skipped": "SKIP",
            }.get(sr.status.value, sr.status.value)
            report_lines.append(
                f"| {sr.name} | {status_icon} | {sr.duration_sec:.1f}s |"
            )
        report_lines.append("")

        # ── 信号摘要 ──────────────────────────────────────────
        signal = ctx.get("signal_result")
        if signal:
            picks = signal.get("picks", [])
            excluded = signal.get("excluded", {})
            report_lines.append("## 信号摘要")
            report_lines.append("")
            report_lines.append(f"- 选股: **{len(picks)}** 只")
            report_lines.append(f"- 策略: {signal.get('metadata', {}).get('strategy', 'unknown')}")
            report_lines.append(
                f"- 排除: ST={excluded.get('st', 0)}, "
                f"次新={excluded.get('new_listing', 0)}, "
                f"低价={excluded.get('low_price', 0)}"
            )
            if picks:
                report_lines.append(f"- Top 10: {', '.join(picks[:10])}")
            report_lines.append("")

        # ── 调仓摘要 ──────────────────────────────────────────
        rebalance = ctx.get("rebalance_summary")
        if rebalance:
            report_lines.append("## 调仓摘要")
            report_lines.append("")
            report_lines.append(f"- 买入: {rebalance.get('n_buys', 0)} 只")
            report_lines.append(f"- 卖出: {rebalance.get('n_sells', 0)} 只")
            report_lines.append(f"- 换手率: {rebalance.get('turnover', 0):.1%}")
            report_lines.append(f"- NAV: {rebalance.get('nav_after', 0):,.2f}")
            report_lines.append(f"- 现金: {rebalance.get('cash_after', 0):,.2f}")
            report_lines.append("")

        # ── 风控状态 ──────────────────────────────────────────
        risk_level = ctx.get("risk_level", "ok")
        risk_alerts = ctx.get("risk_alerts", [])
        report_lines.append("## 风控状态")
        report_lines.append("")
        if risk_level == "ok":
            report_lines.append("无告警")
        else:
            report_lines.append(f"**风险等级: {risk_level.upper()}**")
            report_lines.append("")
            for alert in risk_alerts:
                level = alert.get("level", "info")
                msg = alert.get("msg", str(alert))
                report_lines.append(f"- [{level.upper()}] {msg}")
        report_lines.append("")

        # ── 因子研究（周报）──────────────────────────────────
        rankings = ctx.get("factor_rankings")
        if rankings:
            report_lines.append("## 因子研究")
            report_lines.append("")
            report_lines.append(f"| 排名 | 因子 | IC均值 | ICIR | t统计量 | 类别 |")
            report_lines.append(f"|------|------|--------|------|---------|------|")
            for i, r in enumerate(rankings[:10], 1):
                report_lines.append(
                    f"| {i} | {r['name']} | {r['IC_mean']:.4f} | "
                    f"{r['ICIR']:.4f} | {r['t_stat']:.4f} | {r['category']} |"
                )
            report_lines.append("")

            recommended = ctx.get("recommended_factors", [])
            if recommended:
                report_lines.append(f"**推荐组合**: {', '.join(recommended)}")
                report_lines.append("")

        # ── 策略建议（周报）──────────────────────────────────
        strategy_result = ctx.get("strategy_result")
        if strategy_result:
            rec = strategy_result.get("recommendation", "keep")
            reason = strategy_result.get("reason", "")
            report_lines.append("## 策略建议")
            report_lines.append("")
            report_lines.append(f"- 建议: **{rec.upper()}**")
            report_lines.append(f"- 原因: {reason}")
            report_lines.append("")

        # ── LLM 深度分析（可选）─────────────────────────────
        try:
            from agents.factor_analyst import FactorAnalyst
            analyst = FactorAnalyst()

            # 因子排行分析
            if rankings:
                commentary = analyst.analyze_rankings(rankings, date)
                if commentary:
                    report_lines.append("## AI 分析")
                    report_lines.append("")
                    report_lines.append(commentary)
                    report_lines.append("")

            # 信号洞察
            if signal:
                insight = analyst.daily_market_insight(signal)
                if insight:
                    if not rankings:
                        report_lines.append("## AI 分析")
                        report_lines.append("")
                    report_lines.append(f"**今日洞察**: {insight}")
                    report_lines.append("")
        except Exception:
            pass

        # ── 决策日志 ──────────────────────────────────────────
        if ctx.decisions:
            report_lines.append("## 决策日志")
            report_lines.append("")
            for d in ctx.decisions:
                report_lines.append(
                    f"- **{d['agent']}**: {d['decision']}"
                )
                if d.get("reasoning"):
                    report_lines.append(f"  - {d['reasoning']}")
            report_lines.append("")

        # ── 保存 ──────────────────────────────────────────────
        report_text = "\n".join(report_lines)
        report_path = self._save_report(report_text, date)

        print(f"  日报已生成: {report_path}")
        print(f"  共 {len(report_lines)} 行")

        # 导出仪表盘数据
        try:
            from pipeline.dashboard_export import export_dashboard
            export_dashboard(include_ic=False)
        except Exception as e:
            print(f"  仪表盘导出跳过: {e}")

        return {"report_path": str(report_path), "sections": len(ctx.stage_results)}

    def _save_report(self, report_text: str, date: str) -> Path:
        """保存报告为 Markdown"""
        REPORT_DIR.mkdir(parents=True, exist_ok=True)
        path = REPORT_DIR / f"daily_report_{date}.md"
        with open(path, "w", encoding="utf-8") as f:
            f.write(report_text)
        return path
