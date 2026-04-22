"""
RIAD size-neutralization 稳健性验证

风险假设: RIAD 因子可能实质是"小盘股"的代理
         (retail 热度集中于小盘题材股).
验证方法: 对每个截面日用 log(circ_mv) 做 OLS 回归取残差,
         看残差 IC 是否仍显著.

输出:
    logs/riad_neutralize_YYYYMMDD.json
"""
from __future__ import annotations

import json
import sys
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))

from research.factors.retail_inst_divergence.factor import (  # noqa: E402
    build_attention_panel,
    compute_riad_factor,
)
from research.factors.retail_inst_divergence.evaluate_riad import (  # noqa: E402
    FWD_DAYS,
    IS_END,
    IS_START,
    OOS_END,
    OOS_START,
    PRICE_PATH,
    evaluate_segment,
    load_forward_returns,
)

DB_DIR = ROOT / "data" / "raw" / "tushare" / "daily_basic"


def load_circ_mv_wide(start: str, end: str) -> pd.DataFrame:
    """聚合所有个股 circ_mv (流通市值, 万元), 对齐到 wide panel."""
    start_i, end_i = int(start.replace("-", "")), int(end.replace("-", ""))
    frames = []
    for f in sorted(DB_DIR.glob("*.parquet")):
        try:
            df = pd.read_parquet(f, columns=["ts_code", "trade_date", "circ_mv"])
        except Exception:
            continue
        if df.empty:
            continue
        df = df[df["trade_date"].astype(int).between(start_i, end_i)]
        if df.empty:
            continue
        frames.append(df)
    raw = pd.concat(frames, ignore_index=True)
    raw["trade_date"] = pd.to_datetime(
        raw["trade_date"].astype(str).str.strip(), format="%Y%m%d"
    )
    wide = raw.pivot_table(
        index="trade_date",
        columns="ts_code",
        values="circ_mv",
        aggfunc="last",
    )
    return wide


def size_neutralize(
    factor: pd.DataFrame,
    circ_mv: pd.DataFrame,
    min_stocks: int = 200,
) -> pd.DataFrame:
    """按日对 factor 做 log(circ_mv) 回归取残差.

    纯向量化 OLS:
        y = a + b * x + e ; residual = y - (a + b * x)
        按行 demean 等价.
    """
    common_dates = factor.index.intersection(circ_mv.index)
    common_syms = factor.columns.intersection(circ_mv.columns)
    f = factor.loc[common_dates, common_syms]
    x = np.log(circ_mv.loc[common_dates, common_syms].clip(lower=1.0))

    # 在 f 非 NaN 且 x 非 NaN 的 mask 上回归
    mask = f.notna() & x.notna()
    f_m = f.where(mask)
    x_m = x.where(mask)

    f_mean = f_m.mean(axis=1, skipna=True)
    x_mean = x_m.mean(axis=1, skipna=True)
    fx_cov = ((f_m.sub(f_mean, axis=0)) * (x_m.sub(x_mean, axis=0))).sum(axis=1, skipna=True)
    xx_var = ((x_m.sub(x_mean, axis=0)) ** 2).sum(axis=1, skipna=True)
    beta = (fx_cov / xx_var.replace(0.0, np.nan))
    alpha = f_mean - beta * x_mean

    # 残差 = y - (alpha + beta * x)
    predicted = x_m.mul(beta, axis=0).add(alpha, axis=0)
    residual = f_m - predicted

    # 覆盖度门限
    daily_count = residual.notna().sum(axis=1)
    residual = residual.where(daily_count >= min_stocks, np.nan)
    return residual


def main() -> None:
    full_start, full_end = IS_START, OOS_END

    price = pd.read_parquet(PRICE_PATH)
    cal = price.loc[full_start:full_end].index

    print(f"交易日历: {len(cal)} 日")

    panels = build_attention_panel(full_start, full_end, cal)
    factor_raw = compute_riad_factor(panels["retail_attn"], panels["inst_attn"])
    print(f"原始 RIAD: {factor_raw.shape}")

    print("加载流通市值 (circ_mv)...")
    circ_mv = load_circ_mv_wide(full_start, full_end)
    print(f"circ_mv 宽表: {circ_mv.shape}")

    factor_neut = size_neutralize(factor_raw, circ_mv)
    print(f"size-neutral RIAD: {factor_neut.shape}, 日均有效股: {factor_neut.notna().sum(axis=1).mean():.0f}")

    # 与原因子 IC 相关性 (sanity: 中性化后应仍保留信号但 IC 下降)
    raw_vals = factor_raw.stack()
    neut_vals = factor_neut.stack()
    common_idx = raw_vals.index.intersection(neut_vals.index)
    corr = raw_vals.loc[common_idx].corr(neut_vals.loc[common_idx])
    print(f"raw vs size-neutral 因子相关度: {corr:.3f}")

    fwd_ret, _ = load_forward_returns(full_start, full_end, FWD_DAYS)
    factor_neut_shift = factor_neut.shift(1)

    results = {}
    for label, s, e in [
        ("FULL (size-neutral)", full_start, full_end),
        ("IS 2023-10~2024-12 (size-neutral)", IS_START, IS_END),
        ("OOS 2025 (size-neutral)", OOS_START, OOS_END),
    ]:
        print(f"\n────── {label} ──────")
        results[label] = evaluate_segment(factor_neut_shift, fwd_ret, label, s, e)

    print("\n=== RIAD size-neutral 汇总 ===")
    for lab, r in results.items():
        print(
            f"[{lab}] n={r['n_obs']}  "
            f"IC={r['IC_mean']:+.4f}  ICIR={r['ICIR']:+.3f}  "
            f"HAC t={r['t_stat_hac']:+.2f}  "
            f"LS_mean={r['LS_mean_per_period']:+.4%}  "
            f"pct_pos={r['pct_pos']:.1%}"
        )
        qs = r["quintile_means"]
        if qs:
            print("  分层均值 (20 日持有):  " + "  ".join(f"{k}={v:+.2%}" for k, v in qs.items()))

    stamp = datetime.now().strftime("%Y%m%d")
    out_json = ROOT / "logs" / f"riad_neutralize_{stamp}.json"
    with open(out_json, "w") as f:
        json.dump(
            {
                "generated_at": datetime.now().isoformat(timespec="seconds"),
                "factor": "RIAD (size-neutralized by log_circ_mv)",
                "fwd_days": FWD_DAYS,
                "raw_vs_neutral_corr": float(corr),
                "segments": results,
            },
            f,
            indent=2,
            ensure_ascii=False,
        )
    print(f"\n保存: {out_json}")


if __name__ == "__main__":
    main()
