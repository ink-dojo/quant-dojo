"""
融资余额占流通市值比例 (Margin/MktCap Ratio) — F8

背景：
    margin 表 rzye (融资余额) = 散户融资买入未偿还金额，是零售杠杆指标。
    假设：rzye / circ_mv 高 → 散户加杠杆抢入 → 局部顶部 → 反向未来跑输 (contrarian)

构造：
    margin_ratio = rzye / circ_mv
    变化量：margin_ratio_chg_20d = margin_ratio - margin_ratio.shift(20)

测试：IC / ICIR / HAC t，正反两方向

运行：python research/factors/margin_balance/factor_research.py
"""
import sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))

import warnings
import numpy as np
import pandas as pd

warnings.filterwarnings("ignore")

from utils.factor_analysis import compute_ic_series, ic_summary, quintile_backtest

RAW = ROOT / "data" / "raw" / "tushare"
OUT = ROOT / "research" / "factors" / "margin_balance"
IS_START = "2020-01-01"
IS_END = "2025-12-31"
FWD = 20


def load_series(sub: str, col: str, codes):
    files = list((RAW / sub).glob("*.parquet"))
    code_set = set(codes)
    series = {}
    for f in files:
        if f.stem not in code_set:
            continue
        try:
            df = pd.read_parquet(f, columns=["trade_date", col])
            df["trade_date"] = pd.to_datetime(df["trade_date"].astype(str), errors="coerce")
            df = df.dropna(subset=["trade_date"]).sort_values("trade_date")
            df = df.drop_duplicates(subset=["trade_date"], keep="last").set_index("trade_date")
            series[f.stem] = df[col]
        except Exception:
            continue
    return pd.DataFrame(series)


def main():
    print("="*70)
    print("F8 融资余额 / 流通市值 ratio 因子研究")
    print("="*70)
    OUT.mkdir(parents=True, exist_ok=True)

    price = pd.read_parquet(ROOT / "data/processed/price_wide_close_2014-01-01_2025-12-31_qfq_5477stocks.parquet")
    price.index = pd.to_datetime(price.index)
    price = price.loc[IS_START:IS_END]
    codes = list(price.columns)

    print("[数据] 载入 margin rzye ...")
    rzye = load_series("margin", "rzye", codes)
    rzye = rzye.reindex(index=price.index, columns=codes)
    print(f"  rzye 覆盖 {rzye.notna().sum(axis=1).mean():.0f} 股/日")

    print("[数据] 载入 daily_basic circ_mv ...")
    circ = load_series("daily_basic", "circ_mv", codes)
    circ = circ.reindex(index=price.index, columns=codes)

    # margin_ratio = rzye / (circ_mv * 10000) since circ_mv 单位是万元，rzye 是元
    margin_ratio = (rzye / (circ * 10000)).replace([np.inf, -np.inf], np.nan)
    margin_ratio = margin_ratio.shift(1)  # 避免未来函数

    # 20 日变化
    margin_chg_20d = (margin_ratio - margin_ratio.shift(20))

    # fwd return
    ret_fwd = price.shift(-FWD) / price - 1

    print("\n[A] margin_ratio (level) 20日前瞻 IC:")
    ic_a = compute_ic_series(margin_ratio, ret_fwd, method="spearman", min_stocks=500)
    stats_a = ic_summary(ic_a, name="margin_ratio", fwd_days=FWD)

    print("\n[B] margin_chg_20d (20日变化) IC:")
    ic_b = compute_ic_series(margin_chg_20d, ret_fwd, method="spearman", min_stocks=500)
    stats_b = ic_summary(ic_b, name="margin_chg_20d", fwd_days=FWD)

    # 反向
    for nm, fac in [("-margin_ratio", -margin_ratio), ("-margin_chg_20d", -margin_chg_20d)]:
        ic = compute_ic_series(fac, ret_fwd, method="spearman", min_stocks=500)
        s = ic_summary(ic, name=nm, fwd_days=FWD, verbose=False)
        print(f"    {nm:<20} IC {s['IC_mean']:+.4f}  ICIR {s['ICIR']:+.3f}  HAC t {s['t_stat_hac']:+.2f}")

    # 分层回测 (level)
    print("\n[C] 分层回测 margin_ratio 5 组:")
    try:
        grp, ls = quintile_backtest(margin_ratio, ret_fwd, n_groups=5, long_short="Qn_minus_Q1")
        ann = ls.mean() * 252 / FWD
        vol = ls.std() * np.sqrt(252 / FWD)
        sr = ann / vol if vol > 0 else np.nan
        print(f"    多空年化 {ann:.2%}  夏普 {sr:.2f}")
        print(grp.mean() * 252 / FWD)
    except Exception as e:
        print(f"    分层失败: {e}")
        ann = sr = np.nan

    # 保存
    margin_ratio.to_parquet(OUT / "margin_ratio.parquet")
    margin_chg_20d.to_parquet(OUT / "margin_chg_20d.parquet")

    with open(OUT / "report.md", "w") as f:
        f.write("# F8 融资余额 / 流通市值 ratio 因子\n\n")
        f.write(f"**日期**：2026-04-21  \n\n")
        f.write("## A. margin_ratio (level)\n\n")
        f.write(f"- IC {stats_a['IC_mean']:+.4f}  ICIR {stats_a['ICIR']:+.3f}  HAC t {stats_a['t_stat_hac']:+.2f}\n\n")
        f.write("## B. margin_chg_20d\n\n")
        f.write(f"- IC {stats_b['IC_mean']:+.4f}  ICIR {stats_b['ICIR']:+.3f}  HAC t {stats_b['t_stat_hac']:+.2f}\n\n")
        f.write("## 结论\n\n")
        best = max(abs(stats_a['ICIR']), abs(stats_b['ICIR']))
        if best > 0.3:
            f.write("- ✅ 至少一个变体通过 ICIR 0.3\n")
        else:
            f.write("- ❌ 两变体均 ICIR < 0.3, 不入 v18 候选\n")
    print(f"\n[保存] -> {OUT}")
    print("="*70, "\nDONE")


if __name__ == "__main__":
    main()
