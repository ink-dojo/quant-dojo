"""DSR #30 组件 + ensemble vs DSR #33: 年度 SR 分解 (检查 alpha decay).

前因: 2026-04-21 jialong 质疑 ensemble 可能已死, 因为 #33 2018→2024 SR
单调衰减. 关键问题是 #30 (BB + PV 主板 rescaled) 是否也有同样衰减 — 如果
#30 稳定, ensemble 还能只上 #30; 如果 #30 也衰减, 整个 Phase 3+4 没有
生产级策略.

输出: 2018-2025 年度 ret/SR/MDD 对 BB / PV / #30 ensemble / #33 / 50/50 big
ensemble 共 5 条序列.
"""
from __future__ import annotations
import numpy as np
import pandas as pd


def year_stats(r: pd.Series) -> pd.DataFrame:
    r = r.dropna()
    by_year = r.groupby(r.index.year)
    rows = []
    for y, x in by_year:
        ann_ret = (1 + x).prod() - 1
        sr = x.mean() / x.std() * np.sqrt(252) if x.std() > 0 else np.nan
        cum = (1 + x).cumprod()
        peak = cum.cummax()
        mdd = (cum / peak - 1).min()
        rows.append({"year": y, "ret": ann_ret, "SR": sr, "MDD": mdd, "n_days": len(x)})
    return pd.DataFrame(rows).set_index("year")


def load(path: str) -> pd.Series:
    df = pd.read_parquet(path)
    col = df.columns[0]
    s = df[col].copy()
    s.index = pd.to_datetime(s.index)
    return s.sort_index()


def main():
    bb = load("research/event_driven/dsr30_mainboard_bb_oos.parquet")
    pv = load("research/event_driven/dsr30_mainboard_pv_oos.parquet")
    dsr30 = load("research/event_driven/dsr30_mainboard_recal_ensemble_oos.parquet")
    dsr33 = load("research/event_driven/dsr33_lhb_decline_oos.parquet")

    df = pd.concat([
        bb.rename("bb"), pv.rename("pv"),
        dsr30.rename("dsr30"), dsr33.rename("dsr33"),
    ], axis=1).dropna()
    df["big_ens"] = 0.5 * df["dsr30"] + 0.5 * df["dsr33"]

    print("=" * 72)
    print(f"  年度分解 — {df.index[0].date()} ~ {df.index[-1].date()}  n_days={len(df)}")
    print("=" * 72)

    for col in ["bb", "pv", "dsr30", "dsr33", "big_ens"]:
        s = df[col]
        total_ann = (1 + s).prod() ** (252 / len(s)) - 1
        total_sr = s.mean() / s.std() * np.sqrt(252)
        print(f"\n--- {col}  total: ann={total_ann:+.2%}  SR={total_sr:+.3f} ---")
        yr = year_stats(s)
        print(yr.round(4).to_string())

    # 专门对比 #30 ensemble
    print("\n" + "=" * 72)
    print("  核心对比: DSR #30 ensemble 是否也衰减? (BB + PV 50/50 主板 rescaled)")
    print("=" * 72)
    yr30 = year_stats(df["dsr30"])
    yr33 = year_stats(df["dsr33"])
    yrbe = year_stats(df["big_ens"])
    comp = pd.DataFrame({
        "DSR#30_SR": yr30["SR"],
        "DSR#30_ret": yr30["ret"],
        "DSR#33_SR": yr33["SR"],
        "DSR#33_ret": yr33["ret"],
        "big_ens_SR": yrbe["SR"],
        "big_ens_ret": yrbe["ret"],
    }).round(3)
    print(comp.to_string())

    # Decay check: 前半期 vs 后半期
    print("\n" + "=" * 72)
    print("  Decay: 2018-2021 vs 2022-2025  (4 年 vs 4 年)")
    print("=" * 72)
    for col in ["bb", "pv", "dsr30", "dsr33", "big_ens"]:
        s = df[col]
        early = s[(s.index.year >= 2018) & (s.index.year <= 2021)]
        late = s[(s.index.year >= 2022) & (s.index.year <= 2025)]
        sr_e = early.mean() / early.std() * np.sqrt(252)
        sr_l = late.mean() / late.std() * np.sqrt(252)
        ann_e = (1 + early).prod() ** (252 / len(early)) - 1
        ann_l = (1 + late).prod() ** (252 / len(late)) - 1
        print(f"  {col:8s}: early SR={sr_e:+.2f} ann={ann_e:+.2%}  "
              f"late SR={sr_l:+.2f} ann={ann_l:+.2%}  "
              f"Δ_SR={sr_l - sr_e:+.2f}")

    # 最近 12 个月
    print("\n" + "=" * 72)
    print("  Recent: 2024-2025 (24 months)")
    print("=" * 72)
    recent = df[df.index.year >= 2024]
    for col in ["bb", "pv", "dsr30", "dsr33", "big_ens"]:
        s = recent[col]
        ann = (1 + s).prod() ** (252 / len(s)) - 1
        sr = s.mean() / s.std() * np.sqrt(252)
        print(f"  {col:8s}: ann={ann:+.2%}  SR={sr:+.3f}  n={len(s)}")


if __name__ == "__main__":
    main()
