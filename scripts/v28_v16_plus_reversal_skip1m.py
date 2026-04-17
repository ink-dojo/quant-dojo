"""
v28 = v16 九因子 + reversal_skip1m — 预注册单次实验。

动机 (来自 reversal_factors_eval_20260417.md):
  reversal_skip1m 全 A HAC-t=5.18, long-short sharpe 1.497, MDD -18.94%,
  与 enhanced_mom_60 相关性仅 -0.111 (互补), 2022 熊市 sharpe=1.26。
  这是 v16 层面最强的候选残余 α。

预注册 (不调参):
  - n_stocks = 30 (与 v16 同)
  - IC 加权 (与 v16 同机制, 不改权重方案)
  - 行业中性化 (与 v16 同)
  - 新因子 reversal_skip1m 方向 = +1 (ex-ante IC=+0.017 正向)
  - eval 期 2022-01-04 ~ 2025-12-31 n=969 (与 v16 audit 对齐)
  - DSR n_trials = 7 (v16/v25/v27/v28-breadth/v29-HS300-hedge/v30-ZZ500-hedge/v28-new)

门槛:
  - admission: ann>15%, sharpe>0.80, mdd>-30%, PSR0>0.95
  - DSR ≥ 0.95 才算扣除 selection bias 后仍显著
  - 95% CI 下界 > 0.80 (保守)

严禁 (红线, 若失败):
  - 不换 direction 方向重试
  - 不替换 reversal_skip1m 为 reversal_1m / reversal_5d 重试
  - 不调 skip window (5/10/20) 找最优
  - 不删除 v16 原有因子做 "正交性优化" (那是事后剪枝)
  - 若 admission + DSR 任一失败, 诚实记录并停止, 回到更根本的层面
    (多策略集成 / asset class 扩展)
"""
from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import numpy as np
import pandas as pd

from utils.local_data_loader import get_all_symbols, load_price_wide, load_factor_wide
from utils.alpha_factors import (
    low_vol_20d, team_coin, shadow_lower,
    amihud_illiquidity, price_volume_divergence,
    turnover_acceleration, high_52w_ratio,
    momentum_6m_skip1m, win_rate_60d,
    reversal_skip1m,
)
from utils.metrics import (
    annualized_return, annualized_volatility, sharpe_ratio,
    max_drawdown, win_rate, probabilistic_sharpe, deflated_sharpe,
    bootstrap_sharpe_ci, min_track_record_length,
)
from strategies.multi_factor import MultiFactorStrategy
from strategies.base import StrategyConfig
from pipeline.strategy_registry import _load_industry_map

WARMUP = "2019-01-01"
START = "2022-01-01"
END = "2025-12-31"
N_STOCKS = 30
N_TRIALS = 7
DSR_TARGET = 0.95


def build_v16_factors(price_wide: pd.DataFrame) -> dict:
    symbols = list(price_wide.columns)
    start = str(price_wide.index[0].date())
    end = str(price_wide.index[-1].date())
    factors: dict = {}
    for name, fn, d in [
        ("low_vol_20d",   lambda: low_vol_20d(price_wide),      1),
        ("team_coin",     lambda: team_coin(price_wide),         1),
        ("high_52w",      lambda: high_52w_ratio(price_wide),   -1),
        ("mom_6m_skip1m", lambda: momentum_6m_skip1m(price_wide), -1),
        ("win_rate_60d",  lambda: win_rate_60d(price_wide),     -1),
    ]:
        try:
            factors[name] = (fn(), d)
        except Exception as e:
            print(f"  {name} 跳过: {e}")
    low_wide = load_price_wide(symbols, start, end, field="low")
    if not low_wide.empty:
        factors["shadow_lower"] = (shadow_lower(price_wide, low_wide.reindex_like(price_wide)), -1)
    vol_wide = load_price_wide(symbols, start, end, field="volume")
    if not vol_wide.empty:
        va = vol_wide.reindex_like(price_wide)
        factors["amihud_illiq"] = (amihud_illiquidity(price_wide, va), 1)
        factors["price_vol_divergence"] = (price_volume_divergence(price_wide, va), 1)
    try:
        tv = load_factor_wide(symbols, "turnover", start, end)
        if not tv.empty:
            factors["turnover_accel"] = (turnover_acceleration(tv.reindex_like(price_wide)), -1)
    except Exception as e:
        print(f"  turnover_accel 跳过: {e}")
    return factors


def run_strategy(price: pd.DataFrame, factors: dict, tag: str) -> pd.Series:
    industry_map = _load_industry_map(list(price.columns))
    cfg = StrategyConfig(name=tag)
    s = MultiFactorStrategy(
        config=cfg, factors=factors, n_stocks=N_STOCKS,
        ic_weighting=True, industry_map=industry_map, neutralize=bool(industry_map),
    )
    res = s.run(price)
    col = "portfolio_return" if "portfolio_return" in res.columns else "returns"
    r = res[col].astype(float).loc[START:END]
    first_nz = r.ne(0).idxmax() if r.ne(0).any() else r.index[0]
    return r.loc[first_nz:]


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
    print("[1/6] 加载价格…")
    symbols = get_all_symbols()
    price = load_price_wide(symbols, WARMUP, END, field="close")
    valid = price.columns[price.notna().sum() > 500]
    price = price[list(valid)]
    print(f"  股票: {len(valid)}, 日期: {len(price)}")

    print("[2/6] 构建 v16 九因子…")
    factors_v16 = build_v16_factors(price)
    print(f"  v16 因子数: {len(factors_v16)}")

    print("[3/6] 构建 v28 = v16 + reversal_skip1m…")
    factors_v28 = dict(factors_v16)
    factors_v28["reversal_skip1m"] = (reversal_skip1m(price), 1)
    print(f"  v28 因子数: {len(factors_v28)}")

    print("[4/6] 跑 v16 基准…")
    r16 = run_strategy(price, factors_v16, "v16_baseline")
    print(f"  v16 n={len(r16)} sharpe={sharpe_ratio(r16):.3f}")

    print("[5/6] 跑 v28…")
    r28 = run_strategy(price, factors_v28, "v28")
    print(f"  v28 n={len(r28)} sharpe={sharpe_ratio(r28):.3f}")

    print("[6/6] metrics + 推断…")
    m16 = metrics(r16, "v16 baseline")
    m28 = metrics(r28, "v28 (v16+reversal_skip1m)")
    a16 = admission(m16)
    a28 = admission(m28)

    ci28 = bootstrap_sharpe_ci(r28, n_boot=2000, alpha=0.05, seed=42)
    # 保守的 sharpe_std: 用本次 2 曲线 + prior HS300-hedged 0.835 + ZZ500-hedged 1.050 + v27_half 0.836
    sharpe_std = float(np.std([m16["sharpe"], m28["sharpe"], 0.835, 1.050, 0.836], ddof=1))
    dsr28 = deflated_sharpe(r28, n_trials=N_TRIALS, trials_sharpe_std=max(sharpe_std, 0.1))
    mintrl_08 = min_track_record_length(r28, sr_target=0.8)
    mintrl_05 = min_track_record_length(r28, sr_target=0.5)

    years = sorted(set(r28.index.year))
    y_rows = []
    for y in years:
        r16y = r16[r16.index.year == y]
        r28y = r28[r28.index.year == y]
        y_rows.append({
            "year": int(y), "n": len(r28y),
            "v16_sr": float(sharpe_ratio(r16y)) if len(r16y) > 10 else np.nan,
            "v28_sr": float(sharpe_ratio(r28y)),
            "v28_ann": float(annualized_return(r28y)),
            "v28_mdd": float(max_drawdown(r28y)),
        })
    y_df = pd.DataFrame(y_rows)

    today = date.today().strftime("%Y%m%d")
    out_md = Path(f"journal/v28_v16_plus_reversal_skip1m_{today}.md")
    L: list[str] = []
    L.append(f"# v28 = v16 + reversal_skip1m — 预注册单次实验 — {today}")
    L.append("")
    L.append(f"> 数据: v16 底层 + reversal_skip1m 新因子, eval {r28.index[0].date()}~{r28.index[-1].date()} n={len(r28)}")
    L.append("> 预注册: IC 加权, 30 只, 行业中性, reversal_skip1m 方向=+1")
    L.append(f"> DSR n_trials={N_TRIALS}")
    L.append("")
    L.append("## 1. Metrics 对比")
    L.append("")
    L.append(pd.DataFrame([m16, m28]).to_markdown(index=False, floatfmt=".4f"))
    L.append("")
    L.append("## 2. Admission 判定")
    L.append("")
    L.append(f"- v16 baseline: {a16}")
    L.append(f"- **v28**: {a28}")
    L.append("")
    L.append("## 3. v28 统计推断")
    L.append("")
    L.append(f"- Bootstrap 95% CI: [{ci28['ci_low']:.3f}, {ci28['ci_high']:.3f}]")
    L.append(f"- CI 下界 > 0.80: {'✅' if ci28['ci_low'] > 0.80 else '❌'}")
    L.append(f"- DSR (n_trials={N_TRIALS}, std={sharpe_std:.3f}): **{dsr28:.4f}**")
    L.append(f"- DSR > 0.95: {'✅' if dsr28 >= DSR_TARGET else '❌'}")
    L.append(f"- MinTRL vs sr=0.5: {mintrl_05:.0f} 日 ({mintrl_05/252:.1f} 年)")
    L.append(f"- MinTRL vs sr=0.8: {mintrl_08:.0f} 日 ({mintrl_08/252:.1f} 年)")
    L.append("")
    L.append("## 4. 分年 v28 vs v16")
    L.append("")
    L.append(y_df.to_markdown(index=False, floatfmt=".4f"))
    L.append("")
    L.append("## 5. 诚实结论")
    L.append("")
    pass_adm = a28["all_pass"]
    pass_dsr = dsr28 >= DSR_TARGET
    pass_ci = ci28["ci_low"] > 0.80
    L.append(f"- admission 四门: {'✅' if pass_adm else '❌'}")
    L.append(f"- DSR: {'✅' if pass_dsr else '❌'}")
    L.append(f"- 95% CI 下界 > 0.80: {'✅' if pass_ci else '❌'}")
    L.append("")
    if pass_adm and pass_dsr and pass_ci:
        L.append("**三重过门**: reversal_skip1m 作为 v28 的第 10 个因子, 显著提升 v16。")
        L.append("合规路径: 注册 v28 strategy, 继续累积 2026 Q1+ live 样本做真实 out-of-sample 验证。")
    elif pass_adm and not pass_dsr:
        L.append("**admission 过, DSR 不过**: 即使加入强因子, selection bias 调整后仍不显著。")
        L.append("含义: 样本内 sharpe 看似提升, 但相对 7 组候选的期望最大 sharpe 不足以排除运气。")
        L.append("合规路径: 不声称过门, 转入 paper-trading, 累积样本直到 DSR ≥ 0.95。")
    else:
        L.append("**admission 未过**: reversal_skip1m 没能救活 v16。")
        L.append("可能原因: (a) long-only 顶 30 采样不如 long-short 分组, (b) 因子加 IC 权重后被稀释。")
        L.append("合规下一步: 不重试加减因子, 转多策略集成 (v16 + 完全独立策略族)。")
    L.append("")
    L.append("## 6. 严禁 (红线)")
    L.append("")
    L.append("- 不换 direction 重试; 不换 reversal 窗口 (5/20/40)")
    L.append("- 不删 v16 原有因子做 '优化' (事后剪枝)")
    L.append("- 不用 equal weight / LASSO / IR optimal 等其他权重方案重试")
    L.append("- 若失败, 回到更根本的层面: 多策略集成, asset class 扩展")
    L.append("")

    out_md.write_text("\n".join(L), encoding="utf-8")
    print(f"\n✓ 写出 {out_md}")
    print("\n=== 汇总 ===")
    print(f"  v16 baseline: ann={m16['ann_return']:.2%} sharpe={m16['sharpe']:.3f} mdd={m16['mdd']:.2%}")
    print(f"  v28:          ann={m28['ann_return']:.2%} sharpe={m28['sharpe']:.3f} mdd={m28['mdd']:.2%}")
    print(f"  admission v28: {a28}")
    print(f"  DSR v28: {dsr28:.4f} (target {DSR_TARGET})")
    print(f"  CI v28: [{ci28['ci_low']:.3f}, {ci28['ci_high']:.3f}]")


if __name__ == "__main__":
    main()
