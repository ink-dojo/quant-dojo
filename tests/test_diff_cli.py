"""
test_diff_cli.py — quant_dojo diff 子命令测试

覆盖：
  1. _resolve_run_path 能处理 run_id / 完整路径 / 自动取最新
  2. 自动取最新时会跳过没有 equity_csv 的 run
  3. run_diff 端到端，给出一个最小合成的 live nav + 回测 equity csv，
     在正常路径下输出 summary，--json 模式返回 JSON
"""
import json
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

PROJECT_ROOT = Path(__file__).parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from quant_dojo.commands import diff as diff_cmd


def _write_live_nav(path: Path, rows: list[tuple[str, float]]):
    lines = ["date,nav"]
    for d, n in rows:
        lines.append(f"{d},{n}")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _write_equity_csv(path: Path, rows: list[tuple[str, float]]):
    lines = ["date,cumulative_return"]
    for d, r in rows:
        lines.append(f"{d},{r}")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _write_run_json(path: Path, run_id: str, equity_csv: str | None, strategy="v7"):
    data = {
        "run_id": run_id,
        "strategy_id": strategy,
        "artifacts": {"equity_csv": equity_csv} if equity_csv else {},
    }
    path.write_text(json.dumps(data), encoding="utf-8")


class TestResolveRunPath:
    def test_resolves_explicit_path(self, tmp_path):
        run = tmp_path / "some_run.json"
        _write_run_json(run, "some_run", str(tmp_path / "eq.csv"))
        resolved = diff_cmd._resolve_run_path(str(run), None)
        assert resolved == run

    def test_resolves_run_id_from_live_runs_dir(self, tmp_path, monkeypatch):
        runs_dir = tmp_path / "runs"
        runs_dir.mkdir()
        run = runs_dir / "v7_abc.json"
        _write_run_json(run, "v7_abc", str(tmp_path / "eq.csv"))
        monkeypatch.setattr(diff_cmd, "LIVE_RUNS_DIR", runs_dir)
        resolved = diff_cmd._resolve_run_path("v7_abc", None)
        assert resolved == run

    def test_auto_picks_latest_run_with_equity_csv(self, tmp_path, monkeypatch):
        runs_dir = tmp_path / "runs"
        runs_dir.mkdir()
        # 最新 run 没有 equity_csv → 必须跳过
        newest = runs_dir / "v7_new.json"
        _write_run_json(newest, "v7_new", None)
        older = runs_dir / "v7_old.json"
        _write_run_json(older, "v7_old", str(tmp_path / "eq.csv"))

        # 确保 newer mtime
        import os
        import time
        os.utime(older, (time.time() - 100, time.time() - 100))
        os.utime(newest, None)

        monkeypatch.setattr(diff_cmd, "LIVE_RUNS_DIR", runs_dir)
        resolved = diff_cmd._resolve_run_path(None, "v7")
        assert resolved == older

    def test_returns_none_when_no_runs(self, tmp_path, monkeypatch):
        runs_dir = tmp_path / "runs"
        runs_dir.mkdir()
        monkeypatch.setattr(diff_cmd, "LIVE_RUNS_DIR", runs_dir)
        assert diff_cmd._resolve_run_path(None, None) is None


class TestRunDiffEndToEnd:
    @pytest.fixture
    def setup(self, tmp_path):
        eq_csv = tmp_path / "eq.csv"
        _write_equity_csv(eq_csv, [
            ("2026-03-20", 0.00),
            ("2026-03-21", 0.01),
            ("2026-03-24", 0.015),
        ])
        run_path = tmp_path / "run.json"
        _write_run_json(run_path, "v7_test", str(eq_csv))
        nav_path = tmp_path / "nav.csv"
        _write_live_nav(nav_path, [
            ("2026-03-20", 1_000_000.0),
            ("2026-03-21", 1_005_000.0),
            ("2026-03-24", 1_020_000.0),
        ])
        return run_path, nav_path

    def test_run_diff_text_mode(self, setup, capsys):
        run_path, nav_path = setup
        diff_cmd.run_diff(run=str(run_path), live_nav=str(nav_path))
        out = capsys.readouterr().out
        assert "quant-dojo 实盘 vs 回测差异" in out
        assert "策略: v7" in out
        assert "共同交易日" not in out  # 表格标题不在 CLI 输出里
        assert "累计偏差" in out
        assert "2026-03-20" in out

    def test_run_diff_json_mode(self, setup, capsys):
        run_path, nav_path = setup
        diff_cmd.run_diff(run=str(run_path), live_nav=str(nav_path), as_json=True)
        out = capsys.readouterr().out
        # 应当是合法 JSON
        data = json.loads(out)
        assert data["n_overlap"] == 3
        assert "summary" in data
        assert "meta" in data
        assert data["meta"]["strategy_id"] == "v7"

    def test_run_diff_save_writes_markdown(self, setup, tmp_path, capsys):
        run_path, nav_path = setup
        out_path = tmp_path / "report.md"
        diff_cmd.run_diff(
            run=str(run_path), live_nav=str(nav_path), save=str(out_path)
        )
        assert out_path.exists()
        body = out_path.read_text(encoding="utf-8")
        assert "# 实盘 vs 回测对比" in body
        assert "v7_test" in body

    def test_run_diff_missing_run_exits(self, tmp_path, capsys):
        nav_path = tmp_path / "nav.csv"
        _write_live_nav(nav_path, [("2026-03-20", 1_000_000.0)])
        with pytest.raises(SystemExit) as exc_info:
            diff_cmd.run_diff(run="nonexistent_run", live_nav=str(nav_path))
        # _resolve_run_path 找不到 → exit 1
        assert exc_info.value.code == 1

    def test_run_diff_missing_live_nav_exits(self, setup):
        run_path, _ = setup
        with pytest.raises(SystemExit) as exc_info:
            diff_cmd.run_diff(run=str(run_path), live_nav="/nonexistent/nav.csv")
        assert exc_info.value.code == 1

    def test_run_diff_start_end_filter(self, setup, capsys):
        run_path, nav_path = setup
        # 只保留 2026-03-24 → 1 天 → compute_divergence 会正常返回 ok
        diff_cmd.run_diff(
            run=str(run_path), live_nav=str(nav_path),
            start="2026-03-24", end="2026-03-24",
        )
        out = capsys.readouterr().out
        assert "2026-03-24 ~ 2026-03-24" in out
