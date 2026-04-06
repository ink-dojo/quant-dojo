"""
pipeline/dashboard_export.py — 性能仪表盘数据导出

将 NAV 曲线、因子 IC 历史、换手率统计、告警历史等数据
导出为结构化 JSON，供前端可视化或外部分析工具消费。

输出文件: live/dashboard/dashboard_data.json

用法:
    python -m pipeline.dashboard_export
    # 或在流水线中:
    from pipeline.dashboard_export import export_dashboard
    export_dashboard()
"""

import json
import logging
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

DASHBOARD_DIR = Path(__file__).parent.parent / "live" / "dashboard"
OUTPUT_FILE = DASHBOARD_DIR / "dashboard_data.json"


def _export_nav_curve() -> dict:
    """导出 NAV 曲线数据"""
    from live.paper_trader import NAV_FILE

    if not NAV_FILE.exists():
        return {"dates": [], "values": [], "returns": []}

    try:
        df = pd.read_csv(NAV_FILE)
        if df.empty:
            return {"dates": [], "values": [], "returns": []}

        df["date"] = pd.to_datetime(df["date"])
        df = df.sort_values("date").drop_duplicates(subset=["date"], keep="last")

        navs = df["nav"].values
        returns = pd.Series(navs).pct_change().fillna(0).tolist()

        # 计算回撤序列
        peak = np.maximum.accumulate(navs)
        drawdown = ((navs - peak) / peak).tolist()

        return {
            "dates": [d.strftime("%Y-%m-%d") for d in df["date"]],
            "values": [round(float(v), 2) for v in navs],
            "returns": [round(float(r), 6) for r in returns],
            "drawdown": [round(float(d), 6) for d in drawdown],
        }
    except Exception as e:
        logger.warning("NAV 导出失败: %s", e)
        return {"dates": [], "values": [], "returns": [], "error": str(e)}


def _export_performance_metrics() -> dict:
    """导出绩效指标"""
    try:
        from live.paper_trader import PaperTrader
        trader = PaperTrader()
        return trader.get_performance()
    except Exception as e:
        logger.warning("绩效指标导出失败: %s", e)
        return {"error": str(e)}


def _export_positions() -> list:
    """导出当前持仓"""
    try:
        from live.paper_trader import PaperTrader
        trader = PaperTrader()
        pos_df = trader.get_current_positions()
        if pos_df.empty:
            return []
        return pos_df.to_dict(orient="records")
    except Exception as e:
        logger.warning("持仓导出失败: %s", e)
        return []


def _export_factor_ic_history() -> dict:
    """导出因子 IC 历史数据"""
    from pipeline.active_strategy import get_active_strategy
    from pipeline.factor_monitor import FACTOR_PRESETS, compute_rolling_ic

    active = get_active_strategy()
    preset_key = active if active in FACTOR_PRESETS else "v7"
    factors = FACTOR_PRESETS[preset_key]

    ic_data = {}
    for factor_name in factors:
        try:
            ic_series = compute_rolling_ic(factor_name, lookback_days=60)
            if not ic_series.empty:
                ic_data[factor_name] = {
                    "dates": [d.strftime("%Y-%m-%d") for d in ic_series.index],
                    "values": [round(float(v), 6) for v in ic_series.values],
                    "mean": round(float(ic_series.mean()), 6),
                    "std": round(float(ic_series.std()), 6),
                }
            else:
                ic_data[factor_name] = {"dates": [], "values": [], "mean": None, "std": None}
        except Exception as e:
            ic_data[factor_name] = {"error": str(e)}

    return {"strategy": preset_key, "factors": ic_data}


def _export_factor_health() -> dict:
    """导出因子健康度报告"""
    from pipeline.active_strategy import get_active_strategy
    from pipeline.factor_monitor import FACTOR_PRESETS, factor_health_report

    active = get_active_strategy()
    preset_key = active if active in FACTOR_PRESETS else "v7"

    try:
        report = factor_health_report(factors=FACTOR_PRESETS[preset_key])
        # Convert NaN to None for JSON
        for k, v in report.items():
            if isinstance(v.get("rolling_ic"), float) and np.isnan(v["rolling_ic"]):
                v["rolling_ic"] = None
        return {"strategy": preset_key, "factors": report}
    except Exception as e:
        return {"error": str(e)}


def _export_turnover_history() -> list:
    """导出换手率历史（从流水线审计日志提取）"""
    journal_dir = Path(__file__).parent.parent / "journal"
    if not journal_dir.exists():
        return []

    records = []
    for jfile in sorted(journal_dir.glob("pipeline_*.json")):
        try:
            with open(jfile, encoding="utf-8") as f:
                data = json.load(f)

            # 从 decisions 中提取换手率
            for d in data.get("decisions", []):
                if d.get("agent") == "ExecutorAgent" and "换手率" in d.get("reasoning", ""):
                    reasoning = d["reasoning"]
                    # 解析 "换手率 69.8%, NAV 959,573"
                    parts = reasoning.split(",")
                    for part in parts:
                        if "换手率" in part:
                            try:
                                pct_str = part.strip().replace("换手率", "").strip().rstrip("%").strip()
                                turnover = float(pct_str) / 100
                                records.append({
                                    "date": data["date"],
                                    "turnover": round(turnover, 4),
                                })
                            except ValueError:
                                pass
        except Exception:
            continue

    return records


def _export_signal_history() -> list:
    """导出信号历史（选股数、Top-3 股票）"""
    signal_dir = Path(__file__).parent.parent / "live" / "signals"
    if not signal_dir.exists():
        return []

    records = []
    for sig_file in sorted(signal_dir.glob("*.json"))[-30:]:  # 最近 30 天
        try:
            with open(sig_file, encoding="utf-8") as f:
                data = json.load(f)
            picks = data.get("picks", [])
            records.append({
                "date": sig_file.stem,
                "n_picks": len(picks),
                "top_3": picks[:3],
                "strategy": data.get("metadata", {}).get("strategy", "unknown"),
            })
        except Exception:
            continue

    return records


def _export_strategy_info() -> dict:
    """导出策略状态信息"""
    from pipeline.active_strategy import get_active_strategy, get_strategy_history

    return {
        "active": get_active_strategy(),
        "history": get_strategy_history(),
    }


def _export_recent_alerts() -> list:
    """导出最近告警"""
    try:
        from pipeline.alert_notifier import get_recent_alerts
        return get_recent_alerts(n=20)
    except Exception:
        return []


def export_dashboard(include_ic: bool = False) -> dict:
    """
    导出完整仪表盘数据。

    参数:
        include_ic: 是否包含因子 IC 历史（较慢，需要计算）

    返回:
        dict: 仪表盘数据
    """
    print("  导出仪表盘数据...")

    dashboard = {
        "generated_at": datetime.now().isoformat(),
        "nav": _export_nav_curve(),
        "performance": _export_performance_metrics(),
        "positions": _export_positions(),
        "strategy": _export_strategy_info(),
        "signal_history": _export_signal_history(),
        "turnover_history": _export_turnover_history(),
        "factor_health": _export_factor_health(),
        "recent_alerts": _export_recent_alerts(),
    }

    if include_ic:
        dashboard["factor_ic"] = _export_factor_ic_history()

    # 保存
    DASHBOARD_DIR.mkdir(parents=True, exist_ok=True)
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(dashboard, f, ensure_ascii=False, indent=2, default=str)

    size_kb = OUTPUT_FILE.stat().st_size / 1024
    print(f"  仪表盘数据已导出: {OUTPUT_FILE} ({size_kb:.1f} KB)")

    return dashboard


if __name__ == "__main__":
    import sys
    include_ic = "--ic" in sys.argv
    data = export_dashboard(include_ic=include_ic)
    print(f"\n导出完成，包含以下数据:")
    for key in data:
        if key == "generated_at":
            continue
        val = data[key]
        if isinstance(val, dict):
            print(f"  {key}: {len(val)} fields")
        elif isinstance(val, list):
            print(f"  {key}: {len(val)} records")
        else:
            print(f"  {key}: {val}")
