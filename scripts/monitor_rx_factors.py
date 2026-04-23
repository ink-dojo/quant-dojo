"""
monitor_rx_factors.py — CLI: 跑 RX 因子监控并生成 journal + JSON

Usage:
    python scripts/monitor_rx_factors.py                   # 默认 window 252 + 60 双窗口
    python scripts/monitor_rx_factors.py --window 90       # 仅最近 90 日
    python scripts/monitor_rx_factors.py --end 2025-12-31  # end date 定点

输出:
    journal/rx_factor_health_YYYYMMDD.md — 人读报告
    logs/rx_factor_health_YYYYMMDD.json   — 机器可读
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from pipeline.rx_factor_monitor import RX_REGISTRY, rx_factor_health_report  # noqa: E402


STATUS_EMOJI = {
    "healthy": "✅",
    "degraded": "⚠️",
    "dead": "❌",
    "insufficient_data": "⏳",
    "no_data": "—",
}


def fmt_n(v, pat="{:+.4f}"):
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return "n/a"
    return pat.format(v)


def build_markdown(reports: dict[str, dict], run_at: str) -> str:
    """reports: {window_label: report_dict}."""
    lines = [
        f"# RX 因子健康度周报 — {run_at[:10]}",
        "",
        "> 覆盖 Issue #33/#35/#36 轨道的 6 个差异化因子, 按窗口对比 IC/ICIR 稳定性.",
        "> 门槛: |IC|>0.03 ✅ healthy | |IC|∈[0.02,0.03] 且 |HAC t|≥2 ⚠️ degraded | 其余 ❌ dead",
        "",
    ]

    # 总览表
    lines.append("## 因子健康度对比")
    lines.append("")
    header = ["因子", "Display"]
    for win in reports:
        header += [f"{win} IC", f"{win} HAC t", f"{win} 状态"]
    lines.append("| " + " | ".join(header) + " |")
    lines.append("|" + "|".join(["---"] * len(header)) + "|")

    first_win = list(reports.keys())[0]
    for name in reports[first_win]:
        row = [name]
        row.append(reports[first_win][name].get("display", ""))
        for win, rep in reports.items():
            r = rep.get(name, {})
            ic = fmt_n(r.get("rolling_ic"), "{:+.4f}")
            t = fmt_n(r.get("t_hac"), "{:+.2f}")
            st = r.get("status", "-")
            badge = f"{STATUS_EMOJI.get(st, '?')} {st}"
            row += [ic, t, badge]
        lines.append("| " + " | ".join(str(x) for x in row) + " |")

    lines.append("")
    lines.append("## 各因子详情")
    for name, r in reports[first_win].items():
        lines.append("")
        lines.append(f"### {name} — {r.get('display', '')}")
        lines.append("")
        lines.append(f"- Sign (研究期望方向): `{r.get('sign', 'n/a')}`")
        lines.append(f"- Fwd days: `{r.get('fwd_days', 'n/a')}`")
        lines.append(f"- Earliest start: `{r.get('earliest_start', 'n/a')}`")
        lines.append(f"- Tags: {', '.join(r.get('tags', []))}")
        if r.get("notes"):
            lines.append(f"- Notes: {r['notes']}")
        # 每窗口数字
        lines.append("")
        lines.append("| 窗口 | n | IC | ICIR | HAC t | Status |")
        lines.append("|---|---:|---:|---:|---:|---|")
        for win, rep in reports.items():
            rr = rep.get(name, {})
            lines.append(
                f"| {win} | {rr.get('n_obs', 0)} | "
                f"{fmt_n(rr.get('rolling_ic'), '{:+.4f}')} | "
                f"{fmt_n(rr.get('icir'), '{:+.3f}')} | "
                f"{fmt_n(rr.get('t_hac'), '{:+.2f}')} | "
                f"{STATUS_EMOJI.get(rr.get('status', ''), '?')} {rr.get('status', '')} |"
            )

    lines.append("")
    lines.append("## 判读建议")
    lines.append("")
    # 状态变化
    if len(reports) >= 2:
        wins = list(reports.keys())
        recent, older = wins[0], wins[-1]
        changes = []
        for name in reports[recent]:
            r_old = reports[older].get(name, {}).get("status", "-")
            r_new = reports[recent].get(name, {}).get("status", "-")
            if r_old != r_new:
                changes.append((name, r_old, r_new))
        if changes:
            lines.append(f"### 状态变化 ({older} → {recent})")
            lines.append("")
            for name, old, new in changes:
                lines.append(f"- **{name}**: `{old}` → `{new}`")
            lines.append("")

    # healthy 清单
    healthy = [n for n, r in reports[first_win].items() if r.get("status") == "healthy"]
    if healthy:
        lines.append(f"### 仍 healthy 的因子 ({len(healthy)})")
        lines.append("")
        for n in healthy:
            r = reports[first_win][n]
            lines.append(f"- **{n}**: IC={fmt_n(r.get('rolling_ic'), '{:+.4f}')}, HAC t={fmt_n(r.get('t_hac'), '{:+.2f}')}")
        lines.append("")

    lines.append(f"*Generated at {run_at}*")
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description="RX factor monitor CLI")
    parser.add_argument("--window", type=int, default=252, help="主窗口 (交易日)")
    parser.add_argument("--short-window", type=int, default=120, help="对照短窗口")
    parser.add_argument("--end", type=str, default=None, help="end date YYYY-MM-DD, 默认最新")
    parser.add_argument("--no-short", action="store_true", help="跳过短窗口, 只跑主窗口")
    args = parser.parse_args()

    print(f"=== RX factor monitor (window={args.window}, short={args.short_window}) ===\n")

    reports = {}
    key_main = f"window {args.window}d"
    print(f"[1/{1 if args.no_short else 2}] {key_main} ...")
    reports[key_main] = rx_factor_health_report(
        registry=RX_REGISTRY,
        window_days=args.window,
        end_date=args.end,
    )

    if not args.no_short:
        key_short = f"window {args.short_window}d"
        print(f"[2/2] {key_short} ...")
        reports[key_short] = rx_factor_health_report(
            registry=RX_REGISTRY,
            window_days=args.short_window,
            end_date=args.end,
        )

    # 控制台汇总
    print("\n=== 汇总 ===\n")
    header = f"{'Factor':<12} "
    for win in reports:
        header += f"{'IC ' + win[-8:]:<14} {'t ' + win[-8:]:<11} {'status':<10} "
    print(header)
    print("-" * len(header))
    for name in reports[list(reports.keys())[0]]:
        row = f"{name:<12} "
        for win, rep in reports.items():
            r = rep.get(name, {})
            ic = fmt_n(r.get("rolling_ic"), "{:+.4f}")
            t = fmt_n(r.get("t_hac"), "{:+.2f}")
            st = r.get("status", "-")
            row += f"{ic:<14} {t:<11} {st:<10} "
        print(row)

    # 保存 markdown + JSON
    run_at = datetime.now().isoformat(timespec="seconds")
    stamp = datetime.now().strftime("%Y%m%d")
    md = build_markdown(reports, run_at)
    md_path = ROOT / "journal" / f"rx_factor_health_{stamp}.md"
    md_path.write_text(md)
    print(f"\n保存 markdown: {md_path}")

    json_path = ROOT / "logs" / f"rx_factor_health_{stamp}.json"
    json_path.write_text(json.dumps({
        "generated_at": run_at,
        "window_days": args.window,
        "short_window_days": args.short_window if not args.no_short else None,
        "reports": reports,
    }, indent=2, ensure_ascii=False, default=str))
    print(f"保存 JSON: {json_path}")


if __name__ == "__main__":
    main()
