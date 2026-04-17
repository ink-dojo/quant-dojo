"""
v16 CAPM α/β 分解研究 — short-hedge 可行性上限分析。

研究问题: 对 v16 做 rolling β-hedge (做空 HS300 按滚动 β 比例),
          剥离市场 β 暴露后的纯 α 是否 sharpe > 0.8 显著?

方法 (经典 CAPM, 不调参):
  1. 全期 OLS: r_v16 = α + β × r_hs300 + ε
     — 给出 full-sample β estimate 和 α t-stat
  2. Rolling 252-day OLS: β_t = cov(r_v16[t-252:t], r_hs300[t-252:t]) / var(r_hs300[t-252:t])
     — shift(1) 避免未来数据
  3. Hedged 收益: r_hedged_t = r_v16_t - β_{t-1} × r_hs300_t
     — 这是 "零成本" 理论上限, 实盘要加展期/保证金/基差成本
  4. admission 检查 hedged 曲线 + Bootstrap + DSR

含义判定:
  - 若 hedged sharpe > 0.8 且 DSR > 0.95 → short-hedge 值得工程化
  - 若 hedged sharpe 仍 < 0.8 → v16 纯 α 不足, hedge 也不救, 回到因子层面

不抄近道: α 不是通过任何参数调出来的, 是 OLS 直出; 任何滚动窗口 (252) 是
CAPM 经典默认, 未做 grid search。

输出: journal/v16_capm_alpha_{date}.md
"""
from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import numpy as np
import pandas as pd
from scipy import stats

from pipeline.strategy_registry import get_strategy
from utils.local_data_loader import get_all_symbols, load_price_wide
from utils.metrics import (
    annualized_return, annualized_volatility, sharpe_ratio,
    max_drawdown, win_rate, probabilistic_sharpe, deflated_sharpe,
    bootstrap_sharpe_ci, min_track_record_length,
)

WARMUP = "2019-01-01"
START = "2022-01-01"
END = "2025-12-31"
N_STOCKS = 30
ROLL_WIN = 252  # CAPM 经典 1 年滚动


def load_v16() -> pd.Series:
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


def load_hs300_ret() -> pd.Series:
    hs300 = load_price_wide(["399300"], "2018-01-01", END, field="close")["399300"].dropna()
    return hs300.pct_change().dropna()


def full_ols(y: pd.Series, x: pd.Series) -> dict:
    """全期 OLS y = α + β x + ε, 返回 α, β, t-stats, R²。"""
    aligned = pd.concat([y.rename("y"), x.rename("x")], axis=1).dropna()
    yv = aligned["y"].values
    xv = aligned["x"].values
    n = len(yv)
    x_mean, y_mean = xv.mean(), yv.mean()
    cov = ((xv - x_mean) * (yv - y_mean)).sum()
    var_x = ((xv - x_mean) ** 2).sum()
    beta = cov / var_x
    alpha = y_mean - beta * x_mean
    resid = yv - (alpha + beta * xv)
    tss = ((yv - y_mean) ** 2).sum()
    rss = (resid ** 2).sum()
    r2 = 1 - rss / tss if tss > 0 else 0.0
    se_resid = np.sqrt(rss / (n - 2))
    se_beta = se_resid / np.sqrt(var_x)
    se_alpha = se_resid * np.sqrt(1 / n + x_mean ** 2 / var_x)
    t_alpha = alpha / se_alpha if se_alpha > 0 else np.nan
    t_beta = beta / se_beta if se_beta > 0 else np.nan
    return {
        "n": n,
        "alpha_daily": float(alpha),
        "alpha_ann": float(alpha * 252),
        "beta": float(beta),
        "t_alpha": float(t_alpha),
        "t_beta": float(t_beta),
        "r2": float(r2),
        "resid_std_ann": float(se_resid * np.sqrt(252)),
    }


def rolling_beta_hedge(y: pd.Series, x: pd.Series, window: int = 252) -> pd.Series:
    """滚动 β 估计 (shift(1) 避免偷看) → r_hedged = y - β_{t-1} × x_t。"""
    aligned = pd.concat([y.rename("y"), x.rename("x")], axis=1).dropna()
    cov_w = aligned["y"].rolling(window, min_periods=60).cov(aligned["x"])
    var_w = aligned["x"].rolling(window, min_periods=60).var()
    beta_w = (cov_w / var_w).shift(1)  # 用 t-1 之前的数据估
    hedged = aligned["y"] - beta_w * aligned["x"]
    return hedged.dropna().rename("r_hedged")


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
        "win_rate": float(win_rate(r)),
    }


def admission(m):
    return {
        "ann_pass": m["ann_return"] > 0.15,
        "sharpe_pass": m["sharpe"] > 0.80,
        "mdd_pass": m["mdd"] > -0.30,
        "psr0_pass": m["psr_0"] > 0.95,
        "all_pass": (m["ann_return"] > 0.15 and m["sharpe"] > 0.80
                     and m["mdd"] > -0.30 and m["psr_0"] > 0.95),
    }


def main():
    print("[1/5] 加载 v16 和 HS300 收益…")
    v16 = load_v16()
    hs300 = load_hs300_ret()
    common = v16.index.intersection(hs300.index)
    v16, hs300 = v16.loc[common], hs300.loc[common]
    print(f"  对齐后 n={len(common)}, {common[0].date()}~{common[-1].date()}")

    print("[2/5] 全期 CAPM OLS…")
    ols = full_ols(v16, hs300)
    print(f"  α_ann={ols['alpha_ann']:.2%}  β={ols['beta']:.3f}  "
          f"t_α={ols['t_alpha']:.2f}  t_β={ols['t_beta']:.2f}  R²={ols['r2']:.3f}")

    print(f"[3/5] Rolling {ROLL_WIN}d β-hedge…")
    hedged = rolling_beta_hedge(v16, hs300, window=ROLL_WIN)
    print(f"  hedged 有效 n={len(hedged)}")

    print("[4/5] metrics…")
    m_v16 = metrics_block(v16, "v16 (unhedged)")
    m_bench = metrics_block(hs300, "HS300 (benchmark)")
    m_hedg = metrics_block(hedged, "v16-βHS300 (hedged)")

    a_v16 = admission(m_v16)
    a_hedg = admission(m_hedg)

    # Bootstrap + DSR + MinTRL for hedged
    print("[5/5] hedged 统计推断…")
    ci = bootstrap_sharpe_ci(hedged, n_boot=2000, alpha=0.05, seed=42)
    # DSR: short-hedge 是独立研究方向 (非 regime sweep 家族), 视为新候选
    # 保守: n_trials=5 (v16/v25/v27/v28=hedge/v29=breadth), std 用本次 3 曲线
    sharpe_std_across = np.std([m_v16["sharpe"], m_hedg["sharpe"], m_bench["sharpe"]], ddof=1)
    dsr = deflated_sharpe(hedged, n_trials=5, trials_sharpe_std=max(sharpe_std_across, 0.1))
    mintrl_08 = min_track_record_length(hedged, sr_target=0.8)
    mintrl_05 = min_track_record_length(hedged, sr_target=0.5)

    # 分年
    years = sorted(set(hedged.index.year))
    y_rows = []
    for y in years:
        ry = hedged[hedged.index.year == y]
        y_rows.append({
            "year": int(y), "n": len(ry),
            "ann_return": float(annualized_return(ry)),
            "sharpe": float(sharpe_ratio(ry)),
            "mdd": float(max_drawdown(ry)),
        })
    y_df = pd.DataFrame(y_rows)

    # Markdown
    today = date.today().strftime("%Y%m%d")
    lines = []
    lines.append(f"# v16 CAPM α/β 分解 — short-hedge 可行性上限 — {today}")
    lines.append("")
    lines.append(f"> 数据: v16 fresh equity, HS300 日收益, eval {common[0].date()}~{common[-1].date()} n={len(common)}")
    lines.append(f"> 方法: 全期 OLS + rolling {ROLL_WIN}d β-hedge (shift(1))")
    lines.append(f"> ⚠️ 理论上限: **不含** 展期成本, 保证金占用, 基差风险 — 实盘必更差")
    lines.append("")

    lines.append("## 1. 全期 CAPM OLS 分解")
    lines.append("")
    lines.append(f"r_v16 = α + β × r_HS300 + ε")
    lines.append("")
    lines.append(f"- α (年化): **{ols['alpha_ann']:.2%}** (t = {ols['t_alpha']:.2f})")
    lines.append(f"- β: **{ols['beta']:.3f}** (t = {ols['t_beta']:.2f})")
    lines.append(f"- R²: {ols['r2']:.3f}")
    lines.append(f"- 残差波动 (年化): {ols['resid_std_ann']:.2%}")
    lines.append("")
    lines.append(f"解读: v16 暴露于市场 β={ols['beta']:.2f}, " +
                 ("非零显著" if abs(ols['t_beta']) > 2 else "非零不显著") +
                 f"; 纯 α 年化 {ols['alpha_ann']:.2%} " +
                 ("t 显著" if abs(ols['t_alpha']) > 2 else "**t 不显著**"))
    lines.append("")

    lines.append("## 2. Hedged 曲线 metrics")
    lines.append("")
    df_m = pd.DataFrame([m_v16, m_bench, m_hedg])
    lines.append(df_m.to_markdown(index=False, floatfmt=".4f"))
    lines.append("")

    lines.append("## 3. Admission 判定")
    lines.append("")
    lines.append(f"- v16 unhedged: {a_v16}")
    lines.append(f"- hedged (理论上限): {a_hedg}")
    lines.append("")

    lines.append("## 4. Hedged 统计推断")
    lines.append("")
    lines.append(f"- Bootstrap 95% CI: [{ci['ci_low']:.3f}, {ci['ci_high']:.3f}]")
    lines.append(f"- CI 下界 > 0.80: {'✅' if ci['ci_low'] > 0.80 else '❌'}")
    lines.append(f"- DSR (n_trials=5, std={max(sharpe_std_across, 0.1):.3f}): **{dsr:.4f}**")
    lines.append(f"- MinTRL vs sr=0.5: {mintrl_05:.0f} 日 ({mintrl_05/252:.1f} 年)")
    lines.append(f"- MinTRL vs sr=0.8: {mintrl_08:.0f} 日 ({mintrl_08/252:.1f} 年)")
    lines.append("")

    lines.append("## 5. 分年 hedged")
    lines.append("")
    lines.append(y_df.to_markdown(index=False, floatfmt=".4f"))
    lines.append("")

    lines.append("## 6. 诚实结论")
    lines.append("")
    hedged_pass_admission = a_hedg["all_pass"]
    hedged_pass_dsr = dsr >= 0.95
    hedged_ci_strong = ci["ci_low"] > 0.80
    lines.append(f"- hedged admission 四门: {'✅' if hedged_pass_admission else '❌'}")
    lines.append(f"- hedged DSR: {'✅' if hedged_pass_dsr else '❌'}")
    lines.append(f"- hedged 95% CI 下界 > 0.80: {'✅' if hedged_ci_strong else '❌'}")
    lines.append("")
    if hedged_pass_admission and hedged_pass_dsr and hedged_ci_strong:
        lines.append("**强过门**: 纯 α 在理论上限下达到 admission + DSR + CI 三重显著。")
        lines.append("下一步: 工程化 short-hedge, 用 IH/IF 股指期货替代 HS300 指数,")
        lines.append("加入展期成本 (年化 3-5%)、保证金 (12-14%)、基差风险建模。")
        lines.append("**警告**: 工程化 drag 之后可能打回, 不能声称已过门。")
    elif hedged_pass_admission and not hedged_pass_dsr:
        lines.append("**边缘过门**: admission 过, DSR 不过。")
        lines.append("含义: 纯 α 存在, 但小到扣除 selection bias 后不显著。")
        lines.append("即使理论 hedge 上限都够不到 DSR>0.95, 工程化后更不可能。")
        lines.append("合规路径: 不工程化 short-hedge, 回到因子层面找 stronger α。")
    elif not hedged_pass_admission:
        lines.append("**不过门**: 理论上限都未达到 admission。")
        lines.append("这证明 v16 的 α (剥离 β 后) 本身不足, short-hedge 不是解药。")
        lines.append("合规路径: 必须从底层因子 alpha 提升入手, 而非 overlay hedge。")
        lines.append("可能方向: (a) 找更强的 regime-robust 因子, (b) 换因子加权方案")
        lines.append("(如 LASSO IR optimize), (c) 扩展到更广的 asset class。")
    lines.append("")
    lines.append("## 7. 严禁 (p-hack 红线)")
    lines.append("")
    lines.append("- 不去调 rolling window ∈ {60, 126, 252, 500} 找 'hedge 后 sharpe 最大' 的窗口")
    lines.append("- 不去调 β 估计方法 (OLS vs WLS vs Kalman) 做 model selection 找最优")
    lines.append("- 不做分 regime β-hedge 的 ad-hoc 扩展 (那等于双重 HS300 feedback)")

    out_md = Path(f"journal/v16_capm_alpha_{today}.md")
    out_md.write_text("\n".join(lines), encoding="utf-8")
    print(f"\n✓ 写出 {out_md}")

    print("\n=== hedged 速览 ===")
    print(f"  unhedged v16: ann={m_v16['ann_return']:.2%}  sharpe={m_v16['sharpe']:.3f}  β={ols['beta']:.3f}")
    print(f"  hedged    v16: ann={m_hedg['ann_return']:.2%}  sharpe={m_hedg['sharpe']:.3f}  mdd={m_hedg['mdd']:.2%}")
    print(f"  admission hedged: {a_hedg}")
    print(f"  DSR hedged: {dsr:.4f}")
    print(f"  bootstrap CI: [{ci['ci_low']:.3f}, {ci['ci_high']:.3f}]")


if __name__ == "__main__":
    main()
