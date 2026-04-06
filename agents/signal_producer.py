"""
agents/signal_producer.py — 信号生成 Agent

职责:
  1. Pre-flight 检查（数据新鲜度、交易日历）
  2. 调用 daily_signal.run_daily_pipeline() 生成选股信号
  3. Post-flight 验证（选股数量合理性、评分分布检查）
  4. 异常检测（与前一日信号对比，换手率预警）
"""

import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

SIGNAL_DIR = Path(__file__).parent.parent / "live" / "signals"


class SignalProducer:
    """
    信号生成 Agent：带 pre/post-flight 校验的信号管道。
    """

    def __init__(self):
        from utils.runtime_config import get_pipeline_param
        self.MIN_PICKS = get_pipeline_param("signal_validation.min_picks", 10)
        self.MAX_PICKS = get_pipeline_param("signal_validation.max_picks", 60)
        self.OVERLAP_WARNING_THRESHOLD = get_pipeline_param(
            "signal_validation.overlap_warning_threshold", 0.3
        )

    def run(self, ctx: Any) -> dict:
        """
        生成当日选股信号。

        返回:
            dict: signal pipeline 的原始结果 + 校验信息
        """
        from pipeline.daily_signal import run_daily_pipeline

        date = ctx.date

        # ── Pre-flight 检查 ────────────────────────────────────
        preflight_issues = self._preflight(ctx)
        if preflight_issues:
            for issue in preflight_issues:
                print(f"  [预检] {issue}")

        # ── 读取当前激活策略 ──────────────────────────────────
        from pipeline.active_strategy import get_active_strategy
        strategy = get_active_strategy()
        print(f"  生成信号: {date} (策略: {strategy})")

        if ctx.dry_run:
            ctx.log_decision("SignalProducer", f"[DRY RUN] 跳过信号生成 {date}")
            return {"dry_run": True, "date": date}

        try:
            result = run_daily_pipeline(date=date, strategy=strategy)
        except ValueError as e:
            # 日期不在数据中（非交易日）
            print(f"  非交易日或数据不可用: {e}")
            ctx.log_decision(
                "SignalProducer",
                f"信号生成跳过: {e}",
                "可能是非交易日",
            )
            return {"skipped": True, "reason": str(e), "date": date}

        picks = result.get("picks", [])
        scores = result.get("scores", {})

        # ── Post-flight 验证 ──────────────────────────────────
        postflight = self._postflight(result, ctx)

        ctx.set("signal_result", result)
        ctx.set("signal_picks", picks)
        ctx.set("signal_date", result.get("date", date))

        ctx.log_decision(
            "SignalProducer",
            f"信号生成完成: {len(picks)} 只股票",
            f"策略={strategy}, 排除 ST={result.get('excluded', {}).get('st', 0)}",
        )

        return {
            "signal": result,
            "preflight": preflight_issues,
            "postflight": postflight,
        }

    def _preflight(self, ctx: Any) -> list:
        """信号生成前检查"""
        issues = []

        # 检查数据延迟
        days_stale = ctx.get("data_days_stale", 0)
        if days_stale and days_stale > 5:
            issues.append(f"数据延迟 {days_stale} 天，信号可能不准确")

        return issues

    def _postflight(self, result: dict, ctx: Any) -> dict:
        """
        信号生成后验证。

        检查:
          1. 选股数量是否在合理范围
          2. 评分分布是否正常（无极端值）
          3. 与前一日信号的重叠率
        """
        checks = {"status": "ok", "warnings": []}

        picks = result.get("picks", [])

        # 1. 数量检查
        if len(picks) < self.MIN_PICKS:
            checks["warnings"].append(
                f"选股数量偏少: {len(picks)} < {self.MIN_PICKS}"
            )
        elif len(picks) > self.MAX_PICKS:
            checks["warnings"].append(
                f"选股数量偏多: {len(picks)} > {self.MAX_PICKS}"
            )

        # 2. 评分分布检查
        scores = result.get("scores", {})
        if scores:
            vals = list(scores.values())
            if max(vals) > 10 or min(vals) < -10:
                checks["warnings"].append(
                    f"评分极端值: max={max(vals):.2f}, min={min(vals):.2f}"
                )

        # 3. 与前一日信号重叠率
        prev_picks = self._load_prev_signal(result.get("date", ctx.date))
        if prev_picks:
            overlap = set(picks) & set(prev_picks)
            overlap_rate = len(overlap) / max(len(picks), 1)
            if overlap_rate < self.OVERLAP_WARNING_THRESHOLD:
                checks["warnings"].append(
                    f"与前日信号重叠率低: {overlap_rate:.1%} (换手率可能很高)"
                )
            checks["overlap_rate"] = round(overlap_rate, 4)

        if checks["warnings"]:
            checks["status"] = "warning"
            for w in checks["warnings"]:
                print(f"  [后检] {w}")

        return checks

    def _load_prev_signal(self, current_date: str) -> list:
        """加载前一日的信号"""
        if not SIGNAL_DIR.exists():
            return []

        signal_files = sorted(SIGNAL_DIR.glob("*.json"))
        # 找到当前日期之前的最近一个信号
        for f in reversed(signal_files):
            file_date = f.stem
            if file_date < current_date:
                try:
                    with open(f, "r", encoding="utf-8") as fh:
                        data = json.load(fh)
                    return data.get("picks", [])
                except Exception:
                    pass
        return []
