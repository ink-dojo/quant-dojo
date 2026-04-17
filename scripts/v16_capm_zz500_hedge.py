"""
v16 CAPM β-hedge — market proxy = ZZ500 (399905) 预注册单次实验。

动机 (来自 v16_capm_alpha_20260417.md §8):
  HS300 hedge 失败 (MDD -38.28%), 多变量 OLS 显示 v16 真实 market proxy 是 ZZ500
  (R² 0.610 vs HS300 0.407). 本实验验证 "用正确 proxy hedge 能否过 admission+DSR"。

预注册 (写在代码里, 不是事后补的):
  - window = 252 (与 HS300 实验同参数, 不调优)
  - β 估计: rolling OLS, shift(1) 避免偷看
  - market proxy: ZZ500 (399905) — 基于 ex-ante univariate R² 排序选择, 不是事后扫
  - admission 门槛: ann>15%, sharpe>0.80, mdd>-30%, PSR0>0.95
  - DSR n_trials = 6 (v16/v25/v27/v28-breadth/v29-HS300hedge/v30-ZZ500hedge)

规则 (严禁 p-hack):
  - 若本次不过门, 诚实停止, 不换 window / 不换 proxy / 不换估计方法重试
  - 任何 "边缘不过" 的微调都是 selection bias 放大
  - 本次 DSR 失败的含义: 即使 "对的 market proxy" 也救不活 v16 的 α
"""
from __future__ import annotations

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

WARMUP = "2019-01-01"
START = "2022-01-01"
END = "2025-12-31"
N_STOCKS = 30
ROLL_WIN = 252  # CAPM 经典, 与 HS300 实验完全一致
PROXY_SYMBOL = "399905"  # ZZ500
PROXY_NAME = "ZZ500"
N_TRIALS = 6  # v16/v25/v27/v28-breadth/v29-HS300hedge/v30-ZZ500hedge


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


def load_proxy_ret(sym: str) -> pd.Series:
    px = load_price_wide([sym], "2018-01-01", END, field="close")[sym].dropna()
    return px.pct_change().dropna()


def full_ols(y: pd.Series, x: pd.Series) -> dict:
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
    return {
        "n": n,
        "alpha_daily": float(alpha),
        "alpha_ann": float(alpha * 252),
        "beta": float(beta),
        "t_alpha": float(alpha / se_alpha if se_alpha > 0 else np.nan),
        "t_beta": float(beta / se_beta if se_beta > 0 else np.nan),
        "r2": float(r2),
        "resid_std_ann": float(se_resid * np.sqrt(252)),
    }


def rolling_beta_hedge(y: pd.Series, x: pd.Series, window: int = 252) -> pd.Series:
    aligned = pd.concat([y.rename("y"), x.rename("x")], axis=1).dropna()
    cov_w = aligned["y"].rolling(window, min_periods=60).cov(aligned["x"])
    var_w = aligned["x"].rolling(window, min_periods=60).var()
    beta_w = (cov_w / var_w).shift(1)
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
    print(f"[1/5] 加载 v16 和 {PROXY_NAME} ({PROXY_SYMBOL}) 收益…")
    v16 = load_v16()
    proxy = load_proxy_ret(PROXY_SYMBOL)
    common = v16.index.intersection(proxy.index)
    v16, proxy = v16.loc[common], proxy.loc[common]
    print(f"  对齐后 n={len(common)}, {common[0].date()}~{common[-1].date()}")

    print(f"[2/5] 全期 CAPM OLS on {PROXY_NAME}…")
    ols = full_ols(v16, proxy)
    print(f"  α_ann={ols['alpha_ann']:.2%}  β={ols['beta']:.3f}  "
          f"t_α={ols['t_alpha']:.2f}  t_β={ols['t_beta']:.2f}  R²={ols['r2']:.3f}")

    print(f"[3/5] Rolling {ROLL_WIN}d β-hedge with {PROXY_NAME}…")
    hedged = rolling_beta_hedge(v16, proxy, window=ROLL_WIN)
    print(f"  hedged 有效 n={len(hedged)}")

    print("[4/5] metrics…")
    m_v16 = metrics_block(v16, "v16 (unhedged)")
    m_bench = metrics_block(proxy, f"{PROXY_NAME} (benchmark)")
    m_hedg = metrics_block(hedged, f"v16-β{PROXY_NAME} (hedged)")

    a_hedg = admission(m_hedg)

    print("[5/5] hedged 统计推断…")
    ci = bootstrap_sharpe_ci(hedged, n_boot=2000, alpha=0.05, seed=42)
    # DSR: 严格些, n_trials=6 含 ZZ500, std 用 ZZ500 hedge + HS300 hedge + 3 base 曲线
    # HS300 hedged sharpe = 0.835 (from prior journal), ZZ500 现算
    hs300_hedged_sharpe = 0.8354
    sharpe_pool = [m_v16["sharpe"], m_bench["sharpe"], m_hedg["sharpe"], hs300_hedged_sharpe]
    sharpe_std = float(np.std(sharpe_pool, ddof=1))
    dsr = deflated_sharpe(hedged, n_trials=N_TRIALS, trials_sharpe_std=max(sharpe_std, 0.1))
    mintrl_08 = min_track_record_length(hedged, sr_target=0.8)
    mintrl_05 = min_track_record_length(hedged, sr_target=0.5)

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

    today = date.today().strftime("%Y%m%d")
    lines: list[str] = []
    lines.append(f"# v16 CAPM β-hedge with ZZ500 — 预注册单次实验 — {today}")
    lines.append("")
    lines.append(f"> 数据: v16 fresh equity, {PROXY_NAME} ({PROXY_SYMBOL}) 日收益, eval {common[0].date()}~{common[-1].date()} n={len(common)}")
    lines.append(f"> 方法: 全期 OLS + rolling {ROLL_WIN}d β-hedge (shift(1)), 与 HS300 实验同参数")
    lines.append(f"> 动机: HS300 multi-factor OLS 显示 v16 真实暴露在 ZZ500 (R² 0.610 > 0.407)")
    lines.append(f"> ⚠️ 理论上限: **不含** 展期成本, 保证金占用, IC 期货基差")
    lines.append("")

    lines.append("## 1. 全期 CAPM OLS 分解")
    lines.append("")
    lines.append(f"r_v16 = α + β × r_{PROXY_NAME} + ε")
    lines.append("")
    lines.append(f"- α (年化): **{ols['alpha_ann']:.2%}** (t = {ols['t_alpha']:.2f})")
    lines.append(f"- β: **{ols['beta']:.3f}** (t = {ols['t_beta']:.2f})")
    lines.append(f"- R²: **{ols['r2']:.3f}** (HS300 实验中为 0.407, 本次 proxy 解释力更高)")
    lines.append(f"- 残差波动 (年化): {ols['resid_std_ann']:.2%}")
    lines.append("")

    lines.append("## 2. Hedged 曲线 metrics")
    lines.append("")
    df_m = pd.DataFrame([m_v16, m_bench, m_hedg])
    lines.append(df_m.to_markdown(index=False, floatfmt=".4f"))
    lines.append("")

    lines.append("## 3. Admission 判定 (hedged)")
    lines.append("")
    lines.append(f"- ann_return > 15%: {'✅' if a_hedg['ann_pass'] else '❌'} ({m_hedg['ann_return']:.2%})")
    lines.append(f"- sharpe > 0.80:   {'✅' if a_hedg['sharpe_pass'] else '❌'} ({m_hedg['sharpe']:.3f})")
    lines.append(f"- mdd > -30%:      {'✅' if a_hedg['mdd_pass'] else '❌'} ({m_hedg['mdd']:.2%})")
    lines.append(f"- PSR0 > 0.95:     {'✅' if a_hedg['psr0_pass'] else '❌'} ({m_hedg['psr_0']:.4f})")
    lines.append(f"- 四门合格:        {'✅' if a_hedg['all_pass'] else '❌'}")
    lines.append("")

    lines.append("## 4. Hedged 统计推断")
    lines.append("")
    lines.append(f"- Bootstrap 95% CI: [{ci['ci_low']:.3f}, {ci['ci_high']:.3f}]")
    lines.append(f"- CI 下界 > 0.80: {'✅' if ci['ci_low'] > 0.80 else '❌'}")
    lines.append(f"- DSR (n_trials={N_TRIALS}, std={sharpe_std:.3f}): **{dsr:.4f}**")
    lines.append(f"- DSR > 0.95: {'✅' if dsr >= 0.95 else '❌'}")
    lines.append(f"- MinTRL vs sr=0.5: {mintrl_05:.0f} 日 ({mintrl_05/252:.1f} 年)")
    lines.append(f"- MinTRL vs sr=0.8: {mintrl_08:.0f} 日 ({mintrl_08/252:.1f} 年)")
    lines.append("")

    lines.append("## 5. 分年 hedged")
    lines.append("")
    lines.append(y_df.to_markdown(index=False, floatfmt=".4f"))
    lines.append("")

    lines.append("## 6. 对比 HS300 hedge (prior)")
    lines.append("")
    lines.append(f"| 指标 | HS300-hedged | {PROXY_NAME}-hedged | Δ |")
    lines.append(f"|:---|---:|---:|---:|")
    lines.append(f"| ann_return | 19.59% | {m_hedg['ann_return']:.2%} | {m_hedg['ann_return']-0.1959:+.2%} |")
    lines.append(f"| sharpe     | 0.835  | {m_hedg['sharpe']:.3f} | {m_hedg['sharpe']-0.8354:+.3f} |")
    lines.append(f"| mdd        | -38.28% | {m_hedg['mdd']:.2%} | {m_hedg['mdd']-(-0.3828):+.2%} |")
    lines.append(f"| R² (univariate) | 0.407 | {ols['r2']:.3f} | {ols['r2']-0.407:+.3f} |")
    lines.append("")

    lines.append("## 7. 诚实结论")
    lines.append("")
    hedged_pass_admission = a_hedg["all_pass"]
    hedged_pass_dsr = dsr >= 0.95
    hedged_ci_strong = ci["ci_low"] > 0.80
    if hedged_pass_admission and hedged_pass_dsr and hedged_ci_strong:
        lines.append(f"**三重过门**: ZZ500 作为正确 proxy, admission + DSR + CI 全过。")
        lines.append(f"下一步 (仍需工程化验证): 用 IC 股指期货 (2022-2025 主力合约) 替代指数,")
        lines.append(f"加入展期成本 (IC 贴水年化 5-10%), 保证金占用 12%, 基差风险建模。")
        lines.append(f"**警告**: 工程化 drag (IC 贴水) 大概率把 α 吞掉, 不能声称已完全过门。")
    elif hedged_pass_admission and not hedged_pass_dsr:
        lines.append(f"**admission 过, DSR 不过**: 与 HS300 版本同模式。")
        lines.append(f"即使用更高 R² 的 proxy, selection bias 调整后仍不显著。")
        lines.append(f"含义: v16 的 α 规模不足以跨越 n_trials={N_TRIALS} 的期望最大 sharpe。")
    else:
        lines.append(f"**admission 未过**: 即使正确 proxy, 理论上限仍不合格。")
        lines.append(f"确认 short-hedge 不是解药, α 不足源自因子层面, 非 hedge 参数选择。")
    lines.append("")
    lines.append("## 8. 严禁 (预注册 red line)")
    lines.append("")
    lines.append("- 不换 window (60/126/500) 重试 — 已预注册 252")
    lines.append("- 不换 proxy (SZ50/ZZ1000/GEM) 重试 — 已预注册 ZZ500")
    lines.append("- 不做 shrink/ridge/Kalman β 估计 — 已预注册 OLS")
    lines.append("- 不做 dynamic hedge ratio, 不做分 regime hedge")
    lines.append("- 若本次 admission/DSR 任意失败, 下一步必须回到 **因子层面找 stronger α**")
    lines.append("  (例: reversal 因子残余 IC 研究, cross-sectional ranking 改 ensemble)")
    lines.append("  而非 overlay hedge 方向继续钻牛角")
    lines.append("")

    out_md = Path(f"journal/v16_capm_zz500_hedge_{today}.md")
    out_md.write_text("\n".join(lines), encoding="utf-8")
    print(f"\n✓ 写出 {out_md}")

    print(f"\n=== {PROXY_NAME} hedged 速览 ===")
    print(f"  unhedged v16:     ann={m_v16['ann_return']:.2%}  sharpe={m_v16['sharpe']:.3f}")
    print(f"  ZZ500 benchmark:  ann={m_bench['ann_return']:.2%}  sharpe={m_bench['sharpe']:.3f}")
    print(f"  hedged v16:       ann={m_hedg['ann_return']:.2%}  sharpe={m_hedg['sharpe']:.3f}  mdd={m_hedg['mdd']:.2%}")
    print(f"  admission: {a_hedg}")
    print(f"  DSR: {dsr:.4f}  (n_trials={N_TRIALS}, std={sharpe_std:.3f})")
    print(f"  bootstrap CI: [{ci['ci_low']:.3f}, {ci['ci_high']:.3f}]")


if __name__ == "__main__":
    main()
