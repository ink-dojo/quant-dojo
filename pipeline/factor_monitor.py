"""
factor_monitor.py — 因子健康度监控

定期检查因子的 IC 衰减情况，生成健康度报告。
用于 Phase 5 实时因子监控和预警。
"""

import warnings
from pathlib import Path
from datetime import datetime, timedelta

import numpy as np
import pandas as pd
from scipy import stats

# 因子快照存储路径
FACTOR_SNAPSHOT_DIR = Path(__file__).parent.parent / "live" / "factor_snapshot"


def compute_rolling_ic(
    factor_name: str,
    lookback_days: int = 60,
) -> pd.Series:
    """
    计算因子的滚动 IC（信息系数）

    从 live/factor_snapshot/ 加载因子快照，计算每日的秩相关系数与次日收益的关系。

    参数:
        factor_name    : 因子名称（e.g. "momentum_20", "ep", "low_vol", "turnover"）
        lookback_days  : 回溯天数（默认 60 天），仅返回最近 N 天的 IC 序列

    返回:
        ic_series : pd.Series，index 为 trade_date，values 为日均 IC
                   如果无快照数据，返回空 Series 并产生 warning
    """

    # 检查快照目录是否存在
    if not FACTOR_SNAPSHOT_DIR.exists():
        warnings.warn(
            f"因子快照目录不存在：{FACTOR_SNAPSHOT_DIR}，返回空 Series",
            RuntimeWarning,
            stacklevel=2,
        )
        return pd.Series(dtype=float, name=f"IC_{factor_name}")

    # 扫描所有 parquet 文件
    snapshot_files = sorted(FACTOR_SNAPSHOT_DIR.glob("*.parquet"))
    if not snapshot_files:
        warnings.warn(
            f"快照目录内无 parquet 文件，返回空 Series",
            RuntimeWarning,
            stacklevel=2,
        )
        return pd.Series(dtype=float, name=f"IC_{factor_name}")

    # 按文件名（日期）倒序排列，取最近 lookback_days 个文件
    snapshot_files_recent = snapshot_files[-lookback_days:]

    ic_list = []
    dates_list = []

    for snap_file in snapshot_files_recent:
        try:
            df_snap = pd.read_parquet(snap_file)
        except Exception as e:
            warnings.warn(
                f"读取快照 {snap_file.name} 失败: {e}",
                RuntimeWarning,
                stacklevel=2,
            )
            continue

        # 快照应包含 factor 列（因子值）和 next_return 列（次日收益）
        if factor_name not in df_snap.columns:
            warnings.warn(
                f"快照 {snap_file.name} 中不包含因子 {factor_name}，跳过",
                RuntimeWarning,
                stacklevel=2,
            )
            continue

        if "next_return" not in df_snap.columns:
            warnings.warn(
                f"快照 {snap_file.name} 中不包含 next_return，跳过",
                RuntimeWarning,
                stacklevel=2,
            )
            continue

        # 提取因子值和收益，去掉 NaN
        factor_vals = df_snap[factor_name].dropna()
        returns_vals = df_snap["next_return"].dropna()

        # 取交集
        common_idx = factor_vals.index.intersection(returns_vals.index)
        if len(common_idx) < 30:  # 最少 30 只股票才计算 IC
            continue

        factor_cross = factor_vals[common_idx].values
        returns_cross = returns_vals[common_idx].values

        # 计算秩相关系数（Spearman）
        try:
            corr, _ = stats.spearmanr(factor_cross, returns_cross)
            if not np.isnan(corr):
                ic_list.append(float(corr))
                # 使用文件名（YYYYMMDD.parquet）作为日期
                date_str = snap_file.stem  # 去掉 .parquet 后缀
                dates_list.append(pd.Timestamp(date_str))
        except Exception as e:
            warnings.warn(
                f"计算 {snap_file.name} 的 IC 失败: {e}",
                RuntimeWarning,
                stacklevel=2,
            )
            continue

    if not ic_list:
        warnings.warn(
            f"因子 {factor_name} 未能计算出任何有效的 IC，返回空 Series",
            RuntimeWarning,
            stacklevel=2,
        )
        return pd.Series(dtype=float, name=f"IC_{factor_name}")

    ic_series = pd.Series(ic_list, index=dates_list, name=f"IC_{factor_name}")
    return ic_series.sort_index()


def factor_health_report() -> dict:
    """
    生成因子健康度报告

    对 momentum_20, ep, low_vol, turnover 这四个因子，分别计算：
      1. 滚动 IC（60 日窗口）
      2. IC 均值（作为因子有效性指标）
      3. 状态：
         - "healthy"  : |IC 均值| > 0.02，因子有效
         - "degraded" : |IC 均值| < 0.02，因子衰减
         - "dead"     : |IC 均值| ≈ 0 且 t-stat < 1，因子失效
         - "no_data"  : 无快照数据，无法评估

    返回:
        dict : {
            factor_name: {
                "rolling_ic": float,   # 滚动 IC 均值
                "status": str          # "healthy" / "degraded" / "dead" / "no_data"
            },
            ...
        }
    """
    factors_to_check = ["momentum_20", "ep", "low_vol", "turnover"]
    report = {}

    for factor_name in factors_to_check:
        ic_series = compute_rolling_ic(factor_name, lookback_days=60)

        if ic_series.empty:
            # 无数据，标记为 no_data
            report[factor_name] = {
                "rolling_ic": np.nan,
                "status": "no_data",
            }
            continue

        ic_clean = ic_series.dropna()
        if ic_clean.empty:
            report[factor_name] = {
                "rolling_ic": np.nan,
                "status": "no_data",
            }
            continue

        mean_ic = float(ic_clean.mean())
        std_ic = float(ic_clean.std())
        n_obs = len(ic_clean)

        # 计算 t 统计量
        t_stat = (
            mean_ic / (std_ic / np.sqrt(n_obs))
            if std_ic > 0 and n_obs > 0
            else 0.0
        )

        # 判断因子状态
        abs_mean_ic = abs(mean_ic)
        if abs_mean_ic > 0.02:
            status = "healthy"
        elif abs_mean_ic < 0.02 and abs(t_stat) >= 1:
            status = "degraded"
        else:
            status = "dead"

        report[factor_name] = {
            "rolling_ic": mean_ic,
            "status": status,
        }

    return report


if __name__ == "__main__":
    # 最小验证：运行因子健康度报告
    health = factor_health_report()
    print("因子健康度报告:")
    for factor_name, info in health.items():
        rolling_ic = info["rolling_ic"]
        status = info["status"]
        print(f"  {factor_name:15s} | IC: {rolling_ic:7.4f} | 状态: {status}")
    print("✅ factor_monitor 导入 ok")
