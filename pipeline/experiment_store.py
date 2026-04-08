"""
pipeline/experiment_store.py — Phase 7 实验记录存储

AI 研究助理把 ResearchQuestion 丢给 experiment_runner 后，产出一条
ExperimentRecord 落到 live/experiments/。整个生命周期：

    proposed → running → success / failed / skipped

目录结构：
  live/experiments/
    {experiment_id}.json    — 元数据 + question + 结果 + 关联 run_id

和 run_store 的关系：
  - experiment.run_id 指向 run_store 里那条具体的回测
  - run_store.RunRecord.experiment_id 反向指回 experiment（见后续 Task #134）
  - 两边可以互相查询：给 experiment 能找到回测产物，
    给 run 能找到它是由哪个 question 触发的

设计原则：
  - 和 run_store 一致的纯 JSON 持久化，不引入额外数据库
  - experiment_id 走同一套 _VALID_ID 白名单校验防路径穿越
  - 所有变更通过 save_experiment / update_experiment，不允许散写文件
"""
from __future__ import annotations

import datetime
import hashlib
import json
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Optional

# 锚定到仓库根目录
EXPERIMENTS_DIR = Path(__file__).parent.parent / "live" / "experiments"

# id 白名单：只允许字母、数字、下划线、短横线
_VALID_EXPERIMENT_ID = re.compile(r"^[a-zA-Z0-9_\-]{1,128}$")

# 合法状态集合
VALID_STATUSES = frozenset(["proposed", "running", "success", "failed", "skipped"])


def _validate_experiment_id(experiment_id: str) -> None:
    """校验 experiment_id，防止路径穿越。"""
    if not _VALID_EXPERIMENT_ID.match(experiment_id):
        raise ValueError(f"非法 experiment_id: {experiment_id!r}")


@dataclass
class ExperimentRecord:
    """
    一次实验的完整记录。

    字段：
        experiment_id       — 唯一标识符，建议 generate_experiment_id 生成
        question_id         — 对应 ResearchQuestion.id
        question_type       — ResearchQuestion.type（factor_decay / ... / no_action）
        question_text       — 人类可读问题
        rationale           — ResearchQuestion.rationale
        priority            — high / medium / low
        command             — 要执行的动作（目前只支持 "backtest.run"）
        params              — 执行参数
        status              — proposed / running / success / failed / skipped
        run_id              — 关联的回测 run_id（success 时必填，proposed 时为 None）
        result_summary      — 简短结论：关键指标 + 对照解读
        error               — 失败原因（failed/skipped 时填）
        created_at          — 创建时间 ISO 格式
        updated_at          — 最近一次 save/update 时间
        source              — 原 ResearchQuestion.source，保留溯源
    """
    experiment_id: str = ""
    question_id: str = ""
    question_type: str = ""
    question_text: str = ""
    rationale: str = ""
    priority: str = "medium"
    command: str = ""
    params: dict = field(default_factory=dict)
    status: str = "proposed"
    run_id: Optional[str] = None
    result_summary: Optional[dict] = None
    error: Optional[str] = None
    created_at: str = ""
    updated_at: str = ""
    source: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return asdict(self)


def generate_experiment_id(question_id: str, params: Optional[dict] = None) -> str:
    """
    生成实验唯一 ID：exp_{YYYYMMDD}_{hash[:8]}

    hash 由 question_id + params + 时间戳决定，保证同一轮重复 propose
    也不会相互覆盖。
    """
    now = datetime.datetime.now().isoformat()
    raw = f"{question_id}|{json.dumps(params or {}, sort_keys=True)}|{now}"
    h = hashlib.sha256(raw.encode()).hexdigest()[:8]
    date_tag = datetime.datetime.now().strftime("%Y%m%d")
    return f"exp_{date_tag}_{h}"


def save_experiment(record: ExperimentRecord) -> Path:
    """
    保存实验记录到磁盘（新建或覆盖）。

    - 会自动填充 created_at（首次写入）和 updated_at
    - status 必须在 VALID_STATUSES 中
    - failed 状态没写 error 时补一个"未知错误"
    """
    _validate_experiment_id(record.experiment_id)
    if record.status not in VALID_STATUSES:
        raise ValueError(
            f"非法 status: {record.status!r}，允许值 {sorted(VALID_STATUSES)}"
        )
    if record.status == "failed" and not record.error:
        record.error = "未知错误"

    EXPERIMENTS_DIR.mkdir(parents=True, exist_ok=True)

    now = datetime.datetime.now().isoformat()
    if not record.created_at:
        record.created_at = now
    record.updated_at = now

    path = EXPERIMENTS_DIR / f"{record.experiment_id}.json"
    data = _make_serializable(asdict(record))
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    return path


def get_experiment(experiment_id: str) -> ExperimentRecord:
    """
    按 id 读取单条实验记录。

    异常：
        FileNotFoundError: 记录不存在
        ValueError: id 格式非法
    """
    _validate_experiment_id(experiment_id)
    path = EXPERIMENTS_DIR / f"{experiment_id}.json"
    if not path.exists():
        raise FileNotFoundError(f"实验记录 '{experiment_id}' 不存在")
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    return _dict_to_record(data)


def list_experiments(
    status: Optional[str] = None,
    question_type: Optional[str] = None,
    limit: int = 50,
) -> list[ExperimentRecord]:
    """
    列出历史实验，按 created_at 倒序。

    参数：
        status          — 按状态过滤
        question_type   — 按问题类型过滤
        limit           — 最多返回条数
    """
    if not EXPERIMENTS_DIR.exists():
        return []

    records: list[ExperimentRecord] = []
    for path in EXPERIMENTS_DIR.glob("*.json"):
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            record = _dict_to_record(data)
            if status and record.status != status:
                continue
            if question_type and record.question_type != question_type:
                continue
            records.append(record)
        except (json.JSONDecodeError, KeyError):
            continue

    records.sort(key=lambda r: r.created_at, reverse=True)
    return records[:limit]


def update_experiment(experiment_id: str, **updates) -> ExperimentRecord:
    """
    就地更新一条实验记录的若干字段，返回更新后的 record。

    常用于：
        update_experiment(eid, status="running")
        update_experiment(eid, status="success", run_id="xxx", result_summary={...})
        update_experiment(eid, status="failed", error="...")
    """
    record = get_experiment(experiment_id)
    for k, v in updates.items():
        if not hasattr(record, k):
            raise ValueError(f"ExperimentRecord 没有字段 {k!r}")
        setattr(record, k, v)
    save_experiment(record)
    return record


def delete_experiment(experiment_id: str) -> bool:
    """
    删除一条实验记录。返回是否真的删了。

    只删 experiments 目录下那个 json，不会去动它关联的 run_store 产物。
    """
    _validate_experiment_id(experiment_id)
    path = EXPERIMENTS_DIR / f"{experiment_id}.json"
    if path.exists():
        path.unlink()
        return True
    return False


# ══════════════════════════════════════════════════════════════
# 内部工具
# ══════════════════════════════════════════════════════════════

def _dict_to_record(data: dict) -> ExperimentRecord:
    return ExperimentRecord(
        experiment_id=data.get("experiment_id", ""),
        question_id=data.get("question_id", ""),
        question_type=data.get("question_type", ""),
        question_text=data.get("question_text", ""),
        rationale=data.get("rationale", ""),
        priority=data.get("priority", "medium"),
        command=data.get("command", ""),
        params=data.get("params", {}) or {},
        status=data.get("status", "proposed"),
        run_id=data.get("run_id"),
        result_summary=data.get("result_summary"),
        error=data.get("error"),
        created_at=data.get("created_at", ""),
        updated_at=data.get("updated_at", ""),
        source=data.get("source", {}) or {},
    )


def _make_serializable(obj):
    """递归处理字典，确保所有值可 JSON 序列化。"""
    if isinstance(obj, dict):
        return {k: _make_serializable(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_make_serializable(v) for v in obj]
    if isinstance(obj, float):
        import math
        if math.isnan(obj) or math.isinf(obj):
            return None
        return obj
    if hasattr(obj, "item"):
        return obj.item()
    return obj


if __name__ == "__main__":
    eid = generate_experiment_id("factor_decay_mom_20", {"drop_factor": "mom_20"})
    print(f"生成 experiment_id: {eid}")

    rec = ExperimentRecord(
        experiment_id=eid,
        question_id="factor_decay_mom_20",
        question_type="factor_decay",
        question_text="mom_20 是否降级？",
        rationale="rolling_ic=0.01",
        priority="medium",
        command="backtest.run",
        params={"drop_factor": "mom_20"},
        status="proposed",
    )
    save_experiment(rec)
    loaded = get_experiment(eid)
    print(f"读取: {loaded.question_text}, status={loaded.status}")

    update_experiment(eid, status="success", run_id="fake_run_123",
                      result_summary={"sharpe_delta": 0.1})
    print(f"更新后: {get_experiment(eid).status}")

    delete_experiment(eid)
    print("✅ experiment_store import ok")
