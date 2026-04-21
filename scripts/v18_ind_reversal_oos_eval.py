"""
v18 OOS 评估: v17 (6f with SN crowding) + ind_reversal_3m

新因子: 行业 3 月反转
  ICIR -0.32 (ALL), IS -0.31, OOS -0.35 — OOS 不衰减, 极 robust
  与 v17 是否独立需要验证

训练: 2022-01-01 ~ 2024-12-31
测试: 2025-01-01 ~ 2025-12-31
"""
import sys
import time
import warnings
from pathlib import Path

warnings.filterwarnings("ignore")
ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

import numpy as np
import pandas as pd

from utils.local_data_loader import get_all_symbols, load_price_wide
from utils.data_loader import get_index_history
from utils.metrics import annualized_return, sharpe_ratio, max_drawdown, calmar_ratio, win_rate
from utils.factor_analysis import neutralize_factor_by_industry
from utils.fundamental_loader import get_industry_classification
from utils.tradability_filter import apply_tradability_filter
from utils.multi_factor import icir_weight
from utils.alpha_factors import team_coin as _team_coin, low_vol_20d as _low_vol_20d, enhanced_momentum, bp_factor
from scripts.v6_admission_eval import run_backtest

WARMUP = "2020-01-01"
IS_START = "2022-01-01"
TRAIN_END = "2024-12-31"
OOS_START = "2025-01-01"
OOS_END = "2025-12-31"
N_STOCKS = 30
COST = 0.003
FWD = 20
MIN_W = 0.05


def apply_signs(factors, signs):
    return {n: f * signs.get(n, 1) for n, f in factors.items()}


def calc_metrics(ret, bench=None):
    if ret is None or len(ret) == 0:
        return {}
    m = {
        "ann": annualized_return(ret),
        "sr": sharpe_ratio(ret),
        "mdd": max_drawdown(ret),
        "calmar": calmar_ratio(ret),
        "wr": win_rate(ret),
    }
    if bench is not None:
        common = ret.index.intersection(bench.index)
        if len(common) > 20:
            m["excess"] = annualized_return(ret.loc[common] - bench.loc[common])
    return m


def learn_icir(factors, price, label):
    res = icir_weight(factors=factors, price_wide=price,
                     train_start=IS_START, train_end=TRAIN_END,
                     fwd_days=FWD, min_weight=MIN_W)
    print(f"\n  [{label}] ICIR 权重 (训练 22-24):")
    for n in factors:
        s = res["ic_stats"].get(n, {})
        print(f"    {n:<20} ICIR {s.get('icir',0):+.3f} 权重 {res['weights'].get(n,0):.1%} 方向 {res['signs'].get(n,1):+d}")
    return res


def main():
    t0 = time.time()
    print("="*70)
    print(f"v18 OOS: v17 + ind_reversal_3m (训练 22-24, 测 25)")
    print("="*70)

    print("\n[1/4] 加载 (外置盘 + pb 真值)...")
    symbols = get_all_symbols()
    price = load_price_wide(symbols, WARMUP, OOS_END, field="close")
    valid = price.columns[price.notna().sum() > 300]
    price = price[valid]
    pb = load_price_wide(list(valid), WARMUP, OOS_END, field="pb").reindex(index=price.index, columns=valid)
    hs300 = get_index_history(symbol="sh000300", start=WARMUP, end=OOS_END)
    common = price.index.intersection(hs300.index)
    price = price.loc[common]; pb = pb.reindex(index=price.index); hs300 = hs300.loc[common]
    tradable = apply_tradability_filter(price)
    print(f"  {len(valid)} 股 {len(price)} 日 | pb 覆盖 {pb.notna().mean().mean():.1%} | {time.time()-t0:.1f}s")

    print("\n[2/4] 因子构建...")
    factors_5 = {
        "team_coin": _team_coin(price),
        "low_vol_20d": _low_vol_20d(price),
        "cgo_simple": -(price / price.rolling(60).mean() - 1),
        "enhanced_mom_60": enhanced_momentum(price, window=60),
        "bp": bp_factor(pb).reindex_like(price),
    }
    industry_df = get_industry_classification(symbols=list(price.columns), use_cache=True)
    neutral_5 = {n: neutralize_factor_by_industry(f, industry_df, show_progress=False) for n, f in factors_5.items()}

    # v17 crowding (SN 版)
    raw_crowd = pd.read_parquet(ROOT / "research/factors/crowding_filter/composite_crowding_sn.parquet")
    raw_crowd.index = pd.to_datetime(raw_crowd.index)
    crowd = (-raw_crowd).reindex(index=price.index, columns=price.columns)
    crowd_neu = neutralize_factor_by_industry(crowd, industry_df, show_progress=False)
    neutral_6 = {**neutral_5, "neg_crowding": crowd_neu}

    # ind reversal 3m
    ind_rev = pd.read_parquet(ROOT / "research/factors/industry_momentum/ind_reversal_3m.parquet")
    ind_rev.index = pd.to_datetime(ind_rev.index)
    ind_rev = ind_rev.reindex(index=price.index, columns=price.columns)
    # 已是 -mom_3 方向 (高 rank = 预期反弹)。注意 ind_rev 是广播自行业信号，
    # 做行业中性化会把整个信号抹掉 (行业内全等)。所以不做行业中性, 只做 z-score 归一。
    # 对整体 crowding 的做法保持一致: 用行业中性化版本
    # 但 ind_rev 已经是按行业的均值, 再做行业中性化会归零。
    # 这里不做行业中性, 直接进因子池。
    neutral_7 = {**neutral_6, "ind_reversal_3m": ind_rev}

    hs300_ret = hs300["close"].pct_change().dropna()

    print("\n[3/4] 学权重 + 回测...")
    res9 = learn_icir(neutral_5, price, "v9_5f")
    res17 = learn_icir(neutral_6, price, "v17_6f_SN")
    res18 = learn_icir(neutral_7, price, "v18_7f")

    signed9 = apply_signs(neutral_5, res9["signs"])
    signed17 = apply_signs(neutral_6, res17["signs"])
    signed18 = apply_signs(neutral_7, res18["signs"])

    ret9 = run_backtest(price, signed9, res9["weights"], n_stocks=N_STOCKS, cost=COST, mask=tradable, lag1=True)
    ret17 = run_backtest(price, signed17, res17["weights"], n_stocks=N_STOCKS, cost=COST, mask=tradable, lag1=True)
    ret18 = run_backtest(price, signed18, res18["weights"], n_stocks=N_STOCKS, cost=COST, mask=tradable, lag1=True)

    print("\n[4/4] IS vs OOS 对比")
    results = {}
    for label, ret in [("v9_5f", ret9), ("v17_6f", ret17), ("v18_7f", ret18)]:
        is_ret = ret.loc[IS_START:TRAIN_END]
        oos_ret = ret.loc[OOS_START:OOS_END]
        results[label] = {"is": calc_metrics(is_ret, hs300_ret), "oos": calc_metrics(oos_ret, hs300_ret)}

    print(f"\n  {'策略':<12} {'period':<5} {'年化':>10} {'夏普':>8} {'MDD':>10} {'超额':>10}")
    print("  " + "-"*58)
    for lb in ["v9_5f", "v17_6f", "v18_7f"]:
        for per in ["is", "oos"]:
            m = results[lb][per]
            print(f"  {lb:<12} {per.upper():<5} {m.get('ann',0):>+10.2%} {m.get('sr',0):>8.3f} "
                  f"{m.get('mdd',0):>10.2%} {m.get('excess',float('nan')):>+10.2%}")

    print(f"\n  OOS 差异 (v18 - v17):")
    for k in ["ann", "sr", "mdd", "excess"]:
        d = results["v18_7f"]["oos"].get(k, np.nan) - results["v17_6f"]["oos"].get(k, np.nan)
        if "ann" in k or "mdd" in k or "excess" in k:
            print(f"    Δ {k:<6} {d:+.2%}")
        else:
            print(f"    Δ {k:<6} {d:+.3f}")

    # 保存
    from datetime import date
    report = ROOT / "journal" / f"v18_ind_reversal_oos_{date.today().strftime('%Y%m%d')}.md"
    lines = [
        f"# v18 OOS (v17 + ind_reversal_3m) — {date.today()}",
        "",
        f"训练 {IS_START}~{TRAIN_END} / 测试 {OOS_START}~{OOS_END}",
        "",
        "## 权重",
        "",
        "| 因子 | v18 ICIR | v18 权重 |",
        "| --- | ---: | ---: |",
    ]
    for n in neutral_7:
        s = res18["ic_stats"].get(n, {})
        lines.append(f"| {n} | {s.get('icir',0):+.3f} | {res18['weights'].get(n,0):.1%} |")
    lines += ["", "## IS vs OOS", "",
              "| 策略 | 阶段 | 年化 | 夏普 | MDD | 超额 |",
              "| --- | --- | ---: | ---: | ---: | ---: |"]
    for lb in ["v9_5f", "v17_6f", "v18_7f"]:
        for per in ["is", "oos"]:
            m = results[lb][per]
            lines.append(f"| {lb} | {per.upper()} | {m.get('ann',0):+.2%} | {m.get('sr',0):.3f}"
                         f" | {m.get('mdd',0):.2%} | {m.get('excess',float('nan')):+.2%} |")
    report.write_text("\n".join(lines), encoding="utf-8")
    print(f"\n[报告] {report}")
    print(f"用时 {time.time()-t0:.1f}s")
    print("="*70)


if __name__ == "__main__":
    main()
