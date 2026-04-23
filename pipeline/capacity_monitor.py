"""
pipeline/capacity_monitor.py — Tier 1.2 Capacity Monitoring

检查每个目标持仓的 ADV 占比，防止 scaling 时 slippage 失控。

slippage 模型 (Almgren-Chriss 简化):
    slippage_bps = 50 * (pct_of_adv) ^ 0.6
    例: 5% ADV → 9 bps; 10% ADV → 13 bps; 20% ADV → 20 bps

用法:
    reports = check_capacity(target_positions, aum=10_000_000)
    capped   = cap_positions_to_capacity(target_positions, reports)

CLI:
    python pipeline/capacity_monitor.py --strategy spec_v4 --aum 10000000
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
from dataclasses import dataclass, asdict
from datetime import date, datetime
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

log = logging.getLogger(__name__)

DAILY_BASIC_DIR = ROOT / "data" / "raw" / "tushare" / "daily_basic"
WARN_LOG_DIR = ROOT / "logs"
WARN_LOG_DIR.mkdir(parents=True, exist_ok=True)


# ══════════════════════════════════════════════════════════════
# 数据结构
# ══════════════════════════════════════════════════════════════

@dataclass
class CapacityReport:
    ts_code: str
    target_value_yuan: float
    adv_20d_yuan: float          # 20 日中位 ADV (元)
    pct_of_adv: float            # target_value / adv_20d
    estimated_slippage_bps: float
    flag: str                    # "ok" | "warn" | "blocked"


# ══════════════════════════════════════════════════════════════
# ADV 计算
# ══════════════════════════════════════════════════════════════

def _code_to_short(ts_code: str) -> str:
    """600557.SH → 600557"""
    return ts_code.split(".")[0]


def _load_adv(ts_code: str, lookback_days: int = 20) -> Optional[float]:
    """
    从 daily_basic 加载最近 lookback_days 个交易日的成交额，返回中位数 (元)。

    ADV = median(circ_mv × turnover_rate / 100 × 10000)
    circ_mv 单位: 万元; turnover_rate 单位: %
    → ADV 单位: 元

    Returns None if data unavailable.
    """
    short = _code_to_short(ts_code)
    path = DAILY_BASIC_DIR / f"{short}.parquet"
    if not path.exists():
        log.warning(f"[{ts_code}] daily_basic 文件不存在: {path}")
        return None

    df = pd.read_parquet(path, columns=["trade_date", "circ_mv", "turnover_rate"])
    df = df.sort_values("trade_date").tail(lookback_days)

    if df.empty:
        return None

    df = df.dropna(subset=["circ_mv", "turnover_rate"])
    if df.empty:
        return None

    adv_series = df["circ_mv"] * df["turnover_rate"] / 100 * 10000  # 元
    return float(adv_series.median())


# ══════════════════════════════════════════════════════════════
# slippage 模型
# ══════════════════════════════════════════════════════════════

def _slippage_bps(pct_of_adv: float) -> float:
    """Almgren-Chriss 简化: 50 × pct_of_adv^0.6 (bps)"""
    return 50.0 * (pct_of_adv ** 0.6)


# ══════════════════════════════════════════════════════════════
# 主函数
# ══════════════════════════════════════════════════════════════

def check_capacity(
    target_positions: dict[str, float],
    aum: float,
    adv_lookback_days: int = 20,
    warn_pct_of_adv: float = 0.05,
    block_pct_of_adv: float = 0.10,
) -> list[CapacityReport]:
    """
    对每个 target position 计算 ADV 占比和 slippage 估算。

    Args:
        target_positions : ts_code → 目标市值 (元)
        aum              : 当前总 AUM (元), 仅用于日志打印
        adv_lookback_days: 计算 ADV 用的回看交易日数
        warn_pct_of_adv  : 超过此占比 → warn
        block_pct_of_adv : 超过此占比 → blocked (应 cap 到 warn 水平)

    Returns:
        按 pct_of_adv 降序的 CapacityReport 列表
    """
    reports: list[CapacityReport] = []

    for ts_code, target_value in target_positions.items():
        adv = _load_adv(ts_code, adv_lookback_days)

        if adv is None or adv <= 0:
            log.warning(f"[{ts_code}] ADV 无法计算, 跳过 capacity check")
            reports.append(CapacityReport(
                ts_code=ts_code,
                target_value_yuan=target_value,
                adv_20d_yuan=0.0,
                pct_of_adv=float("nan"),
                estimated_slippage_bps=float("nan"),
                flag="unknown",
            ))
            continue

        pct = target_value / adv
        slip = _slippage_bps(pct)

        if pct > block_pct_of_adv:
            flag = "blocked"
        elif pct > warn_pct_of_adv:
            flag = "warn"
        else:
            flag = "ok"

        reports.append(CapacityReport(
            ts_code=ts_code,
            target_value_yuan=target_value,
            adv_20d_yuan=adv,
            pct_of_adv=pct,
            estimated_slippage_bps=slip,
            flag=flag,
        ))

    reports.sort(key=lambda r: r.pct_of_adv if not np.isnan(r.pct_of_adv) else -1, reverse=True)

    n_blocked = sum(1 for r in reports if r.flag == "blocked")
    n_warn = sum(1 for r in reports if r.flag == "warn")
    log.info(
        f"capacity check: {len(reports)} positions, AUM={aum/1e4:.0f}万, "
        f"blocked={n_blocked}, warn={n_warn}"
    )

    return reports


def cap_positions_to_capacity(
    target_positions: dict[str, float],
    capacity_reports: list[CapacityReport],
    cap_pct_of_adv: float = 0.05,
) -> dict[str, float]:
    """
    对 flag=blocked 的 position 缩到 cap_pct_of_adv × ADV。

    Args:
        target_positions : 原始持仓 (ts_code → 市值元)
        capacity_reports : check_capacity 返回的 CapacityReport 列表
        cap_pct_of_adv   : blocked 仓位缩到此比例 (默认 5%)

    Returns:
        新持仓 dict，blocked 的仓位已缩减，其余不变
    """
    report_map = {r.ts_code: r for r in capacity_reports}
    capped: dict[str, float] = {}

    for ts_code, value in target_positions.items():
        r = report_map.get(ts_code)
        if r is None or r.flag != "blocked" or r.adv_20d_yuan <= 0:
            capped[ts_code] = value
        else:
            new_value = r.adv_20d_yuan * cap_pct_of_adv
            log.warning(
                f"[{ts_code}] cap: {value/1e4:.1f}万 → {new_value/1e4:.1f}万 "
                f"(pct_of_adv {r.pct_of_adv:.1%} → {cap_pct_of_adv:.1%})"
            )
            capped[ts_code] = new_value

    return capped


def write_capacity_warnings(
    reports: list[CapacityReport],
    aum: float,
    out_path: Optional[Path] = None,
) -> None:
    """
    把 flag != ok 的 position 写到 logs/capacity_warnings_YYYYMMDD.json。
    """
    non_ok = [r for r in reports if r.flag not in ("ok",)]
    if not non_ok:
        return

    if out_path is None:
        today = date.today().strftime("%Y%m%d")
        out_path = WARN_LOG_DIR / f"capacity_warnings_{today}.json"

    payload = {
        "generated_at": datetime.now().isoformat(),
        "aum_yuan": aum,
        "warnings": [asdict(r) for r in non_ok],
    }
    out_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False))
    log.info(f"capacity warnings → {out_path} ({len(non_ok)} 条)")


# ══════════════════════════════════════════════════════════════
# CLI
# ══════════════════════════════════════════════════════════════

def _load_spec_v4_positions(aum: float) -> dict[str, float]:
    """从 live/portfolio 或 paper_trade 读取当前持仓 (demo fallback)."""
    state_path = ROOT / "live" / "strategy_state.json"
    if not state_path.exists():
        log.warning("strategy_state.json 不存在, 用 spec v4 demo 持仓 (600557)")
        return {"600557.SH": aum * 0.07}

    try:
        state = json.loads(state_path.read_text())
        positions = state.get("positions", [])
        if not positions:
            log.warning("strategy_state.json 里 positions 为空, 用 demo 持仓")
            return {"600557.SH": aum * 0.07}
        weights = {}
        for p in positions:
            sym = str(p["symbol"])
            w = float(p.get("weight", p.get("target_weight", 0.0)))
            if w > 0:
                weights[sym] = w * aum
        return weights
    except Exception as e:
        log.error(f"读取 strategy_state 失败: {e}")
        return {"600557.SH": aum * 0.07}


def main() -> None:
    ap = argparse.ArgumentParser(description="Tier 1.2 Capacity Monitor")
    ap.add_argument("--aum", type=float, default=10_000_000, help="总 AUM (元)")
    ap.add_argument("--strategy", type=str, default="spec_v4")
    ap.add_argument("--positions", type=str, default=None,
                    help='JSON dict: {"600557.SH": 500000, ...}')
    ap.add_argument("--warn-pct", type=float, default=0.05, help="warn 阈值")
    ap.add_argument("--block-pct", type=float, default=0.10, help="block 阈值")
    args = ap.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

    if args.positions:
        positions = json.loads(args.positions)
    else:
        positions = _load_spec_v4_positions(args.aum)

    if not positions:
        print("没有持仓可检查")
        return

    reports = check_capacity(
        positions,
        aum=args.aum,
        warn_pct_of_adv=args.warn_pct,
        block_pct_of_adv=args.block_pct,
    )

    write_capacity_warnings(reports, aum=args.aum)

    print(f"\n{'='*60}")
    print(f"Capacity Check — AUM: {args.aum/1e4:.0f}万 | Strategy: {args.strategy}")
    print(f"{'='*60}")
    print(f"{'ts_code':<14} {'目标市值(万)':<12} {'ADV_20d(万)':<12} {'pct_ADV':<10} {'slip_bps':<10} {'flag'}")
    print("-" * 70)

    for r in reports:
        adv_str = f"{r.adv_20d_yuan/1e4:.0f}" if r.adv_20d_yuan > 0 else "N/A"
        pct_str = f"{r.pct_of_adv:.2%}" if not np.isnan(r.pct_of_adv) else "N/A"
        slip_str = f"{r.estimated_slippage_bps:.1f}" if not np.isnan(r.estimated_slippage_bps) else "N/A"
        flag_icon = {"ok": "✅", "warn": "⚠️", "blocked": "🚫", "unknown": "❓"}.get(r.flag, r.flag)
        print(
            f"{r.ts_code:<14} {r.target_value_yuan/1e4:<12.1f} {adv_str:<12} "
            f"{pct_str:<10} {slip_str:<10} {flag_icon} {r.flag}"
        )

    blocked = [r for r in reports if r.flag == "blocked"]
    warn = [r for r in reports if r.flag == "warn"]
    print(f"\n总结: {len(reports)} 只 | ok: {len(reports)-len(blocked)-len(warn)} | "
          f"warn: {len(warn)} | blocked: {len(blocked)}")

    if blocked:
        print("\n=== Capped positions (blocked → 5% ADV) ===")
        capped = cap_positions_to_capacity(positions, reports)
        for ts_code in [r.ts_code for r in blocked]:
            orig = positions.get(ts_code, 0)
            new = capped.get(ts_code, 0)
            print(f"  {ts_code}: {orig/1e4:.1f}万 → {new/1e4:.1f}万 ({-100*(1-new/orig):.1f}% 削减)")


if __name__ == "__main__":
    main()
