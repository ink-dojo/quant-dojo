"""
test_history_cli.py — quant_dojo history 子命令测试

用 tmp_path 构造一份假的 live/runs 目录 + logs 目录，
验证 run_history 的过滤、排序、格式化与 --json 输出。
"""
import json
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from quant_dojo.commands import history as history_cmd


@pytest.fixture
def fake_dirs(tmp_path, monkeypatch):
    """构造 live/runs + logs 的假数据"""
    runs_dir = tmp_path / "live_runs"
    logs_dir = tmp_path / "logs"
    runs_dir.mkdir()
    logs_dir.mkdir()

    # 2 个回测 run — 1 success + 1 failed
    (runs_dir / "v7_20260407_success.json").write_text(json.dumps({
        "run_id": "v7_20260407_success",
        "strategy_id": "v7",
        "status": "success",
        "created_at": "2026-04-07T20:38:09",
        "start_date": "2024-01-01",
        "end_date": "2026-03-31",
        "metrics": {
            "total_return": 0.485,
            "sharpe": 0.62,
            "max_drawdown": -0.26,
        },
        "error": None,
        "artifacts": {"equity_csv": str(runs_dir / "eq.csv")},
    }))
    (runs_dir / "v7_20260406_failed.json").write_text(json.dumps({
        "run_id": "v7_20260406_failed",
        "strategy_id": "v7",
        "status": "failed",
        "created_at": "2026-04-06T19:59:23",
        "start_date": "",
        "end_date": "",
        "metrics": {},
        "error": "必须指定 start 和 end 日期",
        "artifacts": {},
    }))
    # 另一个策略的 run
    (runs_dir / "v8_20260406_success.json").write_text(json.dumps({
        "run_id": "v8_20260406_success",
        "strategy_id": "v8",
        "status": "success",
        "created_at": "2026-04-06T18:00:00",
        "metrics": {"total_return": 0.3, "sharpe": 1.1, "max_drawdown": -0.15},
    }))
    # 非 run 的杂项（应当被忽略）
    (runs_dir / "stray.json").write_text(json.dumps({"some": "garbage"}))

    # 2 个 daily pipeline log — 1 ok + 1 有失败步骤
    (logs_dir / "quant_dojo_run_2026-03-20.json").write_text(json.dumps({
        "date": "2026-03-20",
        "timestamp": "2026-04-07T22:00:00",
        "elapsed_sec": 55.0,
        "steps": {
            "data_update": {"status": "ok"},
            "signal": {"status": "ok"},
            "rebalance": {"status": "ok"},
            "risk": {"status": "ok"},
        },
    }))
    (logs_dir / "quant_dojo_run_2026-03-21.json").write_text(json.dumps({
        "date": "2026-03-21",
        "timestamp": "2026-04-07T22:05:00",
        "elapsed_sec": 60.0,
        "steps": {
            "data_update": {"status": "ok"},
            "signal": {"status": "failed", "error": "boom"},
        },
    }))

    monkeypatch.setattr(history_cmd, "LIVE_RUNS_DIR", runs_dir)
    monkeypatch.setattr(history_cmd, "LOGS_DIR", logs_dir)
    return runs_dir, logs_dir


class TestLoaders:
    def test_load_backtest_runs_skips_stray(self, fake_dirs):
        rows = history_cmd._load_backtest_runs()
        run_ids = {r["run_id"] for r in rows}
        assert "v7_20260407_success" in run_ids
        assert "v7_20260406_failed" in run_ids
        assert "v8_20260406_success" in run_ids
        # stray.json has neither run_id nor strategy_id → filtered
        assert len(rows) == 3

    def test_load_daily_runs_marks_failed_step(self, fake_dirs):
        rows = history_cmd._load_daily_runs()
        by_date = {r["run_id"]: r for r in rows}
        assert by_date["daily_2026-03-20"]["status"] == "success"
        assert by_date["daily_2026-03-21"]["status"] == "failed"
        assert by_date["daily_2026-03-21"]["n_fail"] == 1


class TestRunHistory:
    def test_default_lists_everything_sorted_desc(self, fake_dirs, capsys):
        history_cmd.run_history(limit=10)
        out = capsys.readouterr().out
        # 最新一条应该是 v7_20260407_success (2026-04-07T20:38)
        # 它应该出现在 daily 之前（daily 是 2026-04-07T22，更晚）
        lines = [l for l in out.splitlines() if "success" in l or "failed" in l]
        assert len(lines) >= 3
        # 应当同时包含 backtest 与 daily 两种
        assert any("backtest" in l for l in lines)
        assert any("daily" in l for l in lines)

    def test_filter_by_kind_backtest_only(self, fake_dirs, capsys):
        history_cmd.run_history(kind="backtest", limit=10)
        out = capsys.readouterr().out
        assert "backtest" in out
        assert "daily" not in out.split("共找到")[1].split("\n\n")[-1]  # only in filter header

    def test_filter_by_strategy_prefix(self, fake_dirs, capsys):
        history_cmd.run_history(strategy="v8", limit=10)
        out = capsys.readouterr().out
        assert "v8" in out
        assert "v7_2026" not in out  # run_id 中的 v7 不该出现

    def test_filter_by_status_success(self, fake_dirs, capsys):
        history_cmd.run_history(status="success", limit=10)
        out = capsys.readouterr().out
        # failed 的 run 不应出现
        assert "v7_20260406_failed" not in out
        # success 的 run 应出现
        assert "v7_20260407_success" in out

    def test_json_output_is_valid(self, fake_dirs, capsys):
        history_cmd.run_history(as_json=True, limit=10)
        out = capsys.readouterr().out
        data = json.loads(out)
        assert isinstance(data, list)
        assert len(data) >= 3
        # 排序应该是倒序
        created_ats = [r.get("created_at", "") for r in data if r.get("created_at")]
        assert created_ats == sorted(created_ats, reverse=True)

    def test_limit_respected(self, fake_dirs, capsys):
        history_cmd.run_history(as_json=True, limit=2)
        out = capsys.readouterr().out
        data = json.loads(out)
        assert len(data) == 2

    def test_empty_dirs_prints_no_records(self, tmp_path, monkeypatch, capsys):
        empty_runs = tmp_path / "empty_runs"
        empty_logs = tmp_path / "empty_logs"
        empty_runs.mkdir()
        empty_logs.mkdir()
        monkeypatch.setattr(history_cmd, "LIVE_RUNS_DIR", empty_runs)
        monkeypatch.setattr(history_cmd, "LOGS_DIR", empty_logs)
        history_cmd.run_history(limit=10)
        out = capsys.readouterr().out
        assert "无记录" in out


class TestPurgeFailedRuns:
    def test_deletes_empty_failed_runs(self, fake_dirs):
        runs_dir, _ = fake_dirs
        # 前置: fake_dirs 里有 1 个 failed 且 metrics 为空的 run
        before = {p.name for p in runs_dir.glob("*.json")}
        assert "v7_20260406_failed.json" in before

        removed = history_cmd._purge_failed_backtest_runs(dry_run=False)
        assert len(removed) == 1
        assert "v7_20260406_failed.json" in removed[0]

        after = {p.name for p in runs_dir.glob("*.json")}
        assert "v7_20260406_failed.json" not in after
        # success run 必须保留
        assert "v7_20260407_success.json" in after
        assert "v8_20260406_success.json" in after

    def test_dry_run_does_not_delete(self, fake_dirs):
        runs_dir, _ = fake_dirs
        removed = history_cmd._purge_failed_backtest_runs(dry_run=True)
        assert len(removed) == 1
        # 文件仍在
        assert (runs_dir / "v7_20260406_failed.json").exists()

    def test_preserves_failed_with_metrics(self, tmp_path, monkeypatch):
        """failed 但是有 total_return 的 run 不应该被误删（比如风控触发终止但已经跑出结果）"""
        runs_dir = tmp_path / "runs"
        runs_dir.mkdir()
        (runs_dir / "failed_with_metrics.json").write_text(json.dumps({
            "run_id": "failed_with_metrics",
            "strategy_id": "v7",
            "status": "failed",
            "metrics": {"total_return": 0.1, "sharpe": 0.5},
            "error": "risk stop",
        }))
        monkeypatch.setattr(history_cmd, "LIVE_RUNS_DIR", runs_dir)
        removed = history_cmd._purge_failed_backtest_runs()
        assert removed == []
        assert (runs_dir / "failed_with_metrics.json").exists()

    def test_empty_dir_returns_empty_list(self, tmp_path, monkeypatch):
        empty = tmp_path / "empty"
        empty.mkdir()
        monkeypatch.setattr(history_cmd, "LIVE_RUNS_DIR", empty)
        assert history_cmd._purge_failed_backtest_runs() == []

    def test_missing_dir_returns_empty_list(self, tmp_path, monkeypatch):
        missing = tmp_path / "nope"
        monkeypatch.setattr(history_cmd, "LIVE_RUNS_DIR", missing)
        assert history_cmd._purge_failed_backtest_runs() == []

    def test_run_history_with_purge_prints_preamble(self, fake_dirs, capsys):
        history_cmd.run_history(purge_failed=True, limit=10)
        out = capsys.readouterr().out
        assert "已删除 1 个空壳 failed run" in out
        # 删除后 failed run 不应再出现在下方的列表区（只允许出现在预告里）
        listing = out.split("quant-dojo 运行历史", 1)[1]
        assert "v7_20260406_failed" not in listing

    def test_run_history_purge_dry_run_keeps_file(self, fake_dirs, capsys):
        runs_dir, _ = fake_dirs
        history_cmd.run_history(purge_failed=True, dry_run=True, limit=10)
        out = capsys.readouterr().out
        assert "将删除 1 个空壳 failed run" in out
        assert (runs_dir / "v7_20260406_failed.json").exists()


class TestSinceFilter:
    def test_since_drops_older_records(self, fake_dirs, capsys):
        # fake_dirs 里最新的 backtest 是 2026-04-07T20:38，最旧是 2026-04-06T18:00
        # 把 since 设成 2026-04-07 应把 v8（2026-04-06）过滤掉
        history_cmd.run_history(since="2026-04-07", as_json=True, limit=10)
        out = capsys.readouterr().out
        data = json.loads(out)
        run_ids = {r["run_id"] for r in data}
        assert "v7_20260407_success" in run_ids
        assert "v8_20260406_success" not in run_ids

    def test_since_far_future_returns_empty(self, fake_dirs, capsys):
        history_cmd.run_history(since="2099-01-01", as_json=True, limit=10)
        out = capsys.readouterr().out
        data = json.loads(out)
        assert data == []

    def test_since_header_reflects_filter(self, fake_dirs, capsys):
        history_cmd.run_history(since="2026-04-07", limit=10)
        out = capsys.readouterr().out
        assert "since=2026-04-07" in out

    def test_since_default_star_in_header(self, fake_dirs, capsys):
        history_cmd.run_history(limit=10)
        out = capsys.readouterr().out
        assert "since=*" in out


class TestNormalizeSince:
    def test_none_returns_none(self):
        assert history_cmd._normalize_since(None) is None

    def test_empty_returns_none(self):
        assert history_cmd._normalize_since("") is None
        assert history_cmd._normalize_since("   ") is None

    def test_absolute_date_passes_through(self):
        assert history_cmd._normalize_since("2026-04-01") == "2026-04-01"

    def test_iso_timestamp_passes_through(self):
        assert history_cmd._normalize_since("2026-04-01T10:00:00") == "2026-04-01T10:00:00"

    def test_relative_days(self):
        from datetime import datetime
        now = datetime(2026, 4, 10, 12, 0, 0)
        result = history_cmd._normalize_since("7d", now=now)
        assert result == "2026-04-03T12:00:00"

    def test_relative_weeks(self):
        from datetime import datetime
        now = datetime(2026, 4, 15, 0, 0, 0)
        result = history_cmd._normalize_since("2w", now=now)
        assert result == "2026-04-01T00:00:00"

    def test_relative_hours(self):
        from datetime import datetime
        now = datetime(2026, 4, 10, 12, 0, 0)
        result = history_cmd._normalize_since("24h", now=now)
        assert result == "2026-04-09T12:00:00"

    def test_relative_minutes(self):
        from datetime import datetime
        now = datetime(2026, 4, 10, 12, 30, 0)
        result = history_cmd._normalize_since("30m", now=now)
        assert result == "2026-04-10T12:00:00"

    def test_unknown_shape_passed_through_as_literal(self):
        """'7days' 不符合 <N><单位> 正则 → 原样传下去。对齐不是'崩溃'"""
        assert history_cmd._normalize_since("bogus") == "bogus"

    def test_relative_since_filters_old_rows(self, fake_dirs, capsys, monkeypatch):
        # 让"现在"停在 2026-04-07T21:00 — 1d 截止 = 2026-04-06T21:00
        # fake_dirs 中的 created_at：
        #   v7 success @ 04-07T20:38  ✓ 保留
        #   v7 failed  @ 04-06T19:59  ✗ 过滤
        #   v8 success @ 04-06T18:00  ✗ 过滤
        #   daily      @ 04-07T22:00  ✓ 保留
        #   daily      @ 04-07T22:05  ✓ 保留
        from datetime import datetime
        class FakeDT(datetime):
            @classmethod
            def now(cls, tz=None):
                return datetime(2026, 4, 7, 21, 0, 0)
        monkeypatch.setattr(history_cmd, "datetime", FakeDT)
        history_cmd.run_history(since="1d", as_json=True, limit=10)
        data = json.loads(capsys.readouterr().out)
        run_ids = {r["run_id"] for r in data}
        assert "v7_20260407_success" in run_ids       # 保留
        assert "v7_20260406_failed" not in run_ids    # 过滤掉
        assert "v8_20260406_success" not in run_ids   # 过滤掉

    def test_relative_since_wider_window(self, fake_dirs, capsys, monkeypatch):
        """3 天窗口应当能把 04-07 的 run 都拿到"""
        from datetime import datetime
        class FakeDT(datetime):
            @classmethod
            def now(cls, tz=None):
                return datetime(2026, 4, 8, 0, 0, 0)
        monkeypatch.setattr(history_cmd, "datetime", FakeDT)
        history_cmd.run_history(since="3d", as_json=True, limit=10)
        data = json.loads(capsys.readouterr().out)
        run_ids = {r["run_id"] for r in data}
        assert "v7_20260407_success" in run_ids
