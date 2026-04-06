"""
pipeline/alert_notifier.py — 告警通知系统

在风控告警、因子衰减、策略升级等事件发生时发送通知。

通知渠道:
  1. 本地日志文件（始终启用）: logs/alerts.log
  2. Webhook（可选）: 配置 config.yaml 的 alerts.webhook_url
  3. 终端声音提示（macOS，可选）

用法:
    from pipeline.alert_notifier import send_alert, AlertLevel

    send_alert(
        level=AlertLevel.CRITICAL,
        title="因子 bp 已失效",
        body="IC 均值降至 0.001，连续 5 日低于阈值",
        source="RiskGuard",
    )
"""

import json
import logging
import urllib.request
from datetime import datetime
from enum import Enum
from pathlib import Path

logger = logging.getLogger(__name__)

ALERT_LOG_FILE = Path(__file__).parent.parent / "logs" / "alerts.log"


class AlertLevel(str, Enum):
    INFO = "info"
    WARNING = "warning"
    CRITICAL = "critical"


def _get_webhook_url() -> str:
    """从配置文件读取 webhook URL"""
    try:
        from utils.runtime_config import get_config
        cfg = get_config()
        return cfg.get("alerts", {}).get("webhook_url", "")
    except Exception:
        return ""


def _log_to_file(alert: dict):
    """写入本地告警日志"""
    ALERT_LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    line = json.dumps(alert, ensure_ascii=False)
    with open(ALERT_LOG_FILE, "a", encoding="utf-8") as f:
        f.write(line + "\n")


def _send_webhook(url: str, alert: dict) -> bool:
    """发送 webhook 通知（POST JSON）"""
    try:
        payload = json.dumps(alert, ensure_ascii=False).encode("utf-8")
        req = urllib.request.Request(
            url,
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            return resp.status == 200
    except Exception as e:
        logger.warning("Webhook 发送失败 (%s): %s", url, e)
        return False


def send_alert(
    level: AlertLevel,
    title: str,
    body: str = "",
    source: str = "",
    date: str = "",
) -> dict:
    """
    发送告警通知。

    参数:
        level: 告警级别 (info/warning/critical)
        title: 告警标题
        body: 告警详情
        source: 来源 Agent 名称
        date: 关联日期（默认今天）

    返回:
        dict: {"logged": True, "webhook_sent": bool}
    """
    if not date:
        date = datetime.now().strftime("%Y-%m-%d")

    alert = {
        "timestamp": datetime.now().isoformat(),
        "level": level.value if isinstance(level, AlertLevel) else level,
        "title": title,
        "body": body,
        "source": source,
        "date": date,
    }

    # 1. 始终写本地日志
    _log_to_file(alert)

    # 2. 终端输出
    level_str = alert["level"].upper()
    print(f"  [{level_str}] {title}")
    if body:
        print(f"         {body}")

    # 3. Webhook（如果配置了）
    webhook_sent = False
    webhook_url = _get_webhook_url()
    if webhook_url:
        webhook_sent = _send_webhook(webhook_url, alert)

    return {"logged": True, "webhook_sent": webhook_sent}


def send_risk_alerts(alerts: list, date: str = ""):
    """
    批量发送风控告警。

    参数:
        alerts: risk_monitor.check_risk_alerts() 返回的告警列表
        date: 关联日期
    """
    for alert in alerts:
        level_str = alert.get("level", "warning")
        level = AlertLevel(level_str) if level_str in AlertLevel.__members__.values() else AlertLevel.WARNING
        send_alert(
            level=level,
            title=alert.get("msg", str(alert)),
            body=alert.get("code", ""),
            source="RiskGuard",
            date=date,
        )


def send_strategy_change_alert(previous: str, current: str, reason: str, date: str = ""):
    """发送策略切换通知"""
    send_alert(
        level=AlertLevel.WARNING,
        title=f"策略自动升级: {previous} → {current}",
        body=reason,
        source="StrategyComposer",
        date=date,
    )


def send_factor_health_alerts(health_report: dict, date: str = ""):
    """
    根据因子健康度报告发送告警。

    只发送 degraded 和 dead 状态的因子。
    """
    for factor_name, info in health_report.items():
        status = info.get("status")
        if status == "dead":
            send_alert(
                level=AlertLevel.CRITICAL,
                title=f"因子 {factor_name} 已失效",
                body=f"IC 均值: {info.get('rolling_ic', 'N/A'):.4f}" if info.get("rolling_ic") is not None else "",
                source="FactorMonitor",
                date=date,
            )
        elif status == "degraded":
            send_alert(
                level=AlertLevel.WARNING,
                title=f"因子 {factor_name} 正在衰减",
                body=f"IC 均值: {info.get('rolling_ic', 'N/A'):.4f}" if info.get("rolling_ic") is not None else "",
                source="FactorMonitor",
                date=date,
            )


def get_recent_alerts(n: int = 20) -> list:
    """
    读取最近 N 条告警记录。

    返回:
        list[dict]: 告警记录列表（最新在前）
    """
    if not ALERT_LOG_FILE.exists():
        return []

    alerts = []
    with open(ALERT_LOG_FILE, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    alerts.append(json.loads(line))
                except json.JSONDecodeError:
                    pass

    return alerts[-n:][::-1]  # 最新在前
