"""
大单/超大单净流入因子 (Large Order Net Inflow) — F7

背景：
    moneyflow 表按交易额分四档：sm(小) / md(中) / lg(大) / elg(超大)。
    学界惯用口径：lg + elg 代表机构/大户资金流，相对 sm + md 散户资金流。
    假设：大单净流入比例高 → 机构在低位吸筹 → 未来跑赢。
    反方向也要测：A 股散户化强，大单流入可能 = "接盘侠"现象。

构造：
    (A) big_ratio_20d = (buy_lg + buy_elg - sell_lg - sell_elg).rolling(20).sum()
                       / total_vol.rolling(20).sum()
    (B) elg_ratio_20d : 仅超大单 (> 100万)
    (C) big_net_amount_norm: 20 日大单净流入金额 / 流通市值 (用 daily_basic.circ_mv)

测试：20 日前瞻 IC / ICIR / HAC t, 同时测 +/- 两个方向。

运行：python research/factors/moneyflow_large/factor_research.py
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
OUT = ROOT / "research" / "factors" / "moneyflow_large"
IS_START = "2020-01-01"
IS_END = "2025-12-31"
FWD = 20


def load_moneyflow_panel(codes: list):
    """加载 moneyflow，构造宽表：buy_lg_elg_amount, sell_lg_elg_amount, total_amount。"""
    files = list((RAW / "moneyflow").glob("*.parquet"))
    print(f"[数据] moneyflow 文件 {len(files)} 个，按需加载 {len(codes)} 股...")
    code_set = set(codes)
    buy_big = {}   # large + elg buy
    sell_big = {}  # large + elg sell
    total_amt = {} # all four buckets (buy + sell)
    loaded = 0
    for f in files:
        if f.stem not in code_set:
            continue
        try:
            df = pd.read_parquet(f, columns=[
                "trade_date", "buy_lg_amount", "buy_elg_amount",
                "sell_lg_amount", "sell_elg_amount",
                "buy_sm_amount", "buy_md_amount", "sell_sm_amount", "sell_md_amount",
            ])
            df["trade_date"] = pd.to_datetime(df["trade_date"].astype(str), errors="coerce")
            df = df.dropna(subset=["trade_date"]).sort_values("trade_date")
            df = df.drop_duplicates(subset=["trade_date"], keep="last").set_index("trade_date")
            buy_big[f.stem] = df["buy_lg_amount"].fillna(0) + df["buy_elg_amount"].fillna(0)
            sell_big[f.stem] = df["sell_lg_amount"].fillna(0) + df["sell_elg_amount"].fillna(0)
            total_amt[f.stem] = (df["buy_sm_amount"].fillna(0) + df["buy_md_amount"].fillna(0)
                                 + df["buy_lg_amount"].fillna(0) + df["buy_elg_amount"].fillna(0)
                                 + df["sell_sm_amount"].fillna(0) + df["sell_md_amount"].fillna(0)
                                 + df["sell_lg_amount"].fillna(0) + df["sell_elg_amount"].fillna(0))
            loaded += 1
        except Exception:
            continue
    print(f"[数据] 已加载 {loaded} 股")
    return pd.DataFrame(buy_big), pd.DataFrame(sell_big), pd.DataFrame(total_amt)


def main():
    print("="*70)
    print("F7 大单/超大单净流入因子研究")
    print("="*70)
    OUT.mkdir(parents=True, exist_ok=True)

    price = pd.read_parquet(ROOT / "data/processed/price_wide_close_2014-01-01_2025-12-31_qfq_5477stocks.parquet")
    price.index = pd.to_datetime(price.index)
    price = price.loc[IS_START:IS_END]
    codes = list(price.columns)

    buy_big, sell_big, total_amt = load_moneyflow_panel(codes)

    # 对齐到 price index
    buy_big = buy_big.reindex(index=price.index, columns=codes)
    sell_big = sell_big.reindex(index=price.index, columns=codes)
    total_amt = total_amt.reindex(index=price.index, columns=codes)

    # (A) 大单净流入比例 20 日
    net_big = buy_big - sell_big  # 日大单净流入
    net_big_20d = net_big.rolling(20, min_periods=10).sum()
    total_20d = total_amt.rolling(20, min_periods=10).sum().replace(0, np.nan)
    big_ratio_20d = (net_big_20d / total_20d).shift(1)   # .shift(1) 防未来函数

    # (B) 大单净流入金额绝对值 20 日 (万元)
    net_big_amt_20d = net_big_20d.shift(1)

    # fwd return
    ret_fwd = price.shift(-FWD) / price - 1

    print("\n[A] big_ratio_20d (大单净流入 / 总成交额) 20日前瞻 IC:")
    ic_a = compute_ic_series(big_ratio_20d, ret_fwd, method="spearman", min_stocks=500)
    stats_a = ic_summary(ic_a, name="big_ratio_20d", fwd_days=FWD)

    print("\n[B] net_big_amt_20d (大单净流入金额) IC:")
    ic_b = compute_ic_series(net_big_amt_20d, ret_fwd, method="spearman", min_stocks=500)
    stats_b = ic_summary(ic_b, name="net_big_amt_20d", fwd_days=FWD)

    # 分层回测
    print("\n[C] 分层回测 big_ratio_20d 5 组 (大单买入强度):")
    try:
        grp, ls = quintile_backtest(big_ratio_20d, ret_fwd, n_groups=5, long_short="Qn_minus_Q1")
        ann = ls.mean() * 252 / FWD
        vol = ls.std() * np.sqrt(252 / FWD)
        sr = ann / vol if vol > 0 else np.nan
        print(f"    多空年化 {ann:.2%}  夏普 {sr:.2f}")
        grp_ann = grp.mean() * 252 / FWD
        print(grp_ann)
    except Exception as e:
        print(f"    分层回测失败: {e}")
        grp_ann = pd.Series(); ann = np.nan; sr = np.nan

    # 反向测试（A 股散户化 → 大单可能是"接盘"）
    print("\n[D] 反向 -big_ratio_20d IC (若大单 = 接盘侠):")
    inv = -big_ratio_20d
    ic_inv = compute_ic_series(inv, ret_fwd, method="spearman", min_stocks=500)
    stats_inv = ic_summary(ic_inv, name="-big_ratio_20d", fwd_days=FWD, verbose=False)
    print(f"    -big_ratio IC {stats_inv['IC_mean']:+.4f}  ICIR {stats_inv['ICIR']:+.3f}  HAC t {stats_inv['t_stat_hac']:+.2f}")

    # 保存
    big_ratio_20d.to_parquet(OUT / "big_ratio_20d.parquet")
    net_big_amt_20d.to_parquet(OUT / "net_big_amt_20d.parquet")

    with open(OUT / "report.md", "w") as f:
        f.write("# F7 大单/超大单净流入因子研究报告\n\n")
        f.write(f"**日期**：2026-04-21  \n")
        f.write(f"**数据**：moneyflow 2020-2025, 全部 {len(codes)} 股\n\n")
        f.write("## A. big_ratio_20d (大单净流入 / 总成交额)\n\n")
        f.write(f"- IC 均值 {stats_a['IC_mean']:.4f}\n")
        f.write(f"- ICIR {stats_a['ICIR']:.4f}\n")
        f.write(f"- HAC t {stats_a['t_stat_hac']:.4f}\n")
        f.write(f"- IC>0 占比 {stats_a['pct_pos']:.2%}\n\n")
        f.write("## B. net_big_amt_20d (大单净流入金额)\n\n")
        f.write(f"- IC 均值 {stats_b['IC_mean']:.4f}\n")
        f.write(f"- ICIR {stats_b['ICIR']:.4f}\n")
        f.write(f"- HAC t {stats_b['t_stat_hac']:.4f}\n\n")
        f.write("## C. 反向 -big_ratio_20d\n\n")
        f.write(f"- IC {stats_inv['IC_mean']:+.4f}  ICIR {stats_inv['ICIR']:+.3f}  HAC t {stats_inv['t_stat_hac']:+.2f}\n\n")
        f.write("## D. big_ratio_20d 分层年化\n\n")
        if len(grp_ann) > 0:
            f.write(grp_ann.to_frame("ann").round(4).to_markdown())
            f.write(f"\n\n多空 Q5-Q1 年化 {ann:.2%} 夏普 {sr:.2f}\n\n")
        f.write("## 结论\n\n")
        best_icir = max(abs(stats_a["ICIR"]), abs(stats_inv["ICIR"]))
        best_t = max(abs(stats_a["t_stat_hac"]), abs(stats_inv["t_stat_hac"]))
        if best_icir > 0.3 and best_t > 2:
            f.write("- ✅ 至少一个方向通过 ICIR 0.3 + HAC t 2 双门槛\n")
        else:
            f.write("- ❌ 两方向均未通过双门槛\n")
    print(f"\n[保存] -> {OUT}")
    print("="*70, "\nDONE")


if __name__ == "__main__":
    main()
