"""
v16 因子正交性分析 — 定位冗余因子。

DSR 复审发现：v11-v21 共 13 个候选的 pool-sigma 极窄（σ≈0.018），
DSR 排序≈Sharpe 排序，等价于"候选池内部高度同质化"。假设：v16 的 9 因子
里存在冗余，去掉若干就能保持 IC 不变 → 减小 selection bias 的分母，
让 DSR 真正站得住脚。

对 v16 九因子（low_vol_20d, team_coin, shadow_lower, amihud_illiq,
price_vol_divergence, high_52w, turnover_accel, mom_6m_skip1m,
win_rate_60d）做三件事：

1. **Rank-correlation matrix** — 跨截面平均的因子值 Spearman 相关矩阵。
   > 0.7 即视为高度冗余。

2. **Gram-Schmidt 残差化** — 按"IC ICIR 降序"固定顺序，对每个因子
   回归剔除前面所有因子的线性成分，看残差后的 IC / ICIR 是否还站得住。
   残差 ICIR < 0.1 的因子即为 *边际贡献微弱*，建议剔除。

3. **Marginal IC contribution** — 用 stationary bootstrap 在残差 IC
   上构造 95% CI，判断残差 IC 是否显著非零。

输出：
  - journal/factor_orthogonality_v16_{date}.md
  - portfolio/public/data/factor/orthogonality_v16.json

运行：python scripts/factor_orthogonality_analysis.py
"""
from __future__ import annotations

import json
import sys
import time
import warnings
from datetime import date
from pathlib import Path

warnings.filterwarnings("ignore")
sys.path.insert(0, str(Path(__file__).parent.parent))

import numpy as np
import pandas as pd
from scipy import stats

from utils.local_data_loader import get_all_symbols, load_price_wide, load_factor_wide
from utils.factor_analysis import compute_ic_series, ic_summary
from utils.alpha_factors import (
    low_vol_20d, team_coin, shadow_lower, amihud_illiquidity,
    price_volume_divergence, turnover_acceleration, high_52w_ratio,
    momentum_6m_skip1m, win_rate_60d,
)

# ── 常量 ───────────────────────────────────────────────
WARMUP_START = "2019-01-01"
START        = "2022-01-01"
END          = "2025-12-31"
FWD_DAYS     = 5
MIN_COVERAGE = 500  # 每只股票至少 500 个交易日
N_BOOT       = 500

# v16 九因子 (name, direction, category)
V16_FACTORS = [
    ("low_vol_20d",        +1, "risk"),
    ("team_coin",          +1, "behavioral"),
    ("shadow_lower",       -1, "price_action"),
    ("amihud_illiq",       +1, "liquidity"),
    ("price_vol_divergence", +1, "volume"),
    ("high_52w",           -1, "reversal"),
    ("turnover_accel",     -1, "volume"),
    ("mom_6m_skip1m",      -1, "reversal"),
    ("win_rate_60d",       -1, "reversal"),
]

OUTPUT_JSON = (
    Path(__file__).parent.parent
    / "portfolio" / "public" / "data" / "factor"
    / "orthogonality_v16.json"
)
OUTPUT_MD = (
    Path(__file__).parent.parent
    / "journal"
    / f"factor_orthogonality_v16_{date.today().strftime('%Y%m%d')}.md"
)


# ══════════════════════════════════════════════════════════════════
# 数据加载 & 因子计算
# ══════════════════════════════════════════════════════════════════

def load_wide_data() -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    print("[1/6] 加载宽表…")
    t0 = time.time()
    symbols = get_all_symbols()

    price = load_price_wide(symbols, WARMUP_START, END, field="close")
    valid = price.columns[price.notna().sum() > MIN_COVERAGE]
    price = price[valid]
    print(f"  close: {price.shape} (股票 {len(valid)})")

    low = load_price_wide(list(valid), WARMUP_START, END, field="low")
    low = low.reindex_like(price)

    volume = load_price_wide(list(valid), WARMUP_START, END, field="volume")
    volume = volume.reindex_like(price)

    turnover = load_factor_wide(list(valid), "turnover", WARMUP_START, END)
    turnover = turnover.reindex_like(price)

    print(f"  耗时 {time.time() - t0:.1f}s")
    return price, low, volume, turnover


def compute_factors(price, low, volume, turnover) -> dict[str, pd.DataFrame]:
    print("[2/6] 计算 9 因子…")
    t0 = time.time()
    out = {
        "low_vol_20d":           low_vol_20d(price),
        "team_coin":             team_coin(price),
        "shadow_lower":          shadow_lower(price, low),
        "amihud_illiq":          amihud_illiquidity(price, volume),
        "price_vol_divergence":  price_volume_divergence(price, volume),
        "high_52w":              high_52w_ratio(price),
        "turnover_accel":        turnover_acceleration(turnover),
        "mom_6m_skip1m":         momentum_6m_skip1m(price),
        "win_rate_60d":          win_rate_60d(price),
    }
    # 裁到分析期
    for name, df in out.items():
        out[name] = df.loc[START:END]
    print(f"  耗时 {time.time() - t0:.1f}s")
    return out


def compute_fwd_returns(price: pd.DataFrame, fwd_days: int = FWD_DAYS) -> pd.DataFrame:
    """N 日前瞻收益，shift(-fwd_days) 保证因子 t 对应 t..t+N 的收益。"""
    r = price.pct_change(fwd_days).shift(-fwd_days)
    return r.loc[START:END]


# ══════════════════════════════════════════════════════════════════
# 1. 跨截面 Rank-Corr 矩阵
# ══════════════════════════════════════════════════════════════════

def _daily_rank(df: pd.DataFrame) -> pd.DataFrame:
    """按行（每日截面）做 rank，NaN 保留。"""
    return df.rank(axis=1, pct=True)


def cross_section_rank_corr_matrix(
    factors: dict[str, pd.DataFrame],
    directions: dict[str, int],
) -> pd.DataFrame:
    """
    每日截面计算 Spearman rank-corr（= Pearson on pct-rank），
    再对时间做平均；按方向翻转后计算（所有因子方向对齐后再比）。

    返回：N×N DataFrame, index/columns 为因子名。
    """
    ranks = {}
    for name, df in factors.items():
        df_signed = df * directions[name]  # 方向对齐
        ranks[name] = _daily_rank(df_signed)

    names = list(factors.keys())
    n = len(names)
    M = np.full((n, n), np.nan)
    for i in range(n):
        for j in range(i, n):
            ri = ranks[names[i]]
            rj = ranks[names[j]]
            common_idx = ri.index.intersection(rj.index)
            daily_corrs = []
            for dt in common_idx:
                a = ri.loc[dt]
                b = rj.loc[dt]
                mask = a.notna() & b.notna()
                if mask.sum() < 30:
                    continue
                c = np.corrcoef(a[mask], b[mask])[0, 1]
                daily_corrs.append(c)
            M[i, j] = M[j, i] = float(np.nanmean(daily_corrs)) if daily_corrs else np.nan

    return pd.DataFrame(M, index=names, columns=names)


# ══════════════════════════════════════════════════════════════════
# 2. Gram-Schmidt 残差化 & 边际 IC
# ══════════════════════════════════════════════════════════════════

def residualize_against(
    target: pd.DataFrame,
    regressors: list[pd.DataFrame],
) -> pd.DataFrame:
    """
    对每日截面，用 OLS 回归 target ~ [regressors...]，返回残差。
    方便起见，regressors 未对齐 NaN 时直接取交集后回归。
    """
    out = pd.DataFrame(index=target.index, columns=target.columns, dtype=float)
    if not regressors:
        return target.copy()

    for dt in target.index:
        y = target.loc[dt]
        Xs = [r.loc[dt] if dt in r.index else pd.Series(index=y.index, dtype=float)
              for r in regressors]
        X = pd.concat(Xs, axis=1)
        mask = y.notna() & X.notna().all(axis=1)
        if mask.sum() < 30:
            continue
        y_ = y[mask].values.astype(float)
        X_ = X[mask].values.astype(float)
        # 加常数列
        X_ = np.column_stack([np.ones(len(X_)), X_])
        try:
            beta, *_ = np.linalg.lstsq(X_, y_, rcond=None)
            resid = y_ - X_ @ beta
            out.loc[dt, y[mask].index] = resid
        except Exception:
            continue
    return out


def ic_ir_of(factor: pd.DataFrame, ret: pd.DataFrame, direction: int) -> dict:
    signed = factor * direction
    ic = compute_ic_series(signed, ret, method="spearman")
    stats_d = ic_summary(ic, name="f", nw_lag=5, verbose=False)
    return {
        "ic_mean": float(stats_d["IC_mean"]) if not pd.isna(stats_d["IC_mean"]) else None,
        "icir": float(stats_d["ICIR"]) if not pd.isna(stats_d["ICIR"]) else None,
        "t_hac": float(stats_d["t_stat_hac"]) if not pd.isna(stats_d["t_stat_hac"]) else None,
        "n": int(stats_d["n"]),
        "series": ic.dropna(),
    }


# ══════════════════════════════════════════════════════════════════
# 3. Bootstrap CI of residual IC mean
# ══════════════════════════════════════════════════════════════════

def bootstrap_mean_ci(
    x: np.ndarray, n_boot: int = N_BOOT, alpha: float = 0.05, seed: int = 42,
) -> tuple[float, float]:
    """Stationary block bootstrap on x, returns 95% CI of mean."""
    x = np.asarray(x, dtype=float)
    x = x[~np.isnan(x)]
    n = len(x)
    if n < 30:
        return (float("nan"), float("nan"))
    rng = np.random.default_rng(seed)
    block_len = max(int(np.sqrt(n)), 3)
    means = np.empty(n_boot)
    for i in range(n_boot):
        idx = []
        while len(idx) < n:
            start = int(rng.integers(0, n))
            length = int(rng.geometric(1.0 / block_len))
            idx.extend(((np.arange(length) + start) % n).tolist())
        idx = np.asarray(idx[:n])
        means[i] = x[idx].mean()
    return float(np.quantile(means, alpha / 2)), float(np.quantile(means, 1 - alpha / 2))


# ══════════════════════════════════════════════════════════════════
# 主流程
# ══════════════════════════════════════════════════════════════════

def main():
    price, low, volume, turnover = load_wide_data()
    factors = compute_factors(price, low, volume, turnover)
    directions = {name: d for name, d, _ in V16_FACTORS}

    print("[3/6] 前瞻收益…")
    fwd = compute_fwd_returns(price, FWD_DAYS)

    print("[4/6] Rank-corr 矩阵…")
    t0 = time.time()
    corr = cross_section_rank_corr_matrix(factors, directions)
    print(f"  耗时 {time.time() - t0:.1f}s")
    print(corr.round(3))

    # 列出 |corr| > 0.7 的因子对
    high_pairs = []
    names = list(factors.keys())
    for i in range(len(names)):
        for j in range(i + 1, len(names)):
            c = corr.iloc[i, j]
            if np.isfinite(c) and abs(c) > 0.70:
                high_pairs.append((names[i], names[j], round(float(c), 4)))

    print("[5/6] 单因子 IC 基线…")
    t0 = time.time()
    single_ic = {}
    for name, df in factors.items():
        single_ic[name] = ic_ir_of(df, fwd, directions[name])
        ic = single_ic[name]
        print(f"  {name:22s}  IC={ic['ic_mean']:+.4f}  ICIR={ic['icir']:+.3f}  "
              f"tHAC={ic['t_hac']:+.2f}  n={ic['n']}")
    print(f"  耗时 {time.time() - t0:.1f}s")

    # ── Gram-Schmidt 顺序：按 |ICIR| 降序 ────────────────
    order = sorted(names, key=lambda n: abs(single_ic[n]["icir"] or 0.0), reverse=True)
    print(f"[6/6] Gram-Schmidt 顺序: {order}")

    residual_ic = {}
    accumulated_regressors: list[pd.DataFrame] = []
    for rank_i, name in enumerate(order):
        signed = factors[name] * directions[name]
        if not accumulated_regressors:
            resid = signed
        else:
            resid = residualize_against(signed, accumulated_regressors)
        # 残差因子对齐后与 fwd 求 IC
        ic_ser = compute_ic_series(resid, fwd, method="spearman")
        ic_clean = ic_ser.dropna()
        n_eff = len(ic_clean)
        mean_ic = float(ic_clean.mean()) if n_eff else float("nan")
        std_ic = float(ic_clean.std()) if n_eff else float("nan")
        icir = mean_ic / std_ic if std_ic and not np.isnan(std_ic) else float("nan")
        ci_lo, ci_hi = bootstrap_mean_ci(ic_clean.values)
        residual_ic[name] = {
            "order": rank_i + 1,
            "raw_ic": single_ic[name]["ic_mean"],
            "raw_icir": single_ic[name]["icir"],
            "residual_ic": mean_ic,
            "residual_icir": icir,
            "residual_ic_ci95": [ci_lo, ci_hi],
            "marginal_ratio": (mean_ic / single_ic[name]["ic_mean"])
                              if single_ic[name]["ic_mean"] else None,
            "n": n_eff,
        }
        print(f"  [{rank_i+1}] {name:22s}  raw_IC={single_ic[name]['ic_mean']:+.4f}  "
              f"resid_IC={mean_ic:+.4f}  ratio={residual_ic[name]['marginal_ratio'] or 0:+.2%}  "
              f"CI=[{ci_lo:+.4f},{ci_hi:+.4f}]")
        accumulated_regressors.append(signed)

    # ── 冗余判定 ─────────────────────────────────────
    redundant = []
    for name, info in residual_ic.items():
        lo, hi = info["residual_ic_ci95"]
        # "残差 IC 的 95% CI 跨零" → 边际贡献不显著 → 冗余
        if np.isfinite(lo) and np.isfinite(hi) and lo <= 0 <= hi:
            redundant.append(name)
        elif abs(info["residual_icir"] or 0.0) < 0.1:
            redundant.append(name)

    # ── 输出 ─────────────────────────────────────────
    result = {
        "generated_at": date.today().isoformat(),
        "window": {"start": START, "end": END, "fwd_days": FWD_DAYS},
        "factors": [
            {
                "name": n,
                "direction": directions[n],
                "category": dict((x, c) for x, _, c in V16_FACTORS)[n],
                "ic": single_ic[n]["ic_mean"],
                "icir": single_ic[n]["icir"],
                "t_hac": single_ic[n]["t_hac"],
                "n": single_ic[n]["n"],
            }
            for n in names
        ],
        "corr_matrix": corr.round(4).fillna(0).to_dict(),
        "high_corr_pairs": [
            {"a": a, "b": b, "rho": rho} for a, b, rho in high_pairs
        ],
        "gs_order": order,
        "residual_ic": residual_ic,
        "redundant_candidates": redundant,
        "note": (
            "Gram-Schmidt 按 |ICIR| 降序排序；残差 IC 的 95% CI 跨零即判定冗余。"
            "Ratio = residual_IC / raw_IC，<20% 代表该因子 80% 以上信号被前面因子吸收。"
        ),
    }

    OUTPUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_JSON.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n写出 {OUTPUT_JSON}")

    OUTPUT_MD.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_MD.write_text(render_markdown(result), encoding="utf-8")
    print(f"写出 {OUTPUT_MD}")


def render_markdown(res: dict) -> str:
    g = res["generated_at"]
    lines = [
        f"# v16 因子正交性分析 {g}",
        "",
        "> 假设：v16 的 9 因子存在冗余，候选池 σ 过窄导致 DSR ≈ Sharpe 排序。"
        "本文给出冗余因子名单与量化证据。",
        "",
        f"**样本窗口**: {res['window']['start']} – {res['window']['end']}（fwd_days={res['window']['fwd_days']}）",
        "",
        "## 单因子 IC 基线",
        "| 因子 | 方向 | IC | ICIR | HAC t | n |",
        "|------|------|----|------|-------|---|",
    ]
    for f in res["factors"]:
        ic = f["ic"] or 0.0
        icir = f["icir"] or 0.0
        t = f["t_hac"] or 0.0
        lines.append(
            f"| {f['name']} | {'+' if f['direction']>0 else '-'} | "
            f"{ic:+.4f} | {icir:+.3f} | {t:+.2f} | {f['n']} |"
        )
    lines += ["", "## 高相关因子对（|ρ| > 0.70，方向对齐后的截面 rank-corr）"]
    if res["high_corr_pairs"]:
        lines.append("| A | B | ρ |")
        lines.append("|---|---|---|")
        for p in res["high_corr_pairs"]:
            lines.append(f"| {p['a']} | {p['b']} | {p['rho']:+.3f} |")
    else:
        lines.append("*无* — 所有因子对的截面 rank-corr 均 < 0.70。")

    lines += ["", "## Gram-Schmidt 残差化 (按 |ICIR| 降序)"]
    lines.append("| # | 因子 | raw IC | 残差 IC | ratio | 95% CI (boot) | 判定 |")
    lines.append("|---|------|--------|---------|-------|--------------|------|")
    for name in res["gs_order"]:
        info = res["residual_ic"][name]
        lo, hi = info["residual_ic_ci95"]
        ratio = info["marginal_ratio"] or 0.0
        verdict = "**冗余**" if name in res["redundant_candidates"] else "保留"
        lines.append(
            f"| {info['order']} | {name} | "
            f"{info['raw_ic']:+.4f} | {info['residual_ic']:+.4f} | "
            f"{ratio:+.1%} | [{lo:+.4f}, {hi:+.4f}] | {verdict} |"
        )

    lines += [
        "",
        "## 冗余候选",
        ", ".join(res["redundant_candidates"]) or "*无冗余* — 9 因子全部保留",
        "",
        "## 说明",
        res["note"],
        "",
        "## 下一步",
        "- 把上面 \"冗余\" 列表从 v16 剔除，跑 v22 回测，看 DSR 是否上升。",
        "- 如果剔除后 IC 基本不变但 sharpe 下降 → 残余因子叠加是在",
        "  \"真实信号 + 相关噪声\" 之间做权衡，证实候选池 σ 窄确实来自冗余。",
    ]
    return "\n".join(lines) + "\n"


if __name__ == "__main__":
    main()
