"""
Pipeline 模块入口 — Phase 5 自动化流水线

导出所有 pipeline 相关的主要函数：
- run_daily_pipeline   : 生成每日信号文件 (daily_signal)
- generate_weekly_report: 生成周度绩效报告 (weekly_report)
- factor_health_report : 因子健康度诊断 (factor_monitor)
- check_data_freshness : 检查数据目录新鲜度 (data_checker)
"""

from pipeline.data_checker import check_data_freshness
from pipeline.weekly_report import generate_weekly_report

from pipeline.daily_signal import run_daily_pipeline

try:
    from pipeline.factor_monitor import factor_health_report
except ImportError:
    factor_health_report = None


__all__ = [
    'check_data_freshness',
    'generate_weekly_report',
    'run_daily_pipeline',
    'factor_health_report',
]
