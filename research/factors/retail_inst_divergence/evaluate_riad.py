"""
RIAD 因子评估: IC/ICIR + 分层回测 + 2025 OOS 对比

样本期间: 2023-10-01 ~ 2025-12-31
分段:
    - 样本内 (IS): 2023-10-01 ~ 2024-12-31
    - 样本外 (OOS, 2025): 2025-01-01 ~ 2025-12-31  ← 用户要求重点看
持仓窗口 (forward return): 20 交易日 (≈ 1 个月)

输出:
    journal/riad_eval_YYYYMMDD.md — 评估报告
    logs/riad_eval_YYYYMMDD.json  — 数值结果
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
from utils.factor_analysis import (  # noqa: E402
    compute_ic_series,
    ic_summary,
    quintile_backtest,
)


PRICE_PATH = ROOT / "data" / "processed" / "price_wide_close_2014-01-01_2025-12-31_qfq_5477stocks.parquet"

IS_START, IS_END = "2023-10-01", "2024-12-31"
OOS_START, OOS_END = "2025-01-01", "2025-12-31"
FWD_DAYS = 20


def load_forward_returns(start: str, end: str, fwd_days: int) -> tuple[pd.DataFrame, pd.DatetimeIndex]:
    """返回 (fwd_return_wide, trade_calendar).

    ret_wide 的 columns 转为 ts_code 格式 (加 .SZ/.SH/.BJ 后缀) 以匹配因子表.
    """
    price = pd.read_parquet(PRICE_PATH)
    price = price.loc[start:end]
    # 前向收益: t 日持有到 t+fwd 的收益率, 标注在 t 日
    fwd = price.shift(-fwd_days) / price - 1.0

    # 6 位代码 → ts_code
    def _to_tscode(sym: str) -> str:
        if sym.startswith(("60", "688")):
            return f"{sym}.SH"
        if sym.startswith(("00", "30", "301", "002", "003")):
            return f"{sym}.SZ"
        if sym[:1] in ("4", "8"):
            return f"{sym}.BJ"
        return f"{sym}.SZ"  # fallback

    fwd.columns = [_to_tscode(c) for c in fwd.columns]
    return fwd, price.index


def _filter_dates(df: pd.DataFrame, start: str, end: str) -> pd.DataFrame:
    return df.loc[(df.index >= start) & (df.index <= end)]


def evaluate_segment(
    factor: pd.DataFrame,
    fwd_ret: pd.DataFrame,
    label: str,
    start: str,
    end: str,
) -> dict:
    """评估一个时间段."""
    fac_seg = _filter_dates(factor, start, end)
    ret_seg = _filter_dates(fwd_ret, start, end)

    # 按周频采样因子, 避免相邻日 IC 强相关稀释统计量
    sample_dates = fac_seg.index[::5]  # 约每周一次
    fac_seg = fac_seg.loc[sample_dates]
    ret_seg = ret_seg.reindex(sample_dates)

    ic = compute_ic_series(fac_seg, ret_seg, method="spearman", min_stocks=100)
    summ = ic_summary(ic, name=f"RIAD [{label}]", fwd_days=FWD_DAYS, verbose=True)

    # 分层回测: 因子值越大 → 做空 (散户关注溢价), 所以 long_short='Q1_minus_Qn'
    group_ret, ls_ret = quintile_backtest(
        fac_seg, ret_seg, n_groups=5, long_short="Q1_minus_Qn"
    )
    ls_mean = ls_ret.mean(skipna=True)
    ls_std = ls_ret.std(skipna=True)
    # 因为样本是每 5 交易日一个点, fwd 20 日, 两者重叠, 不做 annualize
    q_means = group_ret.mean(skipna=True).to_dict()
    q_count = group_ret.count().mean()

    return {
        "label": label,
        "period": f"{start} ~ {end}",
        "n_obs": int(summ["n"]),
        "sample_cadence_days": 5,
        "fwd_days": FWD_DAYS,
        "IC_mean": float(summ["IC_mean"]),
        "IC_std": float(summ["IC_std"]),
        "ICIR": float(summ["ICIR"]) if pd.notna(summ["ICIR"]) else None,
        "pct_pos": float(summ["pct_pos"]),
        "t_stat": float(summ["t_stat"]) if pd.notna(summ["t_stat"]) else None,
        "t_stat_hac": float(summ["t_stat_hac"]) if pd.notna(summ["t_stat_hac"]) else None,
        "nw_lag": int(summ["nw_lag"]),
        "LS_mean_per_period": float(ls_mean) if pd.notna(ls_mean) else None,
        "LS_std_per_period": float(ls_std) if pd.notna(ls_std) else None,
        "LS_sharpe_unit": float(ls_mean / ls_std) if ls_std and pd.notna(ls_std) else None,
        "quintile_means": {k: float(v) for k, v in q_means.items() if pd.notna(v)},
        "avg_quintile_stocks": float(q_count) if pd.notna(q_count) else None,
    }


def main() -> None:
    full_start, full_end = IS_START, OOS_END

    price = pd.read_parquet(PRICE_PATH)
    cal = price.loc[full_start:full_end].index

    print(f"交易日历: {len(cal)} 日 ({cal[0].date()} ~ {cal[-1].date()})")

    # 构造 attention panel (retail 20 日, inst 60 日)
    panels = build_attention_panel(
        full_start, full_end, cal,
        retail_window=20, inst_window=60,
    )
    print(f"retail_attn 宽表: {panels['retail_attn'].shape}")
    print(f"inst_attn   宽表: {panels['inst_attn'].shape}")

    factor = compute_riad_factor(
        panels["retail_attn"], panels["inst_attn"],
        min_coverage=200,
    )
    print(f"RIAD 因子宽表: {factor.shape}, 每日平均有效股数: {factor.notna().sum(axis=1).mean():.0f}")

    fwd_ret, _ = load_forward_returns(full_start, full_end, FWD_DAYS)
    print(f"forward return 宽表: {fwd_ret.shape}")

    # 因子 t 日, fwd 收益需要 t ~ t+20. 为避免未来函数:
    # 用 factor.shift(1) 对齐 t+1 预测 t+1~t+21 收益 (严格信号 → 次日交易)
    factor_shift = factor.shift(1)

    results: dict[str, dict] = {}
    for label, s, e in [
        ("FULL", full_start, full_end),
        ("IS 2023-10~2024-12", IS_START, IS_END),
        ("OOS 2025", OOS_START, OOS_END),
    ]:
        print(f"\n────── {label} ──────")
        results[label] = evaluate_segment(factor_shift, fwd_ret, label, s, e)

    # 打印汇总表
    print("\n=== RIAD 汇总 ===")
    for lab, r in results.items():
        print(
            f"[{lab}] n={r['n_obs']}  "
            f"IC_mean={r['IC_mean']:+.4f}  ICIR={r['ICIR']:+.3f}  "
            f"HAC t={r['t_stat_hac']:+.2f}  "
            f"LS_mean={r['LS_mean_per_period']:+.4%}  "
            f"pct_pos={r['pct_pos']:.1%}"
        )
        qs = r["quintile_means"]
        if qs:
            print("  分层均值 (20 日持有):  " + "  ".join(f"{k}={v:+.2%}" for k, v in qs.items()))

    # 保存结果
    stamp = datetime.now().strftime("%Y%m%d")
    out_dir = ROOT / "logs"
    out_dir.mkdir(exist_ok=True)
    out_json = out_dir / f"riad_eval_{stamp}.json"
    with open(out_json, "w") as f:
        json.dump(
            {
                "generated_at": datetime.now().isoformat(timespec="seconds"),
                "factor": "RIAD",
                "fwd_days": FWD_DAYS,
                "sample_cadence_days": 5,
                "segments": results,
            },
            f,
            indent=2,
            ensure_ascii=False,
        )
    print(f"\n结果已保存: {out_json}")


if __name__ == "__main__":
    main()
