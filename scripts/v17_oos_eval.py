"""
v17 严格 OOS 评估：2022-2024 学权重 → 2025 测试

相比 v17_crowding_aware_eval.py（IS 同窗口），本脚本做严格 walk-forward：
  - 训练：IS_START=2022-01-01 ~ TRAIN_END=2024-12-31
  - 测试：OOS_START=2025-01-01 ~ OOS_END=2025-12-31

目的：区分 v17 的提升是真 alpha 还是 IS 过拟合。

对照：v9_5f vs v17_6f，两者都在训练期独立学 ICIR 权重。

运行：python scripts/v17_oos_eval.py
"""
import sys
import time
import warnings
from datetime import date
from pathlib import Path

warnings.filterwarnings("ignore")
sys.path.insert(0, str(Path(__file__).parent.parent))

import numpy as np
import pandas as pd

from utils.local_data_loader import get_all_symbols, load_price_wide
from utils.data_loader import get_index_history
from utils.metrics import (
    annualized_return, annualized_volatility, sharpe_ratio,
    max_drawdown, win_rate, calmar_ratio,
)
from utils.factor_analysis import neutralize_factor_by_industry
from utils.fundamental_loader import get_industry_classification
from utils.tradability_filter import apply_tradability_filter
from utils.multi_factor import icir_weight
from utils.alpha_factors import (
    team_coin as _team_coin,
    low_vol_20d as _low_vol_20d,
    enhanced_momentum,
    bp_factor,
)
from scripts.v6_admission_eval import run_backtest

ROOT = Path(__file__).parent.parent

WARMUP_START = "2020-01-01"
IS_START     = "2022-01-01"
TRAIN_END    = "2024-12-31"
OOS_START    = "2025-01-01"
OOS_END      = "2025-12-31"
N_STOCKS     = 30
COST         = 0.003
FWD_DAYS     = 20
MIN_WEIGHT   = 0.05


def apply_signs(factors, signs):
    return {name: fac * signs.get(name, 1) for name, fac in factors.items()}


def learn_icir(factors, price, label):
    res = icir_weight(
        factors=factors,
        price_wide=price,
        train_start=IS_START,
        train_end=TRAIN_END,
        fwd_days=FWD_DAYS,
        min_weight=MIN_WEIGHT,
    )
    print(f"\n  [{label}] 训练期 (2022-01~2024-12) ICIR 权重：")
    for name in factors:
        s = res["ic_stats"].get(name, {})
        print(f"    {name:<20} ICIR {s.get('icir', 0):+.3f}  权重 {res['weights'].get(name, 0):.1%}  方向 {res['signs'].get(name, 1):+d}")
    return res


def calc_metrics(ret, bench=None):
    if ret is None or len(ret) == 0:
        return {}
    m = {
        "ann":    annualized_return(ret),
        "sr":     sharpe_ratio(ret),
        "mdd":    max_drawdown(ret),
        "calmar": calmar_ratio(ret),
        "wr":     win_rate(ret),
    }
    if bench is not None:
        common = ret.index.intersection(bench.index)
        if len(common) > 20:
            m["excess"] = annualized_return(ret.loc[common] - bench.loc[common])
    return m


def main():
    t0 = time.time()
    print("="*70)
    print(f"v17 严格 OOS：训练 {IS_START}~{TRAIN_END} / 测试 {OOS_START}~{OOS_END}")
    print("="*70)

    # 数据
    print("\n[1/4] 加载数据 ...")
    symbols = get_all_symbols()
    price = load_price_wide(symbols, WARMUP_START, OOS_END, field="close")
    valid = price.columns[price.notna().sum() > 300]
    price = price[valid]
    pb = load_price_wide(list(valid), WARMUP_START, OOS_END, field="pb").reindex(index=price.index, columns=valid)
    hs300 = get_index_history(symbol="sh000300", start=WARMUP_START, end=OOS_END)
    common = price.index.intersection(hs300.index)
    price = price.loc[common]; pb = pb.reindex(index=price.index); hs300 = hs300.loc[common]
    tradable = apply_tradability_filter(price)
    print(f"  {len(valid)} 股 | {len(price)} 交易日 | 用时 {time.time()-t0:.1f}s")

    # 因子
    print("\n[2/4] 构建 v9 五因子 + crowding，行业中性化 ...")
    factors_5 = {
        "team_coin":       _team_coin(price),
        "low_vol_20d":     _low_vol_20d(price),
        "cgo_simple":      -(price / price.rolling(60).mean() - 1),
        "enhanced_mom_60": enhanced_momentum(price, window=60),
        "bp":              bp_factor(pb).reindex_like(price),
    }
    industry_df = get_industry_classification(symbols=list(price.columns), use_cache=True)
    neutral_5 = {
        name: neutralize_factor_by_industry(fac, industry_df, show_progress=False)
        for name, fac in factors_5.items()
    }

    raw_crowd = pd.read_parquet(ROOT / "research/factors/crowding_filter/composite_crowding.parquet")
    raw_crowd.index = pd.to_datetime(raw_crowd.index)
    crowd = (-raw_crowd).reindex(index=price.index, columns=price.columns)
    crowd_neu = neutralize_factor_by_industry(crowd, industry_df, show_progress=False)
    neutral_6 = {**neutral_5, "neg_crowding": crowd_neu}

    hs300_ret = hs300["close"].pct_change().dropna()

    # 权重学习 + 全期回测（然后切 OOS）
    print("\n[3/4] 学权重 + 回测 ...")
    res9  = learn_icir(neutral_5, price, "v9_5f")
    res17 = learn_icir(neutral_6, price, "v17_6f")

    signed9  = apply_signs(neutral_5, res9["signs"])
    signed17 = apply_signs(neutral_6, res17["signs"])

    ret9  = run_backtest(price, signed9,  res9["weights"],  n_stocks=N_STOCKS, cost=COST, mask=tradable, lag1=True)
    ret17 = run_backtest(price, signed17, res17["weights"], n_stocks=N_STOCKS, cost=COST, mask=tradable, lag1=True)

    # IS vs OOS 对比
    print("\n[4/4] IS vs OOS 对比")
    results = {}
    for label, ret in [("v9_5f", ret9), ("v17_6f", ret17)]:
        is_ret  = ret.loc[IS_START:TRAIN_END]
        oos_ret = ret.loc[OOS_START:OOS_END]
        results[label] = {
            "is":  calc_metrics(is_ret,  hs300_ret),
            "oos": calc_metrics(oos_ret, hs300_ret),
        }

    print(f"\n  {'策略':<10} {'period':<5} {'年化':>10} {'夏普':>8} {'MDD':>10} {'超额':>10}")
    print("  " + "-"*56)
    for label in ["v9_5f", "v17_6f"]:
        for per in ["is", "oos"]:
            m = results[label][per]
            print(f"  {label:<10} {per.upper():<5} {m.get('ann',0):>+10.2%} {m.get('sr',0):>8.3f} "
                  f"{m.get('mdd',0):>10.2%} {m.get('excess', float('nan')):>+10.2%}")

    # Δ OOS
    print(f"\n  OOS 2025 差异 (v17 - v9):")
    m_d = {k: results["v17_6f"]["oos"].get(k, np.nan) - results["v9_5f"]["oos"].get(k, np.nan)
           for k in ["ann", "sr", "mdd", "excess"]}
    for k, v in m_d.items():
        if "ann" in k or "mdd" in k or "excess" in k:
            print(f"    Δ {k:<6} {v:+.2%}")
        else:
            print(f"    Δ {k:<6} {v:+.3f}")

    # 报告
    report = ROOT / "journal" / f"v17_oos_eval_{date.today().strftime('%Y%m%d')}.md"
    lines = [
        f"# v17 严格 OOS 评估 — {date.today()}",
        "",
        f"训练 {IS_START} ~ {TRAIN_END} / 测试 {OOS_START} ~ {OOS_END}",
        "",
        "## 训练期学到的权重",
        "",
        "| 因子 | v9 ICIR | v9 权重 | v17 ICIR | v17 权重 |",
        "| --- | ---: | ---: | ---: | ---: |",
    ]
    for name in neutral_6:
        i9 = res9["ic_stats"].get(name, {}).get("icir", np.nan) if name in neutral_5 else np.nan
        w9 = res9["weights"].get(name, np.nan) if name in neutral_5 else np.nan
        i17 = res17["ic_stats"].get(name, {}).get("icir", np.nan)
        w17 = res17["weights"].get(name, np.nan)
        i9_s = f"{i9:+.3f}" if not np.isnan(i9) else "—"
        w9_s = f"{w9:.1%}"  if not np.isnan(w9) else "—"
        lines.append(f"| {name} | {i9_s} | {w9_s} | {i17:+.3f} | {w17:.1%} |")

    lines += [
        "",
        "## IS vs OOS",
        "",
        "| 策略 | 阶段 | 年化 | 夏普 | MDD | 超额 |",
        "| --- | --- | ---: | ---: | ---: | ---: |",
    ]
    for label in ["v9_5f", "v17_6f"]:
        for per in ["is", "oos"]:
            m = results[label][per]
            lines.append(
                f"| {label} | {per.upper()} | {m.get('ann',0):+.2%} | {m.get('sr',0):.3f}"
                f" | {m.get('mdd',0):.2%} | {m.get('excess', float('nan')):+.2%} |"
            )

    lines += [
        "",
        "## OOS 差异 (v17 - v9)",
        "",
    ]
    for k, v in m_d.items():
        if "ann" in k or "mdd" in k or "excess" in k:
            lines.append(f"- Δ {k}: {v:+.2%}")
        else:
            lines.append(f"- Δ {k}: {v:+.3f}")

    d_sr_oos = m_d["sr"]
    d_ann_oos = m_d["ann"]
    lines += [
        "",
        "## 结论",
        "",
    ]
    if d_sr_oos > 0.1 and d_ann_oos > 0.02:
        lines.append(f"- ✅ v17 OOS 显著胜出：夏普 {d_sr_oos:+.2f}，年化 {d_ann_oos:+.2%}")
        lines.append("- 推荐：正式采纳 -composite_crowding 进因子池")
    elif d_sr_oos > 0.03:
        lines.append(f"- ⚠️ v17 OOS 略胜 (夏普 {d_sr_oos:+.3f})，边际效用")
    else:
        lines.append(f"- ❌ v17 OOS 未超越 v9 (夏普 {d_sr_oos:+.3f})，IS 提升系过拟合")
        lines.append("- 可能原因：crowding 在 2022-2024 regime (抱团回落 + 小微盘崩盘) 下更有效，2025 公募回归后效力减弱")
    report.write_text("\n".join(lines), encoding="utf-8")
    print(f"\n[报告] {report}")
    print(f"\n总用时 {time.time()-t0:.1f}s")
    print("="*70)


if __name__ == "__main__":
    main()
