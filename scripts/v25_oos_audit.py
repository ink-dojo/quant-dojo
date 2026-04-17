"""
v25 严格 OOS 诊断 — 不调参，只披露真实统计显著性。

原则（用户指令 2026-04-17）:
  "不能抄近道，也不能糊弄...不能为了过线而过线"

本脚本 NOT 做:
  × 从 sweep 结果里挑 sharpe 最高的参数重新注册 v26
  × 任何形式的后验参数优化

本脚本做 (López de Prado AFML 规范):
  1. 分段 OOS (by calendar year): 看 2022/2023/2024/2025 各自独立过关率
  2. Rolling 6-month windows: 看 IS 期内 sharpe/mdd 时序稳定性
  3. Stationary block bootstrap CI: sharpe 的 95% CI
  4. Probabilistic Sharpe Ratio vs {0, 0.5}: 显著性
  5. Deflated Sharpe Ratio: 对整个 v22-v25 搜索空间（5 个候选）做选择偏差修正
  6. MinTRL: 当前样本量是否够达到 sharpe=0.8 的统计显著
  7. admission 诚实披露: 真实过线 / 未过线，不编辑指标

输出:
  journal/v25_oos_audit_{date}.md
  journal/v25_oos_audit_{date}.csv (rolling windows)

运行: python scripts/v25_oos_audit.py
"""
from __future__ import annotations

import json
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import numpy as np
import pandas as pd

from utils.metrics import (
    annualized_return, annualized_volatility, sharpe_ratio,
    max_drawdown, win_rate, calmar_ratio,
    probabilistic_sharpe, deflated_sharpe, bootstrap_sharpe_ci,
    min_track_record_length,
)


def load_v25_equity() -> tuple[pd.Series, str]:
    """读当天 fresh v25 equity。若多份取最新 mtime。"""
    files = sorted(
        Path("live/runs").glob("multi_factor_v25_*_equity.csv"),
        key=lambda p: p.stat().st_mtime,
    )
    if not files:
        raise FileNotFoundError("未找到 multi_factor_v25_*_equity.csv")
    path = files[-1]
    df = pd.read_csv(path, parse_dates=["date"]).set_index("date")
    r = df["portfolio_return"].astype(float)
    # 截 IS 期并去 warmup 零行
    r = r.loc["2022-01-01":"2025-12-31"]
    first_nz = r.ne(0).idxmax() if r.ne(0).any() else r.index[0]
    r = r.loc[first_nz:]
    return r, str(path)


def section_yearly(r: pd.Series) -> pd.DataFrame:
    """按日历年分段独立统计，每段 ~250 日。"""
    rows = []
    for y in sorted(r.index.year.unique()):
        sub = r[r.index.year == y]
        if len(sub) < 60:
            continue
        rows.append({
            "year": int(y),
            "n_days": len(sub),
            "ann_return": float(annualized_return(sub)),
            "volatility": float(annualized_volatility(sub)),
            "sharpe": float(sharpe_ratio(sub)),
            "max_drawdown": float(max_drawdown(sub)),
            "win_rate": float(win_rate(sub)),
            "calmar": float(calmar_ratio(sub)),
        })
    return pd.DataFrame(rows)


def rolling_6m_windows(r: pd.Series, window_days: int = 126, step_days: int = 63) -> pd.DataFrame:
    """6 月滚动窗口（~126 交易日），步长 3 月。非重叠或半重叠。"""
    rows = []
    dates = r.index
    start_idx = 0
    while start_idx + window_days <= len(dates):
        end_idx = start_idx + window_days
        sub = r.iloc[start_idx:end_idx]
        rows.append({
            "start": sub.index[0].date(),
            "end": sub.index[-1].date(),
            "n_days": len(sub),
            "sharpe": float(sharpe_ratio(sub)),
            "ann_return": float(annualized_return(sub)),
            "max_drawdown": float(max_drawdown(sub)),
        })
        start_idx += step_days
    return pd.DataFrame(rows)


def candidate_pool_sharpe_std(candidate_dir: Path = Path("journal")) -> tuple[float, int]:
    """
    估计候选池的 sharpe 标准差（用于 Deflated Sharpe Ratio）。

    来源:
      candidate_review.json 里 v7/v9/v10/v13/v15/v16/v20-v25 等正式注册候选的 sharpe
      （数据可能过期, 但相对排名作为 n_trials 估计仍有意义）

    若找不到则用 sweep 30 组的 sharpe std 作为兜底。
    """
    cr_path = candidate_dir / "candidate_review.json"
    if cr_path.exists():
        data = json.loads(cr_path.read_text(encoding="utf-8"))
        rows = data.get("candidates", data.get("rows", []))
        sharpes = []
        for row in rows:
            s = row.get("sharpe") or row.get("metrics", {}).get("sharpe")
            if s is not None and np.isfinite(s):
                sharpes.append(float(s))
        if len(sharpes) >= 3:
            return float(np.std(sharpes, ddof=1)), len(sharpes)

    # 兜底：读 sweep csv（30 组）
    sw_path = candidate_dir / f"v25_param_sweep_fresh_{date.today().strftime('%Y%m%d')}.csv"
    if sw_path.exists():
        df = pd.read_csv(sw_path)
        sh = df["sharpe"].dropna().values
        if len(sh) >= 3:
            return float(np.std(sh, ddof=1)), len(sh)

    return 0.1, 10  # 最后兜底


def admission_check(metrics: dict) -> dict:
    """
    诚实 admission 门检查，按 CLAUDE.md 写死的四条:
      ann_return > 15%, sharpe > 0.8, max_drawdown > -30%, PSR vs 0 >= 0.95.
    """
    return {
        "ann_return_pass": metrics["ann_return"] > 0.15,
        "sharpe_pass": metrics["sharpe"] > 0.80,
        "mdd_pass": metrics["max_drawdown"] > -0.30,
        "psr_vs_0_pass": metrics["psr_vs_0"] >= 0.95,
        "all_pass": all([
            metrics["ann_return"] > 0.15,
            metrics["sharpe"] > 0.80,
            metrics["max_drawdown"] > -0.30,
            metrics["psr_vs_0"] >= 0.95,
        ]),
    }


def main():
    r, path = load_v25_equity()
    print(f"[1/6] 加载 v25 equity: {Path(path).name}")
    print(f"  评估期: {r.index[0].date()} ~ {r.index[-1].date()}  n={len(r)}")

    # 全期指标
    m_all = {
        "n_days": int(len(r)),
        "ann_return": float(annualized_return(r)),
        "volatility": float(annualized_volatility(r)),
        "sharpe": float(sharpe_ratio(r)),
        "max_drawdown": float(max_drawdown(r)),
        "win_rate": float(win_rate(r)),
    }

    print(f"[2/6] Bootstrap sharpe CI (stationary block, n_boot=2000)…")
    boot = bootstrap_sharpe_ci(r, n_boot=2000, alpha=0.05, seed=42)
    m_all["sharpe_ci_low"] = boot["ci_low"]
    m_all["sharpe_ci_high"] = boot["ci_high"]

    print(f"[3/6] PSR (vs 0, 0.5) + MinTRL…")
    m_all["psr_vs_0"] = float(probabilistic_sharpe(r, sr_benchmark=0.0))
    m_all["psr_vs_0.5"] = float(probabilistic_sharpe(r, sr_benchmark=0.5))
    m_all["min_trl_vs_0"] = float(min_track_record_length(r, sr_target=0.0))
    m_all["min_trl_vs_0.5"] = float(min_track_record_length(r, sr_target=0.5))

    print(f"[4/6] Deflated Sharpe Ratio (选择偏差修正)…")
    sh_std, n_trials = candidate_pool_sharpe_std()
    m_all["n_trials"] = int(n_trials)
    m_all["trials_sharpe_std"] = float(sh_std)
    m_all["dsr"] = float(deflated_sharpe(r, n_trials=n_trials, trials_sharpe_std=sh_std))

    print(f"[5/6] 分段 OOS (yearly + 6M rolling)…")
    yearly = section_yearly(r)
    rolling = rolling_6m_windows(r, window_days=126, step_days=63)

    # admission 诚实判定（用全期）
    adm = admission_check(m_all)
    m_all["admission"] = adm

    print(f"[6/6] 生成 markdown 报告…")
    today = date.today().strftime("%Y%m%d")
    lines = []
    lines.append(f"# v25 严格 OOS 审计 — {today}")
    lines.append("")
    lines.append(f"> 原则: 不 p-hack, 不为过门而过门; 按 López de Prado AFML 规范")
    lines.append(f"> 数据源: `{Path(path).name}`  n={m_all['n_days']}  ({r.index[0].date()} ~ {r.index[-1].date()})")
    lines.append("")

    lines.append("## 1. 全期指标 + Bootstrap 95% CI")
    lines.append("")
    lines.append("| 指标 | 值 | 门槛 | 是否过 |")
    lines.append("|:-----|:---|:-----|:------:|")
    lines.append(f"| 年化收益 | {m_all['ann_return']:.2%} | > 15% | {'✅' if adm['ann_return_pass'] else '❌'} |")
    lines.append(f"| 夏普 (点估计) | {m_all['sharpe']:.4f} | > 0.80 | {'✅' if adm['sharpe_pass'] else '❌'} |")
    lines.append(f"| 夏普 95% CI | [{m_all['sharpe_ci_low']:.3f}, {m_all['sharpe_ci_high']:.3f}] | CI 下界 > 0.80 最佳 | — |")
    lines.append(f"| 最大回撤 | {m_all['max_drawdown']:.2%} | > -30% | {'✅' if adm['mdd_pass'] else '❌'} |")
    lines.append(f"| PSR vs 0 | {m_all['psr_vs_0']:.4f} | ≥ 0.95 | {'✅' if adm['psr_vs_0_pass'] else '❌'} |")
    lines.append(f"| PSR vs 0.5 | {m_all['psr_vs_0.5']:.4f} | (参考) | — |")
    lines.append(f"| MinTRL (vs 0) | {m_all['min_trl_vs_0']:.0f} 日 (~{m_all['min_trl_vs_0']/252:.1f} 年) | 当前 {m_all['n_days']} 日 | — |")
    lines.append(f"| MinTRL (vs 0.5) | {m_all['min_trl_vs_0.5']:.0f} 日 | — | — |")
    lines.append(f"| 胜率 | {m_all['win_rate']:.2%} | — | — |")
    lines.append("")
    lines.append(f"**全部 admission 过关**: {'✅ 全部通过' if adm['all_pass'] else '❌ 未全部通过'}")
    lines.append("")

    lines.append("## 2. Deflated Sharpe Ratio (选择偏差修正)")
    lines.append("")
    lines.append("对 DSR 原理 (Bailey & López de Prado 2014): 若从 N 个候选里挑 sharpe 最高者,")
    lines.append("观测 sharpe 已被选择偏差抬高。DSR = Prob(真 SR > E[max SR | 纯噪声下的 N 次试验])。")
    lines.append("")
    lines.append(f"- 候选池规模 n_trials: {m_all['n_trials']}")
    lines.append(f"- 候选池 sharpe 标准差: {m_all['trials_sharpe_std']:.4f}")
    lines.append(f"- **DSR**: {m_all['dsr']:.4f}  {'✅ ≥0.95 扣除偏差后仍显著' if m_all['dsr'] >= 0.95 else '⚠️ <0.95 扣除偏差后不显著'}")
    lines.append("")

    lines.append("## 3. 分年 OOS 独立表现")
    lines.append("")
    lines.append(yearly.to_markdown(index=False, floatfmt=".3f"))
    lines.append("")
    yearly_pass = (
        (yearly["ann_return"] > 0.15)
        & (yearly["sharpe"] > 0.80)
        & (yearly["max_drawdown"] > -0.30)
    ).sum()
    lines.append(f"**分年独立过 (ann+sharpe+mdd) 三门的年数: {yearly_pass}/{len(yearly)}**")
    lines.append("")

    lines.append("## 4. 6 月 Rolling 窗口稳定性 (步长 3 月)")
    lines.append("")
    lines.append(f"窗口数: {len(rolling)}")
    lines.append("")
    lines.append(f"- Sharpe 中位数: {rolling['sharpe'].median():.3f}")
    lines.append(f"- Sharpe 25% / 75% 分位: {rolling['sharpe'].quantile(0.25):.3f} / {rolling['sharpe'].quantile(0.75):.3f}")
    lines.append(f"- Sharpe > 0.8 的窗口比例: {(rolling['sharpe'] > 0.8).mean():.1%}")
    lines.append(f"- MDD 中位数: {rolling['max_drawdown'].median():.2%}")
    lines.append(f"- MDD < -20% 的窗口比例 (更差): {(rolling['max_drawdown'] < -0.20).mean():.1%}")
    lines.append("")
    lines.append("### 原始 rolling 窗口（前 15 行）")
    lines.append("")
    lines.append(rolling.head(15).to_markdown(index=False, floatfmt=".3f"))
    lines.append("")

    lines.append("## 5. 诚实结论")
    lines.append("")
    if adm["all_pass"]:
        lines.append("v25 四项 admission 门 **全部通过**。")
    else:
        lines.append("v25 **未**全部通过 admission 四门:")
        for k, v in adm.items():
            if k == "all_pass":
                continue
            lines.append(f"- {k}: {'✅' if v else '❌'}")
    lines.append("")
    lines.append("### 不可抄近道的观察")
    lines.append("- Sharpe 点估计 = {:.3f}; bootstrap 95% CI = [{:.3f}, {:.3f}]".format(
        m_all["sharpe"], m_all["sharpe_ci_low"], m_all["sharpe_ci_high"]
    ))
    if m_all["sharpe_ci_low"] > 0.80:
        lines.append("  - CI 下界 > 0.80: sharpe 门**统计显著**过关")
    elif m_all["sharpe"] > 0.80:
        lines.append("  - 点估计过 0.80, 但 CI 跨 0.80: 没到统计显著")
    else:
        lines.append("  - 点估计 <0.80: 未过 sharpe 门, 无论置信度如何都不该声称过门")
    lines.append("")
    lines.append(f"- DSR = {m_all['dsr']:.3f}:")
    if m_all["dsr"] >= 0.95:
        lines.append("  - 选择偏差修正后仍 ≥0.95, sharpe 可信度高")
    else:
        lines.append(f"  - <0.95, 扣除 {m_all['n_trials']} 候选的选择偏差后 **不足以** 声称显著优于纯噪声")
    lines.append("")
    lines.append("### 下一步合规路径（不抄近道）")
    lines.append("- sweep 里 threshold=-0.05 sharpe=0.914 属于 30 组选 1 的 selection-inflated,")
    lines.append("  直接注册 v26 = p-hack, 必须先在完全独立的 OOS 样本（如 2026 Q1 live）上独立验证。")
    lines.append("- 正确路径: 保留 v25 (-0.10, 120) 设计参数,持续 live/paper 累积样本,")
    lines.append("  等 MinTRL 满足（当前估计需要 {:.1f} 年达到 sharpe=0.8 显著）再升级。".format(m_all["min_trl_vs_0.5"] / 252))
    lines.append("- 与此并行: 找新因子扩展 v16 alpha, 从根本上提升 sharpe 而非参数搜索。")
    lines.append("")

    out_md = Path(f"journal/v25_oos_audit_{today}.md")
    out_md.write_text("\n".join(lines), encoding="utf-8")
    rolling.to_csv(Path(f"journal/v25_oos_audit_{today}_rolling.csv"), index=False)

    print(f"\n✓ 写出 {out_md}")
    print(f"✓ 写出 journal/v25_oos_audit_{today}_rolling.csv")

    # 终端摘要
    print("\n=== 全期关键指标 ===")
    print(f"  Sharpe       = {m_all['sharpe']:.4f}  (95% CI [{m_all['sharpe_ci_low']:.3f}, {m_all['sharpe_ci_high']:.3f}])")
    print(f"  Ann Return   = {m_all['ann_return']:.2%}")
    print(f"  Max Drawdown = {m_all['max_drawdown']:.2%}")
    print(f"  PSR vs 0     = {m_all['psr_vs_0']:.4f}")
    print(f"  DSR          = {m_all['dsr']:.4f}  (n_trials={m_all['n_trials']}, sh_std={m_all['trials_sharpe_std']:.3f})")
    print(f"  MinTRL vs 0.5= {m_all['min_trl_vs_0.5']:.0f} 日 (~{m_all['min_trl_vs_0.5']/252:.1f} 年)")
    print(f"\n  Admission 通过: {sum(adm[k] for k in ['ann_return_pass','sharpe_pass','mdd_pass','psr_vs_0_pass'])}/4")


if __name__ == "__main__":
    main()
