"""
Pipeline 模块入口

导出所有 pipeline 相关的主要函数：
- 日报 (daily_signal)
- 周报 (weekly_report)
- 因子监控 (factor_monitor)
- 数据检查 (data_checker)
"""

from pipeline.data_checker import check_data_freshness
from pipeline.weekly_report import generate_weekly_report

# 条件导入：daily_signal 和 factor_monitor 可能还未实现
try:
    from pipeline.daily_signal import run_daily_pipeline
except ImportError:
    run_daily_pipeline = None

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
