"""Tests for scripts/paper_trade_daily.py and paper_trade_monthly_review.py.

End-to-end: generate signal → trader → kill-switch → report files land on disk.
"""
from __future__ import annotations

import shutil
import tempfile
from pathlib import Path

import pandas as pd
import pytest

from live.event_kill_switch import KillAction
from live.event_paper_trader import EventPaperTrader
from pipeline.event_signal import (
    BB_UNIT_WEIGHT,
    EventEntry,
    PV_UNIT_WEIGHT,
)
from scripts.paper_trade_daily import (
    _build_prices_dict,
    _write_daily_report,
    _write_orders_csv,
    _push_alert,
)


@pytest.fixture
def tmp_pt_dir():
    d = Path(tempfile.mkdtemp(prefix="pt_test_"))
    yield d
    shutil.rmtree(d, ignore_errors=True)


def test_build_prices_dict_filters_nans(tmp_pt_dir):
    idx = pd.DatetimeIndex(["2025-06-16"])
    df = pd.DataFrame({"600000": [10.0], "600001": [pd.NA], "600002": [0.0]},
                      index=idx, dtype="object")
    # Cast columns to numeric to match real data path
    for c in df.columns:
        df[c] = pd.to_numeric(df[c], errors="coerce")
    prices = _build_prices_dict(df, pd.Timestamp("2025-06-16"))
    assert prices == {"600000": 10.0}


def test_orders_csv_records_today_trades(tmp_pt_dir):
    trader = EventPaperTrader(1_000_000, tmp_pt_dir)
    entry = EventEntry(
        symbol="600000", leg="bb",
        event_date="2025-06-13", entry_date="2025-06-16",
        exit_date="2025-07-14",
        unit_weight=BB_UNIT_WEIGHT, signal=5.0, threshold=3.0,
    )
    trader.process_day("2025-06-16", [entry], {"600000": 10.0})

    orders_path = tmp_pt_dir / "orders.csv"
    _write_orders_csv(orders_path, trader, pd.Timestamp("2025-06-16"),
                      summary={"n_buys": 1, "n_sells": 0})
    assert orders_path.exists()

    import csv
    with open(orders_path) as f:
        rows = list(csv.DictReader(f))
    assert len(rows) == 1
    assert rows[0]["symbol"] == "600000"
    assert rows[0]["action"] == "buy"
    assert rows[0]["reason"] == "entry"
    trader.close()


def test_daily_report_markdown(tmp_pt_dir):
    trader = EventPaperTrader(1_000_000, tmp_pt_dir)
    entry = EventEntry(
        symbol="600000", leg="bb",
        event_date="2025-06-13", entry_date="2025-06-16",
        exit_date="2025-07-14",
        unit_weight=BB_UNIT_WEIGHT, signal=5.0, threshold=3.0,
    )
    summary = trader.process_day("2025-06-16", [entry], {"600000": 10.0})

    from live.event_kill_switch import evaluate
    kill = evaluate(trader.nav_series(), as_of=pd.Timestamp("2025-06-16"))

    report_path = tmp_pt_dir / "daily_report.md"
    _write_daily_report(report_path, pd.Timestamp("2025-06-16"),
                        summary, kill, trader)
    text = report_path.read_text(encoding="utf-8")
    assert "Paper-Trade Daily Report" in text
    assert "2025-06-16" in text
    assert "NAV" in text
    assert "Kill switch" in text
    assert "600000" in text  # position is reported
    trader.close()


def test_alert_is_silent_on_ok(tmp_pt_dir):
    from live.event_kill_switch import KillReport, KillAction
    kill = KillReport(as_of="2025-06-16", action=KillAction.OK)
    alerts_path = tmp_pt_dir / "alerts.log"
    _push_alert(kill, alerts_path)
    # No file written on OK action
    assert not alerts_path.exists()


def test_alert_writes_on_halt(tmp_pt_dir, capsys):
    from live.event_kill_switch import KillReport, KillAction
    kill = KillReport(
        as_of="2025-06-16", action=KillAction.HALT,
        reasons=["累计回撤 25.00% > 20%"],
    )
    alerts_path = tmp_pt_dir / "alerts.log"
    _push_alert(kill, alerts_path)
    assert alerts_path.exists()
    text = alerts_path.read_text(encoding="utf-8")
    assert "HALT" in text
    assert "累计回撤" in text
    captured = capsys.readouterr()
    assert "ALERT" in captured.err


def test_monthly_review_on_empty_portfolio(tmp_pt_dir):
    from scripts.paper_trade_monthly_review import run_review
    review = run_review("2025-06", portfolio_dir=tmp_pt_dir)
    # No data yet — expect a "note" field rather than stats
    assert "note" in review or review.get("stats", {}).get("n_days", 0) == 0
