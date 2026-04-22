"""
RIAD Regime-Aware Gate

Pre-registered rule (不可事后调):
    若过去 20 交易日 HS300 收益 > +3% → 关掉 short leg (仅做 long Q2Q3)
    否则 → 正常 Q2Q3_minus_Q5 LS

目的: 基于 OOS 2025 观察到的 short leg 在牛市反噬 (Q5_short_only Ann -36%),
     用可观测、不未来窥视的 regime 信号决定 short 是否参与.

验证方法:
    1. 加载 RIAD 日频 net_ls (研究) + gross_long / gross_short 分拆
    2. 按 HS300 20d return 构造 regime mask
    3. 合成: gated_ls = gross_long - gross_short * (1 - long_only_mask) - cost
    4. 对比 baseline / gated 的 Sharpe / MDD / OOS 表现

red line: threshold 一旦 pre-reg 为 +3%, 不基于 OOS 结果回头调 (例如改 +2% 或 +4%).
"""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[3]
RIAD_PATH = ROOT / "research" / "factors" / "retail_inst_divergence" / "riad_ls_daily_returns.parquet"
HS300_PATH = ROOT / "data" / "raw" / "tushare" / "index_daily_000300.parquet"

GATE_WINDOW = 20
GATE_THRESHOLD = 0.03  # HS300 20d return > +3% → long-only


def load_hs300_regime() -> pd.Series:
    df = pd.read_parquet(HS300_PATH)
    df["trade_date"] = pd.to_datetime(df["trade_date"].astype(str).str.strip(), format="%Y%m%d")
    df = df.sort_values("trade_date").set_index("trade_date")
    # pct_chg 是 % 单位, 转小数
    daily_ret = df["pct_chg"].astype(float) / 100.0
    # 20 日累计
    rolled = (1 + daily_ret).rolling(GATE_WINDOW).apply(np.prod, raw=True) - 1.0
    return rolled.rename("hs300_20d_ret")


def apply_gate(daily: pd.DataFrame, hs300_20d: pd.Series) -> pd.DataFrame:
    """返回 gated dataframe, 列扩展:
        regime_long_only: bool, 当日是否关 short leg
        gated_gross_ls:  gross_long - (1 - regime) * gross_short
        gated_net_ls:    gated_gross_ls - cost
    """
    out = daily.copy()
    reg = hs300_20d.reindex(out.index, method="ffill")
    # 使用 T-1 日 signal (防未来函数): 今日决策基于昨日 hs300_20d
    long_only = (reg.shift(1) > GATE_THRESHOLD).fillna(False)
    out["regime_long_only"] = long_only
    out["gated_gross_ls"] = np.where(
        out["regime_long_only"],
        out["gross_long"],             # long-only: 只做多
        out["gross_ls"],               # LS: 做多-做空
    )
    out["gated_net_ls"] = out["gated_gross_ls"] - out["cost"]
    return out


def summarize(series: pd.Series, label: str) -> dict:
    s = series.dropna()
    if s.empty:
        return {}
    ann = s.mean() * 252
    vol = s.std(ddof=1) * np.sqrt(252)
    sr = ann / vol if vol > 0 else np.nan
    cum_series = (1 + s).cumprod()
    dd = (cum_series / cum_series.cummax() - 1).min()
    return {
        "label": label,
        "n_days": len(s),
        "ann_return": float(ann),
        "ann_vol": float(vol),
        "sharpe": float(sr) if not np.isnan(sr) else None,
        "mdd": float(dd),
        "cum": float(cum_series.iloc[-1] - 1),
    }


def main() -> None:
    daily = pd.read_parquet(RIAD_PATH)
    print(f"RIAD daily shape: {daily.shape}")
    hs = load_hs300_regime()
    gated = apply_gate(daily, hs)
    print(f"Long-only days (HS300 20d > +{GATE_THRESHOLD*100:.0f}%): "
          f"{int(gated['regime_long_only'].sum())} / {len(gated)} ({gated['regime_long_only'].mean()*100:.1f}%)")

    print("\n=== Baseline vs Gated ===\n")
    rows = []
    for lab, s, e in [
        ("FULL 2023-10~2025-12", "2023-10-01", "2025-12-31"),
        ("IS 2023-10~2024-12", "2023-10-01", "2024-12-31"),
        ("OOS 2025", "2025-01-01", "2025-12-31"),
    ]:
        base = gated.loc[s:e, "net_ls"]
        g = gated.loc[s:e, "gated_net_ls"]
        sub_long_only_days = gated.loc[s:e, "regime_long_only"].sum()
        total_days = gated.loc[s:e].shape[0]
        base_s = summarize(base, f"{lab} [baseline]")
        gate_s = summarize(g, f"{lab} [gated]")
        rows.append((lab, base_s, gate_s, int(sub_long_only_days), int(total_days)))

    header = f"{'Segment':<22} {'Mode':<10} {'n':>5} {'Ann%':>7} {'Vol%':>6} {'Sharpe':>7} {'MDD%':>8} {'LO days':>8}"
    print(header)
    print("-" * len(header))
    for lab, base_s, gate_s, lo_days, total in rows:
        for mode, rs in [("baseline", base_s), ("gated", gate_s)]:
            if not rs:
                continue
            sr = rs["sharpe"] if rs["sharpe"] is not None else float("nan")
            lo_str = f"{lo_days}/{total}" if mode == "gated" else "-"
            print(
                f"{lab:<22} {mode:<10} "
                f"{rs['n_days']:>5} "
                f"{rs['ann_return']*100:>+6.2f} "
                f"{rs['ann_vol']*100:>5.2f} "
                f"{sr:>+6.2f} "
                f"{rs['mdd']*100:>+7.2f} "
                f"{lo_str:>8}"
            )

    # 保存
    out_pq = ROOT / "logs" / "riad_regime_gated_returns.parquet"
    gated.to_parquet(out_pq)
    print(f"\n保存: {out_pq}")

    stamp = datetime.now().strftime("%Y%m%d")
    out_json = ROOT / "logs" / f"riad_regime_gate_{stamp}.json"
    with open(out_json, "w") as f:
        json.dump(
            {
                "generated_at": datetime.now().isoformat(timespec="seconds"),
                "rule": f"long-only when HS300 {GATE_WINDOW}d return (T-1) > +{GATE_THRESHOLD*100:.0f}%",
                "pre_reg_locked": True,
                "results": {lab: {"baseline": b, "gated": g, "long_only_days": lo, "total_days": t}
                            for lab, b, g, lo, t in rows},
            },
            f, indent=2, ensure_ascii=False,
        )
    print(f"保存: {out_json}")


if __name__ == "__main__":
    main()
