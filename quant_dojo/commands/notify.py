"""
quant_dojo notify — 发送运行结果通知

支持通用 webhook（飞书/钉钉/Slack 格式自动适配）。
从 config.yaml 的 alerts.webhook_url 读取 URL。
"""
import json
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).parent.parent.parent


def send_run_notification(date: str, results: dict, elapsed: float):
    """运行完成后发送通知"""
    try:
        from utils.runtime_config import get_config
        cfg = get_config()
        webhook_url = cfg.get("alerts", {}).get("webhook_url", "")
        if not webhook_url:
            return  # 未配置，静默跳过

        n_ok = sum(1 for r in results.values() if r.get("status") != "failed")
        n_fail = sum(1 for r in results.values() if r.get("status") == "failed")
        n_picks = results.get("signal", {}).get("n_picks", 0)
        risk_level = results.get("risk", {}).get("level", "unknown")

        status_emoji = "OK" if n_fail == 0 else "FAIL"
        title = f"[quant-dojo] {date} 每日流水线 {status_emoji}"

        lines = [
            f"日期: {date}",
            f"耗时: {elapsed:.1f}s",
            f"成功: {n_ok} / 失败: {n_fail}",
            f"选股: {n_picks} 只",
            f"风控: {risk_level}",
        ]

        # 失败详情
        for step, result in results.items():
            if result.get("status") == "failed":
                lines.append(f"[FAIL] {step}: {result.get('error', '未知错误')}")

        body = "\n".join(lines)
        _send_webhook(webhook_url, title, body)

    except Exception as e:
        logger.warning("通知发送失败: %s", e)


def _send_webhook(url: str, title: str, body: str):
    """发送 webhook 通知（自动适配格式）"""
    import urllib.request

    # 根据 URL 判断格式
    if "feishu" in url or "larksuite" in url:
        payload = {
            "msg_type": "text",
            "content": {"text": f"{title}\n\n{body}"},
        }
    elif "dingtalk" in url or "oapi.dingtalk" in url:
        payload = {
            "msgtype": "text",
            "text": {"content": f"{title}\n\n{body}"},
        }
    elif "slack" in url or "hooks.slack" in url:
        payload = {
            "text": f"*{title}*\n```\n{body}\n```",
        }
    else:
        # 通用格式
        payload = {
            "title": title,
            "body": body,
        }

    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            if resp.status == 200:
                logger.info("通知已发送")
            else:
                logger.warning("通知发送返回 %d", resp.status)
    except Exception as e:
        logger.warning("Webhook 请求失败: %s", e)
