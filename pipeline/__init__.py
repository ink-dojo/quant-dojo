"""
Pipeline 模块入口 — Phase 5 自动化流水线 + 控制面

导出所有 pipeline 相关的主要函数：
- run_daily_pipeline    : 生成每日信号文件 (daily_signal)
- generate_weekly_report: 生成周度绩效报告 (weekly_report)
- factor_health_report  : 因子健康度诊断 (factor_monitor)
- check_data_freshness  : 检查数据目录新鲜度 (data_checker)
- list_strategies       : 列出已注册策略 (strategy_registry)
- get_strategy          : 获取策略条目 (strategy_registry)
- run_strategy          : 通过注册表运行回测 (strategy_registry)
- list_runs / get_run   : 运行记录管理 (run_store)
"""

from pipeline.data_checker import check_data_freshness
from pipeline.weekly_report import generate_weekly_report

from pipeline.daily_signal import run_daily_pipeline

try:
    from pipeline.factor_monitor import factor_health_report
except ImportError:
    factor_health_report = None

from pipeline.strategy_registry import list_strategies, get_strategy, run_strategy
from pipeline.run_store import list_runs, get_run, save_run, compare_runs


__all__ = [
    'check_data_freshness',
    'generate_weekly_report',
    'run_daily_pipeline',
    'factor_health_report',
    'list_strategies',
    'get_strategy',
    'run_strategy',
    'list_runs',
    'get_run',
    'save_run',
    'compare_runs',
]
