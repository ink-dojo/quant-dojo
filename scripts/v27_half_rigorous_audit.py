"""
v27_half (bear=0.5 simple mask) 严谨审计 — 回答 "过门是真的吗?"。

v27_half 是规则型策略 (无训练参数):
  if HS300_shift(1) < MA120: exposure = 0.5
  else:                      exposure = 1.0

规则型策略的严谨度来自:
  1. DSR 修正 — v27 共享 regime_stop 候选池 (v25 扫的 30 组 + v27 2 个)
  2. 切换成本建模 — bear↔bull 切换的换仓成本扣除
  3. MinTRL — 达到 sharpe 显著所需最短样本
  4. Bootstrap block CI — 已有
  5. 分年 + 6M rolling 稳定性 — 已在 v27 对照脚本里
  6. Purged k-fold — 对规则型策略只是 "分段 OOS sharpe" 验证稳定

输出: journal/v27_half_rigorous_audit_{date}.md
"""
from __future__ import annotations

import json
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import numpy as np
import pandas as pd

from pipeline.strategy_registry import get_strategy
from utils.local_data_loader import get_all_symbols, load_price_wide
from utils.metrics import (
    annualized_return, annualized_volatility, sharpe_ratio,
    max_drawdown, win_rate, probabilistic_sharpe, deflated_sharpe,
    bootstrap_sharpe_ci, min_track_record_length,
)
from utils.purged_cv import purged_kfold_indices
from utils.stop_loss import hs300_bear_regime

WARMUP = "2019-01-01"
START = "2022-01-01"
END = "2025-12-31"
MA = 120
N_STOCKS = 30

# v27_half 切换成本假设 (单边 0.1% 成本, 半仓切换约是半仓额的 trade)
ROUND_TRIP_COST = 0.001


def load_v16_fresh() -> pd.Series:
    symbols = get_all_symbols()
    price = load_price_wide(symbols, WARMUP, END, field="close")
    valid = price.columns[price.notna().sum() > 500]
    price = price[list(valid)]
    entry = get_strategy("multi_factor_v16")
    strat = entry.factory({"n_stocks": N_STOCKS})
    res = strat.run(price)
    col = "portfolio_return" if "portfolio_return" in res.columns else "returns"
    r = res[col].astype(float).loc[START:END]
    first_nz = r.ne(0).idxmax() if r.ne(0).any() else r.index[0]
    return r.loc[first_nz:]


def v27_half_with_cost(v16: pd.Series, regime: pd.Series, cost_per_switch: float) -> tuple[pd.Series, int]:
    """
    v27_half = v16 × exposure_t, 其中 exposure_t ∈ {0.5, 1.0} 来自 regime。
    切换成本在 exposure 变动日扣除 |Δexposure| × 2 × cost_per_switch (单边成本)。

    cost_per_switch = 0.001 表示单边 10 bps, 即 bear↔bull 一次来回约扣 10 bps × |Δw|。
    这里 |Δw| = 0.5 (满仓→半仓), round-trip 一次 = 10 bps 扣除。

    返回: (调整后收益 Series, 切换次数)
    """
    exposure = pd.Series(1.0, index=v16.index)
    exposure[regime] = 0.5
    adj = v16 * exposure

    # 切换日: exposure 变化
    dw = exposure.diff().fillna(0)
    n_switches = int((dw != 0).sum())

    # 切换成本: 在切换日扣 |Δw| × cost_per_switch
    cost = dw.abs() * cost_per_switch
    return (adj - cost), n_switches


def mintrl_block(r: pd.Series) -> dict:
    return {
        "mintrl_vs_0":  min_track_record_length(r, sr_target=0.0),
        "mintrl_vs_0.5": min_track_record_length(r, sr_target=0.5),
        "mintrl_vs_0.8": min_track_record_length(r, sr_target=0.8),
    }


def metrics_block(r: pd.Series, name: str) -> dict:
    return {
        "策略": name,
        "n": len(r),
        "ann_return": float(annualized_return(r)),
        "sharpe": float(sharpe_ratio(r)),
        "mdd": float(max_drawdown(r)),
        "vol": float(annualized_volatility(r)),
        "psr_0": float(probabilistic_sharpe(r, sr_benchmark=0.0)),
        "psr_0.5": float(probabilistic_sharpe(r, sr_benchmark=0.5)),
    }


def purged_oos_sharpe(v27: pd.Series, n_splits: int = 5, horizon: int = 5, embargo: float = 0.02) -> list[dict]:
    """规则型策略: purged k-fold 只用来验证各 OOS fold 的 sharpe 稳定性。"""
    dates = v27.index
    rows = []
    for split in purged_kfold_indices(dates, n_splits=n_splits, label_horizon=horizon, embargo_pct=embargo):
        test_r = v27.iloc[split.test_idx]
        rows.append({
            "fold": split.fold,
            "n_test": len(split.test_idx),
            "test_start": str(test_r.index[0].date()),
            "test_end": str(test_r.index[-1].date()),
            "ann_return": float(annualized_return(test_r)),
            "sharpe": float(sharpe_ratio(test_r)),
            "mdd": float(max_drawdown(test_r)),
        })
    return rows


def main():
    print("[1/6] 加载 v16 底层 + regime…")
    v16 = load_v16_fresh()
    hs300 = load_price_wide(["399300"], "2018-01-01", END, field="close")["399300"].dropna()
    regime = hs300_bear_regime(hs300, ma_window=MA, shift_days=1).reindex(v16.index).fillna(False).astype(bool)

    print("[2/6] 构造 v27_half (含切换成本) …")
    v27_pre, n_switches = v27_half_with_cost(v16, regime, cost_per_switch=0)
    v27_cost, _ = v27_half_with_cost(v16, regime, cost_per_switch=ROUND_TRIP_COST)
    print(f"  regime 切换次数: {n_switches} (全期 {len(v16)} 天)")
    print(f"  成本扣除后 ann: {annualized_return(v27_cost):.2%} (无成本 {annualized_return(v27_pre):.2%})")

    print("[3/6] 核心 metrics…")
    m_pre = metrics_block(v27_pre, "v27_half (no cost)")
    m_cost = metrics_block(v27_cost, "v27_half (with cost)")

    # admission 判定
    def admission(m):
        return {
            "ann_pass": m["ann_return"] > 0.15,
            "sharpe_pass": m["sharpe"] > 0.80,
            "mdd_pass": m["mdd"] > -0.30,
            "psr0_pass": m["psr_0"] > 0.95,
        }
    a_pre = admission(m_pre); a_cost = admission(m_cost)

    print("[4/6] DSR 修正 (保守 n_trials=32) …")
    # 候选池 sharpe std: 读 v25 sweep artifact 里的 6 组+本次 v27 比较的 4 组
    # 保守估计: 参考 v25 之前的 30 候选 sweep_sharpe_std=0.0663, 稍微加大
    trials_sharpe_std = 0.08  # 保守上调, 含 v27 衍生
    dsr_cost = float(deflated_sharpe(v27_cost, n_trials=32, trials_sharpe_std=trials_sharpe_std))
    print(f"  DSR (n_trials=32, std={trials_sharpe_std}): {dsr_cost:.4f}")

    print("[5/6] Bootstrap CI + MinTRL…")
    ci_cost = bootstrap_sharpe_ci(v27_cost, n_boot=2000, alpha=0.05, seed=42)
    mintrl_cost = mintrl_block(v27_cost)

    print("[6/6] Purged k-fold OOS sharpe 稳定性…")
    pk_rows = purged_oos_sharpe(v27_cost, n_splits=5, horizon=5, embargo=0.02)
    pk_df = pd.DataFrame(pk_rows)

    # 分年
    years = sorted(set(v27_cost.index.year))
    y_rows = []
    for y in years:
        ry = v27_cost[v27_cost.index.year == y]
        y_rows.append({
            "year": int(y),
            "n": len(ry),
            "ann_return": float(annualized_return(ry)),
            "sharpe": float(sharpe_ratio(ry)),
            "mdd": float(max_drawdown(ry)),
            "win_rate": float(win_rate(ry)),
        })
    y_df = pd.DataFrame(y_rows)

    # markdown
    today = date.today().strftime("%Y%m%d")
    lines = []
    lines.append(f"# v27_half 严谨审计 — {today}")
    lines.append("")
    lines.append(f"> 规则: HS300<MA{MA} shift(1) → exposure=0.5; 否则 exposure=1.0")
    lines.append(f"> 数据: v16 底层 fresh run, eval {v27_cost.index[0].date()}~{v27_cost.index[-1].date()} n={len(v27_cost)}")
    lines.append(f"> 切换成本: 单边 {ROUND_TRIP_COST*100:.2f}% × |Δw| per switch")
    lines.append("")

    lines.append("## 1. 核心 metrics")
    lines.append("")
    df_m = pd.DataFrame([m_pre, m_cost])
    lines.append(df_m.to_markdown(index=False, floatfmt=".4f"))
    lines.append("")

    lines.append("## 2. Admission 判定")
    lines.append("")
    lines.append(f"- 无成本: {a_pre} → {'✅ 全过' if all(a_pre.values()) else '❌ 未全过'}")
    lines.append(f"- 含成本: {a_cost} → {'✅ 全过' if all(a_cost.values()) else '❌ 未全过'}")
    lines.append("")
    lines.append(f"切换次数: **{n_switches}** 次 (全期 {len(v16)} 天, 即 {n_switches/len(v16)*100:.2f}% 的天数切换)")
    lines.append("")

    lines.append("## 3. Deflated Sharpe Ratio")
    lines.append("")
    lines.append(f"- n_trials 保守估计: 32 (v25 原 sweep 30 + v27 系 4 个结构对照, 去重)")
    lines.append(f"- trials_sharpe_std: {trials_sharpe_std} (比 v25 sweep 的 0.0663 上调, 考虑 v27 结构差异)")
    lines.append(f"- **DSR (含成本)**: {dsr_cost:.4f}")
    lines.append(f"- 门槛: DSR ≥ 0.95 才算扣除 selection bias 后仍显著")
    lines.append(f"- 判定: {'✅ DSR 过门' if dsr_cost >= 0.95 else '❌ DSR 不过门, 相对 n_trials=32 的期望最大 sharpe 仍不显著'}")
    lines.append("")

    lines.append("## 4. Bootstrap 95% CI (with cost)")
    lines.append("")
    lines.append(f"- Sharpe 点估计: {ci_cost['sharpe']:.4f}")
    lines.append(f"- 95% CI: [{ci_cost['ci_low']:.4f}, {ci_cost['ci_high']:.4f}]")
    ci_pass_str = '✅' if ci_cost['ci_low'] > 0.80 else '❌ (无法声称稳定过 0.80)'
    lines.append(f"- CI 下界 > 0.80: {ci_pass_str}")
    lines.append("")

    lines.append("## 5. MinTRL (with cost)")
    lines.append("")
    lines.append(f"- 达到 sharpe>0 显著: {mintrl_cost['mintrl_vs_0']:.0f} 日 (当前 {len(v27_cost)})")
    lines.append(f"- 达到 sharpe>0.5 显著: {mintrl_cost['mintrl_vs_0.5']:.0f} 日 (~{mintrl_cost['mintrl_vs_0.5']/252:.1f} 年)")
    lines.append(f"- 达到 sharpe>0.8 显著: {mintrl_cost['mintrl_vs_0.8']:.0f} 日 (~{mintrl_cost['mintrl_vs_0.8']/252:.1f} 年)")
    lines.append("")

    lines.append("## 6. Purged k-fold OOS sharpe (embargo 2%, h=5)")
    lines.append("")
    lines.append(pk_df.to_markdown(index=False, floatfmt=".4f"))
    lines.append("")
    pk_sharpe = pk_df["sharpe"]
    lines.append(f"- OOS fold sharpe 中位数: {pk_sharpe.median():.3f}")
    lines.append(f"- OOS fold sharpe 最小: {pk_sharpe.min():.3f}, 最大: {pk_sharpe.max():.3f}")
    lines.append(f"- >0.8 的 fold 占比: {(pk_sharpe > 0.8).mean():.0%}")
    lines.append("")

    lines.append("## 7. 分年 (with cost)")
    lines.append("")
    lines.append(y_df.to_markdown(index=False, floatfmt=".4f"))
    pass_year = y_df[(y_df["ann_return"] > 0.15) & (y_df["sharpe"] > 0.80) & (y_df["mdd"] > -0.30)]
    lines.append("")
    lines.append(f"- 分年独立过三门 (ann+sharpe+mdd): {len(pass_year)}/{len(y_df)}")
    lines.append("")

    lines.append("## 8. 诚实结论")
    lines.append("")
    all_pass_cost = all(a_cost.values())
    dsr_pass = dsr_cost >= 0.95
    ci_pass = ci_cost["ci_low"] > 0.80
    lines.append(f"- Admission 四门 (含成本): {'✅' if all_pass_cost else '❌'}")
    dsr_str = '✅' if dsr_pass else f'❌ ({dsr_cost:.3f} < 0.95)'
    lines.append(f"- DSR (n_trials=32): {dsr_str}")
    lines.append(f"- Bootstrap CI 下界 >0.80: {'✅' if ci_pass else '❌'}")
    lines.append("")
    if all_pass_cost and dsr_pass:
        lines.append("**过门状态**: v27_half 过 admission, 且 DSR 修正后仍显著。可以考虑注册为 v27 候选,")
        lines.append("但必须在 2026 Q1+ 独立 live/paper OOS 样本上继续累积验证, MinTRL 达到才算正式毕业。")
    elif all_pass_cost and not dsr_pass:
        lines.append("**过门状态**: admission 过, DSR **未过**。")
        lines.append("含义: 样本内 sharpe 看起来 OK, 但相对 32 组候选的期望最大 sharpe, 不足以声称真显著。")
        lines.append("合规路径: 不注册为过门候选, 而是作为 paper-trading 候选, 持续累积样本直到 DSR>0.95。")
    elif not all_pass_cost:
        lines.append("**过门状态**: 扣除切换成本后 admission 未全过。")
        lines.append("含义: 之前的 'v27_half 过门' 是忽略成本的理想上限, 实盘会被成本打回。")
    lines.append("")
    lines.append("**严禁抄近道的后续路径**:")
    lines.append("1. 不去微调 regime_threshold / scale / MA 参数找 '更高的 sharpe' — 那是 selection bias 放大器")
    lines.append("2. 如需升级, 应换 regime 指标 (macro, breadth), 用独立样本验证, 不沿用同一 HS300 MA 家族")
    lines.append("3. 继续累积 live 样本 (2026 Q1+) 是最合法的过门路径, 不能用 backtest 样本反复榨取置信")
    lines.append("")

    out_md = Path(f"journal/v27_half_rigorous_audit_{today}.md")
    out_md.write_text("\n".join(lines), encoding="utf-8")
    print(f"\n✓ 写出 {out_md}")

    # 速览
    print("\n=== 含成本速览 ===")
    print(f"  ann: {m_cost['ann_return']:.2%}  sharpe: {m_cost['sharpe']:.3f}  mdd: {m_cost['mdd']:.2%}  psr0: {m_cost['psr_0']:.3f}")
    print(f"  admission (cost): {a_cost}  all_pass={all(a_cost.values())}")
    print(f"  DSR (n_trials=32): {dsr_cost:.4f}")
    print(f"  95% CI: [{ci_cost['ci_low']:.3f}, {ci_cost['ci_high']:.3f}]")
    print(f"  分年独立过三门: {len(pass_year)}/{len(y_df)}")


if __name__ == "__main__":
    main()
