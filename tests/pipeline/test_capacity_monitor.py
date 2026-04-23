"""
Tier 1.2 Capacity Monitor 单元测试.

用合成 ADV 数据验证 check_capacity / cap_positions_to_capacity / slippage 计算,
不依赖 SSD 数据.
"""
from __future__ import annotations

import math
import pytest
import pandas as pd
from pathlib import Path
from unittest.mock import patch

from pipeline.capacity_monitor import (
    CapacityReport,
    _slippage_bps,
    _load_adv,
    check_capacity,
    cap_positions_to_capacity,
    write_capacity_warnings,
)


# ─────────────────────────────────────────────────────────────
# slippage 模型
# ─────────────────────────────────────────────────────────────

def test_slippage_formula_examples():
    """50 × x^0.6 对标参考值."""
    assert _slippage_bps(0.05) == pytest.approx(50 * 0.05 ** 0.6, rel=1e-6)
    assert _slippage_bps(0.10) == pytest.approx(50 * 0.10 ** 0.6, rel=1e-6)
    assert _slippage_bps(0.20) == pytest.approx(50 * 0.20 ** 0.6, rel=1e-6)


def test_slippage_monotone_increasing():
    pcts = [0.01, 0.05, 0.10, 0.20, 0.50]
    slips = [_slippage_bps(p) for p in pcts]
    assert slips == sorted(slips)


def test_slippage_5pct_approx_8to9bps():
    """spec 文档说 5% ADV ≈ 9 bps (四舍五入); 实际公式给 8.29 bps."""
    result = _slippage_bps(0.05)
    assert 8.0 < result < 9.5, f"5% ADV slippage={result:.2f}, 预期 8~9.5 bps"


# ─────────────────────────────────────────────────────────────
# check_capacity — mock _load_adv
# ─────────────────────────────────────────────────────────────

def _mock_adv(ts_code: str, lookback_days: int = 20) -> float | None:
    """合成 ADV: 000001→5亿, 000002→1亿, 000003→None (数据缺失)"""
    adv_map = {"000001.SZ": 5e8, "000002.SZ": 1e8}
    return adv_map.get(ts_code)


@pytest.fixture
def patched_check(monkeypatch):
    monkeypatch.setattr("pipeline.capacity_monitor._load_adv", _mock_adv)
    return check_capacity


def test_flag_ok(patched_check):
    """目标市值 2000万 / ADV 5亿 = 4% < 5% → ok"""
    positions = {"000001.SZ": 2_000_0000}  # 2000万
    reports = patched_check(positions, aum=1e8)
    assert len(reports) == 1
    r = reports[0]
    assert r.flag == "ok"
    assert r.pct_of_adv == pytest.approx(0.04, rel=1e-4)


def test_flag_warn(patched_check):
    """目标市值 6000万 / ADV 5亿 = 12% > 10% → blocked (跨过 warn)"""
    # 先测 warn: 3000万 / 5亿 = 6% ∈ (5%, 10%)
    positions = {"000001.SZ": 3_000_0000}  # 3000万
    reports = patched_check(positions, aum=1e8)
    assert reports[0].flag == "warn"


def test_flag_blocked(patched_check):
    """目标市值 8000万 / ADV 5亿 = 16% > 10% → blocked"""
    positions = {"000001.SZ": 8_000_0000}  # 8000万
    reports = patched_check(positions, aum=1e8)
    assert reports[0].flag == "blocked"


def test_missing_adv_returns_unknown(patched_check):
    """无 ADV 数据 → flag=unknown"""
    positions = {"000003.SZ": 1_000_0000}
    reports = patched_check(positions, aum=1e8)
    assert reports[0].flag == "unknown"
    assert math.isnan(reports[0].pct_of_adv)


def test_sorted_by_pct_of_adv_descending(patched_check):
    """结果应按 pct_of_adv 降序排列."""
    # 000002: 1500万 / 1亿 = 15% > 000001: 2000万 / 5亿 = 4%
    positions = {"000001.SZ": 2_000_0000, "000002.SZ": 1_500_0000}
    reports = patched_check(positions, aum=1e8)
    pcts = [r.pct_of_adv for r in reports if not math.isnan(r.pct_of_adv)]
    assert pcts == sorted(pcts, reverse=True)


def test_slippage_stored_in_report(patched_check):
    """report.estimated_slippage_bps 应与 _slippage_bps 一致."""
    positions = {"000001.SZ": 2_500_0000}  # 2500万 / 5亿 = 5%
    reports = patched_check(positions, aum=1e8)
    r = reports[0]
    assert r.estimated_slippage_bps == pytest.approx(_slippage_bps(r.pct_of_adv), rel=1e-6)


# ─────────────────────────────────────────────────────────────
# cap_positions_to_capacity
# ─────────────────────────────────────────────────────────────

def _make_report(ts_code, target_value, adv, pct, flag):
    slip = _slippage_bps(pct) if not math.isnan(pct) else float("nan")
    return CapacityReport(
        ts_code=ts_code,
        target_value_yuan=target_value,
        adv_20d_yuan=adv,
        pct_of_adv=pct,
        estimated_slippage_bps=slip,
        flag=flag,
    )


def test_cap_blocked_position():
    """blocked position 被缩到 5% ADV."""
    adv = 5e8
    positions = {"000001.SZ": 8_000_0000}
    reports = [_make_report("000001.SZ", 8_000_0000, adv, 0.16, "blocked")]
    capped = cap_positions_to_capacity(positions, reports)
    expected = adv * 0.05
    assert capped["000001.SZ"] == pytest.approx(expected, rel=1e-6)


def test_cap_leaves_ok_unchanged():
    """ok / warn position 不被修改."""
    positions = {"000001.SZ": 2_000_0000, "000002.SZ": 1_500_0000}
    reports = [
        _make_report("000001.SZ", 2_000_0000, 5e8, 0.04, "ok"),
        _make_report("000002.SZ", 1_500_0000, 1e8, 0.15, "warn"),
    ]
    capped = cap_positions_to_capacity(positions, reports)
    assert capped["000001.SZ"] == pytest.approx(2_000_0000)
    assert capped["000002.SZ"] == pytest.approx(1_500_0000)


def test_cap_preserves_all_keys():
    """所有 key 都保留, 只有 blocked 的值变化."""
    positions = {"A": 100, "B": 200, "C": 300}
    reports = [
        _make_report("A", 100, 1000, 0.10, "ok"),
        _make_report("B", 200, 1000, 0.20, "blocked"),
        _make_report("C", 300, 1000, 0.30, "blocked"),
    ]
    capped = cap_positions_to_capacity(positions, reports, cap_pct_of_adv=0.05)
    assert set(capped.keys()) == {"A", "B", "C"}
    assert capped["A"] == 100
    assert capped["B"] == pytest.approx(1000 * 0.05)
    assert capped["C"] == pytest.approx(1000 * 0.05)


# ─────────────────────────────────────────────────────────────
# write_capacity_warnings
# ─────────────────────────────────────────────────────────────

def test_write_warnings_creates_json(tmp_path):
    reports = [
        _make_report("000002.SZ", 1_500_0000, 1e8, 0.15, "warn"),
    ]
    out = tmp_path / "test_warnings.json"
    write_capacity_warnings(reports, aum=1e8, out_path=out)
    assert out.exists()
    import json
    data = json.loads(out.read_text())
    assert len(data["warnings"]) == 1
    assert data["warnings"][0]["ts_code"] == "000002.SZ"


def test_write_warnings_skips_ok(tmp_path):
    """全部 ok 时不创建文件."""
    reports = [_make_report("000001.SZ", 2_000_0000, 5e8, 0.04, "ok")]
    out = tmp_path / "should_not_exist.json"
    write_capacity_warnings(reports, aum=1e8, out_path=out)
    assert not out.exists()


# ─────────────────────────────────────────────────────────────
# _load_adv 集成测试 (需要 SSD 数据)
# ─────────────────────────────────────────────────────────────

@pytest.mark.integration
def test_load_adv_real_data():
    """000001.SZ 的 ADV 应 > 0 且合理 (A 股主板大盘股, 日均 > 1亿)."""
    adv = _load_adv("000001.SZ", lookback_days=20)
    assert adv is not None
    assert adv > 1e8, f"000001.SZ ADV {adv/1e8:.2f}亿 异常偏低"
    assert adv < 1e12, f"000001.SZ ADV {adv/1e8:.2f}亿 异常偏高"
