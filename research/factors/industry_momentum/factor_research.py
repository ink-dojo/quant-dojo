"""
F13 行业动量因子 (Industry Momentum) — 散户友好低频策略

背景:
    Moskowitz & Grinblatt (1999) 经典: 行业过去 12-1 月动量 → 未来 1 月跑赢。
    A 股散户实现: 直接买行业 ETF (申万一级 30+ ETF 已上市)。
    HFT 无法抢跑: 月频换仓, 行业级别。
    适合散户: 无选股负担, 交易成本极低 (ETF 0.01% vs 个股 0.1%), 分散化。

构造:
    (A) ind_mom_12_1: 行业过去 252 日 - 过去 21 日 收益 (跳过最近反转)
    (B) ind_mom_6_1: 行业过去 126 日 - 过去 21 日
    (C) ind_mom_3: 行业过去 63 日 (纯动量)

评估:
    - 将行业层面 signal 反广播到个股 (组内共享 signal)
    - IC at FWD 20d (个股)
    - 行业分层回测: 月频换行业 top/bot 多空
    - IS/OOS 拆分

数据:
    price_wide_close + 行业分类 (申万一级)

运行: python research/factors/industry_momentum/factor_research.py
"""
import sys
import warnings
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))

import numpy as np
import pandas as pd

warnings.filterwarnings("ignore")

from utils.factor_analysis import compute_ic_series, ic_summary
from utils.fundamental_loader import get_industry_classification

PRICE = ROOT / "data" / "processed" / "price_wide_close_2014-01-01_2025-12-31_qfq_5477stocks.parquet"
OUT = ROOT / "research" / "factors" / "industry_momentum"

IS_START = "2015-01-01"
IS_END = "2025-12-31"


def build_industry_index(price: pd.DataFrame, industry_df: pd.DataFrame) -> pd.DataFrame:
    """行业等权指数 (日频)."""
    # industry_df 返回: columns=['symbol', 'industry_code']
    ind_map = (
        industry_df[["symbol", "industry_code"]]
        .dropna()
        .drop_duplicates(subset="symbol", keep="last")
        .set_index("symbol")["industry_code"]
        .to_dict()
    )
    # 每日每行业的等权均值 (基于 log return)
    ret = price.pct_change()
    # Group columns by industry
    ind_groups = {}
    for sym, ind in ind_map.items():
        if sym in ret.columns and isinstance(ind, str) and ind:
            ind_groups.setdefault(ind, []).append(sym)
    ind_ret = {}
    for ind, syms in ind_groups.items():
        if len(syms) >= 5:  # 至少 5 股
            ind_ret[ind] = ret[syms].mean(axis=1)
    ind_ret = pd.DataFrame(ind_ret)
    # 累积为 index
    ind_idx = (1 + ind_ret.fillna(0)).cumprod()
    print(f"  {len(ind_groups)} 行业, 合格 (>=5 股) {len(ind_ret.columns)}")
    return ind_idx, ind_map


def compute_ind_momentum(ind_idx: pd.DataFrame, long_window: int, skip: int) -> pd.DataFrame:
    """行业动量: past long_window 日总 return 减去最近 skip 日总 return."""
    ret_long = ind_idx / ind_idx.shift(long_window) - 1
    ret_skip = ind_idx / ind_idx.shift(skip) - 1
    return ret_long - ret_skip


def broadcast_to_stocks(ind_signal: pd.DataFrame, ind_map: dict, codes: list) -> pd.DataFrame:
    """把行业级别 signal 广播回个股: 股票 i 的 signal = 其所属行业当日 signal."""
    # cols: stocks
    panel = pd.DataFrame(index=ind_signal.index, columns=codes, dtype=float)
    for sym in codes:
        ind = ind_map.get(sym)
        if ind and ind in ind_signal.columns:
            panel[sym] = ind_signal[ind].values
    return panel


def main():
    print("=" * 70)
    print("F13 行业动量因子研究")
    print("=" * 70)
    OUT.mkdir(parents=True, exist_ok=True)

    price = pd.read_parquet(PRICE)
    price.index = pd.to_datetime(price.index)
    price = price.loc[IS_START:IS_END]
    codes = list(price.columns)
    print(f"[价格] {len(price)} 交易日 × {len(codes)} 股")

    print("\n[行业] 加载分类...")
    industry_df = get_industry_classification(symbols=codes, use_cache=True)
    print(f"  行业分类覆盖 {industry_df['industry_code'].notna().sum()} 股")

    print("\n[行业指数] 构造等权累积...")
    ind_idx, ind_map = build_industry_index(price, industry_df)
    print(f"  行业指数形状 {ind_idx.shape}")

    # 行业动量变体
    print("\n[信号] 构造行业动量...")
    mom_12_1 = compute_ind_momentum(ind_idx, 252, 21)  # 12-1 月
    mom_6_1 = compute_ind_momentum(ind_idx, 126, 21)   # 6-1 月
    mom_3 = ind_idx / ind_idx.shift(63) - 1            # 3 月 (含近期)
    mom_12 = ind_idx / ind_idx.shift(252) - 1          # 纯 12 月

    # shift 1 防未来函数 (today's 12-1 momentum 明天才能交易)
    mom_12_1 = mom_12_1.shift(1)
    mom_6_1 = mom_6_1.shift(1)
    mom_3 = mom_3.shift(1)
    mom_12 = mom_12.shift(1)

    # ===== 行业级别测试 =====
    print("\n[行业级] 月频换仓 top-N 行业 多空 (fwd 21d):")
    fwd_ind = ind_idx.pct_change(21).shift(-21)  # 未来 21 日行业收益

    def ind_long_short(signal, fwd, n_top=5, n_bot=5, freq=21):
        """每 freq 日对行业 signal 排序, 做多 top n 做空 bot n, 等权。"""
        sig = signal.iloc[::freq]  # 月频取样
        sig = sig.dropna(how="all")
        rets = []
        for t in sig.index:
            row = signal.loc[t].dropna()
            if len(row) < (n_top + n_bot):
                continue
            top = row.nlargest(n_top).index
            bot = row.nsmallest(n_bot).index
            fwd_row = fwd.loc[t]
            top_r = fwd_row.reindex(top).mean()
            bot_r = fwd_row.reindex(bot).mean()
            rets.append((t, top_r, bot_r, top_r - bot_r))
        return pd.DataFrame(rets, columns=["date", "top", "bot", "ls"]).set_index("date")

    for name, sig in [("mom_12_1", mom_12_1), ("mom_6_1", mom_6_1), ("mom_3", mom_3), ("mom_12", mom_12)]:
        ls_df = ind_long_short(sig, fwd_ind, n_top=5, n_bot=5, freq=21)
        if len(ls_df) == 0:
            continue
        ls = ls_df["ls"]
        ann = ls.mean() * 12
        vol = ls.std() * np.sqrt(12)
        sr = ann / vol if vol > 0 else np.nan
        top_ann = ls_df["top"].mean() * 12
        bot_ann = ls_df["bot"].mean() * 12
        print(f"    {name:<10}  top-5 ann {top_ann:+.2%}  bot-5 ann {bot_ann:+.2%}  LS ann {ann:+.2%}  夏普 {sr:.2f}  n_months {len(ls)}")

    # ===== 个股级 IC (广播到股票后做截面 IC, 股票内有多行业就同一值) =====
    print("\n[个股级] 行业信号广播到股票 → 截面 IC (fwd 20d):")
    ret20 = price.shift(-20) / price - 1
    for name, sig in [("mom_12_1", mom_12_1), ("mom_6_1", mom_6_1), ("mom_3", mom_3)]:
        fac = broadcast_to_stocks(sig, ind_map, codes)
        ic = compute_ic_series(fac, ret20, method="spearman", min_stocks=500)
        s = ic_summary(ic, name=name, fwd_days=20, verbose=False)
        print(f"    {name:<10} IC {s['IC_mean']:+.4f}  ICIR {s['ICIR']:+.3f}  HAC t {s['t_stat_hac']:+.2f}  n {s['n']}")

    # ===== IS / OOS on best variant =====
    print("\n[IS/OOS] mom_12_1 行业级 long-short:")
    ls_df = ind_long_short(mom_12_1, fwd_ind, n_top=5, n_bot=5, freq=21)
    for label, sl in [("IS 2015-2021", slice("2015-01-01", "2021-12-31")),
                      ("OOS 2022-2025", slice("2022-01-01", "2025-12-31"))]:
        ls_sl = ls_df.loc[sl]
        if len(ls_sl) == 0:
            continue
        ann = ls_sl["ls"].mean() * 12
        vol = ls_sl["ls"].std() * np.sqrt(12)
        sr = ann / vol if vol > 0 else np.nan
        print(f"    {label:<15}  ann {ann:+.2%}  夏普 {sr:.2f}  months {len(ls_sl)}")

    # 保存 (行业级 signal)
    mom_12_1.to_parquet(OUT / "ind_mom_12_1.parquet")
    mom_6_1.to_parquet(OUT / "ind_mom_6_1.parquet")
    # 保存行业级 3m 反转 signal (广播到股票) — 这是最强的 stock-level 信号
    mom_3_panel = broadcast_to_stocks(mom_3, ind_map, codes)
    # 取负号 (高 rank = 行业前 3m 跌多 → 预期反弹)
    ind_reversal_3m = -mom_3_panel
    ind_reversal_3m.to_parquet(OUT / "ind_reversal_3m.parquet")
    # 保存 ind_map
    pd.Series(ind_map).to_frame("industry_code").to_parquet(OUT / "industry_map.parquet")

    with open(OUT / "report.md", "w") as f:
        f.write("# F13 行业动量因子研究\n\n")
        f.write(f"**日期**: 2026-04-21  \n")
        f.write("## 设置\n\n")
        f.write(f"- 价格: qfq 2015-2025, {len(codes)} 股\n")
        f.write(f"- 行业: 申万一级 ({ind_idx.shape[1]} 行业)\n")
        f.write("- 变体: 12-1m, 6-1m, 3m, 12m\n\n")
        f.write("## 策略实现\n\n")
        f.write("散户执行方案: 每月底对 30+ 申万一级 ETF 按过去 12-1 月收益排序, 持有 top-5 行业等权 ETF, 月末换仓。\n")

    print(f"\n[保存] {OUT}")
    print("=" * 70)
    print("DONE")


if __name__ == "__main__":
    main()
