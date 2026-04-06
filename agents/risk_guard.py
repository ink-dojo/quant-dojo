"""
agents/risk_guard.py — 风控守卫 Agent

职责:
  1. 执行全套风控检查（回撤、集中度、因子健康）
  2. 根据告警等级决定是否中止流水线
  3. 记录风控决策到审计日志
  4. CRITICAL 级别告警可以触发流水线 halt
"""

import logging
from typing import Any

logger = logging.getLogger(__name__)


class RiskGuard:
    """
    风控守卫：流水线的最后安全门。

    规则:
      - WARNING 级别: 记录并继续
      - CRITICAL 级别: 记录并可选中止流水线（halt_on_critical=True）
    """

    def __init__(self, halt_on_critical: bool = False):
        """
        参数:
            halt_on_critical: CRITICAL 告警时是否中止流水线
                              默认 False（模拟盘阶段，记录但不中止）
        """
        self.halt_on_critical = halt_on_critical

    def run(self, ctx: Any) -> dict:
        """
        执行风控检查。

        返回:
            dict: {alerts: [...], risk_level: "ok"|"warning"|"critical", halted: bool}
        """
        from live.risk_monitor import check_risk_alerts, format_risk_report
        from live.paper_trader import PaperTrader

        result = {
            "alerts": [],
            "risk_level": "ok",
            "halted": False,
        }

        try:
            trader = PaperTrader()
            portfolio = trader.get_current_positions()

            if portfolio.empty:
                print("  无持仓，跳过风控检查")
                ctx.log_decision("RiskGuard", "跳过风控: 无持仓")
                return result

            alerts = check_risk_alerts(portfolio)

        except Exception as e:
            print(f"  风控检查异常: {e}")
            logger.error("风控检查失败: %s", e)
            result["alerts"] = [{"level": "warning", "msg": f"风控检查失败: {e}"}]
            result["risk_level"] = "warning"
            return result

        result["alerts"] = alerts

        if not alerts:
            print("  风控正常，无告警")
            ctx.log_decision("RiskGuard", "风控检查通过，无告警")
            return result

        # 分级处理
        critical_alerts = [a for a in alerts if a.get("level") == "critical"]
        warning_alerts = [a for a in alerts if a.get("level") == "warning"]

        if critical_alerts:
            result["risk_level"] = "critical"
            for a in critical_alerts:
                print(f"  [CRITICAL] {a.get('msg', a)}")
        if warning_alerts:
            if result["risk_level"] != "critical":
                result["risk_level"] = "warning"
            for a in warning_alerts:
                print(f"  [WARNING] {a.get('msg', a)}")

        # CRITICAL 处理
        if critical_alerts and self.halt_on_critical:
            result["halted"] = True
            ctx.halt = True
            ctx.halt_reason = f"风控 CRITICAL: {critical_alerts[0].get('msg', '')}"
            ctx.log_decision(
                "RiskGuard",
                f"中止流水线: {len(critical_alerts)} 个 CRITICAL 告警",
                "; ".join(a.get("msg", str(a)) for a in critical_alerts),
            )
        else:
            ctx.log_decision(
                "RiskGuard",
                f"风控检查: {len(warning_alerts)} WARNING, {len(critical_alerts)} CRITICAL",
                "继续运行（模拟盘模式不中止）",
            )

        ctx.set("risk_alerts", alerts)
        ctx.set("risk_level", result["risk_level"])

        # 发送告警通知
        if alerts:
            try:
                from pipeline.alert_notifier import send_risk_alerts
                send_risk_alerts(alerts, date=ctx.date)
            except Exception:
                pass

        return result
