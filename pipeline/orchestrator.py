"""
pipeline/orchestrator.py — AI Agent 流水线编排器

协调多个专业 Agent 按阶段执行量化流水线：
  数据检查 → 因子挖掘(周) → 策略组合(周) → 信号生成(日) → 执行调仓(日) → 风控(日) → 报告(日)

每个 Agent 的输入/输出通过 PipelineContext 传递，
所有决策记录到 journal/ 目录下的审计日志。
"""

import json
import logging
import time
import traceback
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger(__name__)

JOURNAL_DIR = Path(__file__).parent.parent / "journal"


class StageStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    SUCCESS = "success"
    FAILED = "failed"
    SKIPPED = "skipped"


@dataclass
class StageResult:
    """单个阶段的执行结果"""
    name: str
    status: StageStatus
    duration_sec: float = 0.0
    output: Any = None
    error: Optional[str] = None


@dataclass
class PipelineContext:
    """
    流水线上下文 — 各 Agent 之间的数据总线。

    每个 Agent 把结果写入 context，下游 Agent 从 context 读取。
    """
    date: str  # 当前交易日 YYYY-MM-DD
    mode: str = "daily"  # "daily" | "weekly" | "full"
    dry_run: bool = False

    # Agent 输出存储
    data: Dict[str, Any] = field(default_factory=dict)

    # 决策日志
    decisions: List[Dict] = field(default_factory=list)

    # 阶段结果
    stage_results: List[StageResult] = field(default_factory=list)

    # 是否应该中止后续阶段（RiskGuard 可设置）
    halt: bool = False
    halt_reason: str = ""

    def set(self, key: str, value: Any):
        """写入上下文数据"""
        self.data[key] = value

    def get(self, key: str, default=None) -> Any:
        """读取上下文数据"""
        return self.data.get(key, default)

    def log_decision(self, agent: str, decision: str, reasoning: str = ""):
        """记录一个决策"""
        self.decisions.append({
            "time": datetime.now().isoformat(),
            "agent": agent,
            "decision": decision,
            "reasoning": reasoning,
        })


@dataclass
class PipelineStage:
    """流水线阶段定义"""
    name: str
    agent_fn: Callable[[PipelineContext], Any]
    # 执行条件：daily/weekly/always
    schedule: str = "daily"
    # 失败时是否中止后续阶段
    critical: bool = False
    # 超时（秒）
    timeout: int = 600


class PipelineOrchestrator:
    """
    流水线编排器。

    用法:
        orch = PipelineOrchestrator()
        orch.add_stage("data_check", data_agent.run, schedule="daily")
        orch.add_stage("factor_mine", factor_miner.run, schedule="weekly")
        ...
        results = orch.execute(date="2026-04-03", mode="daily")
    """

    def __init__(self):
        self.stages: List[PipelineStage] = []

    def add_stage(
        self,
        name: str,
        agent_fn: Callable[[PipelineContext], Any],
        schedule: str = "daily",
        critical: bool = False,
        timeout: int = 600,
    ):
        """注册一个流水线阶段"""
        self.stages.append(PipelineStage(
            name=name,
            agent_fn=agent_fn,
            schedule=schedule,
            critical=critical,
            timeout=timeout,
        ))

    def execute(
        self,
        date: str = None,
        mode: str = "daily",
        dry_run: bool = False,
    ) -> PipelineContext:
        """
        执行流水线。

        参数:
            date: 交易日期，None 则自动取今天
            mode: "daily" | "weekly" | "full"
            dry_run: True 时各 Agent 不执行实际操作

        返回:
            PipelineContext 包含所有阶段结果和决策日志
        """
        if date is None:
            date = datetime.now().strftime("%Y-%m-%d")

        ctx = PipelineContext(date=date, mode=mode, dry_run=dry_run)

        # 判断今天是否是周末（周任务在周一执行）
        dt = datetime.strptime(date, "%Y-%m-%d")
        is_weekly_day = dt.weekday() == 0  # 周一

        print(f"\n{'='*60}")
        print(f"  量化流水线启动 | {date} | 模式: {mode}")
        print(f"{'='*60}\n")

        t0 = time.time()

        for stage in self.stages:
            # 检查调度条件
            if stage.schedule == "weekly" and mode == "daily" and not is_weekly_day:
                result = StageResult(
                    name=stage.name,
                    status=StageStatus.SKIPPED,
                    output="非周执行日，跳过",
                )
                ctx.stage_results.append(result)
                continue

            # 检查是否已被中止
            if ctx.halt:
                result = StageResult(
                    name=stage.name,
                    status=StageStatus.SKIPPED,
                    output=f"流水线已中止: {ctx.halt_reason}",
                )
                ctx.stage_results.append(result)
                continue

            # 执行阶段
            print(f"▸ [{stage.name}] 开始...")
            stage_t0 = time.time()

            try:
                output = stage.agent_fn(ctx)
                duration = time.time() - stage_t0
                result = StageResult(
                    name=stage.name,
                    status=StageStatus.SUCCESS,
                    duration_sec=round(duration, 2),
                    output=output,
                )
                print(f"  [{stage.name}] 完成 ({duration:.1f}s)")

            except Exception as e:
                duration = time.time() - stage_t0
                error_msg = f"{type(e).__name__}: {e}"
                result = StageResult(
                    name=stage.name,
                    status=StageStatus.FAILED,
                    duration_sec=round(duration, 2),
                    error=error_msg,
                )
                print(f"  [{stage.name}] 失败 ({duration:.1f}s): {error_msg}")
                logger.error("阶段 %s 失败:\n%s", stage.name, traceback.format_exc())

                if stage.critical:
                    ctx.halt = True
                    ctx.halt_reason = f"关键阶段 {stage.name} 失败: {error_msg}"
                    ctx.log_decision(
                        "orchestrator",
                        f"中止流水线: {stage.name} 失败",
                        error_msg,
                    )

            ctx.stage_results.append(result)

        total_time = time.time() - t0

        # 汇总
        n_success = sum(1 for r in ctx.stage_results if r.status == StageStatus.SUCCESS)
        n_failed = sum(1 for r in ctx.stage_results if r.status == StageStatus.FAILED)
        n_skipped = sum(1 for r in ctx.stage_results if r.status == StageStatus.SKIPPED)

        print(f"\n{'='*60}")
        print(f"  流水线完成 | 耗时 {total_time:.1f}s")
        print(f"  成功: {n_success} | 失败: {n_failed} | 跳过: {n_skipped}")
        print(f"{'='*60}\n")

        # 保存审计日志
        self._save_journal(ctx, total_time)

        return ctx

    def _save_journal(self, ctx: PipelineContext, total_time: float):
        """保存审计日志到 journal/ 目录"""
        JOURNAL_DIR.mkdir(parents=True, exist_ok=True)

        journal = {
            "date": ctx.date,
            "mode": ctx.mode,
            "dry_run": ctx.dry_run,
            "total_time_sec": round(total_time, 2),
            "stages": [
                {
                    "name": r.name,
                    "status": r.status.value,
                    "duration_sec": r.duration_sec,
                    "error": r.error,
                }
                for r in ctx.stage_results
            ],
            "decisions": ctx.decisions,
            "halted": ctx.halt,
            "halt_reason": ctx.halt_reason,
            "timestamp": datetime.now().isoformat(),
        }

        path = JOURNAL_DIR / f"pipeline_{ctx.date}.json"
        with open(path, "w", encoding="utf-8") as f:
            json.dump(journal, f, ensure_ascii=False, indent=2)
        print(f"审计日志: {path}")


def build_default_pipeline() -> PipelineOrchestrator:
    """
    构建默认的量化流水线。

    阶段:
      1. data_check    (daily, critical)  — 数据新鲜度检查 + 更新
      2. factor_mine   (weekly)           — 全因子库 IC 筛选
      3. strategy_compose (weekly)        — 最优因子组合确定
      4. signal        (daily, critical)  — 信号生成
      5. execute       (daily)            — 模拟调仓
      6. risk_guard    (daily)            — 风控检查
      7. report        (daily)            — 日报生成
    """
    from agents.data_agent import DataAgent
    from agents.factor_miner import FactorMiner
    from agents.strategy_composer import StrategyComposer
    from agents.signal_producer import SignalProducer
    from agents.executor_agent import ExecutorAgent
    from agents.risk_guard import RiskGuard
    from agents.reporter import Reporter

    data_agent = DataAgent()
    factor_miner = FactorMiner()
    strategy_composer = StrategyComposer()
    signal_producer = SignalProducer()
    executor = ExecutorAgent()
    risk_guard = RiskGuard()
    reporter = Reporter()

    orch = PipelineOrchestrator()
    orch.add_stage("data_check", data_agent.run, schedule="daily", critical=True)
    orch.add_stage("factor_mine", factor_miner.run, schedule="weekly")
    orch.add_stage("strategy_compose", strategy_composer.run, schedule="weekly")
    orch.add_stage("signal", signal_producer.run, schedule="daily", critical=True)
    orch.add_stage("execute", executor.run, schedule="daily")
    orch.add_stage("risk_guard", risk_guard.run, schedule="daily")
    orch.add_stage("report", reporter.run, schedule="daily")

    return orch
