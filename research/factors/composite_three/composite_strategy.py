"""
3-因子 Composite Long-Only 策略

基于 RIAD / MFD / BGFD 三因子正交性 (|corr| < 0.2), 做 long-only 合成:
    signal_s,t = (-RIAD_z) + (-MFD_z) + (+BGFD_z)
    按 cross-section z-score 等权合成, 做多 top 30%, 等权配置.

为什么不做空端:
    OOS 2025 显示 short leg 在牛市是灾难 (Q5_short -1.41 Sharpe, BGFD -2.29 Sharpe).
    Long-only 规避 regime shift 风险 + 解决 A 股融券限制.

持仓窗口: 20 交易日 (月频换仓)
成本: 双边 0.3% (单边 0.15%)
Universe: 因子全部有值的股票 (三因子交集)

分段:
    IS 2023-10 ~ 2024-12 (震荡市)
    OOS 2025 (涨市)
    FULL
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

from research.factors.broker_gold_fade.factor import (  # noqa: E402
    compute_bgfd_factor,
    compute_consensus_streak,
    load_broker_recommend,
)
from research.factors.moneyflow_divergence.factor import compute_mfd_factor  # noqa: E402
from research.factors.retail_inst_divergence.factor import (  # noqa: E402
    build_attention_panel,
    compute_riad_factor,
)
from research.factors.retail_inst_divergence.industry_eval import load_industry_series  # noqa: E402
from research.factors.retail_inst_divergence.neutralize_eval import (  # noqa: E402
    load_circ_mv_wide,
    size_neutralize,
)
from utils.factor_analysis import industry_neutralize_fast  # noqa: E402

START, END = "2023-10-01", "2025-12-31"
PRICE_PATH = ROOT / "data" / "processed" / "price_wide_close_2014-01-01_2025-12-31_qfq_5477stocks.parquet"
COST_ONE_WAY = 0.0015
HOLD_DAYS = 20
TOP_PCT = 0.30


def _to_ts(sym: str) -> str:
    if sym.startswith(("60", "68")):
        return f"{sym}.SH"
    if sym.startswith(("00", "30")):
        return f"{sym}.SZ"
    return f"{sym}.SZ"


def _zscore_row(df: pd.DataFrame) -> pd.DataFrame:
    mu = df.mean(axis=1)
    sd = df.std(axis=1).replace(0.0, np.nan)
    return df.sub(mu, axis=0).div(sd, axis=0)


def build_composite(
    riad: pd.DataFrame,
    mfd: pd.DataFrame,
    bgfd_monthly: pd.DataFrame,
    trading_cal: pd.DatetimeIndex,
) -> pd.DataFrame:
    """
    合成因子. RIAD/MFD 每日, BGFD 每月 (向前 ffill).

    信号方向: 做多 signal 高 = 低 RIAD + 低 MFD + 高 BGFD = 机构关注 / smart money inflow / 券商一致看好.
    """
    # BGFD monthly -> daily ffill
    bgfd_daily_rows = []
    for d in trading_cal:
        ym = d.year * 100 + d.month
        # 找到最近的 <= 当前月的 BGFD 记录
        valid_months = [m for m in bgfd_monthly.index if m <= ym]
        if valid_months:
            bgfd_daily_rows.append(bgfd_monthly.loc[max(valid_months)].rename(d))
        else:
            bgfd_daily_rows.append(pd.Series(dtype=float, name=d))
    bgfd_daily = pd.DataFrame(bgfd_daily_rows)

    # 对齐共同 symbols (并集, 缺失视 NaN)
    all_syms = riad.columns.union(mfd.columns).union(bgfd_daily.columns)
    riad_a = riad.reindex(index=trading_cal, columns=all_syms)
    mfd_a = mfd.reindex(index=trading_cal, columns=all_syms)
    bgfd_a = bgfd_daily.reindex(index=trading_cal, columns=all_syms)

    # cross-section zscore
    riad_z = _zscore_row(riad_a)
    mfd_z = _zscore_row(mfd_a)
    bgfd_z = _zscore_row(bgfd_a)

    # 合成 signal: 做多方向 (RIAD/MFD 取负, BGFD 取正)
    signal = -riad_z.add(mfd_z, fill_value=0.0).sub(bgfd_z, fill_value=0.0)
    # 等价于: signal = -RIAD - MFD + BGFD (三个因子 z-score 相加 / 加权)

    # 有效性: 至少 RIAD 或 MFD 之一有值 (BGFD 只覆盖 ~10% universe, 不强制)
    valid_count = riad_a.notna().astype(int).add(mfd_a.notna().astype(int))
    signal = signal.where(valid_count >= 1, np.nan)
    # 截面最小覆盖
    daily_cov = signal.notna().sum(axis=1)
    signal = signal.where(daily_cov >= 200, np.nan)
    return signal


def run_long_only(
    signal: pd.DataFrame,
    price: pd.DataFrame,
    hold_days: int = HOLD_DAYS,
    top_pct: float = TOP_PCT,
) -> list[dict]:
    """每 hold_days 日按 signal top X% 等权多头组合."""
    all_dates = signal.index.intersection(price.index)
    rebal_dates = all_dates[::hold_days]

    records = []
    prev_set: set[str] = set()
    for i, d in enumerate(rebal_dates[:-1]):
        s = signal.loc[d].dropna()
        if len(s) < 100:
            continue
        threshold = s.quantile(1 - top_pct)
        long_syms = list(s[s >= threshold].index)

        next_d = rebal_dates[i + 1]
        p0, p1 = price.loc[d], price.loc[next_d]
        rets = (p1 / p0 - 1.0).dropna()
        long_rets = rets.reindex(long_syms).dropna()
        if len(long_rets) < 10:
            continue
        gross = float(long_rets.mean())

        # turnover: |new ∩ old| / len(new ∪ old)
        new_set = set(long_syms)
        if prev_set:
            turn = len(new_set.symmetric_difference(prev_set)) / max(
                len(new_set | prev_set), 1
            )
        else:
            turn = 1.0
        cost = turn * 2 * COST_ONE_WAY
        net = gross - cost
        prev_set = new_set

        records.append({
            "date": str(d.date()),
            "n_long": int(len(long_syms)),
            "gross_ret": gross,
            "net_ret": net,
            "turnover": float(turn),
            "cost": float(cost),
        })
    return records


def summarize(records: list[dict], label: str, periods_per_year: float = 252 / HOLD_DAYS) -> dict:
    if not records:
        return {}
    rets = np.array([r["net_ret"] for r in records])
    ann_ret = rets.mean() * periods_per_year
    ann_vol = rets.std(ddof=1) * np.sqrt(periods_per_year)
    sharpe = ann_ret / ann_vol if ann_vol > 0 else np.nan
    cum = np.cumprod(1 + rets) - 1
    peak = np.maximum.accumulate(np.cumprod(1 + rets))
    dd = (np.cumprod(1 + rets) - peak) / peak
    mdd = float(dd.min()) if len(dd) else 0.0
    avg_turn = float(np.mean([r["turnover"] for r in records]))
    return {
        "label": label,
        "n_periods": len(rets),
        "ann_return": float(ann_ret),
        "ann_vol": float(ann_vol),
        "sharpe": float(sharpe) if not np.isnan(sharpe) else None,
        "mdd": mdd,
        "cum_net": float(cum[-1]) if len(cum) else 0.0,
        "avg_turnover": avg_turn,
        "win_rate": float((rets > 0).mean()),
    }


def main() -> None:
    price = pd.read_parquet(PRICE_PATH)
    price.columns = [_to_ts(c) for c in price.columns]
    cal = price.loc[START:END].index

    print("构造 RIAD (size + industry neutralize)...")
    panels = build_attention_panel(START, END, cal)
    riad_raw = compute_riad_factor(panels["retail_attn"], panels["inst_attn"])
    circ_mv = load_circ_mv_wide(START, END)
    riad_sn = size_neutralize(riad_raw, circ_mv)
    ind_series = load_industry_series()
    riad = industry_neutralize_fast(riad_sn, ind_series)

    print("构造 MFD...")
    mfd = compute_mfd_factor("2023-07-15", END, window=20, min_coverage=500)

    print("构造 BGFD...")
    br_raw = load_broker_recommend("2023-07", "2025-12")
    cons = compute_consensus_streak(br_raw)
    bgfd = compute_bgfd_factor(cons, sorted(cons["month_i"].unique()))

    print("合成 composite 信号...")
    signal = build_composite(riad, mfd, bgfd, cal)
    signal_exec = signal.shift(1)  # 次日交易
    print(f"composite 日均有效股: {signal_exec.notna().sum(axis=1).mean():.0f}")

    # 回测三段
    records_full = run_long_only(
        signal_exec.loc[START:END], price.loc[START:END]
    )
    records_is = run_long_only(
        signal_exec.loc["2023-10-01":"2024-12-31"], price.loc["2023-10-01":"2024-12-31"]
    )
    records_oos = run_long_only(
        signal_exec.loc["2025-01-01":"2025-12-31"], price.loc["2025-01-01":"2025-12-31"]
    )

    # 对照: 等权全 A (所有股票) 做 benchmark
    eq_returns = []
    all_dates = price.loc[START:END].index
    rebal = all_dates[::HOLD_DAYS]
    for i, d in enumerate(rebal[:-1]):
        p0 = price.loc[d].dropna()
        p1 = price.loc[rebal[i + 1]]
        common = p0.index.intersection(p1.index)
        if len(common) < 100:
            continue
        r = ((p1.loc[common] / p0.loc[common] - 1.0)).mean()
        eq_returns.append(float(r))
    bm_ann = np.mean(eq_returns) * (252 / HOLD_DAYS)
    bm_vol = np.std(eq_returns, ddof=1) * np.sqrt(252 / HOLD_DAYS)
    bm_sr = bm_ann / bm_vol if bm_vol else np.nan
    print(f"\n等权全 A benchmark: Ann={bm_ann*100:.2f}% Vol={bm_vol*100:.2f}% Sharpe={bm_sr:.2f}")

    results = {
        "FULL": summarize(records_full, "FULL"),
        "IS 2023-10~2024-12": summarize(records_is, "IS"),
        "OOS 2025": summarize(records_oos, "OOS 2025"),
        "benchmark_eqwt": {
            "ann_return": float(bm_ann), "ann_vol": float(bm_vol),
            "sharpe": float(bm_sr) if bm_vol else None,
            "n_periods": len(eq_returns),
        },
    }

    print("\n=== 3-Factor Composite Long-Only (双边 0.3%, 20d 调仓, Top 30%) ===\n")
    header = f"{'Segment':<20} {'N':>3} {'Ann%':>7} {'Vol%':>7} {'Sharpe':>7} {'MDD%':>8} {'Turn%':>8} {'Win%':>6} {'Cum%':>8}"
    print(header)
    print("-" * len(header))
    for lab in ["FULL", "IS 2023-10~2024-12", "OOS 2025"]:
        r = results[lab]
        if not r:
            continue
        sr = r["sharpe"] if r["sharpe"] is not None else float("nan")
        print(
            f"{lab:<20} {r['n_periods']:>3} "
            f"{r['ann_return']*100:>6.2f} "
            f"{r['ann_vol']*100:>6.2f} "
            f"{sr:>7.2f} "
            f"{r['mdd']*100:>7.2f} "
            f"{r['avg_turnover']*100:>7.2f} "
            f"{r['win_rate']*100:>5.1f} "
            f"{r['cum_net']*100:>7.2f}"
        )
    bm = results["benchmark_eqwt"]
    bm_sr_val = bm["sharpe"] if bm["sharpe"] is not None else float("nan")
    print(
        f"{'Benchmark EqWt':<20} {bm['n_periods']:>3} "
        f"{bm['ann_return']*100:>6.2f} "
        f"{bm['ann_vol']*100:>6.2f} "
        f"{bm_sr_val:>7.2f} "
    )

    stamp = datetime.now().strftime("%Y%m%d")
    out_json = ROOT / "logs" / f"composite_three_{stamp}.json"
    with open(out_json, "w") as f:
        json.dump(
            {
                "generated_at": datetime.now().isoformat(timespec="seconds"),
                "strategy": "3-factor composite long-only (RIAD-sizeInd, MFD, BGFD)",
                "signal_formula": "-zscore(RIAD_size_ind) - zscore(MFD) + zscore(BGFD)",
                "long_pct": TOP_PCT,
                "hold_days": HOLD_DAYS,
                "cost_one_way": COST_ONE_WAY,
                "results": results,
            },
            f, indent=2, ensure_ascii=False,
        )
    print(f"\n保存: {out_json}")


if __name__ == "__main__":
    main()
