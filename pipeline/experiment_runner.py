"""
pipeline/experiment_runner.py — Phase 7 ResearchQuestion → 回测执行器

把 research_planner 产出的 ResearchQuestion 列表转成实际的回测运行：
  1. 为每条 question 创建一条 ExperimentRecord（status=proposed）
  2. 调用 control_surface.execute("backtest.run", approved=True, ...) 跑回测
  3. 把 run_id 和结果摘要写回 experiment 记录

设计原则：
  - 只支持 proposed_experiment.command == "backtest.run"，其它全部 skipped
  - 必须 approved=True 才算真正拉起真实回测，保留控制面原本的审批语义
  - 回测跑挂了只写 failed record，不往外抛异常 —— runner 是 "尽量多跑完"
    而不是 "一个失败就停"
  - 默认回测日期来自 DEFAULT_BACKTEST_* 常量，可 monkeypatch
  - 默认 strategy_id 来自 DEFAULT_STRATEGY_ID，可通过 run_experiments 的参数覆盖
  - 不读 ResearchQuestion 以外的输入，方便和 research_planner 解耦单测
"""
from __future__ import annotations

import datetime
from typing import Any, Callable, Optional

from pipeline.experiment_store import (
    ExperimentRecord,
    generate_experiment_id,
    save_experiment,
    update_experiment,
)
from pipeline.research_planner import ResearchQuestion


# ══════════════════════════════════════════════════════════════
# 默认配置 —— 单测可 monkeypatch
# ══════════════════════════════════════════════════════════════

# 默认用 multi_factor 做对照实验，因为它支持最多可调参数
DEFAULT_STRATEGY_ID = "multi_factor"

# 回测默认跨度 3 年以上
def _default_backtest_window() -> tuple[str, str]:
    end = datetime.date.today()
    start = end - datetime.timedelta(days=365 * 3)
    return start.strftime("%Y-%m-%d"), end.strftime("%Y-%m-%d")


# 跳过这些 question_type：它们不产生 backtest 实验
_SKIP_TYPES = frozenset(["no_action", "factor_insufficient"])


# ══════════════════════════════════════════════════════════════
# 核心流程
# ══════════════════════════════════════════════════════════════

def propose_experiment(
    question: ResearchQuestion,
    strategy_id: str = DEFAULT_STRATEGY_ID,
    start: Optional[str] = None,
    end: Optional[str] = None,
) -> ExperimentRecord:
    """
    为一条 question 落一条 proposed 记录到 experiment_store。

    不会真的跑回测 —— 只是把 question 持久化为 experiment。
    跑回测由 run_experiment 负责。
    """
    default_start, default_end = _default_backtest_window()
    start = start or default_start
    end = end or default_end

    proposed = question.proposed_experiment or {}
    command = proposed.get("command", "")
    raw_params = dict(proposed.get("params") or {})

    # question 里的 params 是 "怎么改策略"（如 drop_factor=mom_20），
    # 我们把它塞进 backtest.run 的 params 字段，再加上固定的 strategy_id/start/end
    strategy_params = raw_params

    eid = generate_experiment_id(question.id, raw_params)
    record = ExperimentRecord(
        experiment_id=eid,
        question_id=question.id,
        question_type=question.type,
        question_text=question.question,
        rationale=question.rationale,
        priority=question.priority,
        command=command,
        params={
            "strategy_id": strategy_id,
            "start": start,
            "end": end,
            "params": strategy_params,
        },
        status="proposed",
        source=dict(question.source or {}),
    )
    save_experiment(record)
    return record


def run_experiment(
    record: ExperimentRecord,
    executor: Optional[Callable[..., dict]] = None,
) -> ExperimentRecord:
    """
    执行一条 proposed experiment。

    参数：
        record    — 已经落盘的 ExperimentRecord（status=proposed）
        executor  — control_surface.execute 的可插拔注入点，单测用。
                    签名：executor(command, approved=True, **params) -> dict

    返回：
        更新后的 ExperimentRecord

    行为：
      - 非 backtest.run 命令 → skipped
      - question_type ∈ SKIP_TYPES → skipped
      - executor 抛异常 → failed
      - executor 返回 {"status": "error"} → failed
      - executor 返回 {"status": "success", "data": {"run_id": ..., "metrics": ...}} → success
    """
    if executor is None:
        from pipeline.control_surface import execute as executor  # lazy import

    if record.question_type in _SKIP_TYPES:
        return update_experiment(
            record.experiment_id,
            status="skipped",
            error=f"question_type={record.question_type} 不触发回测",
        )

    if record.command != "backtest.run":
        return update_experiment(
            record.experiment_id,
            status="skipped",
            error=f"command={record.command!r} 当前不支持",
        )

    # 切 running
    update_experiment(record.experiment_id, status="running")

    try:
        call_params = dict(record.params or {})
        result = executor("backtest.run", approved=True, **call_params)
    except Exception as e:
        return update_experiment(
            record.experiment_id,
            status="failed",
            error=f"executor 异常: {e}",
        )

    if not isinstance(result, dict):
        return update_experiment(
            record.experiment_id,
            status="failed",
            error=f"executor 返回非 dict: {type(result).__name__}",
        )

    status = result.get("status")
    if status != "success":
        return update_experiment(
            record.experiment_id,
            status="failed",
            error=result.get("error") or f"executor status={status!r}",
        )

    data = result.get("data") or {}
    run_id = data.get("run_id")
    metrics = data.get("metrics") or {}

    return update_experiment(
        record.experiment_id,
        status="success",
        run_id=run_id,
        result_summary=_build_summary(metrics),
    )


def run_experiments(
    questions: list[ResearchQuestion],
    strategy_id: str = DEFAULT_STRATEGY_ID,
    start: Optional[str] = None,
    end: Optional[str] = None,
    max_runs: Optional[int] = None,
    executor: Optional[Callable[..., dict]] = None,
) -> list[ExperimentRecord]:
    """
    propose + run 的批处理入口。

    参数：
        questions   — research_planner.plan_research() 的输出
        strategy_id — 对照回测跑哪个策略
        start/end   — 回测时间段，默认近 3 年
        max_runs    — 最多真正执行几条（仅 budget 控制，多余的留 proposed）
        executor    — control_surface.execute 注入点

    返回：所有 experiment 记录（包括只 proposed 没跑的）
    """
    records: list[ExperimentRecord] = []
    executed = 0
    for q in questions:
        rec = propose_experiment(q, strategy_id=strategy_id, start=start, end=end)

        # 不可执行的直接在 run_experiment 里落 skipped
        if q.type in _SKIP_TYPES or rec.command != "backtest.run":
            rec = run_experiment(rec, executor=executor)
            records.append(rec)
            continue

        if max_runs is not None and executed >= max_runs:
            # 超预算：保留 proposed 状态，不跑
            records.append(rec)
            continue

        rec = run_experiment(rec, executor=executor)
        records.append(rec)
        executed += 1

    return records


# ══════════════════════════════════════════════════════════════
# 内部工具
# ══════════════════════════════════════════════════════════════

def _build_summary(metrics: dict) -> dict:
    """
    从回测 metrics 里挑关键字段做 summary。

    只留最常看的几个 —— 完整 metrics 仍在 run_store 那条 RunRecord 上。
    """
    if not metrics:
        return {}
    keys = [
        "total_return",
        "annualized_return",
        "sharpe",
        "max_drawdown",
        "volatility",
        "win_rate",
        "n_trading_days",
    ]
    return {k: metrics[k] for k in keys if k in metrics}


if __name__ == "__main__":
    from pipeline.research_planner import plan_research

    # 用一个 degraded 因子触发 ResearchQuestion
    health = {"mom_20": {"status": "degraded", "rolling_ic": 0.01, "t_stat": 1.2, "n_obs": 80}}
    qs = plan_research(factor_health=health)
    print(f"{len(qs)} questions")
    # 用假 executor 避免真的跑回测
    def fake_executor(command, approved=False, **kwargs):
        return {
            "status": "success",
            "data": {"run_id": "fake_run_123", "metrics": {"sharpe": 1.1, "max_drawdown": -0.08}},
        }
    results = run_experiments(qs, executor=fake_executor)
    for r in results:
        print(f"  {r.experiment_id[:20]}... {r.status} run_id={r.run_id}")
    print("✅ experiment_runner import ok")
