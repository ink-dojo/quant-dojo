"""
test_dashboard_trigger_router.py — POST /api/trigger/* 端点测试

覆盖 Phase 6 最后一项 dashboard 操作页的后端 trigger 路由。

策略：构造最小 FastAPI app 只挂载 trigger router，用 monkeypatch 替换
control_surface.execute，避免真的跑 rebalance / weekly_report。
"""
import sys
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

PROJECT_ROOT = Path(__file__).parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from dashboard.routers import trigger as trigger_router


@pytest.fixture
def client(monkeypatch):
    """挂载最小 app，并暴露一个可配置的 fake execute"""
    app = FastAPI()
    app.include_router(trigger_router.router, prefix="/api/trigger")

    fake_calls = []

    def make_fake(return_value):
        def fake(command, approved=False, **kwargs):
            fake_calls.append({"command": command, "approved": approved, "kwargs": kwargs})
            return return_value
        return fake

    # 默认成功回包
    import pipeline.control_surface as cs
    monkeypatch.setattr(cs, "execute", make_fake({
        "status": "success",
        "data": {"ok": True},
    }))

    return TestClient(app), fake_calls, monkeypatch, make_fake


class TestRebalanceEndpoint:
    def test_rebalance_with_explicit_date(self, client):
        tc, calls, _, _ = client
        resp = tc.post("/api/trigger/rebalance", json={"date": "2026-04-07"})
        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "ok"
        assert body["command"] == "rebalance.run"
        assert body["data"] == {"ok": True}
        # 内部应当调用一次 execute，带 approved=True + date=2026-04-07
        assert len(calls) == 1
        call = calls[0]
        assert call["command"] == "rebalance.run"
        assert call["approved"] is True
        assert call["kwargs"] == {"date": "2026-04-07"}

    def test_rebalance_blank_date_defaults_to_today(self, client):
        tc, calls, _, _ = client
        resp = tc.post("/api/trigger/rebalance", json={"date": ""})
        assert resp.status_code == 200
        assert len(calls) == 1
        date_arg = calls[0]["kwargs"]["date"]
        # 格式 YYYY-MM-DD
        assert len(date_arg) == 10
        assert date_arg[4] == "-" and date_arg[7] == "-"

    def test_rebalance_error_maps_to_400(self, client, monkeypatch):
        tc, _, _, make_fake = client
        import pipeline.control_surface as cs
        monkeypatch.setattr(cs, "execute", make_fake({
            "status": "error",
            "error": "无法加载收盘价",
        }))
        resp = tc.post("/api/trigger/rebalance", json={"date": "2026-04-07"})
        assert resp.status_code == 400
        detail = resp.json()["detail"]
        assert detail["command"] == "rebalance.run"
        assert "无法加载收盘价" in detail["error"]

    def test_rebalance_without_approval_maps_to_403(self, client, monkeypatch):
        """
        如果 control_surface.execute 拒绝（requires_approval），
        虽然 router 已经传了 approved=True，但为了防御性我们仍要验证
        router 会把 requires_approval 转成 403。
        """
        tc, _, _, make_fake = client
        import pipeline.control_surface as cs
        monkeypatch.setattr(cs, "execute", make_fake({
            "status": "requires_approval",
            "message": "need approval",
        }))
        resp = tc.post("/api/trigger/rebalance", json={"date": "2026-04-07"})
        assert resp.status_code == 403


class TestWeeklyReportEndpoint:
    def test_weekly_report_with_explicit_week(self, client):
        tc, calls, _, _ = client
        resp = tc.post("/api/trigger/weekly-report", json={"week": "2026-W14"})
        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"
        assert calls[0]["command"] == "report.weekly"
        assert calls[0]["kwargs"] == {"week": "2026-W14"}

    def test_weekly_report_blank_week_omits_kwarg(self, client):
        """
        空字符串的 week 不应当作为 "" 透传到服务层，而应直接略过，
        让 control_surface 的默认逻辑（取当前周）生效。
        """
        tc, calls, _, _ = client
        resp = tc.post("/api/trigger/weekly-report", json={"week": ""})
        assert resp.status_code == 200
        assert "week" not in calls[0]["kwargs"]

    def test_weekly_report_error_maps_to_400(self, client, monkeypatch):
        tc, _, _, make_fake = client
        import pipeline.control_surface as cs
        monkeypatch.setattr(cs, "execute", make_fake({
            "status": "error",
            "error": "没有可用的 run 数据",
        }))
        resp = tc.post("/api/trigger/weekly-report", json={"week": "2026-W14"})
        assert resp.status_code == 400
        assert "没有可用的 run 数据" in resp.json()["detail"]["error"]
