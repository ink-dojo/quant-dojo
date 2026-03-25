"""
risk_service.py — 风险预警服务层

封装 live.risk_monitor 的风险预警查询，捕获所有异常并返回结构化 dict。
"""


def get_risk_alerts():
    """
    获取当前持仓的风险预警列表。

    构造 PaperTrader 实例，调用 check_risk_alerts(pt, price_data={})，
    返回预警条目列表；无预警时返回空列表。

    返回:
        list[dict]，每项格式为::

            {"level": "warning"|"critical", "msg": "...", "symbol": "..."}

        无预警时返回 []。捕获任何异常时返回::

            {"error": "<异常信息>", "alerts": []}
    """
    try:
        from live.risk_monitor import check_risk_alerts
        from live.paper_trader import PaperTrader

        pt = PaperTrader()
        alerts = check_risk_alerts(pt, price_data={})
        return alerts if alerts is not None else []
    except Exception:
        return {"error": "Internal server error", "alerts": []}


if __name__ == "__main__":
    print("=== risk alerts ===")
    result = get_risk_alerts()
    if isinstance(result, dict) and "error" in result:
        print(f"⚠️  error: {result['error']}")
    else:
        print(f"预警条数: {len(result)}")
        for alert in result:
            print(f"  [{alert['level']}] {alert['msg']}")

    print("\n✅ risk_service 检查完毕")
