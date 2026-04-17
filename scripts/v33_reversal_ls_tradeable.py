"""
v33 = reversal_skip1m 真实可交易 L/S — 预注册单次实验。

动机 (来自 reversal_factors_eval_20260417.md 诊断):
  报告的 "HAC-t=5.18, LS sharpe=1.497" 是学术 gross 值:
    - 没扣融券成本 (A 股 ~8% 年化)
    - 没扣双边交易成本 (单边 15 bps × 两腿 × 日换手)
    - 假定全 A 可融券 (实际 ~1600 只, 不纠正则是乐观上限)
  如果扣完这两层 sharpe 仍 > 0.8 且 DSR > 0.95, 是真正 tradeable 候选。
  如果扣完就垮, 之前的 "反转因子很强" 结论需要附注 "学术性强, 实操性弱"。

预注册 (唯一确定性方案, 零参数搜索):
  - 因子: reversal_skip1m (单一)
  - 全体 A 股 (notna>500), 不做可融券过滤 (乐观上限)
  - 日频: 每日再平衡, 等权 quintile
  - 长腿 = Q5, 短腿 = Q1 (反转因子正 IC → 值大 = 买)
  - borrow_cost_annual = 0.08
  - txn_cost_per_side = 0.0015
  - eval 2022-01-04 ~ 2025-12-31 (v16 对齐)
  - DSR n_trials = 10 (+1 于昨日 9)

严禁 (不调参):
  - 不换因子 (不测 reversal_1m, reversal_5d)
  - 不换 quintile 数 (5 固定)
  - 不换 borrow/txn 参数搜最优
  - 不加 regime / vol-target overlay
  - 不改 long/short 口径 (Q5-Q1 固定)
  - 若 sharpe < 0.8 或 DSR < 0.95, 诚实闭环, 不重试
"""
from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import numpy as np
import pandas as pd

from utils.local_data_loader import get_all_symbols, load_price_wide
from utils.alpha_factors import reversal_skip1m
from utils.ls_costs import (
    quintile_weights, leg_turnover, leg_return, tradable_ls_pnl,
)
from utils.metrics import (
    annualized_return, annualized_volatility, sharpe_ratio,
    max_drawdown, win_rate, probabilistic_sharpe, deflated_sharpe,
    bootstrap_sharpe_ci, min_track_record_length,
)

WARMUP = "2019-01-01"
START = "2022-01-01"
END = "2025-12-31"
N_GROUPS = 5
BORROW_ANNUAL = 0.08
TXN_PER_SIDE = 0.0015
N_TRIALS = 10
DSR_TARGET = 0.95


def metrics(r: pd.Series, name: str) -> dict:
    return {
        "策略": name,
        "n": len(r),
        "ann_return": float(annualized_return(r)),
        "sharpe": float(sharpe_ratio(r)),
        "mdd": float(max_drawdown(r)),
        "vol": float(annualized_volatility(r)),
        "psr_0": float(probabilistic_sharpe(r, sr_benchmark=0.0)),
        "psr_0.5": float(probabilistic_sharpe(r, sr_benchmark=0.5)),
        "win_rate": float(win_rate(r)),
    }


def admission(m: dict) -> dict:
    return {
        "ann_pass": m["ann_return"] > 0.15,
        "sharpe_pass": m["sharpe"] > 0.80,
        "mdd_pass": m["mdd"] > -0.30,
        "psr0_pass": m["psr_0"] > 0.95,
        "all_pass": (m["ann_return"] > 0.15 and m["sharpe"] > 0.80
                     and m["mdd"] > -0.30 and m["psr_0"] > 0.95),
    }


def main():
    print("[1/6] 加载 warmup 起全体 A 股收盘…")
    symbols = get_all_symbols()
    price = load_price_wide(symbols, WARMUP, END, field="close")
    valid = price.columns[price.notna().sum() > 500]
    price = price[list(valid)]
    print(f"  股票数 {len(valid)}, 日期 {len(price)}")

    print("[2/6] 计算 reversal_skip1m 因子 (5d/60d)…")
    factor = reversal_skip1m(price)
    # shift(1) 防前视: 当日因子只能用次日收益实现
    factor = factor.shift(1)
    factor_eval = factor.loc[START:END]
    ret_eval = price.pct_change().loc[START:END]
    print(f"  eval 因子 shape {factor_eval.shape}, 非 NaN 比例 {factor_eval.notna().mean().mean():.2%}")

    print(f"[3/6] 按 {N_GROUPS} 分位切权重…")
    weights = quintile_weights(factor_eval, n_groups=N_GROUPS)
    w_long = weights[-1]   # Q5 (因子最大 = 最强反转信号)
    w_short = weights[0]   # Q1

    print("[4/6] 计算腿日收益 + 换手…")
    r_long = leg_return(w_long, ret_eval)
    r_short = leg_return(w_short, ret_eval)
    tl = leg_turnover(w_long)
    ts = leg_turnover(w_short)
    gross_ls = (r_long - r_short)
    print(f"  gross LS 日均 {gross_ls.mean()*252:.2%} 年化 (未扣费)")
    print(f"  长腿日均换手 {tl.mean():.2%}, 短腿 {ts.mean():.2%}")

    print(f"[5/6] 扣融券 {BORROW_ANNUAL:.0%} + 双边 txn {TXN_PER_SIDE:.2%} …")
    net_ls = tradable_ls_pnl(
        r_long, r_short, tl, ts,
        borrow_cost_annual=BORROW_ANNUAL,
        txn_cost_per_side=TXN_PER_SIDE,
    ).dropna()
    # 去除 warmup 期全 0 段
    first_nz = net_ls.ne(0).idxmax() if net_ls.ne(0).any() else net_ls.index[0]
    net_ls = net_ls.loc[first_nz:]

    print("[6/6] 指标 + 推断…")
    m_gross = metrics(gross_ls.dropna().loc[first_nz:], "gross LS (学术)")
    m_net = metrics(net_ls, "net LS (tradeable)")
    a_gross = admission(m_gross)
    a_net = admission(m_net)

    # Trial pool for DSR
    sharpe_pool = [
        0.676,     # v16 baseline
        0.835,     # v16 + HS300 hedge (dde58e4 predecessor)
        1.050,     # v16 + ZZ500 hedge
        0.668,     # v28 v16+reversal_skip1m
        -0.216,    # TSM 50/50
        0.490,     # v16+TSM 50/50
        0.368,     # v16+TSM invVol
        0.836,     # v27_half
        1.497,     # reversal_skip1m gross LS (prior)
        float(m_net["sharpe"]),  # this trial
    ]
    sharpe_std = float(np.std(sharpe_pool, ddof=1))

    ci_net = bootstrap_sharpe_ci(net_ls, n_boot=2000, alpha=0.05, seed=42)
    dsr_net = deflated_sharpe(net_ls, n_trials=N_TRIALS, trials_sharpe_std=max(sharpe_std, 0.1))
    mintrl_08 = min_track_record_length(net_ls, sr_target=0.8)
    mintrl_05 = min_track_record_length(net_ls, sr_target=0.5)

    # 分年诊断
    years = sorted(set(net_ls.index.year))
    yrows = []
    for y in years:
        gy = gross_ls[gross_ls.index.year == y]
        ny = net_ls[net_ls.index.year == y]
        yrows.append({
            "year": int(y), "n": len(ny),
            "gross_sr": float(sharpe_ratio(gy)) if len(gy) > 5 else np.nan,
            "net_sr": float(sharpe_ratio(ny)),
            "net_ann": float(annualized_return(ny)),
            "net_mdd": float(max_drawdown(ny)),
        })
    y_df = pd.DataFrame(yrows)

    today = date.today().strftime("%Y%m%d")
    out_md = Path(f"journal/v33_reversal_ls_tradeable_{today}.md")
    L: list[str] = []
    L.append(f"# v33 = reversal_skip1m tradeable L/S — 预注册单次实验 — {today}")
    L.append("")
    L.append(f"> 预注册: Q5-Q1 日频等权, borrow {BORROW_ANNUAL:.0%}, txn/side {TXN_PER_SIDE:.3%}")
    L.append(f"> eval {net_ls.index[0].date()}~{net_ls.index[-1].date()} n={len(net_ls)}")
    L.append(f"> DSR n_trials={N_TRIALS}, sharpe_std={sharpe_std:.3f}")
    L.append("")

    L.append("## 1. gross vs net 对比")
    L.append("")
    L.append(pd.DataFrame([m_gross, m_net]).to_markdown(index=False, floatfmt=".4f"))
    L.append("")
    drag_annual = (m_gross["ann_return"] - m_net["ann_return"])
    L.append(f"- 总摩擦年化: {drag_annual:.2%} "
             f"(融券 {BORROW_ANNUAL:.2%} + txn 估 {drag_annual - BORROW_ANNUAL:.2%})")
    L.append(f"- 长腿日均换手 {tl.mean():.2%}, 短腿 {ts.mean():.2%}")
    L.append("")

    L.append("## 2. Admission 判定")
    L.append("")
    L.append(f"- gross LS: {a_gross}")
    L.append(f"- **net LS (tradeable)**: {a_net}")
    L.append("")

    L.append("## 3. net LS 统计推断")
    L.append("")
    L.append(f"- Bootstrap 95% CI: [{ci_net['ci_low']:.3f}, {ci_net['ci_high']:.3f}]")
    L.append(f"- CI 下界 > 0.80: {'OK' if ci_net['ci_low'] > 0.80 else 'FAIL'}")
    L.append(f"- DSR (n_trials={N_TRIALS}, std={sharpe_std:.3f}): **{dsr_net:.4f}**")
    L.append(f"- DSR > 0.95: {'OK' if dsr_net >= DSR_TARGET else 'FAIL'}")
    L.append(f"- MinTRL vs sr=0.5: {mintrl_05:.0f} 日 ({mintrl_05/252:.1f} 年)")
    L.append(f"- MinTRL vs sr=0.8: {mintrl_08:.0f} 日 ({mintrl_08/252:.1f} 年)")
    L.append("")

    L.append("## 4. 分年诊断")
    L.append("")
    L.append(y_df.to_markdown(index=False, floatfmt=".4f"))
    L.append("")

    L.append("## 5. 诚实结论")
    L.append("")
    L.append(f"- gross sharpe: {m_gross['sharpe']:.3f}, net sharpe: {m_net['sharpe']:.3f}")
    L.append(f"- 摩擦扣除幅度: {m_gross['sharpe'] - m_net['sharpe']:.3f} sharpe 点")
    L.append(f"- admission 四门 (net): {'OK' if a_net['all_pass'] else 'FAIL'}")
    L.append(f"- DSR (net, n_trials={N_TRIALS}): {'OK' if dsr_net >= DSR_TARGET else 'FAIL'}")
    L.append(f"- CI 下界 > 0.80 (net): {'OK' if ci_net['ci_low'] > 0.80 else 'FAIL'}")
    L.append("")
    pass_adm = a_net["all_pass"]
    pass_dsr = dsr_net >= DSR_TARGET
    pass_ci = ci_net["ci_low"] > 0.80
    if pass_adm and pass_dsr and pass_ci:
        L.append("**三重过门**: reversal_skip1m 扣融券+txn 后仍真正 tradeable。")
        L.append("下一步: 加可融券标的过滤 (更现实), 再确认是否稳健。")
    elif pass_adm and not pass_dsr:
        L.append("**admission 过, DSR 不过**: sample 内强但扣 selection bias (n_trials=10) 后不显著。")
        L.append("合规: 不声称过门, 转 paper-trading 累积 OOS。")
    elif not pass_adm:
        L.append("**net admission 未过**: 融券成本 + txn 把表面强 sharpe 击穿。")
        L.append("含义: 之前报告的 'LS sharpe=1.497' 是学术 gross 值, 实操需要附注。")
        L.append("合规: 停止反转因子方向, 不重试调参数。")
    L.append("")

    L.append("## 6. 严禁 (红线)")
    L.append("")
    L.append("- 不换因子 (reversal_1m, reversal_5d, etc.)")
    L.append("- 不换 quintile (10/20 分位)")
    L.append("- 不调 borrow / txn / long-short 口径")
    L.append("- 不加 regime/overlay")
    L.append("- 失败就写结论, 不 ad-hoc")
    L.append("")

    out_md.write_text("\n".join(L), encoding="utf-8")
    print(f"\n写出 {out_md}")
    print("\n=== 汇总 ===")
    print(f"  gross LS: ann={m_gross['ann_return']:.2%} sr={m_gross['sharpe']:.3f} mdd={m_gross['mdd']:.2%}")
    print(f"  net LS:   ann={m_net['ann_return']:.2%} sr={m_net['sharpe']:.3f} mdd={m_net['mdd']:.2%}")
    print(f"  admission net: {a_net['all_pass']}")
    print(f"  DSR net: {dsr_net:.4f} (target {DSR_TARGET})")
    print(f"  CI net: [{ci_net['ci_low']:.3f}, {ci_net['ci_high']:.3f}]")


if __name__ == "__main__":
    main()
