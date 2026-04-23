"""
RIAD Fold 3 诊断 — 按 SW1 行业的 LS attribution

做法:
    每 20 日调仓, 对每个 SW1 行业 i (前 2 位 code):
        该行业内 Q2Q3 (factor rank 行业内 [20%, 60%]) long
        该行业内 Q5   (factor rank 行业内 [80%, 100%]) short
        行业 LS_i = within-industry Q2Q3 mean - Q5 mean
    记录每个行业每周期的 LS, 按行业分段汇总.

目的: 识别 2025 H2 alpha 消失是否 concentrate 在某几个行业
      (比如 TMT / 军工 / 新能源 — 这些 2025 散户热度重灾区)

Note: 行业内样本少, Q2Q3/Q5 各需 ≥ 3 只股票才记录
"""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[3]

from research.factors.retail_inst_divergence.daily_returns import (  # noqa: E402
    COST_ONE_WAY, LONG_HIGH, LONG_LOW, PRICE_PATH, REBALANCE_DAYS,
    SHORT_HIGH, SHORT_LOW, _to_ts, build_riad_neutral,
)
from research.factors.retail_inst_divergence.industry_eval import load_industry_series  # noqa: E402

SW1_NAMES = {
    "11": "农林牧渔", "21": "采掘", "22": "化工", "23": "钢铁", "24": "有色",
    "27": "电子", "28": "家电", "33": "食品饮料", "34": "纺织服装", "35": "轻工",
    "36": "医药生物", "37": "公用事业", "41": "交通运输", "42": "房地产",
    "43": "商业贸易", "45": "休闲服务", "46": "综合", "48": "建筑材料",
    "49": "建筑装饰", "51": "电气设备", "61": "国防军工", "62": "计算机",
    "63": "传媒", "64": "通信", "71": "银行", "72": "非银金融",
    "73": "汽车", "74": "机械设备",
}


def build_industry_ls_daily(
    factor: pd.DataFrame,
    price: pd.DataFrame,
    ind_sw1: pd.Series,
    start: str, end: str,
) -> dict[str, pd.Series]:
    """
    返回: dict[sw1_code] -> pd.Series (daily LS returns for that industry)
    """
    dates = price.loc[start:end].index
    rebal = dates[::REBALANCE_DAYS]
    pct = price.pct_change()
    rebal_idx = pd.DatetimeIndex(rebal)

    # 预先: 每个调仓日对每个行业的 long/short set
    per_period: list[dict[str, tuple[set, set]]] = []
    for d in rebal:
        if d not in factor.index:
            per_period.append({}); continue
        s = factor.loc[d].dropna()
        if len(s) < 200:
            per_period.append({}); continue

        ind_groups: dict[str, list[str]] = {}
        for ts, v in s.items():
            if ts not in ind_sw1.index:
                continue
            ind = ind_sw1[ts]
            ind_groups.setdefault(ind, []).append(ts)

        period_dict = {}
        for ind, members in ind_groups.items():
            if len(members) < 10:
                continue
            s_ind = s[members]
            q_ll, q_lh = s_ind.quantile(LONG_LOW), s_ind.quantile(LONG_HIGH)
            q_sl, q_sh = s_ind.quantile(SHORT_LOW), s_ind.quantile(SHORT_HIGH)
            long_set = set(s_ind[(s_ind >= q_ll) & (s_ind <= q_lh)].index)
            short_set = set(s_ind[(s_ind >= q_sl) & (s_ind <= q_sh)].index)
            if len(long_set) >= 3 and len(short_set) >= 3:
                period_dict[ind] = (long_set, short_set)
        per_period.append(period_dict)

    # 日度: 对每个行业累计 LS
    ind_daily = {}
    for d in dates:
        pos = rebal_idx.searchsorted(d, side="right") - 1
        if pos < 0 or d not in pct.index:
            continue
        period_dict = per_period[pos]
        if not period_dict:
            continue
        row = pct.loc[d]
        for ind, (long_set, short_set) in period_dict.items():
            long_syms = [s for s in long_set if s in row.index]
            short_syms = [s for s in short_set if s in row.index]
            if len(long_syms) < 2 or len(short_syms) < 2:
                continue
            long_r = float(row[long_syms].mean(skipna=True))
            short_r = float(row[short_syms].mean(skipna=True))
            ind_daily.setdefault(ind, {})[d] = long_r - short_r

    return {ind: pd.Series(v).sort_index() for ind, v in ind_daily.items()}


def sharpe(s: pd.Series) -> float:
    s = s.dropna()
    if len(s) < 20:
        return np.nan
    mu, sd = s.mean() * 252, s.std(ddof=1) * np.sqrt(252)
    return mu / sd if sd > 0 else np.nan


def cum(s: pd.Series) -> float:
    s = s.dropna()
    if s.empty:
        return np.nan
    return float((1 + s).prod() - 1)


def main() -> None:
    start, end = "2023-10-01", "2025-12-31"
    price = pd.read_parquet(PRICE_PATH)
    price.columns = [_to_ts(c) for c in price.columns]

    print("构造 RIAD + 行业分类...")
    factor = build_riad_neutral(start, end, price).shift(1)
    ind_sw1 = load_industry_series()  # value 是前 2 位
    print(f"  SW1 行业: {ind_sw1.nunique()}")

    print("计算行业内 LS daily...")
    ind_daily = build_industry_ls_daily(factor, price, ind_sw1, start, end)
    print(f"  覆盖行业数: {len(ind_daily)}")

    segments = [
        ("2024 H1", "2024-01-01", "2024-06-30"),
        ("2024 H2", "2024-07-01", "2024-12-31"),
        ("2025 H1", "2025-01-01", "2025-06-30"),
        ("2025 H2", "2025-07-01", "2025-12-31"),
    ]

    print("\n=== 各 SW1 行业 LS Sharpe (4 分段) ===\n")
    header = f"{'SW1':<6} {'行业':<10} "
    for lab, _, _ in segments:
        header += f"{lab:>8} "
    header += f"{'Δ H2':>8}"  # 2025 H2 - 2024 H1
    print(header)
    print("-" * len(header))

    rows = []
    for ind in sorted(ind_daily.keys()):
        name = SW1_NAMES.get(ind, "?")
        series = ind_daily[ind]
        srs_seg = {}
        cums_seg = {}
        for lab, s, e in segments:
            sub = series.loc[s:e]
            srs_seg[lab] = sharpe(sub)
            cums_seg[lab] = cum(sub)
        rows.append({"sw1": ind, "name": name, "sharpe": srs_seg, "cum": cums_seg})

    # 按 2025 H2 Sharpe 从低到高排序 (最负的前列 = 贡献最大衰退)
    rows.sort(key=lambda r: r["sharpe"]["2025 H2"] if pd.notna(r["sharpe"]["2025 H2"]) else 99)
    for r in rows:
        line = f"{r['sw1']:<6} {r['name']:<10} "
        for lab, _, _ in segments:
            v = r["sharpe"][lab]
            line += f"{('n/a' if pd.isna(v) else f'{v:+.2f}'):>8} "
        # delta: 2025 H2 - 2024 H1
        s_h1 = r["sharpe"]["2024 H1"]
        s_h2_25 = r["sharpe"]["2025 H2"]
        if pd.notna(s_h1) and pd.notna(s_h2_25):
            delta = s_h2_25 - s_h1
            line += f"{delta:+.2f}"
        print(line)

    # 汇总: 哪些行业 2025 H2 SR < -1 (严重失效)
    fail_inds = [r for r in rows if pd.notna(r["sharpe"]["2025 H2"]) and r["sharpe"]["2025 H2"] < -1]
    win_inds = [r for r in rows if pd.notna(r["sharpe"]["2025 H2"]) and r["sharpe"]["2025 H2"] > 1]
    print(f"\n2025 H2 严重失效 (SR < -1) 行业 ({len(fail_inds)}):")
    for r in fail_inds:
        print(f"  {r['sw1']} {r['name']}: SR={r['sharpe']['2025 H2']:+.2f}, cum={r['cum']['2025 H2']*100:+.2f}%")
    print(f"\n2025 H2 仍有 alpha (SR > 1) 行业 ({len(win_inds)}):")
    for r in win_inds:
        print(f"  {r['sw1']} {r['name']}: SR={r['sharpe']['2025 H2']:+.2f}, cum={r['cum']['2025 H2']*100:+.2f}%")

    stamp = datetime.now().strftime("%Y%m%d")
    out_json = ROOT / "logs" / f"riad_industry_attribution_{stamp}.json"
    with open(out_json, "w") as f:
        json.dump({
            "generated_at": datetime.now().isoformat(timespec="seconds"),
            "segments": [s[0] for s in segments],
            "rows": [{
                "sw1": r["sw1"], "name": r["name"],
                "sharpe": {k: (float(v) if pd.notna(v) else None) for k, v in r["sharpe"].items()},
                "cum": {k: (float(v) if pd.notna(v) else None) for k, v in r["cum"].items()},
            } for r in rows],
        }, f, indent=2, ensure_ascii=False)
    print(f"\n保存: {out_json}")


if __name__ == "__main__":
    main()
