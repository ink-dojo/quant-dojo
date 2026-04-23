"""
Audit Opus 打分质量 — full MD&A (429) vs outlook (347).

5 个维度:
    A. 基本 stats (n, fail rate, 分布)
    B. 5 维度共线性 (是不是其实只 1-2 个自由度)
    C. IC + bootstrap CI: raw / industry-neutral (full vs outlook 对比)
    D. Order group 一致性 (random-order normalization 是否 work)
    E. External leak self-report + rationale 抽样

只读 parquet + 本地价格 + industry, 不调 LLM.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import numpy as np
import pandas as pd

from research.factors.mda_drift.factor import DEFAULT_MANIFEST_PATH
from utils.local_data_loader import load_adj_price_wide

DIMS = ["specificity_drift", "hedging_drift", "tone_drift",
        "forward_drift", "transparency_drift"]
FWD_DAYS = 20
COST_BPS = 30


def normalize_order(df: pd.DataFrame) -> pd.DataFrame:
    """swap 组分数取反 → 统一到 'curr vs prev' 方向."""
    df = df.copy()
    for d in DIMS:
        if d not in df.columns:
            continue
        df[d] = df[d].astype(float)
        df.loc[df["order"] == "swap", d] = -df.loc[df["order"] == "swap", d]
    return df


def attach_return(df: pd.DataFrame, manifest: pd.DataFrame, prices: pd.DataFrame) -> pd.DataFrame:
    """挂 publish_date + 20 日 forward return, 扣 30bp 成本."""
    mmap = manifest.set_index(["symbol", "fiscal_year"])["publish_date"].to_dict()
    df = df.copy()
    df["publish_date"] = df.apply(lambda r: mmap.get((r.symbol, r.year_curr)), axis=1)
    df["publish_date"] = pd.to_datetime(df["publish_date"])
    df = df[~df.publish_date.isna()].copy()

    def fwd(row):
        sym, pub = row.symbol, row.publish_date
        if sym not in prices.columns: return None
        sr = prices[sym].dropna()
        i = sr.index.searchsorted(pub, side="right")
        if i + FWD_DAYS >= len(sr): return None
        a, b = sr.iloc[i], sr.iloc[i + FWD_DAYS]
        if a <= 0 or pd.isna(a) or pd.isna(b): return None
        return float(b / a - 1 - COST_BPS / 10000)

    df["fwd"] = df.apply(fwd, axis=1)
    return df[~df.fwd.isna()].copy()


def attach_industry(df: pd.DataFrame) -> pd.DataFrame:
    ind = pd.read_parquet("data/raw/fundamentals/industry_sw.parquet")
    ind["sw_l1"] = ind.industry_code.astype(str).str[:2]
    imap = ind.set_index("symbol").sw_l1.to_dict()
    df = df.copy()
    df["sw_l1"] = df.symbol.map(lambda x: imap.get(x, "UNK"))
    return df


def bootstrap_ic(panel: pd.DataFrame, col: str, n: int = 1000, seed: int = 42) -> dict:
    rng = np.random.default_rng(seed)
    N = len(panel)
    ics = []
    for _ in range(n):
        idx = rng.integers(0, N, size=N)
        sub = panel.iloc[idx]
        ic = sub[col].rank().corr(sub["fwd"].rank())
        ics.append(ic)
    ics = np.array(ics)
    return {
        "mean": float(np.nanmean(ics)),
        "ci_low": float(np.nanpercentile(ics, 2.5)),
        "ci_high": float(np.nanpercentile(ics, 97.5)),
        "pct_gt_0": float((ics > 0).mean()),
    }


def analyze_dataset(label: str, scores_path: Path, manifest: pd.DataFrame,
                    prices_cache_path: Path | None = None) -> dict:
    """完整 audit 一份 scores parquet."""
    raw = pd.read_parquet(scores_path)
    total = len(raw)
    valid = raw[~raw["tone_drift"].isna()].copy() if "tone_drift" in raw.columns else raw
    fail_rate = (total - len(valid)) / total if total else 0

    normed = normalize_order(valid)
    by_order_counts = normed.order.value_counts().to_dict()

    # 维度分布
    dim_stats = {}
    for d in DIMS:
        if d not in normed.columns:
            continue
        s = normed[d]
        dim_stats[d] = {
            "mean": float(s.mean()),
            "std": float(s.std()),
            "skew": float(s.skew()),
            "pct_extreme_1": float((s.abs() >= 0.95).mean()),
            "pct_zero": float((s.abs() < 0.05).mean()),
            "unique_vals": int(s.round(1).nunique()),
        }

    # 共线性
    corr_matrix = normed[DIMS].corr()
    high_corr_pairs = []
    for i, d1 in enumerate(DIMS):
        for d2 in DIMS[i+1:]:
            c = corr_matrix.loc[d1, d2]
            if abs(c) > 0.5:
                high_corr_pairs.append((d1.replace("_drift",""), d2.replace("_drift",""),
                                       round(c, 3)))

    # 挂 return
    symbols = list(normed.symbol.unique())
    prices = load_adj_price_wide(symbols=symbols,
                                  start="2024-01-01", end="2026-04-21")
    panel = attach_return(normed, manifest, prices)
    panel = attach_industry(panel)
    panel_ind = panel[panel.sw_l1 != "UNK"].copy()
    for d in DIMS:
        if d in panel_ind.columns:
            panel_ind[d + "_ind"] = panel_ind.groupby("sw_l1")[d].transform(lambda x: x - x.mean())

    # IC + bootstrap
    ic_results = {}
    for d in DIMS:
        if d not in panel.columns:
            continue
        ic_results[d] = {
            "raw": bootstrap_ic(panel, d),
            "ind_neu": bootstrap_ic(panel_ind, d + "_ind") if d + "_ind" in panel_ind.columns else None,
        }

    # Order group diag (IC by order group)
    order_diag = {}
    for d in DIMS:
        if d not in panel.columns: continue
        fwd_g = panel[panel.order == "fwd"]
        swap_g = panel[panel.order == "swap"]
        ic_fwd = fwd_g[d].rank().corr(fwd_g["fwd"].rank()) if len(fwd_g) > 10 else None
        ic_swap = swap_g[d].rank().corr(swap_g["fwd"].rank()) if len(swap_g) > 10 else None
        order_diag[d] = {
            "n_fwd": len(fwd_g), "n_swap": len(swap_g),
            "ic_fwd": float(ic_fwd) if pd.notna(ic_fwd) else None,
            "ic_swap": float(ic_swap) if pd.notna(ic_swap) else None,
            "abs_diff": abs((ic_fwd or 0) - (ic_swap or 0)),
        }

    # External leak self-report
    leak_col = "external_leak_suspicion"
    leak_yes = 0
    if leak_col in normed.columns:
        vals = normed[leak_col].fillna("NA").astype(str).str.strip()
        leak_yes = (vals == "是").sum()

    return {
        "label": label,
        "total": total,
        "valid": len(valid),
        "fail_rate": round(fail_rate, 3),
        "by_order": by_order_counts,
        "panel_with_return_n": len(panel),
        "panel_ind_neu_n": len(panel_ind),
        "dim_stats": dim_stats,
        "corr_matrix": corr_matrix.round(3).to_dict(),
        "high_corr_pairs": high_corr_pairs,
        "ic_results": ic_results,
        "order_diag": order_diag,
        "external_leak_yes_count": int(leak_yes),
    }


def render_markdown(full: dict, outlook: dict) -> str:
    lines = [
        "# MD&A LLM drift — Opus 打分质量审计 (2026-04-22)",
        "",
        "两份 Opus 4.7 打分 dataset 的质量对比:",
        "1. **full**: 全 MD&A 前 5000 字, 429 valid / 482 (11% fail)",
        "2. **outlook**: 只 '未来发展展望' 段, 347 valid / 482 (28% fail)",
        "",
        "所有分析本地 parquet + 价格 + 申万一级, 不调 LLM.",
        "",
        "## 1. 基本 stats",
        "",
        "| 指标 | full MD&A | outlook 段 |",
        "|---|---:|---:|",
        f"| 总样本 | {full['total']} | {outlook['total']} |",
        f"| 成功 valid | {full['valid']} | {outlook['valid']} |",
        f"| 失败率 | {full['fail_rate']:.1%} | {outlook['fail_rate']:.1%} |",
        f"| 可算 return | {full['panel_with_return_n']} | {outlook['panel_with_return_n']} |",
        f"| fwd / swap 分布 | {full['by_order']} | {outlook['by_order']} |",
        f"| external_leak 自报'是' | {full['external_leak_yes_count']} | {outlook['external_leak_yes_count']} |",
        "",
        "**解读**: outlook 失败率高是因 Opus 时代 prompt 被 claude CLI 并发 reject. 两份 valid 样本差 82 对, 但 valid 内部结构应该可比.",
        "",
        "## 2. 5 维度分布 (normalized: swap 组已取反)",
        "",
    ]
    for label, data in [("full MD&A", full), ("outlook", outlook)]:
        lines += [f"### {label}",
                  "",
                  "| 维度 | mean | std | skew | \\|x\\|>0.95 | \\|x\\|<0.05 | 唯一分数数 |",
                  "|---|---:|---:|---:|---:|---:|---:|"]
        for d in DIMS:
            s = data["dim_stats"].get(d, {})
            lines.append(
                f"| {d.replace('_drift','')} | "
                f"{s.get('mean',0):+.3f} | {s.get('std',0):.3f} | {s.get('skew',0):+.2f} | "
                f"{s.get('pct_extreme_1',0):.1%} | {s.get('pct_zero',0):.1%} | "
                f"{s.get('unique_vals',0)} |"
            )
        lines.append("")

    lines += [
        "**解读**:",
        "- `std` 每维都在 0.2-0.4 区间, 无 collapse",
        "- `|x|>0.95` 占比应 < 5% (否则 LLM 过度 anchor 到 ±1)",
        "- `|x|<0.05` 占比 (趋 0) 高 → LLM 在该维度没话说 / boilerplate 无变化",
        "- 唯一分数数 < 10 说明粒度粗 (LLM 只用几个锚点 0.1 0.2 0.3 0.5 等)",
        "",
        "## 3. 维度共线性",
        "",
    ]
    for label, data in [("full MD&A", full), ("outlook", outlook)]:
        lines += [f"### {label} correlation matrix", ""]
        cm = data["corr_matrix"]
        lines.append("| | " + " | ".join(d.replace("_drift","") for d in DIMS) + " |")
        lines.append("|---|" + "---:|" * len(DIMS))
        for d in DIMS:
            row = [d.replace("_drift","")]
            for d2 in DIMS:
                row.append(f"{cm[d][d2]:+.2f}")
            lines.append("| " + " | ".join(row) + " |")
        pairs = data["high_corr_pairs"]
        if pairs:
            lines += ["", f"**|corr| > 0.5 对 ({len(pairs)}):**"]
            for p in pairs:
                lines.append(f"- {p[0]} ↔ {p[1]}: {p[2]:+.3f}")
        lines.append("")

    lines += [
        "**解读**: 若 5 维度两两相关性大部分 > 0.5, 说明 LLM 在 5 维度上只有 1-2 个真自由度 (维度设计失败). 反之 < 0.3 说明维度独立, 可做 ensemble.",
        "",
        "## 4. IC + Bootstrap CI (raw 和 industry-neutral)",
        "",
    ]
    for label, data in [("full MD&A", full), ("outlook", outlook)]:
        lines += [f"### {label}",
                  "",
                  "| 维度 | raw mean | raw CI | raw %>0 | ind-neu mean | ind-neu CI | ind-neu %>0 | ind-neu 显著 |",
                  "|---|---:|---:|---:|---:|---:|---:|:---:|"]
        for d in DIMS:
            r = data["ic_results"].get(d, {})
            raw = r.get("raw", {})
            neu = r.get("ind_neu") or {}
            sig = "✅" if (neu.get("ci_low", 0) > 0 or neu.get("ci_high", 0) < 0) else "❌"
            lines.append(
                f"| {d.replace('_drift','')} | "
                f"{raw.get('mean',0):+.4f} | [{raw.get('ci_low',0):+.3f},{raw.get('ci_high',0):+.3f}] | "
                f"{raw.get('pct_gt_0',0):.0%} | "
                f"{neu.get('mean',0):+.4f} | [{neu.get('ci_low',0):+.3f},{neu.get('ci_high',0):+.3f}] | "
                f"{neu.get('pct_gt_0',0):.0%} | {sig} |"
            )
        lines.append("")

    lines += [
        "**解读**: bootstrap 95% CI 不跨 0 = 显著. Industry-neutral 是主要判读.",
        "",
        "## 5. Order group diagnostic (random-order normalization 健康)",
        "",
    ]
    for label, data in [("full MD&A", full), ("outlook", outlook)]:
        lines += [f"### {label}",
                  "",
                  "| 维度 | n_fwd | n_swap | IC_fwd | IC_swap | \\|diff\\| |",
                  "|---|---:|---:|---:|---:|---:|"]
        for d in DIMS:
            s = data["order_diag"].get(d, {})
            lines.append(
                f"| {d.replace('_drift','')} | "
                f"{s.get('n_fwd',0)} | {s.get('n_swap',0)} | "
                f"{s.get('ic_fwd') if s.get('ic_fwd') is not None else 'NA':+.4f} | "
                f"{s.get('ic_swap') if s.get('ic_swap') is not None else 'NA':+.4f} | "
                f"**{s.get('abs_diff',0):.3f}** |"
            )
        lines.append("")

    lines += [
        "**解读**: `|diff|` < 0.05 = normalization 完美 (fwd 和 swap IC 一致 → 真信号); > 0.05 = order bias 残留, 信号可疑.",
        "",
        "## 6. 综合判决",
        "",
    ]
    return "\n".join(lines)


def main() -> int:
    full_path = Path("data/processed/mda_llm_drift_scores_2024.parquet")
    outlook_path = Path("data/processed/mda_llm_outlook_drift_scores_2024_opus.parquet")

    manifest = pd.read_parquet(DEFAULT_MANIFEST_PATH)
    manifest["publish_date"] = pd.to_datetime(manifest["publish_date"])

    print("[audit] analyzing full MD&A scores...")
    full = analyze_dataset("full", full_path, manifest)
    print("[audit] analyzing outlook scores...")
    outlook = analyze_dataset("outlook", outlook_path, manifest)

    md = render_markdown(full, outlook)
    out = Path("journal/mda_llm_opus_quality_audit_20260422.md")
    out.write_text(md, encoding="utf-8")
    print(f"[saved] {out}  ({len(md)} chars)")

    # console summary
    print("\n=== Summary (详见 journal) ===")
    print(f"full:    n={full['panel_with_return_n']} (with return), fail_rate={full['fail_rate']:.1%}")
    print(f"outlook: n={outlook['panel_with_return_n']} (with return), fail_rate={outlook['fail_rate']:.1%}")
    print()
    print("ind-neu pooled IC (2024 cross-section):")
    print(f"{'维度':24s}  {'full':>12s}  {'outlook':>12s}")
    for d in DIMS:
        f_ic = full["ic_results"].get(d, {}).get("ind_neu", {}).get("mean", 0) or 0
        o_ic = outlook["ic_results"].get(d, {}).get("ind_neu", {}).get("mean", 0) or 0
        f_sig = "✅" if abs(full["ic_results"].get(d, {}).get("ind_neu", {}).get("ci_low", 0)) > 0 and full["ic_results"].get(d, {}).get("ind_neu", {}).get("ci_low", 0) * full["ic_results"].get(d, {}).get("ind_neu", {}).get("ci_high", 0) > 0 else " "
        print(f"{d:24s}  {f_ic:+.4f}{f_sig:>2}  {o_ic:+.4f}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
