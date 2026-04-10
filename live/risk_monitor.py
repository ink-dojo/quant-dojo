"""
risk_monitor.py — 实时风险监控

检查持仓的回撤、集中度等风险指标，生成预警列表。
"""

import os
from datetime import date
from pathlib import Path
from typing import Optional, Tuple

import numpy as np
import pandas as pd

# nav.csv 路径（与 paper_trader.py 保持一致）
NAV_FILE = Path(__file__).parent / "portfolio" / "nav.csv"

def _load_risk_thresholds() -> Tuple[float, float, float]:
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


def _compute_current_drawdown() -> Optional[float]:
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


def compute_effective_n(positions: dict) -> float:
    """
    有效持仓数（Effective N）。

    Effective N = 1 / sum(w_i²)
    完全等权时 EN = N，高度集中时 EN → 1。

    参数:
        positions: {symbol: weight} 或 {symbol: shares} 均可，内部会做归一化
    返回:
        float，有效持仓数
    """
    weights = np.array(list(positions.values()), dtype=float)
    weights = weights / weights.sum()  # 归一化
    return float(1.0 / (weights ** 2).sum())


def check_factor_exposure(
    positions: dict,
    factor_wide: dict,
    threshold: float = 1.5,
) -> list:
    """
    检查当前持仓的因子暴露是否过度集中。

    对持仓股票在最新截面计算各因子的加权平均 z-score，
    若绝对值超过 threshold，产生 FACTOR_CONCENTRATION 告警。

    参数:
        positions:   {symbol: weight} 当前持仓权重
        factor_wide: {factor_name: pd.DataFrame(日期×股票)} 因子宽表
        threshold:   z-score 绝对值阈值，默认 1.5
    返回:
        list of dict: [{level, code, msg, factor, exposure}, ...]
    """
    alerts = []
    if not positions or not factor_wide:
        return alerts

    syms = list(positions.keys())
    raw_weights = np.array(list(positions.values()), dtype=float)
    if raw_weights.sum() == 0:
        return alerts
    weights = raw_weights / raw_weights.sum()  # 归一化，防止传入 shares

    today = date.today().isoformat()

    for factor_name, df in factor_wide.items():
        if not isinstance(df, pd.DataFrame) or df.empty:
            continue

        # 取最新日期截面
        latest_row = df.iloc[-1]

        # 仅保留持仓中有该因子值的股票
        available_syms = [s for s in syms if s in latest_row.index and pd.notna(latest_row[s])]
        if not available_syms:
            continue

        # 截面 z-score（用该截面全体股票的均值和标准差）
        cross_section = latest_row.dropna()
        mean = cross_section.mean()
        std = cross_section.std()
        if std == 0 or pd.isna(std):
            continue

        z_scores = (latest_row[available_syms] - mean) / std

        # 对持仓股票取加权平均 z-score（按权重在 available_syms 子集中重新归一化）
        sym_indices = [syms.index(s) for s in available_syms]
        sub_weights = weights[sym_indices]
        if sub_weights.sum() == 0:
            continue
        sub_weights = sub_weights / sub_weights.sum()

        weighted_z = float(np.dot(sub_weights, z_scores[available_syms].values))

        if abs(weighted_z) > threshold:
            # 根据因子名给出可读的风险描述
            if "illiq" in factor_name or "amihud" in factor_name:
                hint = "可能集中持有流动性差个股"
            elif "momentum" in factor_name or "mom" in factor_name:
                hint = "可能存在追涨行为"
            elif "size" in factor_name or "mktcap" in factor_name:
                hint = "可能集中持有某一市值段"
            elif "value" in factor_name or "pb" in factor_name or "pe" in factor_name:
                hint = "可能集中于估值极端个股"
            else:
                hint = "因子暴露偏高，请检查持仓分散性"

            alerts.append({
                "level": "warning",
                "code": "FACTOR_CONCENTRATION",
                "msg": (
                    f"持仓对 {factor_name} 因子暴露过高"
                    f"（z={weighted_z:.2f}），{hint}"
                ),
                "factor": factor_name,
                "exposure": round(weighted_z, 4),
                "symbol": "",
                "as_of_date": today,
            })

    return alerts


def check_risk_alerts(portfolio, price_data: Optional[dict] = None) -> list:
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
                "code": "DRAWDOWN_CRITICAL",
                "msg": f"净值回撤已达 {drawdown:.1%}，超过 {DRAWDOWN_CRITICAL:.0%} 临界线，请立即检查持仓",
                "symbol": "",
                "as_of_date": date.today().isoformat(),
            })
        elif drawdown <= DRAWDOWN_WARNING:
            alerts.append({
                "level": "warning",
                "code": "DRAWDOWN_WARNING",
                "msg": f"净值回撤 {drawdown:.1%}，已超过 {DRAWDOWN_WARNING:.0%} 预警线",
                "symbol": "",
                "as_of_date": date.today().isoformat(),
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
                        "code": "CONCENTRATION_EXCEEDED",
                        "msg": f"{sym} 占组合 {weight:.1%}，超过单股集中度上限 {CONCENTRATION_LIMIT:.0%}",
                        "symbol": sym,
                        "as_of_date": date.today().isoformat(),
                    })
    except Exception as e:
        _log_decision(f"集中度检查失败，跳过: {e}")

    # --- 3. 行业集中度检查（尝试加载行业数据，不可用时静默跳过）---
    try:
        from utils.fundamental_loader import get_industry_classification
        stock_symbols = [sym for sym in portfolio.positions if sym != "__cash__"]
        if stock_symbols and total_value > 0:
            industry_df = get_industry_classification(symbols=stock_symbols)
            if not industry_df.empty and "industry_name" in industry_df.columns:
                # 按行业汇总持仓市值
                sector_values = {}
                for sym in stock_symbols:
                    info = portfolio.positions[sym]
                    price = price_data.get(sym, info.get("current_price", 0))
                    pos_val = info["shares"] * price
                    match = industry_df[industry_df["symbol"] == sym]
                    sector = match["industry_name"].iloc[0] if not match.empty else "未知"
                    sector_values[sector] = sector_values.get(sector, 0) + pos_val

                sector_limit = 0.40  # 单行业不超过 40%
                for sector, val in sector_values.items():
                    weight = val / total_value
                    if weight > sector_limit:
                        alerts.append({
                            "level": "warning",
                            "code": "SECTOR_CONCENTRATION",
                            "msg": f"行业 {sector} 占组合 {weight:.1%}，超过 {sector_limit:.0%} 上限",
                            "symbol": "",
                            "as_of_date": date.today().isoformat(),
                        })
    except Exception:
        # 行业数据不可用时静默跳过，不产生噪音日志
        pass

    # --- 4. 因子 IC 衰减检查 ---
    try:
        from pipeline.factor_monitor import factor_health_report, FACTOR_PRESETS  # type: ignore
        from pipeline.active_strategy import get_active_strategy
        _active = get_active_strategy()
        _preset_key = _active if _active in FACTOR_PRESETS else "v7"
        # 构建用于 effective_n 附加的持仓字典
        _positions_for_health: dict = {}
        try:
            _positions_for_health = {
                sym: info["shares"]
                for sym, info in portfolio.positions.items()
                if sym != "__cash__" and info.get("shares", 0) > 0
            }
        except Exception:
            pass
        health = factor_health_report(
            factors=FACTOR_PRESETS[_preset_key],
            positions=_positions_for_health or None,
        )
        for factor_name, info in health.items():
            if factor_name == "__meta__":
                continue  # 跳过元信息键，不产生告警
            status = info.get("status")
            # insufficient_data / no_data 不是告警，只是 Phase 5 早期常态
            if status in ("degraded", "dead"):
                code = "FACTOR_DEGRADED" if status == "degraded" else "FACTOR_DEAD"
                n_obs = info.get("n_obs", 0)
                alerts.append({
                    "level": "warning" if status == "degraded" else "critical",
                    "code": code,
                    "msg": (
                        f"因子 {factor_name} 状态: {status}，"
                        f"IC 已衰减（n={n_obs}），请检查因子有效性"
                    ),
                    "symbol": "",
                    "as_of_date": date.today().isoformat(),
                })
    except ImportError:
        # pipeline 模块尚未安装，属于预期情况，记录决策后跳过
        _log_decision(
            "因子 IC 衰减检查：pipeline.factor_monitor 未安装，跳过该检查项。"
            "待 pipeline 模块部署后自动启用。"
        )
    except Exception as e:
        _log_decision(f"因子 IC 检查异常，跳过: {e}")

    # --- 5. Effective N 集中度检查 ---
    try:
        stock_positions = {
            sym: info["shares"]
            for sym, info in portfolio.positions.items()
            if sym != "__cash__" and info.get("shares", 0) > 0
        }
        if stock_positions:
            n_positions = len(stock_positions)
            effective_n = compute_effective_n(stock_positions)
            if effective_n < n_positions * 0.5:
                alerts.append({
                    "level": "warning",
                    "code": "CONCENTRATION_EXCEEDED",
                    "msg": (
                        f"有效持仓数 {effective_n:.1f} 不足名义持仓数 {n_positions} 的一半，"
                        f"组合集中度过高（Effective N = {effective_n:.2f}）"
                    ),
                    "symbol": "",
                    "as_of_date": date.today().isoformat(),
                })
    except Exception as e:
        _log_decision(f"Effective N 检查失败，跳过: {e}")

    return alerts


def check_price_anomalies(prices: dict) -> list:
    """
    检查价格字典中的异常价格，返回预警列表。

    参数:
        prices: {symbol: price} 价格字典，symbol 为股票代码，price 为最新价格
    返回:
        预警列表，每项含 level, code, msg, symbol, as_of_date 字段；
        prices 为空或 None 时返回空列表
    """
    if not prices:
        return []

    alerts = []
    today = date.today().isoformat()
    for sym, price in prices.items():
        if price <= 0:
            alerts.append({
                "level": "critical",
                "code": "ZERO_PRICE",
                "msg": f"{sym} 价格异常: {price}，价格不得为零或负值",
                "symbol": sym,
                "as_of_date": today,
            })
    return alerts


def run_risk_check(nav_history=None, positions: dict = None) -> list:
    """
    独立风险检查入口，不依赖 PaperTrader 实例。

    参数:
        nav_history: 净值历史（预留接口，当前未使用），传 None 跳过
        positions:   {symbol: price} 格式的持仓价格字典；
                     非空时触发价格异常检查
    返回:
        预警列表，结构同 check_risk_alerts 返回值
    """
    alerts = []
    positions = positions or {}

    if positions:
        alerts.extend(check_price_anomalies(positions))

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
            code_tag = f"[{a['code']}] " if a.get("code") else ""
            sym_tag = f" `[{a['symbol']}]`" if a["symbol"] else ""
            lines.append(f"- {code_tag}{a['msg']}{sym_tag}")
        lines.append("")

    if warning_alerts:
        lines.append("### 🟡 Warning")
        for a in warning_alerts:
            code_tag = f"[{a['code']}] " if a.get("code") else ""
            sym_tag = f" `[{a['symbol']}]`" if a["symbol"] else ""
            lines.append(f"- {code_tag}{a['msg']}{sym_tag}")
        lines.append("")

    lines.append(f"_共 {len(alerts)} 条预警（{len(critical_alerts)} critical / {len(warning_alerts)} warning）_")
    return "\n".join(lines)


if __name__ == "__main__":
    # 最小验证：独立运行时打印空报告
    report = format_risk_report([])
    print(report)
    print("✅ risk_monitor 导入 ok")
