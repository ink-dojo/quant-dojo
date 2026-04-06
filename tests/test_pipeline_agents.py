"""
test_pipeline_agents.py — 流水线 Agent 单元测试

测试所有 7 个流水线 Agent + 编排器:
  1. PipelineOrchestrator — 编排、调度、halt 逻辑
  2. DataAgent — 新鲜度检查、缓存清理
  3. FactorMiner — 因子筛选、贪心选择、共线性控制
  4. StrategyComposer — 组合评估、升级判定
  5. SignalProducer — pre/post-flight 校验
  6. ExecutorAgent — 调仓执行、NAV 验证
  7. RiskGuard — 风控告警、halt 决策
  8. Reporter — 日报结构完整性

所有外部依赖均 mock 隔离，无需真实数据。
"""

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch, PropertyMock

# 注入缺失第三方依赖 stub
for _pkg in ("akshare",):
    if _pkg not in sys.modules:
        sys.modules[_pkg] = MagicMock()

import numpy as np
import pandas as pd

# 确保项目根目录在 sys.path
PROJECT_ROOT = Path(__file__).parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from pipeline.orchestrator import (
    PipelineOrchestrator,
    PipelineContext,
    PipelineStage,
    StageResult,
    StageStatus,
)


# ─────────────────────────────────────────────────────────────────────────
# Helper
# ─────────────────────────────────────────────────────────────────────────

def make_ctx(**kwargs):
    """快速创建测试用的 PipelineContext"""
    defaults = {"date": "2026-04-03", "mode": "daily", "dry_run": False}
    defaults.update(kwargs)
    return PipelineContext(**defaults)


# ─────────────────────────────────────────────────────────────────────────
# 1. PipelineOrchestrator
# ─────────────────────────────────────────────────────────────────────────

class TestPipelineOrchestrator(unittest.TestCase):
    """编排器核心逻辑测试"""

    def test_empty_pipeline_succeeds(self):
        """空流水线应成功执行且返回空结果"""
        orch = PipelineOrchestrator()
        with tempfile.TemporaryDirectory() as tmp:
            with patch("pipeline.orchestrator.JOURNAL_DIR", Path(tmp)):
                ctx = orch.execute(date="2026-01-01", mode="daily")
        self.assertEqual(len(ctx.stage_results), 0)
        self.assertFalse(ctx.halt)

    def test_stages_execute_in_order(self):
        """各阶段按注册顺序执行"""
        call_order = []

        def stage_a(ctx):
            call_order.append("a")

        def stage_b(ctx):
            call_order.append("b")

        orch = PipelineOrchestrator()
        orch.add_stage("a", stage_a)
        orch.add_stage("b", stage_b)

        with tempfile.TemporaryDirectory() as tmp:
            with patch("pipeline.orchestrator.JOURNAL_DIR", Path(tmp)):
                ctx = orch.execute(date="2026-01-01")

        self.assertEqual(call_order, ["a", "b"])
        self.assertEqual(len(ctx.stage_results), 2)
        self.assertTrue(all(r.status == StageStatus.SUCCESS for r in ctx.stage_results))

    def test_critical_stage_failure_halts_pipeline(self):
        """critical 阶段失败后，后续阶段应被跳过"""
        def failing_stage(ctx):
            raise RuntimeError("boom")

        def should_not_run(ctx):
            raise AssertionError("this should be skipped")

        orch = PipelineOrchestrator()
        orch.add_stage("critical_step", failing_stage, critical=True)
        orch.add_stage("after_step", should_not_run)

        with tempfile.TemporaryDirectory() as tmp:
            with patch("pipeline.orchestrator.JOURNAL_DIR", Path(tmp)):
                ctx = orch.execute(date="2026-01-01")

        self.assertTrue(ctx.halt)
        self.assertEqual(ctx.stage_results[0].status, StageStatus.FAILED)
        self.assertEqual(ctx.stage_results[1].status, StageStatus.SKIPPED)

    def test_non_critical_failure_continues(self):
        """非 critical 阶段失败后，后续阶段继续执行"""
        ran_after = []

        def failing_stage(ctx):
            raise RuntimeError("boom")

        def after_stage(ctx):
            ran_after.append(True)

        orch = PipelineOrchestrator()
        orch.add_stage("non_critical", failing_stage, critical=False)
        orch.add_stage("after", after_stage)

        with tempfile.TemporaryDirectory() as tmp:
            with patch("pipeline.orchestrator.JOURNAL_DIR", Path(tmp)):
                ctx = orch.execute(date="2026-01-01")

        self.assertFalse(ctx.halt)
        self.assertEqual(ctx.stage_results[0].status, StageStatus.FAILED)
        self.assertEqual(ctx.stage_results[1].status, StageStatus.SUCCESS)
        self.assertTrue(ran_after)

    def test_weekly_stages_skip_on_non_monday_daily(self):
        """daily 模式 + 非周一 → weekly 阶段应跳过"""
        def weekly_fn(ctx):
            raise AssertionError("should not run")

        orch = PipelineOrchestrator()
        orch.add_stage("weekly_task", weekly_fn, schedule="weekly")

        # 2026-04-03 是周五
        with tempfile.TemporaryDirectory() as tmp:
            with patch("pipeline.orchestrator.JOURNAL_DIR", Path(tmp)):
                ctx = orch.execute(date="2026-04-03", mode="daily")

        self.assertEqual(ctx.stage_results[0].status, StageStatus.SKIPPED)

    def test_weekly_stages_run_on_monday(self):
        """daily 模式 + 周一 → weekly 阶段应执行"""
        ran = []

        def weekly_fn(ctx):
            ran.append(True)

        orch = PipelineOrchestrator()
        orch.add_stage("weekly_task", weekly_fn, schedule="weekly")

        # 2026-03-30 是周一
        with tempfile.TemporaryDirectory() as tmp:
            with patch("pipeline.orchestrator.JOURNAL_DIR", Path(tmp)):
                ctx = orch.execute(date="2026-03-30", mode="daily")

        self.assertTrue(ran)
        self.assertEqual(ctx.stage_results[0].status, StageStatus.SUCCESS)

    def test_retry_on_failure_then_success(self):
        """重试后成功应记录为 SUCCESS"""
        call_count = [0]

        def flaky_stage(ctx):
            call_count[0] += 1
            if call_count[0] < 3:
                raise RuntimeError("transient error")
            return "ok"

        orch = PipelineOrchestrator()
        orch.add_stage("flaky", flaky_stage, max_retries=2, retry_backoff_sec=0.01)

        with tempfile.TemporaryDirectory() as tmp:
            with patch("pipeline.orchestrator.JOURNAL_DIR", Path(tmp)):
                ctx = orch.execute(date="2026-01-01")

        self.assertEqual(call_count[0], 3)
        self.assertEqual(ctx.stage_results[0].status, StageStatus.SUCCESS)

    def test_retry_exhausted_fails(self):
        """重试耗尽应记录为 FAILED"""
        def always_fail(ctx):
            raise RuntimeError("permanent error")

        orch = PipelineOrchestrator()
        orch.add_stage("bad", always_fail, max_retries=1, retry_backoff_sec=0.01)

        with tempfile.TemporaryDirectory() as tmp:
            with patch("pipeline.orchestrator.JOURNAL_DIR", Path(tmp)):
                ctx = orch.execute(date="2026-01-01")

        self.assertEqual(ctx.stage_results[0].status, StageStatus.FAILED)

    def test_journal_saved(self):
        """执行后应保存审计日志"""
        orch = PipelineOrchestrator()
        orch.add_stage("noop", lambda ctx: None)

        with tempfile.TemporaryDirectory() as tmp:
            journal_dir = Path(tmp)
            with patch("pipeline.orchestrator.JOURNAL_DIR", journal_dir):
                orch.execute(date="2026-01-01")

            journal_file = journal_dir / "pipeline_2026-01-01.json"
            self.assertTrue(journal_file.exists())

            with open(journal_file) as f:
                journal = json.load(f)

            self.assertEqual(journal["date"], "2026-01-01")
            self.assertEqual(len(journal["stages"]), 1)
            self.assertEqual(journal["stages"][0]["status"], "success")


# ─────────────────────────────────────────────────────────────────────────
# 2. PipelineContext
# ─────────────────────────────────────────────────────────────────────────

class TestPipelineContext(unittest.TestCase):
    """PipelineContext 数据总线测试"""

    def test_set_and_get(self):
        ctx = make_ctx()
        ctx.set("key", 42)
        self.assertEqual(ctx.get("key"), 42)

    def test_get_default(self):
        ctx = make_ctx()
        self.assertIsNone(ctx.get("missing"))
        self.assertEqual(ctx.get("missing", "default"), "default")

    def test_log_decision(self):
        ctx = make_ctx()
        ctx.log_decision("TestAgent", "did a thing", "because reasons")
        self.assertEqual(len(ctx.decisions), 1)
        self.assertEqual(ctx.decisions[0]["agent"], "TestAgent")
        self.assertEqual(ctx.decisions[0]["decision"], "did a thing")

    def test_halt_default_false(self):
        ctx = make_ctx()
        self.assertFalse(ctx.halt)


# ─────────────────────────────────────────────────────────────────────────
# 3. DataAgent
# ─────────────────────────────────────────────────────────────────────────

class TestDataAgent(unittest.TestCase):
    """数据管家 Agent 测试"""

    @patch("agents.data_agent.DataAgent._check_quality", return_value=[])
    @patch("utils.local_data_loader.get_all_symbols", return_value=["000001"])
    @patch("pipeline.data_checker.check_data_freshness")
    def test_fresh_data_no_update(self, mock_fresh, mock_syms, mock_quality):
        """数据新鲜 → 不触发更新"""
        from agents.data_agent import DataAgent

        mock_fresh.return_value = {"latest_date": "2026-04-02", "days_stale": 1}

        agent = DataAgent()
        ctx = make_ctx()
        result = agent.run(ctx)

        self.assertFalse(result["update"]["triggered"])
        self.assertEqual(ctx.get("data_days_stale"), 1)

    @patch("agents.data_agent.DataAgent._check_quality", return_value=[])
    @patch("agents.data_agent.DataAgent._clear_cache")
    @patch("utils.local_data_loader.get_all_symbols", return_value=["000001"])
    @patch("pipeline.data_update.run_update")
    @patch("pipeline.data_checker.check_data_freshness")
    def test_stale_data_triggers_update(self, mock_fresh, mock_update, mock_syms, mock_cache, mock_quality):
        """数据过期 → 触发更新"""
        from agents.data_agent import DataAgent

        mock_fresh.return_value = {"latest_date": "2026-03-20", "days_stale": 14}
        mock_update.return_value = {"updated": ["000001", "000002"], "skipped": [], "failed": []}

        agent = DataAgent()
        ctx = make_ctx()
        result = agent.run(ctx)

        self.assertTrue(result["update"]["triggered"])
        self.assertEqual(result["update"]["updated"], 2)
        mock_update.assert_called_once()

    @patch("agents.data_agent.DataAgent._check_quality", return_value=[])
    @patch("utils.local_data_loader.get_all_symbols", return_value=["000001"])
    @patch("pipeline.data_checker.check_data_freshness")
    def test_dry_run_no_update(self, mock_fresh, mock_syms, mock_quality):
        """dry_run 模式不触发更新（即使数据过期）"""
        from agents.data_agent import DataAgent

        mock_fresh.return_value = {"latest_date": "2026-03-01", "days_stale": 30}

        agent = DataAgent()
        ctx = make_ctx(dry_run=True)
        result = agent.run(ctx)

        self.assertFalse(result["update"]["triggered"])


# ─────────────────────────────────────────────────────────────────────────
# 4. FactorMiner — _select_top_k 贪心算法
# ─────────────────────────────────────────────────────────────────────────

class TestFactorMinerSelection(unittest.TestCase):
    """FactorMiner 因子选择算法单元测试"""

    def _make_miner(self):
        from agents.factor_miner import FactorMiner
        return FactorMiner()

    def test_select_top_k_basic(self):
        """基础选择：按 |ICIR| 排序选 Top-K"""
        miner = self._make_miner()
        rankings = [
            {"name": "f1", "IC_mean": 0.05, "ICIR": 0.5, "t_stat": 3.0},
            {"name": "f2", "IC_mean": 0.04, "ICIR": 0.4, "t_stat": 2.5},
            {"name": "f3", "IC_mean": 0.03, "ICIR": 0.3, "t_stat": 2.0},
            {"name": "f4", "IC_mean": 0.02, "ICIR": 0.25, "t_stat": 1.8},
            {"name": "f5", "IC_mean": 0.015, "ICIR": 0.22, "t_stat": 1.6},
            {"name": "f6", "IC_mean": 0.015, "ICIR": 0.21, "t_stat": 1.5},
        ]
        selected = miner._select_top_k(rankings, corr_matrix={})
        self.assertEqual(len(selected), 5)
        self.assertEqual(selected, ["f1", "f2", "f3", "f4", "f5"])

    def test_select_skips_below_threshold(self):
        """IC/ICIR/t-stat 不达标的因子应被跳过"""
        miner = self._make_miner()
        rankings = [
            {"name": "good", "IC_mean": 0.05, "ICIR": 0.5, "t_stat": 3.0},
            {"name": "low_ic", "IC_mean": 0.01, "ICIR": 0.5, "t_stat": 3.0},  # |IC| < 0.015
            {"name": "low_icir", "IC_mean": 0.05, "ICIR": 0.1, "t_stat": 3.0},  # |ICIR| < 0.2
            {"name": "low_t", "IC_mean": 0.05, "ICIR": 0.5, "t_stat": 1.0},  # |t| < 1.5
        ]
        selected = miner._select_top_k(rankings, corr_matrix={})
        self.assertEqual(selected, ["good"])

    def test_select_filters_correlated_factors(self):
        """高相关因子应被排除"""
        miner = self._make_miner()
        rankings = [
            {"name": "f1", "IC_mean": 0.05, "ICIR": 0.5, "t_stat": 3.0},
            {"name": "f2", "IC_mean": 0.04, "ICIR": 0.4, "t_stat": 2.5},
            {"name": "f3", "IC_mean": 0.03, "ICIR": 0.3, "t_stat": 2.0},
        ]
        # f2 与 f1 高度相关
        corr_matrix = {
            "f1": {"f1": 1.0, "f2": 0.85, "f3": 0.2},
            "f2": {"f1": 0.85, "f2": 1.0, "f3": 0.3},
            "f3": {"f1": 0.2, "f2": 0.3, "f3": 1.0},
        }
        selected = miner._select_top_k(rankings, corr_matrix)
        self.assertIn("f1", selected)
        self.assertNotIn("f2", selected)  # corr > 0.7 with f1
        self.assertIn("f3", selected)


# ─────────────────────────────────────────────────────────────────────────
# 5. StrategyComposer — _eval_combo
# ─────────────────────────────────────────────────────────────────────────

class TestStrategyComposerEval(unittest.TestCase):
    """策略组合 Agent 评估逻辑测试"""

    def _make_composer(self):
        from agents.strategy_composer import StrategyComposer
        return StrategyComposer()

    def test_eval_combo_returns_icir(self):
        """评估组合应返回 IC 加权 ICIR"""
        composer = self._make_composer()
        rank_by_name = {
            "f1": {"name": "f1", "IC_mean": 0.04, "ICIR": 0.5},
            "f2": {"name": "f2", "IC_mean": 0.02, "ICIR": 0.3},
        }
        result = composer._eval_combo(["f1", "f2"], rank_by_name)
        self.assertEqual(result["n_valid"], 2)
        self.assertGreater(result["combo_icir"], 0)
        # IC 加权 → f1 权重更大 → combo_icir 偏向 0.5
        self.assertGreater(result["combo_icir"], 0.3)

    def test_eval_combo_missing_factors(self):
        """缺失因子不计入评估"""
        composer = self._make_composer()
        rank_by_name = {
            "f1": {"name": "f1", "IC_mean": 0.04, "ICIR": 0.5},
        }
        result = composer._eval_combo(["f1", "missing_factor"], rank_by_name)
        self.assertEqual(result["n_valid"], 1)

    def test_eval_combo_all_missing(self):
        """所有因子都缺失 → combo_icir=0"""
        composer = self._make_composer()
        result = composer._eval_combo(["x", "y"], rank_by_name={})
        self.assertEqual(result["combo_icir"], 0.0)
        self.assertEqual(result["n_valid"], 0)


# ─────────────────────────────────────────────────────────────────────────
# 6. SignalProducer — Pre/Post-flight
# ─────────────────────────────────────────────────────────────────────────

class TestSignalProducer(unittest.TestCase):
    """信号生成 Agent 测试"""

    def test_preflight_warns_stale_data(self):
        """数据延迟 > 5 天应产生预检警告"""
        from agents.signal_producer import SignalProducer

        producer = SignalProducer()
        ctx = make_ctx()
        ctx.set("data_days_stale", 10)

        issues = producer._preflight(ctx)
        self.assertTrue(any("延迟" in i for i in issues))

    def test_preflight_ok_when_fresh(self):
        """数据新鲜时无预检问题"""
        from agents.signal_producer import SignalProducer

        producer = SignalProducer()
        ctx = make_ctx()
        ctx.set("data_days_stale", 2)

        issues = producer._preflight(ctx)
        self.assertEqual(issues, [])

    def test_postflight_warns_few_picks(self):
        """选股数 < MIN_PICKS 应发警告"""
        from agents.signal_producer import SignalProducer

        producer = SignalProducer()
        ctx = make_ctx()

        result = {"picks": ["A", "B", "C"], "scores": {}, "date": "2026-04-03"}
        checks = producer._postflight(result, ctx)
        self.assertEqual(checks["status"], "warning")
        self.assertTrue(any("偏少" in w for w in checks["warnings"]))

    def test_postflight_warns_many_picks(self):
        """选股数 > MAX_PICKS 应发警告"""
        from agents.signal_producer import SignalProducer

        producer = SignalProducer()
        ctx = make_ctx()

        result = {"picks": [f"s{i}" for i in range(70)], "scores": {}, "date": "2026-04-03"}
        checks = producer._postflight(result, ctx)
        self.assertEqual(checks["status"], "warning")
        self.assertTrue(any("偏多" in w for w in checks["warnings"]))

    @patch("agents.signal_producer.SignalProducer._load_prev_signal", return_value=[])
    def test_postflight_ok_normal_picks(self, mock_prev):
        """正常选股数无警告"""
        from agents.signal_producer import SignalProducer

        producer = SignalProducer()
        ctx = make_ctx()

        result = {"picks": [f"s{i}" for i in range(30)], "scores": {}, "date": "2026-04-03"}
        checks = producer._postflight(result, ctx)
        self.assertEqual(checks["status"], "ok")

    @patch("pipeline.daily_signal.run_daily_pipeline")
    def test_dry_run_skips_signal(self, mock_pipeline):
        """dry_run 模式不调用信号生成"""
        from agents.signal_producer import SignalProducer

        producer = SignalProducer()
        ctx = make_ctx(dry_run=True)
        result = producer.run(ctx)

        self.assertTrue(result.get("dry_run"))
        mock_pipeline.assert_not_called()

    def test_postflight_extreme_scores_warning(self):
        """评分极端值应产生警告"""
        from agents.signal_producer import SignalProducer

        producer = SignalProducer()
        ctx = make_ctx()

        result = {
            "picks": [f"s{i}" for i in range(30)],
            "scores": {"s0": 15.0, "s1": -12.0},
            "date": "2026-04-03",
        }
        checks = producer._postflight(result, ctx)
        self.assertTrue(any("极端值" in w for w in checks["warnings"]))


# ─────────────────────────────────────────────────────────────────────────
# 7. RiskGuard
# ─────────────────────────────────────────────────────────────────────────

class TestRiskGuard(unittest.TestCase):
    """风控守卫 Agent 测试"""

    @patch("live.risk_monitor.check_risk_alerts", return_value=[])
    @patch("live.paper_trader.PaperTrader")
    def test_no_alerts_ok(self, mock_trader_cls, mock_alerts):
        """无告警 → risk_level=ok"""
        from agents.risk_guard import RiskGuard

        mock_trader = MagicMock()
        mock_trader.get_current_positions.return_value = pd.DataFrame({"sym": ["A"]})
        mock_trader_cls.return_value = mock_trader

        guard = RiskGuard(halt_on_critical=False)
        ctx = make_ctx()
        result = guard.run(ctx)

        self.assertEqual(result["risk_level"], "ok")
        self.assertFalse(result["halted"])

    @patch("live.risk_monitor.check_risk_alerts")
    @patch("live.paper_trader.PaperTrader")
    def test_critical_alert_with_halt(self, mock_trader_cls, mock_alerts):
        """CRITICAL 告警 + halt_on_critical=True → 中止流水线"""
        from agents.risk_guard import RiskGuard

        mock_trader = MagicMock()
        mock_trader.get_current_positions.return_value = pd.DataFrame({"sym": ["A"]})
        mock_trader_cls.return_value = mock_trader
        mock_alerts.return_value = [
            {"level": "critical", "msg": "最大回撤超过 10%"},
        ]

        guard = RiskGuard(halt_on_critical=True)
        ctx = make_ctx()
        result = guard.run(ctx)

        self.assertEqual(result["risk_level"], "critical")
        self.assertTrue(result["halted"])
        self.assertTrue(ctx.halt)

    @patch("live.risk_monitor.check_risk_alerts")
    @patch("live.paper_trader.PaperTrader")
    def test_critical_alert_without_halt(self, mock_trader_cls, mock_alerts):
        """CRITICAL 告警 + halt_on_critical=False → 记录但不中止"""
        from agents.risk_guard import RiskGuard

        mock_trader = MagicMock()
        mock_trader.get_current_positions.return_value = pd.DataFrame({"sym": ["A"]})
        mock_trader_cls.return_value = mock_trader
        mock_alerts.return_value = [
            {"level": "critical", "msg": "因子 bp 已死"},
        ]

        guard = RiskGuard(halt_on_critical=False)
        ctx = make_ctx()
        result = guard.run(ctx)

        self.assertEqual(result["risk_level"], "critical")
        self.assertFalse(result["halted"])
        self.assertFalse(ctx.halt)

    @patch("live.paper_trader.PaperTrader")
    def test_empty_portfolio_skips(self, mock_trader_cls):
        """无持仓 → 跳过风控检查"""
        from agents.risk_guard import RiskGuard

        mock_trader = MagicMock()
        mock_trader.get_current_positions.return_value = pd.DataFrame()
        mock_trader_cls.return_value = mock_trader

        guard = RiskGuard()
        ctx = make_ctx()
        result = guard.run(ctx)

        self.assertEqual(result["risk_level"], "ok")


# ─────────────────────────────────────────────────────────────────────────
# 8. Reporter
# ─────────────────────────────────────────────────────────────────────────

class TestReporter(unittest.TestCase):
    """报告生成 Agent 测试"""

    def test_minimal_report(self):
        """最小报告应包含标题和概览"""
        from agents.reporter import Reporter

        reporter = Reporter()
        ctx = make_ctx()
        # 添加最基本的 stage_results
        ctx.stage_results.append(
            StageResult(name="test_stage", status=StageStatus.SUCCESS, duration_sec=1.0)
        )

        with tempfile.TemporaryDirectory() as tmp:
            with patch("agents.reporter.REPORT_DIR", Path(tmp)):
                result = reporter.run(ctx)

            report_path = Path(result["report_path"])
            self.assertTrue(report_path.exists())

            content = report_path.read_text(encoding="utf-8")
            self.assertIn("量化流水线日报", content)
            self.assertIn("2026-04-03", content)
            self.assertIn("test_stage", content)

    def test_report_includes_signal_section(self):
        """有信号数据时应包含信号摘要"""
        from agents.reporter import Reporter

        reporter = Reporter()
        ctx = make_ctx()
        ctx.stage_results.append(
            StageResult(name="signal", status=StageStatus.SUCCESS, duration_sec=5.0)
        )
        ctx.set("signal_result", {
            "picks": ["000001", "000002", "600000"],
            "excluded": {"st": 10, "new_listing": 2, "low_price": 5},
            "metadata": {"strategy": "v7"},
        })

        with tempfile.TemporaryDirectory() as tmp:
            with patch("agents.reporter.REPORT_DIR", Path(tmp)):
                result = reporter.run(ctx)

            content = Path(result["report_path"]).read_text(encoding="utf-8")
            self.assertIn("信号摘要", content)
            self.assertIn("**3**", content)  # 3 只选股

    def test_report_includes_risk_section(self):
        """有风控告警时应包含风控状态"""
        from agents.reporter import Reporter

        reporter = Reporter()
        ctx = make_ctx()
        ctx.stage_results.append(
            StageResult(name="risk", status=StageStatus.SUCCESS, duration_sec=1.0)
        )
        ctx.set("risk_level", "critical")
        ctx.set("risk_alerts", [
            {"level": "critical", "msg": "最大回撤 12%"},
        ])

        with tempfile.TemporaryDirectory() as tmp:
            with patch("agents.reporter.REPORT_DIR", Path(tmp)):
                result = reporter.run(ctx)

            content = Path(result["report_path"]).read_text(encoding="utf-8")
            self.assertIn("风控状态", content)
            self.assertIn("CRITICAL", content)
            self.assertIn("最大回撤", content)

    def test_report_includes_decisions(self):
        """决策日志应写入报告"""
        from agents.reporter import Reporter

        reporter = Reporter()
        ctx = make_ctx()
        ctx.stage_results.append(
            StageResult(name="test", status=StageStatus.SUCCESS, duration_sec=0.5)
        )
        ctx.log_decision("TestAgent", "做了重要决策", "因为某原因")

        with tempfile.TemporaryDirectory() as tmp:
            with patch("agents.reporter.REPORT_DIR", Path(tmp)):
                result = reporter.run(ctx)

            content = Path(result["report_path"]).read_text(encoding="utf-8")
            self.assertIn("决策日志", content)
            self.assertIn("TestAgent", content)
            self.assertIn("做了重要决策", content)


# ─────────────────────────────────────────────────────────────────────────
# 9. ExecutorAgent
# ─────────────────────────────────────────────────────────────────────────

class TestExecutorAgent(unittest.TestCase):
    """调仓执行 Agent 测试"""

    def test_no_picks_skips(self):
        """无选股信号 → 跳过调仓"""
        from agents.executor_agent import ExecutorAgent

        executor = ExecutorAgent()
        ctx = make_ctx()
        # 不设 signal_picks
        result = executor.run(ctx)
        self.assertTrue(result.get("skipped"))

    def test_dry_run_no_trade(self):
        """dry_run 不执行实际调仓"""
        from agents.executor_agent import ExecutorAgent

        executor = ExecutorAgent()
        ctx = make_ctx(dry_run=True)
        ctx.set("signal_picks", ["000001", "000002"])

        result = executor.run(ctx)
        self.assertTrue(result.get("dry_run"))


# ─────────────────────────────────────────────────────────────────────────
# 10. Integration: Build default pipeline (import check)
# ─────────────────────────────────────────────────────────────────────────

class TestBuildDefaultPipeline(unittest.TestCase):
    """测试 build_default_pipeline 能正常构建"""

    def test_build_creates_8_stages(self):
        from pipeline.orchestrator import build_default_pipeline
        orch = build_default_pipeline()
        self.assertEqual(len(orch.stages), 8)

    def test_stage_names(self):
        from pipeline.orchestrator import build_default_pipeline
        orch = build_default_pipeline()
        names = [s.name for s in orch.stages]
        self.assertIn("data_check", names)
        self.assertIn("signal", names)
        self.assertIn("risk_guard", names)
        self.assertIn("report", names)

    def test_critical_stages(self):
        """data_check 和 signal 应标记为 critical"""
        from pipeline.orchestrator import build_default_pipeline
        orch = build_default_pipeline()
        critical_names = [s.name for s in orch.stages if s.critical]
        self.assertIn("data_check", critical_names)
        self.assertIn("signal", critical_names)


if __name__ == "__main__":
    unittest.main()
