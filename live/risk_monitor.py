"""
risk_monitor.py — 实时风险监控

检查持仓的回撤、集中度等风险指标，生成预警列表。
"""

import os
from pathlib import Path

import numpy as np
import pandas as pd

# nav.csv 路径（与 paper_trader.py 保持一致）
NAV_FILE = Path(__file__).parent / "portfolio" / "nav.csv"

def _load_risk_thresholds() -> tuple[float, float, float]:
    """
    从运行时配置加载风险阈值。

    优先读取 config/config.yaml 的 phase5 节；
    若配置不可用，降级为硬编码默认值。

    返回:
        (drawdown_warning, drawdown_critical, concentration_limit) 三元组
    """
    try:
        from utils.runtime_config import (
            get_concentration_limit,
            get_drawdown_critical,
            get_drawdown_warning,
        )
        return get_drawdown_warning(), get_drawdown_critical(), get_concentration_limit()
    except Exception:
        return -0.05, -0.10, 0.15


# 风险阈值（从运行时配置读取，不存在时使用默认值）
DRAWDOWN_WARNING, DRAWDOWN_CRITICAL, CONCENTRATION_LIMIT = _load_risk_thresholds()

# 决策日志路径
DECISIONS_LOG = Path(__file__).parent.parent / ".claude" / "decisions.md"


def _log_decision(msg: str):
    """
    记录运行时决策到 .claude/decisions.md。

    参数:
        msg: 决策说明文字
    """
    DECISIONS_LOG.parent.mkdir(parents=True, exist_ok=True)
    with open(DECISIONS_LOG, "a", encoding="utf-8") as f:
        from datetime import datetime
        f.write(f"\n- [{datetime.now().strftime('%Y-%m-%d %H:%M')}] {msg}\n")


def _compute_current_drawdown() -> float | None:
    """
    从 nav.csv 计算当前回撤（相对历史最高净值）。

    返回:
        当前回撤（负值），若无数据则返回 None
    """
    if not NAV_FILE.exists():
        return None

    nav_df = pd.read_csv(NAV_FILE)
    if nav_df.empty or "nav" not in nav_df.columns:
        return None

    navs = nav_df["nav"].values
    if len(navs) == 0:
        return None

    peak = np.maximum.accumulate(navs)
    current_drawdown = (navs[-1] - peak[-1]) / peak[-1]
    return float(current_drawdown)


def check_risk_alerts(portfolio, price_data: dict | None = None) -> list:
    """
    检查当前持仓的各类风险指标，返回预警列表。

    检查项目:
      1. 净值回撤：相对历史最高净值的跌幅
      2. 单股集中度：单只股票占组合市值比例
      3. 行业集中度：若无行业数据则跳过（记录决策）
      4. 因子 IC 衰减：调用 pipeline.factor_monitor（若可用）

    参数:
        portfolio: PaperTrader 实例（需有 positions 属性和 _portfolio_value 方法）
        price_data: {symbol: price} 当日价格字典

    返回:
        预警列表，每项为 {"level": "warning"|"critical", "msg": "...", "symbol": "..."}
    """
    alerts = []
    price_data = price_data or {}

    # --- 1. 回撤检查 ---
    drawdown = _compute_current_drawdown()
    if drawdown is not None:
        if drawdown <= DRAWDOWN_CRITICAL:
            alerts.append({
                "level": "critical",
                "msg": f"净值回撤已达 {drawdown:.1%}，超过 {DRAWDOWN_CRITICAL:.0%} 临界线，请立即检查持仓",
                "symbol": "",
            })
        elif drawdown <= DRAWDOWN_WARNING:
            alerts.append({
                "level": "warning",
                "msg": f"净值回撤 {drawdown:.1%}，已超过 {DRAWDOWN_WARNING:.0%} 预警线",
                "symbol": "",
            })

    # --- 2. 单股集中度检查 ---
    try:
        total_value = portfolio._portfolio_value(price_data)
        if total_value > 0:
            for sym, info in portfolio.positions.items():
                if sym == "__cash__":
                    continue
                price = price_data.get(sym, info.get("current_price", 0))
                position_value = info["shares"] * price
                weight = position_value / total_value
                if weight > CONCENTRATION_LIMIT:
                    alerts.append({
                        "level": "warning",
                        "msg": f"{sym} 占组合 {weight:.1%}，超过单股集中度上限 {CONCENTRATION_LIMIT:.0%}",
                        "symbol": sym,
                    })
    except Exception as e:
        _log_decision(f"集中度检查失败，跳过: {e}")

    # --- 3. 行业集中度检查（无行业数据时跳过）---
    _log_decision(
        "行业集中度检查：当前无 sector 映射数据，跳过该检查项。"
        "待接入行业分类数据后启用（参考 utils/fundamental_loader.py）"
    )

    # --- 4. 因子 IC 衰减检查 ---
    try:
        from pipeline.factor_monitor import factor_health_report  # type: ignore
        health = factor_health_report()
        for factor_name, info in health.items():
            status = info.get("status")
            if status in ("degraded", "dead"):
                alerts.append({
                    "level": "warning" if status == "degraded" else "critical",
                    "msg": f"因子 {factor_name} 状态: {status}，IC 已衰减，请检查因子有效性",
                    "symbol": "",
                })
    except ImportError:
        # pipeline 模块尚未安装，属于预期情况，记录决策后跳过
        _log_decision(
            "因子 IC 衰减检查：pipeline.factor_monitor 未安装，跳过该检查项。"
            "待 pipeline 模块部署后自动启用。"
        )
    except Exception as e:
        _log_decision(f"因子 IC 检查异常，跳过: {e}")

    return alerts


def format_risk_report(alerts: list) -> str:
    """
    将预警列表格式化为 Markdown 风险报告。

    参数:
        alerts: check_risk_alerts 返回的预警列表
    返回:
        Markdown 格式的风险报告字符串
    """
    lines = ["## Risk Report", ""]

    if not alerts:
        lines.append("✅ 无风险预警，组合状态正常。")
        return "\n".join(lines)

    # 按级别分组
    critical_alerts = [a for a in alerts if a["level"] == "critical"]
    warning_alerts = [a for a in alerts if a["level"] == "warning"]

    if critical_alerts:
        lines.append("### 🔴 Critical")
        for a in critical_alerts:
            sym_tag = f" `[{a['symbol']}]`" if a["symbol"] else ""
            lines.append(f"- {a['msg']}{sym_tag}")
        lines.append("")

    if warning_alerts:
        lines.append("### 🟡 Warning")
        for a in warning_alerts:
            sym_tag = f" `[{a['symbol']}]`" if a["symbol"] else ""
            lines.append(f"- {a['msg']}{sym_tag}")
        lines.append("")

    lines.append(f"_共 {len(alerts)} 条预警（{len(critical_alerts)} critical / {len(warning_alerts)} warning）_")
    return "\n".join(lines)


if __name__ == "__main__":
    # 最小验证：独立运行时打印空报告
    report = format_risk_report([])
    print(report)
    print("✅ risk_monitor 导入 ok")
