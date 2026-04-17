"""
v16 + TSM 多策略集成 — 预注册单次实验。

动机 (来自 tsm_index_20260417.md):
  - TSM 单独 sharpe 负, 但与 v16 相关性 -0.143 (独立)
  - 2022 TSM sharpe=+0.62, v16 sharpe=-0.67 — 严格反相, diversification 价值集中在 v16 最痛的年份
  - 合规路径: 测 v16 + TSM 合并是否 admission + DSR 双过

预注册权重方案 (ex-ante, 不调参):
  方案 A: 50/50 等权 (零自由度)
  方案 B: inverse-vol using 2019-01 ~ 2021-12 warmup 期 vol (单一确定性方案)

DSR n_trials = 9 (v16/v25/v27/v28-breadth/v29-HS300/v30-ZZ500/v28-reversal/v31-TSM/v32-combo)

严禁:
  - 不改权重 scheme (只测 A 和 B 两种预注册方案)
  - 不改 TSM lookback
  - 不删除 v16 或 TSM 任一侧
  - 不加 overlay (regime filter / stop loss 等)
  - 若 A 和 B 都失败, 诚实停止
"""
from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import numpy as np
import pandas as pd

from utils.local_data_loader import get_all_symbols, load_price_wide
from utils.metrics import (
    annualized_return, annualized_volatility, sharpe_ratio,
    max_drawdown, win_rate, probabilistic_sharpe, deflated_sharpe,
    bootstrap_sharpe_ci, min_track_record_length,
)
from pipeline.strategy_registry import get_strategy

WARMUP = "2019-01-01"
WARMUP_END = "2021-12-31"  # 用于 ex-ante vol 估计
START = "2022-01-01"
END = "2025-12-31"
LOOKBACK = 126
COST_PER_TURN = 0.0015
N_TRIALS_COMBO = 9


def tsm_signal(close: pd.Series, lookback: int = 126) -> pd.Series:
    log_close = np.log(close)
    past_ret = log_close - log_close.shift(lookback)
    return np.sign(past_ret).shift(1).fillna(0)


def tsm_return(close: pd.Series, sig: pd.Series, cost: float) -> pd.Series:
    dr = close.pct_change()
    gross = (sig * dr).fillna(0)
    turn = sig.diff().abs().fillna(0)
    return gross - cost * turn


def load_v16_full() -> pd.Series:
    symbols = get_all_symbols()
    price = load_price_wide(symbols, WARMUP, END, field="close")
    valid = price.columns[price.notna().sum() > 500]
    price = price[list(valid)]
    entry = get_strategy("multi_factor_v16")
    strat = entry.factory({"n_stocks": 30})
    res = strat.run(price)
    col = "portfolio_return" if "portfolio_return" in res.columns else "returns"
    r = res[col].astype(float)
    return r


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
    print("[1/5] 加载 v16 完整 equity…")
    r_v16_full = load_v16_full()
    # 去掉前面全零段
    first_nz = r_v16_full.ne(0).idxmax() if r_v16_full.ne(0).any() else r_v16_full.index[0]
    r_v16_full = r_v16_full.loc[first_nz:]

    print("[2/5] 构建 TSM 50/50 完整序列…")
    hs300 = load_price_wide(["399300"], WARMUP, END, field="close")["399300"].dropna()
    zz500 = load_price_wide(["399905"], WARMUP, END, field="close")["399905"].dropna()
    r_tsm_h = tsm_return(hs300, tsm_signal(hs300, LOOKBACK), COST_PER_TURN)
    r_tsm_z = tsm_return(zz500, tsm_signal(zz500, LOOKBACK), COST_PER_TURN)
    common_tsm = r_tsm_h.index.intersection(r_tsm_z.index)
    r_tsm = 0.5 * r_tsm_h.loc[common_tsm] + 0.5 * r_tsm_z.loc[common_tsm]

    print("[3/5] 对齐 + 估计 warmup 期 vol…")
    common = r_v16_full.index.intersection(r_tsm.index)
    r_v16 = r_v16_full.loc[common]
    r_tsm = r_tsm.loc[common]

    warmup_mask = (r_v16.index >= pd.Timestamp(WARMUP)) & (r_v16.index <= pd.Timestamp(WARMUP_END))
    vol_v16 = float(r_v16.loc[warmup_mask].std() * np.sqrt(252))
    vol_tsm = float(r_tsm.loc[warmup_mask].std() * np.sqrt(252))
    print(f"  warmup vol: v16={vol_v16:.2%}  TSM={vol_tsm:.2%}")

    # Eval 段
    eval_mask = (r_v16.index >= pd.Timestamp(START)) & (r_v16.index <= pd.Timestamp(END))
    r_v16_e = r_v16.loc[eval_mask]
    r_tsm_e = r_tsm.loc[eval_mask]

    print("[4/5] 组合 A=50/50, B=inverse-vol…")
    r_combo_A = 0.5 * r_v16_e + 0.5 * r_tsm_e

    inv_v, inv_t = 1 / max(vol_v16, 1e-6), 1 / max(vol_tsm, 1e-6)
    w_v, w_t = inv_v / (inv_v + inv_t), inv_t / (inv_v + inv_t)
    print(f"  inverse-vol weights: v16={w_v:.3f}  TSM={w_t:.3f}")
    r_combo_B = w_v * r_v16_e + w_t * r_tsm_e

    print("[5/5] metrics + 推断…")
    m_v16 = metrics(r_v16_e, "v16 只")
    m_tsm = metrics(r_tsm_e, "TSM 50/50 只")
    m_A = metrics(r_combo_A, "v16+TSM 等权")
    m_B = metrics(r_combo_B, f"v16+TSM invVol ({w_v:.2f}/{w_t:.2f})")

    a_v16 = admission(m_v16)
    a_A = admission(m_A)
    a_B = admission(m_B)

    sharpe_pool = [m_v16["sharpe"], m_tsm["sharpe"], m_A["sharpe"], m_B["sharpe"],
                   0.835, 1.050, 0.836]  # prior trials
    sharpe_std = float(np.std(sharpe_pool, ddof=1))

    ci_A = bootstrap_sharpe_ci(r_combo_A, n_boot=2000, alpha=0.05, seed=42)
    ci_B = bootstrap_sharpe_ci(r_combo_B, n_boot=2000, alpha=0.05, seed=42)
    dsr_A = deflated_sharpe(r_combo_A, n_trials=N_TRIALS_COMBO, trials_sharpe_std=max(sharpe_std, 0.1))
    dsr_B = deflated_sharpe(r_combo_B, n_trials=N_TRIALS_COMBO, trials_sharpe_std=max(sharpe_std, 0.1))

    mintrl_A = min_track_record_length(r_combo_A, sr_target=0.8)
    mintrl_B = min_track_record_length(r_combo_B, sr_target=0.8)

    # 分年
    years = sorted(set(r_combo_A.index.year))
    yrows = []
    for y in years:
        rA = r_combo_A[r_combo_A.index.year == y]
        rB = r_combo_B[r_combo_B.index.year == y]
        rv = r_v16_e[r_v16_e.index.year == y]
        rt = r_tsm_e[r_tsm_e.index.year == y]
        yrows.append({
            "year": int(y), "n": len(rA),
            "v16_sr": float(sharpe_ratio(rv)) if len(rv) > 5 else np.nan,
            "TSM_sr": float(sharpe_ratio(rt)) if len(rt) > 5 else np.nan,
            "A_sr": float(sharpe_ratio(rA)),
            "B_sr": float(sharpe_ratio(rB)),
            "A_mdd": float(max_drawdown(rA)),
            "B_mdd": float(max_drawdown(rB)),
        })
    y_df = pd.DataFrame(yrows)

    today = date.today().strftime("%Y%m%d")
    out_md = Path(f"journal/v16_tsm_ensemble_{today}.md")
    L: list[str] = []
    L.append(f"# v16 + TSM 多策略集成 — 预注册 — {today}")
    L.append("")
    L.append(f"> 预注册: 方案 A (50/50), 方案 B (inverse-vol from warmup 2019-2021)")
    L.append(f"> eval {r_combo_A.index[0].date()}~{r_combo_A.index[-1].date()} n={len(r_combo_A)}")
    L.append(f"> warmup vol: v16={vol_v16:.2%}, TSM={vol_tsm:.2%}")
    L.append(f"> inverse-vol weights: v16={w_v:.3f}, TSM={w_t:.3f}")
    L.append(f"> DSR n_trials={N_TRIALS_COMBO}")
    L.append("")

    L.append("## 1. Metrics")
    L.append("")
    L.append(pd.DataFrame([m_v16, m_tsm, m_A, m_B]).to_markdown(index=False, floatfmt=".4f"))
    L.append("")

    L.append("## 2. Admission")
    L.append("")
    L.append(f"- v16 only: {a_v16}")
    L.append(f"- 方案 A (50/50): {a_A}")
    L.append(f"- 方案 B (inverse-vol): {a_B}")
    L.append("")

    L.append("## 3. 统计推断")
    L.append("")
    L.append(f"| 方案 | Sharpe | CI | CI>0.80 | DSR | DSR>0.95 | MinTRL(0.8) |")
    L.append(f"|:---|---:|:---|:---:|---:|:---:|---:|")
    L.append(f"| A 50/50 | {m_A['sharpe']:.3f} | [{ci_A['ci_low']:.3f}, {ci_A['ci_high']:.3f}] | {'✅' if ci_A['ci_low']>0.80 else '❌'} | {dsr_A:.4f} | {'✅' if dsr_A>=0.95 else '❌'} | {mintrl_A:.0f}d |")
    L.append(f"| B invVol | {m_B['sharpe']:.3f} | [{ci_B['ci_low']:.3f}, {ci_B['ci_high']:.3f}] | {'✅' if ci_B['ci_low']>0.80 else '❌'} | {dsr_B:.4f} | {'✅' if dsr_B>=0.95 else '❌'} | {mintrl_B:.0f}d |")
    L.append("")

    L.append("## 4. 分年诊断")
    L.append("")
    L.append(y_df.to_markdown(index=False, floatfmt=".4f"))
    L.append("")

    L.append("## 5. 诚实结论")
    L.append("")
    pass_any = a_A["all_pass"] or a_B["all_pass"]
    dsr_any = (dsr_A >= 0.95) or (dsr_B >= 0.95)
    if pass_any and dsr_any:
        L.append("**至少一个方案双过门**: TSM 作为 diversifier 成功, v16+TSM 合规。")
        L.append("下一步: 注册新策略 (v29 = v16+TSM), paper-trading 验证 2026 Q1+ OOS。")
    elif pass_any and not dsr_any:
        L.append("**admission 过 DSR 不过**: 组合显著性不足以扣除 selection bias (n_trials 已累积多)。")
        L.append("合规: 继续累积 live 样本, 或寻找独立 proxy 实验 (不在 backtest 样本里重测)。")
    else:
        L.append("**两方案均未过 admission**: TSM 的 diversification 价值不足以提升到 admission 线。")
        L.append("诚实停止此方向, 回到更根本的改动 (asset class 扩展, live sample 累积)。")
    L.append("")

    L.append("## 6. 严禁 (红线)")
    L.append("")
    L.append("- 不测 60/40, 70/30, 40/60 等其他权重 — 已预注册 A 和 B 两种")
    L.append("- 不改 TSM lookback (126)")
    L.append("- 不加 regime/stop/vol-target overlay")
    L.append("- 不把 v16 换成 v13/v14/v15 ensemble 等变体重试")
    L.append("- 失败就 commit 诚实结论, 不 ad-hoc 调整")
    L.append("")

    out_md.write_text("\n".join(L), encoding="utf-8")
    print(f"\n✓ 写出 {out_md}")
    print("\n=== 速览 ===")
    print(f"  v16 only: ann={m_v16['ann_return']:.2%} sr={m_v16['sharpe']:.3f} mdd={m_v16['mdd']:.2%}")
    print(f"  TSM 50/50: ann={m_tsm['ann_return']:.2%} sr={m_tsm['sharpe']:.3f} mdd={m_tsm['mdd']:.2%}")
    print(f"  方案 A (50/50):       ann={m_A['ann_return']:.2%} sr={m_A['sharpe']:.3f} mdd={m_A['mdd']:.2%} adm={a_A['all_pass']} dsr={dsr_A:.3f}")
    print(f"  方案 B (invVol {w_v:.2f}/{w_t:.2f}): ann={m_B['ann_return']:.2%} sr={m_B['sharpe']:.3f} mdd={m_B['mdd']:.2%} adm={a_B['all_pass']} dsr={dsr_B:.3f}")


if __name__ == "__main__":
    main()
