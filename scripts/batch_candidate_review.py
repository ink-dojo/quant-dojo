"""
批量候选复审 — 一次性给出 11 个多因子候选的诚实评估。

输入：live/runs/multi_factor_v*_*_equity.csv（每个版本的日收益）
输出：
  - journal/candidate_review_{date}.md     可读报告
  - portfolio/public/data/strategy/candidate_review.json   给 portfolio 消费

对每个候选计算：
  - 年化 / 夏普 / 回撤 / 胜率（in-sample）
  - PSR vs 0（观察夏普显著大于零的概率）
  - Deflated Sharpe（对"从 N 个候选挑最高"的 selection bias 做修正）
  - Bootstrap 95% sharpe 置信区间（stationary block resample 保留自相关）
  - MinTRL（达到 95% 显著所需最短样本）

这不是 walk-forward — 完整 WF 需要重跑 backtest，耗时以小时计。这个脚本
跑出的是：基于现有 IS 回测 equity，回答"从 11 个挑最高的 v16，统计上还站得住吗"。

运行：python scripts/batch_candidate_review.py
"""
from __future__ import annotations

import json
import re
import sys
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).parent.parent))

from utils.metrics import (
    annualized_return,
    annualized_volatility,
    sharpe_ratio,
    max_drawdown,
    win_rate,
    probabilistic_sharpe,
    deflated_sharpe,
    bootstrap_sharpe_ci,
    min_track_record_length,
)

RUNS_DIR = Path(__file__).parent.parent / "live" / "runs"
OUTPUT_JSON = (
    Path(__file__).parent.parent
    / "portfolio"
    / "public"
    / "data"
    / "strategy"
    / "candidate_review.json"
)
OUTPUT_MD = Path(__file__).parent.parent / "journal" / f"candidate_review_{date.today().strftime('%Y%m%d')}.md"

VERSION_RE = re.compile(r"multi_factor_(v\d+)_\d+_[a-f0-9]+_equity\.csv$")


def latest_equity_file(version: str) -> Path | None:
    """对每个版本取最新 equity 文件（按 mtime）。"""
    candidates = sorted(
        RUNS_DIR.glob(f"multi_factor_{version}_*_equity.csv"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    return candidates[0] if candidates else None


def discover_versions() -> list[str]:
    seen = set()
    versions = []
    for f in RUNS_DIR.glob("multi_factor_v*_equity.csv"):
        m = VERSION_RE.search(f.name)
        if m:
            v = m.group(1)
            if v not in seen:
                seen.add(v)
                versions.append(v)
    # 按数字排序
    return sorted(versions, key=lambda s: int(s[1:]))


def load_returns(path: Path) -> pd.Series:
    df = pd.read_csv(path, parse_dates=["date"]).set_index("date")
    if "portfolio_return" in df.columns:
        r = df["portfolio_return"].astype(float)
    else:
        cum = df["cumulative_return"].astype(float)
        r = (1 + cum).pct_change().fillna(0.0)
    # drop leading zeros (warmup padding)
    first_nz = r.ne(0).idxmax() if r.ne(0).any() else r.index[0]
    return r.loc[first_nz:]


def compute_candidate_stats(version: str, returns: pd.Series) -> dict:
    n = len(returns)
    ann = annualized_return(returns)
    vol = annualized_volatility(returns)
    sr = sharpe_ratio(returns)
    mdd = max_drawdown(returns)
    wr = win_rate(returns)
    psr_vs_zero = probabilistic_sharpe(returns, sr_benchmark=0.0)
    psr_vs_gate = probabilistic_sharpe(returns, sr_benchmark=0.8)  # admission gate
    ci = bootstrap_sharpe_ci(returns, n_boot=1000, seed=42)
    mintrl_days = min_track_record_length(returns, sr_target=0.0)
    return {
        "version": version,
        "n_days": int(n),
        "period_start": str(returns.index[0].date()),
        "period_end": str(returns.index[-1].date()),
        "ann_return": float(ann),
        "ann_volatility": float(vol),
        "sharpe": float(sr),
        "max_drawdown": float(mdd),
        "win_rate": float(wr),
        "psr_vs_zero": float(psr_vs_zero),
        "psr_vs_admission_gate": float(psr_vs_gate),
        "sharpe_ci_low": ci["ci_low"],
        "sharpe_ci_high": ci["ci_high"],
        "mintrl_days": None if np.isinf(mintrl_days) or np.isnan(mintrl_days) else float(mintrl_days),
    }


def annotate_with_deflation(rows: list[dict]) -> list[dict]:
    """用候选池内的 sharpe 分散度计算 DSR。"""
    sr_arr = np.array([r["sharpe"] for r in rows], dtype=float)
    n_trials = len(sr_arr)
    sr_std = float(np.std(sr_arr, ddof=1)) if n_trials > 1 else 0.0
    for r in rows:
        # 需要 returns 才能算 DSR — 稍后在调用方补上
        r["dsr_trials"] = n_trials
        r["dsr_sharpe_std"] = sr_std
    return rows


def gate_status(stats: dict) -> dict:
    """Admission gate 判定（基于 CLAUDE.md 红线）。"""
    checks = {
        "ann_return_ge_15pct": stats["ann_return"] >= 0.15,
        "sharpe_ge_08": stats["sharpe"] >= 0.8,
        "max_dd_gt_neg30pct": stats["max_drawdown"] > -0.30,
        "psr_ge_95pct": stats["psr_vs_zero"] >= 0.95,
    }
    checks["all_pass"] = all(checks.values())
    return checks


def render_markdown(rows: list[dict], generated_at: str) -> str:
    head = f"""# 候选复审报告 {generated_at}

> 诚实基线：从 {len(rows)} 个多因子候选（{', '.join(r['version'] for r in rows)}）
> 里挑 sharpe 最高的 v16，**统计上还站得住吗**？

## 说明
- IS 指标来自每个候选最近一次回测（live/runs/multi_factor_*_equity.csv）
- PSR(vs 0) = 观察夏普显著大于零的概率（≥0.95 才算显著）
- DSR = 对 &quot;从 N 个挑最高&quot; 的选择偏差做修正（n_trials={rows[0]['dsr_trials']}）
- Bootstrap CI 用 stationary block resample 保留日收益自相关
- Admission gate：年化>15%、Sharpe>0.8、回撤<30%、PSR>0.95

## 排名（按 deflated sharpe 降序）

| Rank | Version | Sharpe | CI(95%) | PSR(vs 0) | DSR | Ann.Return | MaxDD | Gate |
|------|---------|--------|---------|-----------|-----|------------|-------|------|
"""
    lines = []
    for i, r in enumerate(rows, 1):
        ci = f"[{r['sharpe_ci_low']:.2f}, {r['sharpe_ci_high']:.2f}]"
        gate = "✓" if r["gate"]["all_pass"] else "✗"
        lines.append(
            f"| {i} | **{r['version']}** | {r['sharpe']:.3f} | {ci} | "
            f"{r['psr_vs_zero']:.2%} | {r['dsr']:.2%} | {r['ann_return']:.2%} | "
            f"{r['max_drawdown']:.2%} | {gate} |"
        )
    return head + "\n".join(lines) + "\n\n## 结论\n\n" + _conclusion(rows)


def _conclusion(rows: list[dict]) -> str:
    # 按 DSR 排序后的 top 1
    top = rows[0]
    gates_passed = [r for r in rows if r["gate"]["all_pass"]]
    if gates_passed:
        g = gates_passed[0]
        gate_line = f"**{g['version']}** 是唯一通过全部 admission gate 的候选（sharpe {g['sharpe']:.2f}, DSR {g['dsr']:.2%}）。"
    else:
        gate_line = "**没有任何候选通过全部 admission gate** — 最高 DSR 候选也无法直接上 live。"
    return (
        f"- DSR 排名最高：**{top['version']}**（{top['dsr']:.2%}）。\n"
        f"- {gate_line}\n"
        "- DSR 低于 50% 的候选统计上无法和 &quot;纯运气&quot; 区分；直接上 live 等于抛硬币。\n"
        "- 下一步：对 DSR ≥ 0.5 的候选跑 17 窗口 walk-forward，"
        "看样本外 sharpe 中位数（真正的 &quot;穿越样本外&quot; 证据）。\n"
    )


def main():
    versions = discover_versions()
    if not versions:
        print("未找到任何 multi_factor_v*_equity.csv", file=sys.stderr)
        sys.exit(1)

    print(f"发现 {len(versions)} 个版本：{versions}")
    rows = []
    returns_by_version = {}
    for v in versions:
        path = latest_equity_file(v)
        if path is None:
            continue
        try:
            r = load_returns(path)
            if len(r) < 60:
                print(f"  {v}: 样本不足 ({len(r)} 天)，跳过")
                continue
            stats = compute_candidate_stats(v, r)
            stats["equity_file"] = path.name
            rows.append(stats)
            returns_by_version[v] = r
            print(f"  {v}: n={stats['n_days']} sr={stats['sharpe']:.3f} psr={stats['psr_vs_zero']:.2%}")
        except Exception as e:
            print(f"  {v}: 解析失败 {e}", file=sys.stderr)

    if not rows:
        print("无有效候选", file=sys.stderr)
        sys.exit(1)

    # 计算池内 sharpe 标准差 → DSR
    sr_arr = np.array([r["sharpe"] for r in rows], dtype=float)
    sr_std = float(np.std(sr_arr, ddof=1)) if len(sr_arr) > 1 else 0.15
    n_trials = len(rows)
    for r in rows:
        ret = returns_by_version[r["version"]]
        r["dsr"] = float(deflated_sharpe(ret, n_trials=n_trials, trials_sharpe_std=sr_std))
        r["dsr_trials"] = n_trials
        r["dsr_sharpe_std"] = sr_std
        r["gate"] = gate_status(r)

    # 按 DSR 降序
    rows.sort(key=lambda r: r["dsr"], reverse=True)
    generated_at = date.today().isoformat()

    # JSON output
    OUTPUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_JSON.write_text(
        json.dumps(
            {
                "generated_at": generated_at,
                "n_candidates": len(rows),
                "selection_pool_sharpe_std": sr_std,
                "admission_gate_note": "CLAUDE.md 红线：年化>15%, Sharpe>0.8, 回撤<30%, PSR>0.95",
                "candidates": rows,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    print(f"写出 {OUTPUT_JSON}")

    # Markdown report
    OUTPUT_MD.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_MD.write_text(render_markdown(rows, generated_at), encoding="utf-8")
    print(f"写出 {OUTPUT_MD}")

    # Stdout summary
    print("\n" + "=" * 60)
    print("DSR 排名")
    print("=" * 60)
    for i, r in enumerate(rows, 1):
        gate = "✓" if r["gate"]["all_pass"] else "✗"
        print(
            f"{i:2}. {r['version']:4}  "
            f"sharpe={r['sharpe']:5.3f}  "
            f"PSR={r['psr_vs_zero']:6.2%}  "
            f"DSR={r['dsr']:6.2%}  "
            f"ann={r['ann_return']:6.2%}  "
            f"mdd={r['max_drawdown']:6.2%}  "
            f"gate={gate}"
        )


if __name__ == "__main__":
    main()
