"""
回测运行记录存储 — 标准化的运行产物管理

每次通过控制面执行的回测都会产生一条 RunRecord，持久化到 live/runs/ 目录。
Dashboard 和 AI agent 通过此模块读取历史运行、对比策略表现。

使用方式：
  from pipeline.run_store import save_run, list_runs, get_run, compare_runs

目录结构：
  live/runs/
    {run_id}.json          — 运行元数据 + 绩效指标
    {run_id}_equity.csv    — 净值曲线（可选）

存储架构：
  每条运行记录由两个文件组成：
    {run_id}.json       — 元数据 + 绩效指标
    {run_id}_equity.csv — 净值/收益序列（可选）

JSON 字段说明：
  run_id        — 唯一标识符，格式 {strategy_id}_{YYYYMMDD}_{hash[:8]}
  strategy_id   — 策略注册表 ID（如 "dual_ma", "multi_factor"）
  strategy_name — 策略人类可读名称
  params        — 运行时使用的参数字典
  start_date    — 回测开始日期 YYYY-MM-DD
  end_date      — 回测结束日期 YYYY-MM-DD
  status        — "success" | "failed"
  metrics       — 绩效指标字典，标准字段：
                    total_return, annualized_return, sharpe,
                    max_drawdown, volatility, win_rate, n_trading_days
  error         — 失败原因字符串（status=failed 时必填，否则 null）
  created_at    — 记录创建时间 ISO 格式
  artifacts     — 产物文件路径字典，可能的 key：
                    equity_csv — 净值序列 CSV 路径（Index=日期，列=策略输出的 DataFrame 列）

equity_csv 语义：
  存储的是策略 run() 返回的 results_df，通常包含 daily returns 或 equity curve。
  具体列名取决于策略实现。消费方不应假设固定列名，而应从 CSV header 读取。
"""

from __future__ import annotations

import json
import hashlib
import datetime
import re
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Optional

# 锚定到仓库根目录，避免依赖 cwd
RUNS_DIR = Path(__file__).parent.parent / "live" / "runs"

# run_id 白名单：只允许字母、数字、下划线、短横线
_VALID_RUN_ID = re.compile(r'^[a-zA-Z0-9_\-]{1,128}$')

# 标准绩效指标字段（文档/验证参考，不强制执行）
REQUIRED_METRIC_KEYS = frozenset([
    "total_return", "annualized_return", "sharpe",
    "max_drawdown", "volatility", "win_rate", "n_trading_days"
])


def _validate_run_id(run_id: str) -> None:
    """
    校验 run_id 格式，防止路径穿越

    参数:
        run_id: 运行 ID

    异常:
        ValueError: run_id 包含非法字符
    """
    if not _VALID_RUN_ID.match(run_id):
        raise ValueError(f"非法 run_id: {run_id!r}")


@dataclass
class RunRecord:
    """
    标准运行记录

    属性:
        run_id: 运行唯一标识符（自动生成）
        strategy_id: 策略注册表 ID
        strategy_name: 策略人类可读名称
        params: 运行参数
        start_date: 回测开始日期
        end_date: 回测结束日期
        status: 运行状态 success / failed
        metrics: 绩效指标字典
        error: 错误信息（失败时）
        created_at: 创建时间 ISO 格式
        artifacts: 产物文件路径字典
    """
    run_id: str = ""
    strategy_id: str = ""
    strategy_name: str = ""
    params: dict = field(default_factory=dict)
    start_date: str = ""
    end_date: str = ""
    status: str = "pending"
    metrics: dict = field(default_factory=dict)
    error: Optional[str] = None
    created_at: str = ""
    artifacts: dict = field(default_factory=dict)


def generate_run_id(strategy_id: str, start: str, end: str, params: dict) -> str:
    """
    生成运行唯一标识符

    格式：{strategy_id}_{YYYYMMDD}_{hash[:8]}
    hash 由参数 + 时间戳决定，确保唯一性

    参数:
        strategy_id: 策略 ID
        start: 开始日期
        end: 结束日期
        params: 参数字典

    返回:
        运行 ID 字符串
    """
    now = datetime.datetime.now().isoformat()
    raw = f"{strategy_id}|{start}|{end}|{json.dumps(params, sort_keys=True)}|{now}"
    h = hashlib.sha256(raw.encode()).hexdigest()[:8]
    date_tag = datetime.datetime.now().strftime("%Y%m%d")
    return f"{strategy_id}_{date_tag}_{h}"


def save_run(record: RunRecord, equity_df=None) -> Path:
    """
    保存运行记录到磁盘

    参数:
        record: RunRecord 实例
        equity_df: 可选的净值曲线 DataFrame（需有 date 索引）

    返回:
        记录文件路径
    """
    _validate_run_id(record.run_id)
    RUNS_DIR.mkdir(parents=True, exist_ok=True)

    # 失败运行必须有错误信息
    if record.status == "failed" and record.error is None:
        record.error = "未知错误"

    # 先保存净值曲线（如果有），再写 JSON（一次写入）
    if equity_df is not None:
        equity_path = RUNS_DIR / f"{record.run_id}_equity.csv"
        equity_df.to_csv(equity_path)
        record.artifacts["equity_csv"] = str(equity_path)

    record_path = RUNS_DIR / f"{record.run_id}.json"
    data = _make_serializable(asdict(record))

    with open(record_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    return record_path


def list_runs(
    strategy_id: Optional[str] = None,
    limit: int = 20,
    status: Optional[str] = None,
) -> list[RunRecord]:
    """
    列出历史运行记录

    参数:
        strategy_id: 按策略 ID 过滤（可选）
        limit: 返回最多条数
        status: 按状态过滤（可选）

    返回:
        RunRecord 列表，按创建时间倒序
    """
    if not RUNS_DIR.exists():
        return []

    records = []
    json_files = [p for p in RUNS_DIR.glob("*.json") if not p.name.endswith("_equity.csv")]
    for path in json_files:
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            record = _dict_to_record(data)
            if strategy_id and record.strategy_id != strategy_id:
                continue
            if status and record.status != status:
                continue
            records.append(record)
        except (json.JSONDecodeError, KeyError):
            continue

    # 按 created_at 倒序排列，mtime 不可靠
    records.sort(key=lambda r: r.created_at, reverse=True)
    return records[:limit]


def get_run(run_id: str) -> RunRecord:
    """
    获取单条运行记录

    参数:
        run_id: 运行 ID

    返回:
        RunRecord

    异常:
        FileNotFoundError: 记录不存在
        ValueError: run_id 格式非法
    """
    _validate_run_id(run_id)
    path = RUNS_DIR / f"{run_id}.json"
    if not path.exists():
        raise FileNotFoundError(f"运行记录 '{run_id}' 不存在")

    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    return _dict_to_record(data)


def compare_runs(run_ids: list[str]) -> dict:
    """
    对比多个运行记录的绩效指标

    参数:
        run_ids: 运行 ID 列表

    返回:
        dict: {
            "runs": [{run_id, strategy_id, strategy_name, params, metrics, ...}, ...],
            "metric_names": [指标名列表],
        }
    """
    runs = []
    all_metric_keys = set()

    for run_id in run_ids:
        try:
            record = get_run(run_id)
            run_data = {
                "run_id": record.run_id,
                "strategy_id": record.strategy_id,
                "strategy_name": record.strategy_name,
                "params": record.params,
                "start_date": record.start_date,
                "end_date": record.end_date,
                "status": record.status,
                "metrics": record.metrics or {},
                "error": record.error,
                "created_at": record.created_at,
            }
            all_metric_keys.update((record.metrics or {}).keys())
            runs.append(run_data)
        except FileNotFoundError:
            runs.append({"run_id": run_id, "error": "记录不存在"})

    return {
        "runs": runs,
        "metric_names": sorted(all_metric_keys),
    }


def delete_run(run_id: str) -> bool:
    """
    删除运行记录及其产物

    参数:
        run_id: 运行 ID

    返回:
        是否成功删除

    异常:
        ValueError: run_id 格式非法
    """
    _validate_run_id(run_id)
    deleted = False
    for suffix in [".json", "_equity.csv"]:
        path = RUNS_DIR / f"{run_id}{suffix}"
        if path.exists():
            path.unlink()
            deleted = True
    return deleted


# ══════════════════════════════════════════════════════════════
# 内部工具
# ══════════════════════════════════════════════════════════════

def _dict_to_record(data: dict) -> RunRecord:
    """从字典构造 RunRecord"""
    return RunRecord(
        run_id=data.get("run_id", ""),
        strategy_id=data.get("strategy_id", ""),
        strategy_name=data.get("strategy_name", ""),
        params=data.get("params", {}),
        start_date=data.get("start_date", ""),
        end_date=data.get("end_date", ""),
        status=data.get("status", "unknown"),
        metrics=data.get("metrics", {}),
        error=data.get("error"),
        created_at=data.get("created_at", ""),
        artifacts=data.get("artifacts", {}),
    )


def _make_serializable(obj):
    """递归处理字典，确保所有值可 JSON 序列化"""
    if isinstance(obj, dict):
        return {k: _make_serializable(v) for k, v in obj.items()}
    elif isinstance(obj, list):
        return [_make_serializable(v) for v in obj]
    elif isinstance(obj, float):
        import math
        if math.isnan(obj) or math.isinf(obj):
            return None
        return obj
    elif hasattr(obj, 'item'):
        # numpy scalar
        return obj.item()
    return obj


if __name__ == "__main__":
    # 快速验证
    rid = generate_run_id("test", "2023-01-01", "2024-12-31", {"n": 30})
    print(f"生成 run_id: {rid}")

    record = RunRecord(
        run_id=rid,
        strategy_id="test",
        strategy_name="测试策略",
        params={"n": 30},
        start_date="2023-01-01",
        end_date="2024-12-31",
        status="success",
        metrics={"sharpe": 1.23, "max_drawdown": -0.15},
        created_at=datetime.datetime.now().isoformat(),
    )
    path = save_run(record)
    print(f"保存到: {path}")

    loaded = get_run(rid)
    print(f"读取: {loaded.strategy_name}, sharpe={loaded.metrics['sharpe']}")

    runs = list_runs()
    print(f"历史记录: {len(runs)} 条")

    # 清理测试数据
    delete_run(rid)
    print("✅ run_store import ok")
