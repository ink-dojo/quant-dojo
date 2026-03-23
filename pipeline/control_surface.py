"""
控制面契约 — AI agent 和外部系统安全调用 quant-dojo 的唯一入口

所有 AI agent 应通过本模块提供的函数调用系统功能，
而不是直接 import 内部模块。

命令分为两类：
  - 只读命令：查询数据、列出策略、查看运行记录
  - 变更命令：运行回测、生成信号、执行调仓（需人工确认）

使用方式：
  from pipeline.control_surface import list_commands, execute

  # 查看所有可用命令
  for cmd in list_commands():
      print(cmd["name"], cmd["description"], cmd["mutates"])

  # 执行命令
  result = execute("strategies.list")
  result = execute("backtest.run", strategy_id="multi_factor",
                   start="2023-01-01", end="2024-12-31")
"""
from __future__ import annotations

from typing import Optional


# ══════════════════════════════════════════════════════════════
# 命令定义
# ══════════════════════════════════════════════════════════════

_COMMANDS = {
    # ── 只读命令 ─────────────────────────────────────────────
    "strategies.list": {
        "description": "列出所有已注册策略",
        "mutates": False,
        "params": [],
    },
    "backtest.list": {
        "description": "列出历史回测记录",
        "mutates": False,
        "params": [
            {"name": "strategy_id", "required": False, "description": "按策略ID过滤"},
            {"name": "limit", "required": False, "description": "最大条数", "default": 20},
        ],
    },
    "backtest.get": {
        "description": "获取单条运行记录",
        "mutates": False,
        "params": [
            {"name": "run_id", "required": True, "description": "运行ID"},
        ],
    },
    "backtest.compare": {
        "description": "对比多个回测运行",
        "mutates": False,
        "params": [
            {"name": "run_ids", "required": True, "description": "运行ID列表"},
        ],
    },
    "positions.get": {
        "description": "查看当前模拟盘持仓",
        "mutates": False,
        "params": [],
    },
    "performance.get": {
        "description": "查看模拟盘绩效",
        "mutates": False,
        "params": [],
    },
    "factor_health.get": {
        "description": "查看因子健康度",
        "mutates": False,
        "params": [],
    },
    "risk.check": {
        "description": "运行风险检查",
        "mutates": False,
        "params": [],
    },
    "data.freshness": {
        "description": "检查数据新鲜度",
        "mutates": False,
        "params": [],
    },
    "doctor": {
        "description": "系统诊断",
        "mutates": False,
        "params": [],
    },

    # ── 变更命令（需人工确认）───────────────────────────────
    "backtest.run": {
        "description": "运行策略回测",
        "mutates": True,
        "params": [
            {"name": "strategy_id", "required": True, "description": "策略ID"},
            {"name": "start", "required": True, "description": "开始日期"},
            {"name": "end", "required": True, "description": "结束日期"},
            {"name": "params", "required": False, "description": "策略参数字典"},
        ],
    },
    "signal.run": {
        "description": "生成每日选股信号",
        "mutates": True,
        "params": [
            {"name": "date", "required": False, "description": "日期（默认今日）"},
        ],
    },
    "rebalance.run": {
        "description": "执行模拟盘调仓",
        "mutates": True,
        "params": [
            {"name": "date", "required": True, "description": "调仓日期"},
        ],
    },
    "report.weekly": {
        "description": "生成周报",
        "mutates": True,
        "params": [
            {"name": "week", "required": False, "description": "周 YYYY-Www"},
        ],
    },
}


def list_commands() -> list[dict]:
    """
    列出所有可用的控制面命令

    返回:
        命令信息列表，每项包含 name, description, mutates, params
    """
    return [
        {
            "name": name,
            "description": info["description"],
            "mutates": info["mutates"],
            "params": info["params"],
        }
        for name, info in _COMMANDS.items()
    ]


def execute(command: str, **kwargs) -> dict:
    """
    执行控制面命令

    参数:
        command: 命令名称（如 "strategies.list", "backtest.run"）
        **kwargs: 命令参数

    返回:
        dict: {"status": "success"|"error", "data": ..., "error": ...}
    """
    if command not in _COMMANDS:
        available = ", ".join(_COMMANDS.keys())
        return {
            "status": "error",
            "error": f"未知命令 '{command}'，可用命令：{available}",
        }

    try:
        handler = _HANDLERS.get(command)
        if handler is None:
            return {"status": "error", "error": f"命令 '{command}' 未实现"}
        result = handler(**kwargs)
        return {"status": "success", "data": result}
    except Exception as e:
        return {"status": "error", "error": str(e)}


# ══════════════════════════════════════════════════════════════
# 命令实现
# ══════════════════════════════════════════════════════════════

def _strategies_list(**kwargs):
    """列出策略"""
    from pipeline.strategy_registry import list_strategies
    entries = list_strategies()
    return [
        {"id": e.id, "name": e.name, "description": e.description}
        for e in entries
    ]


def _backtest_list(strategy_id: str = None, limit: int = 20, **kwargs):
    """列出回测记录"""
    from pipeline.run_store import list_runs
    runs = list_runs(strategy_id=strategy_id, limit=limit)
    return [
        {
            "run_id": r.run_id,
            "strategy_id": r.strategy_id,
            "status": r.status,
            "metrics": r.metrics,
            "created_at": r.created_at,
        }
        for r in runs
    ]


def _backtest_get(run_id: str, **kwargs):
    """获取单条记录"""
    from pipeline.run_store import get_run
    from dataclasses import asdict
    r = get_run(run_id)
    return asdict(r)


def _backtest_compare(run_ids: list, **kwargs):
    """对比回测"""
    from pipeline.run_store import compare_runs
    return compare_runs(run_ids)


def _backtest_run(
    strategy_id: str,
    start: str,
    end: str,
    params: Optional[dict] = None,
    **kwargs,
):
    """运行回测"""
    import datetime
    from pipeline.strategy_registry import run_strategy, get_strategy
    from pipeline.run_store import generate_run_id, RunRecord, save_run

    entry = get_strategy(strategy_id)
    result = run_strategy(strategy_id, start, end, params)

    if result["status"] == "failed":
        return {"status": "failed", "error": result["error"]}

    run_id = generate_run_id(strategy_id, start, end, result["params"])
    record = RunRecord(
        run_id=run_id,
        strategy_id=strategy_id,
        strategy_name=entry.name,
        params=result["params"],
        start_date=start,
        end_date=end,
        status="success",
        metrics=result["metrics"],
        created_at=datetime.datetime.now().isoformat(),
    )
    save_run(record, equity_df=result.get("results_df"))

    return {"run_id": run_id, "metrics": result["metrics"]}


def _signal_run(date: str = None, **kwargs):
    """生成信号"""
    import datetime
    from pipeline.daily_signal import run_daily_pipeline
    if date is None:
        date = datetime.date.today().strftime("%Y-%m-%d")
    return run_daily_pipeline(date)


def _rebalance_run(date: str, **kwargs):
    """执行调仓"""
    import pandas as pd
    from pipeline.daily_signal import run_daily_pipeline
    from utils.local_data_loader import load_price_wide
    from live.paper_trader import PaperTrader

    result = run_daily_pipeline(date)
    picks = result.get("picks", [])
    if result.get("error"):
        return {"status": "failed", "error": result["error"]}

    price_wide = load_price_wide(picks, date, date, field="close")
    if price_wide.empty:
        return {"status": "failed", "error": f"无法加载 {date} 的收盘价"}

    prices = {
        sym: float(price_wide.iloc[-1][sym])
        for sym in price_wide.columns
        if pd.notna(price_wide.iloc[-1][sym])
    }

    trader = PaperTrader()
    summary = trader.rebalance(picks, prices, date)
    return summary


def _positions_get(**kwargs):
    """查看持仓"""
    from live.paper_trader import PaperTrader
    trader = PaperTrader()
    pos = trader.get_current_positions()
    if pos is None:
        return {"positions": {}}
    if hasattr(pos, "to_dict"):
        return {"positions": pos.to_dict("records")}
    return {"positions": pos}


def _performance_get(**kwargs):
    """查看绩效"""
    from live.paper_trader import PaperTrader
    trader = PaperTrader()
    return trader.get_performance()


def _factor_health_get(**kwargs):
    """因子健康度"""
    from pipeline.factor_monitor import factor_health_report
    return factor_health_report()


def _risk_check(**kwargs):
    """风险检查"""
    from live.paper_trader import PaperTrader
    from live.risk_monitor import check_risk_alerts
    trader = PaperTrader()
    return check_risk_alerts(trader)


def _data_freshness(**kwargs):
    """数据新鲜度"""
    from pipeline.data_checker import check_data_freshness
    return check_data_freshness()


def _report_weekly(week: str = None, **kwargs):
    """生成周报"""
    from pipeline.weekly_report import generate_weekly_report
    return generate_weekly_report(week)


def _doctor(**kwargs):
    """系统诊断"""
    results = {}
    modules = [
        "utils", "strategies", "backtest.engine",
        "pipeline.daily_signal", "pipeline.strategy_registry",
        "pipeline.run_store", "live.paper_trader",
        "live.risk_monitor", "agents",
    ]
    for mod in modules:
        try:
            __import__(mod)
            results[mod] = "ok"
        except Exception as e:
            results[mod] = f"error: {e}"
    return results


# ── 命令→处理函数映射 ────────────────────────────────────────
_HANDLERS = {
    "strategies.list": _strategies_list,
    "backtest.list": _backtest_list,
    "backtest.get": _backtest_get,
    "backtest.compare": _backtest_compare,
    "backtest.run": _backtest_run,
    "signal.run": _signal_run,
    "rebalance.run": _rebalance_run,
    "positions.get": _positions_get,
    "performance.get": _performance_get,
    "factor_health.get": _factor_health_get,
    "risk.check": _risk_check,
    "data.freshness": _data_freshness,
    "report.weekly": _report_weekly,
    "doctor": _doctor,
}


if __name__ == "__main__":
    # 快速验证
    commands = list_commands()
    print(f"控制面命令 ({len(commands)} 个)：\n")
    for cmd in commands:
        rw = "📝" if cmd["mutates"] else "👁"
        print(f"  {rw} {cmd['name']:<25} {cmd['description']}")
    print()

    # 测试只读命令
    result = execute("strategies.list")
    print(f"strategies.list: {result['status']}, {len(result.get('data', []))} 策略")

    result = execute("doctor")
    print(f"doctor: {result['status']}")

    print("\n✅ control_surface import ok")
