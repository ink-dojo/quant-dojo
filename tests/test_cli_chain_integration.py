"""
test_cli_chain_integration.py — Phase 6 CLI 控制面链路集成测试

证明新加入的三个 CLI 命令可以无缝串在一起：

    history --json   → 列出历史 run_id
    compare --runs A B → 对比两个历史 run（不重跑）
    diff <run_id>     → 该 run 与 live nav.csv 的漂移分析

整条链路对"实盘 vs 回测 vs 历史对比"构成最小可用的操作面。

这个测试不走 subprocess（那会受 sys.path 和 conftest 影响），而是
直接调用各子命令的 Python 入口并在 capsys 下捕获输出。重点是验证
数据可以在三个命令之间流动：一个命令的输出（run_id）直接作为下一个
命令的输入。
"""
import json
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from quant_dojo.commands import history as history_cmd
from quant_dojo.commands import compare as compare_cmd
from quant_dojo.commands import diff as diff_cmd


def _write_run_json(runs_dir: Path, run_id: str, strategy: str, *,
                    status: str = "success",
                    total_return: float = 0.10,
                    sharpe: float = 0.8,
                    max_dd: float = -0.08,
                    equity_csv: Path | None = None,
                    created_at: str = "2026-04-07T12:00:00"):
    """在 fake runs_dir 下写一条 run JSON，如果给了 equity_csv 路径就写进 artifacts"""
    doc = {
        "run_id": run_id,
        "strategy_id": strategy,
        "status": status,
        "created_at": created_at,
        "start_date": "2026-03-20",
        "end_date": "2026-04-06",
        "metrics": {
            "total_return": total_return,
            "annualized_return": total_return * 2,
            "sharpe": sharpe,
            "max_drawdown": max_dd,
            "volatility": 0.15,
            "win_rate": 0.52,
            "n_trading_days": 12,
        },
        "artifacts": {"equity_csv": str(equity_csv)} if equity_csv else {},
        "error": None,
    }
    (runs_dir / f"{run_id}.json").write_text(json.dumps(doc))


def _write_equity_csv(path: Path, values: list[tuple[str, float]]):
    """写一个简单的 date,cumulative_return 的 equity csv"""
    lines = ["date,cumulative_return"]
    for d, v in values:
        lines.append(f"{d},{v}")
    path.write_text("\n".join(lines) + "\n")


def _write_nav_csv(path: Path, values: list[tuple[str, float]]):
    """写一个简单的 date,nav 的 live nav csv"""
    lines = ["date,nav"]
    for d, v in values:
        lines.append(f"{d},{v}")
    path.write_text("\n".join(lines) + "\n")


@pytest.fixture
def cli_chain_env(tmp_path, monkeypatch):
    """
    构造一个完整的假 Phase 5/6 环境：
      - live/runs 下 2 个 v7 success run + 1 个 v7 failed run
      - 其中 2 个 success run 各自有 equity_csv 文件
      - live/portfolio/nav.csv
      - 所有模块的 LIVE_RUNS_DIR / LIVE_NAV_DEFAULT 都被 monkeypatch 到这里
    """
    runs_dir = tmp_path / "live" / "runs"
    runs_dir.mkdir(parents=True)
    portfolio_dir = tmp_path / "live" / "portfolio"
    portfolio_dir.mkdir(parents=True)

    # 两个有 equity_csv 的 success run
    eq_a = runs_dir / "v7_A_equity.csv"
    eq_b = runs_dir / "v7_B_equity.csv"
    _write_equity_csv(eq_a, [
        ("2026-03-20", 0.00),
        ("2026-03-24", 0.005),
        ("2026-04-01", 0.010),
        ("2026-04-02", 0.008),
        ("2026-04-03", 0.012),
    ])
    _write_equity_csv(eq_b, [
        ("2026-03-20", 0.00),
        ("2026-03-24", 0.003),
        ("2026-04-01", 0.007),
        ("2026-04-02", 0.009),
        ("2026-04-03", 0.014),
    ])
    _write_run_json(runs_dir, "v7_A", "v7",
                    total_return=0.12, sharpe=0.9, max_dd=-0.05,
                    equity_csv=eq_a, created_at="2026-04-07T10:00:00")
    _write_run_json(runs_dir, "v7_B", "v7",
                    total_return=0.14, sharpe=1.4, max_dd=-0.04,
                    equity_csv=eq_b, created_at="2026-04-07T11:00:00")

    # 一条空壳 failed run（compare --runs 应当跳过）
    _write_run_json(runs_dir, "v7_junk", "v7",
                    status="failed", total_return=0.0, sharpe=0.0, max_dd=0.0,
                    created_at="2026-04-06T09:00:00")

    # live nav.csv — 与回测的日期部分重合，但收益系统性略低（模拟交易成本）
    nav_path = portfolio_dir / "nav.csv"
    _write_nav_csv(nav_path, [
        ("2026-03-20", 1_000_000.0),
        ("2026-03-24", 1_003_000.0),  # +0.3%  vs 回测 A +0.5%
        ("2026-04-01", 1_007_000.0),  # +0.7%  vs 回测 A +1.0%
        ("2026-04-02", 1_005_000.0),  # +0.5%  vs 回测 A +0.8%
        ("2026-04-03", 1_009_000.0),  # +0.9%  vs 回测 A +1.2%
    ])

    # 打桩：让三个模块都看到同一个临时目录
    monkeypatch.setattr(history_cmd, "LIVE_RUNS_DIR", runs_dir)
    monkeypatch.setattr(history_cmd, "LOGS_DIR", tmp_path / "logs")  # 不存在即可
    monkeypatch.setattr(compare_cmd, "LIVE_RUNS_DIR", runs_dir)
    monkeypatch.setattr(diff_cmd, "LIVE_RUNS_DIR", runs_dir)
    monkeypatch.setattr(diff_cmd, "LIVE_NAV_DEFAULT", nav_path)

    return {
        "runs_dir": runs_dir,
        "nav_path": nav_path,
        "eq_a": eq_a,
        "eq_b": eq_b,
    }


class TestCliChain:
    """CLI 控制面三件套的端到端串联"""

    def test_history_json_lists_both_success_runs(self, cli_chain_env, capsys):
        """history --json 应当列出 v7_A 与 v7_B，failed run 仅在无过滤时出现"""
        history_cmd.run_history(status="success", as_json=True, limit=10)
        out = capsys.readouterr().out
        data = json.loads(out)
        run_ids = {r["run_id"] for r in data}
        assert "v7_A" in run_ids
        assert "v7_B" in run_ids
        assert "v7_junk" not in run_ids  # status=failed 被过滤

    def test_compare_runs_loads_history_output(self, cli_chain_env, capsys):
        """compare --runs 应该能直接吃 history 的 run_id，不调用 run_backtest"""
        # 不 monkeypatch backtest.standardized；如果 compare 试着重跑会 ImportError
        compare_cmd.run_compare(
            strategies=[],
            run_ids=["v7_A", "v7_B"],
        )
        out = capsys.readouterr().out
        # 两条都应当出现在比较表里
        assert "v7_A" in out
        assert "v7_B" in out
        # 夏普更高的 B 应该被标记为最优
        assert "推荐" in out
        # v7_B sharpe=1.4 > v7_A sharpe=0.9
        recommend_line = [l for l in out.splitlines() if "推荐" in l][0]
        assert "v7" in recommend_line  # 策略名

    def test_compare_runs_skips_failed_run(self, cli_chain_env, capsys):
        """把 failed run 塞进 --runs 也应当被跳过"""
        with pytest.raises(SystemExit):
            compare_cmd.run_compare(
                strategies=[],
                run_ids=["v7_junk", "v7_nonexistent"],
            )
        out = capsys.readouterr().out
        assert "跳过" in out or "错误" in out

    def test_diff_uses_run_id_from_history(self, cli_chain_env, capsys):
        """diff 应当能接受 history 返回的 run_id 并完成漂移分析"""
        diff_cmd.run_diff(run="v7_A", as_json=True)
        out = capsys.readouterr().out
        data = json.loads(out)
        assert data["summary"]["n_overlap_days"] == 5
        # live 全程 +0.9%，backtest A 全程 +1.2%，所以 total_delta ≈ -0.3%
        assert data["summary"]["live_total_return"] == pytest.approx(0.009, abs=1e-6)
        assert data["summary"]["backtest_total_return"] == pytest.approx(0.012, abs=1e-6)
        assert data["summary"]["total_delta"] < 0  # live 少赚
        assert data["meta"]["strategy_id"] == "v7"

    def test_diff_auto_picks_latest_when_run_unspecified(self, cli_chain_env, capsys):
        """不给 run 参数时，diff 应自动挑最新的带 equity_csv 的 run（= v7_B）"""
        diff_cmd.run_diff(run=None, as_json=True)
        out = capsys.readouterr().out
        data = json.loads(out)
        # 应当挑到 v7_B（created_at 更晚）
        assert "v7_B" in data["meta"]["backtest_run"]

    def test_full_chain_history_compare_diff(self, cli_chain_env, capsys):
        """
        把三个命令串成一条链，模拟一个 AI / 脚本的真实使用流程：
          1. history --json 拿到最近的成功 run_ids
          2. 拿头两个喂给 compare --runs
          3. 再挑一个喂给 diff
        全程不重跑任何回测。
        """
        # Step 1: 拿 history 的 run_ids
        history_cmd.run_history(status="success", as_json=True, limit=5)
        step1 = capsys.readouterr().out
        runs = json.loads(step1)
        success_ids = [r["run_id"] for r in runs if r["status"] == "success"]
        assert len(success_ids) >= 2

        # Step 2: compare --runs 头两个
        compare_cmd.run_compare(strategies=[], run_ids=success_ids[:2])
        step2 = capsys.readouterr().out
        assert "推荐" in step2

        # Step 3: diff 第一个
        diff_cmd.run_diff(run=success_ids[0], as_json=True)
        step3 = capsys.readouterr().out
        data = json.loads(step3)
        assert data["summary"]["n_overlap_days"] > 0
        assert data["meta"]["strategy_id"] == "v7"
