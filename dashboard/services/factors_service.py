"""
factors_service.py — 因子健康度与截面快照服务层

封装因子监控相关查询，所有函数捕获异常并返回结构化 dict。
"""

from pathlib import Path
from typing import Any

# 因子快照目录（与 pipeline/factor_monitor.py 保持一致）
_SNAPSHOT_DIR = Path(__file__).parent.parent.parent / "live" / "factor_snapshot"

# factor_health_report 状态到三值归一化映射
_STATUS_MAP = {
    "healthy": "healthy",
    "degraded": "warning",
    "dead": "failed",
    "no_data": "warning",
}


def get_factor_health() -> dict:
    """
    获取各因子当前健康状态。

    调用 pipeline.factor_monitor.factor_health_report()，将返回的每个因子状态
    归一化为 "healthy" / "warning" / "failed" 三个值之一。

    返回:
        dict，格式为::

            {
                "momentum_20": {"rolling_ic": 0.035, "status": "healthy"},
                "ep":          {"rolling_ic": 0.012, "status": "warning"},
                ...
            }

        捕获任何异常时返回::

            {"error": "<异常信息>", "factors": {}}
    """
    try:
        from pipeline.factor_monitor import factor_health_report

        raw = factor_health_report()
        factors: dict[str, Any] = {}
        for factor_name, info in raw.items():
            raw_status = info.get("status", "no_data")
            normalized = _STATUS_MAP.get(raw_status, "warning")
            factors[factor_name] = {
                "rolling_ic": info.get("rolling_ic"),
                "status": normalized,
            }
        return factors
    except Exception as e:
        return {"error": str(e), "factors": {}}


def get_factor_snapshot() -> dict:
    """
    读取最新日期的因子截面快照，返回各因子的描述统计。

    扫描 live/factor_snapshot/ 目录，取文件名最大（即最新日期）的 .parquet 文件，
    用 pandas 读取后计算每列（因子）的均值、中位数、25% 和 75% 分位数。

    返回:
        dict，格式为::

            {
                "as_of_date": "20260321",
                "stats": {
                    "momentum_20": {"mean": 0.12, "median": 0.10, "q25": 0.05, "q75": 0.18},
                    ...
                }
            }

        文件不存在时返回::

            {"as_of_date": null, "stats": {}}
    """
    try:
        import pandas as pd

        if not _SNAPSHOT_DIR.exists():
            return {"as_of_date": None, "stats": {}}

        parquet_files = sorted(_SNAPSHOT_DIR.glob("*.parquet"))
        if not parquet_files:
            return {"as_of_date": None, "stats": {}}

        latest_file = parquet_files[-1]
        as_of_date = latest_file.stem  # 文件名即日期，如 "20260321"

        df = pd.read_parquet(latest_file)

        stats: dict[str, Any] = {}
        for col in df.columns:
            series = df[col].dropna()
            if series.empty:
                continue
            stats[col] = {
                "mean": round(float(series.mean()), 6),
                "median": round(float(series.median()), 6),
                "q25": round(float(series.quantile(0.25)), 6),
                "q75": round(float(series.quantile(0.75)), 6),
            }

        return {"as_of_date": as_of_date, "stats": stats}
    except Exception:
        return {"as_of_date": None, "stats": {}}


if __name__ == "__main__":
    print("=== factor health ===")
    health = get_factor_health()
    print(health)

    print("\n=== factor snapshot ===")
    snapshot = get_factor_snapshot()
    print(f"as_of_date: {snapshot['as_of_date']}")
    print(f"因子数: {len(snapshot['stats'])}")
    for fname, s in snapshot["stats"].items():
        print(f"  {fname}: {s}")

    print("\n✅ factors_service 检查完毕")
