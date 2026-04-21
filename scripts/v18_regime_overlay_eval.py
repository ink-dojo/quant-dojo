"""v18 regime-overlay evaluation.

### Pre-registration (2026-04-21, 锁参数, 跑完不调)

**背景**:
- v17 (v9 五因子 + -composite_crowding) IS 2022-2025 ann +5.98%, SR 0.28, MDD -39.55%, 远未达 5/5 admission gate
- OOS 2025 独立窗口 v17 ann +35%, SR 1.46 (因为 2025 是 bull 年)
- 分年度: 2022 SR -0.21, 2023 SR 0.15, 2024 SR -0.13, 2025 SR 1.59
- 诊断: 因子本身是 stock-selection 正的, 但在 bear/flat (2022/2024) 市场 beta 拖累
  → 加 regime overlay 应该显著改善 MDD 和 Sharpe

**假设**: HS300 RSRS 看空信号时清仓 (regime_scale=0.0), 应该:
- 减掉 2022 / 2024 的 -8% / -7% 年化
- 保留 2023 flat / 2025 bull 的 +3% / +38%
- 组合 ann ~+15-20%, MDD 应降到 -20% 以下

**锁定参数**:
| 项 | 值 |
|---|---|
| 因子 | v17 六因子 (team_coin, low_vol_20d, cgo_simple, enhanced_mom_60, bp, neg_crowding) |
| 中性化 | 行业中性化 |
| 权重学习 | ICIR 加权 (2022-01-01 ~ 2025-12-31 全期) |
| 持仓 | top 30 月频 rebalance |
| 成本 | 0.3% 双边 |
| lag1 | True |
| Regime signal | HS300 RSRS (regression 18d, zscore 252d) |
| Regime threshold | upper=0.30, lower=-0.30 (rsrs_regime_mask 默认) |
| Regime rule | bullish=True 正常, bullish=False 清仓 (regime_scale=0.0) |
| Period | 2022-01-01 ~ 2025-12-31 (crowding 数据起) |

**Admission gate (5/5)**:
1. ann > 15%
2. Sharpe > 0.8
3. MDD > -30%
4. PSR > 0.95 (vs SR=0 null)
5. Bootstrap CI_low > 0.5
5/5 → 上 paper-trade (替代或并行现 DSR #30+#33 spec)
4/5 → 记录, 选择是否 WF 二次验证
≤3/5 → 记录 post-mortem, 放弃 regime overlay 路径, 直接用 v17 原始方案进模拟盘
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
    probabilistic_sharpe, bootstrap_sharpe_ci,
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
from utils.market_regime import rsrs_regime_mask
from scripts.v6_admission_eval import run_backtest

ROOT = Path(__file__).parent.parent

WARMUP_START = "2020-01-01"
IS_START     = "2022-01-01"
IS_END       = "2025-12-31"
N_STOCKS     = 30
COST         = 0.003
FWD_DAYS     = 20
MIN_WEIGHT   = 0.05
RSRS_UPPER   = 0.30
RSRS_LOWER   = -0.30


def apply_signs(factors, signs):
    return {name: fac * signs.get(name, 1) for name, fac in factors.items()}


def calc_all_metrics(ret, bench=None):
    if ret is None or len(ret) == 0:
        return {}
    m = {
        "ann":    annualized_return(ret),
        "vol":    annualized_volatility(ret),
        "sr":     sharpe_ratio(ret),
        "mdd":    max_drawdown(ret),
        "calmar": calmar_ratio(ret),
        "wr":     win_rate(ret),
        "psr":    probabilistic_sharpe(ret, sr_benchmark=0.0),
    }
    boot = bootstrap_sharpe_ci(ret, n_boot=2000)
    m["ci_low"] = boot["ci_low"]
    m["ci_high"] = boot["ci_high"]
    if bench is not None:
        common = ret.index.intersection(bench.index)
        if len(common) > 20:
            m["excess"] = annualized_return(ret.loc[common] - bench.loc[common])
    return m


def year_by_year(ret):
    out = {}
    for y in sorted(set(ret.index.year)):
        yret = ret[ret.index.year == y]
        if len(yret) > 30:
            out[y] = {
                "ann": (1 + yret).prod() - 1,
                "sr":  sharpe_ratio(yret),
                "mdd": max_drawdown(yret),
            }
    return out


def gate_check(m, label):
    g = {
        "ann>15%": m.get("ann", 0) > 0.15,
        "sr>0.8": m.get("sr", 0) > 0.8,
        "mdd>-30%": m.get("mdd", -1) > -0.30,
        "PSR>0.95": m.get("psr", 0) > 0.95,
        "ci_low>0.5": m.get("ci_low", 0) > 0.5,
    }
    n = sum(g.values())
    print(f"\n  [{label}] admission gate {n}/5:")
    for k, v in g.items():
        print(f"    {'PASS' if v else 'FAIL'} {k}")
    return n, g


def main():
    t0 = time.time()
    print("="*70)
    print(f"v18 regime-overlay eval: {IS_START} ~ {IS_END}")
    print("="*70)

    # [1] 加载数据
    print("\n[1/5] 加载价格 / PB / HS300 / 可交易性 mask ...")
    # 从 cache 目录列 symbols (源盘权限不可用时的 fallback)
    cache_dir = Path("data/cache/local")
    symbols = sorted(p.stem for p in cache_dir.glob("*.parquet"))
    if not symbols:
        symbols = get_all_symbols()
    print(f"  symbols from cache: {len(symbols)}")
    price = load_price_wide(symbols, WARMUP_START, IS_END, field="close")
    valid = price.columns[price.notna().sum() > 300]
    price = price[valid]
    pb = load_price_wide(list(valid), WARMUP_START, IS_END, field="pb").reindex(index=price.index, columns=valid)
    hs300 = get_index_history(symbol="sh000300", start=WARMUP_START, end=IS_END)
    common = price.index.intersection(hs300.index)
    price = price.loc[common]; pb = pb.reindex(index=price.index); hs300 = hs300.loc[common]
    tradable = apply_tradability_filter(price)
    print(f"  {len(valid)} 股 | {len(price)} 交易日")

    # [2] 构建因子
    print("\n[2/5] 因子 + 中性化 ...")
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
    raw_crowd = pd.read_parquet(ROOT / "research/factors/crowding_filter/composite_crowding_sn.parquet")
    raw_crowd.index = pd.to_datetime(raw_crowd.index)
    crowd = (-raw_crowd).reindex(index=price.index, columns=price.columns)
    crowd_neu = neutralize_factor_by_industry(crowd, industry_df, show_progress=False)
    neutral_6 = {**neutral_5, "neg_crowding": crowd_neu}

    # [3] 学权重
    print("\n[3/5] 学 ICIR 权重 ...")
    res = icir_weight(
        factors=neutral_6,
        price_wide=price,
        train_start=IS_START,
        train_end=IS_END,
        fwd_days=FWD_DAYS,
        min_weight=MIN_WEIGHT,
    )
    print(f"  权重: " + ", ".join(f"{k}={v:.1%}" for k, v in res["weights"].items()))
    signed = apply_signs(neutral_6, res["signs"])

    # [4] 构造 regime mask
    print(f"\n[4/5] 构造 HS300 RSRS regime mask (upper={RSRS_UPPER}, lower={RSRS_LOWER}) ...")
    regime_mask = rsrs_regime_mask(
        high=hs300["high"],
        low=hs300["low"],
        upper=RSRS_UPPER,
        lower=RSRS_LOWER,
    ).reindex(price.index).ffill().fillna(True)
    bull_days = regime_mask.loc[IS_START:IS_END].mean()
    print(f"  bullish 占比 ({IS_START}~{IS_END}): {bull_days:.1%}")

    # [5] 回测: v17 vs v18
    print("\n[5/5] 回测 v17 (无 regime) vs v18 (regime overlay 清仓) ...")
    ret_v17 = run_backtest(price, signed, res["weights"], n_stocks=N_STOCKS, cost=COST,
                           mask=tradable, lag1=True)
    ret_v18 = run_backtest(price, signed, res["weights"], n_stocks=N_STOCKS, cost=COST,
                           mask=tradable, lag1=True,
                           regime_mask=regime_mask, regime_scale=0.0)

    hs300_ret = hs300["close"].pct_change().dropna()
    is_mask = lambda r: r.loc[IS_START:IS_END]
    m17 = calc_all_metrics(is_mask(ret_v17), hs300_ret)
    m18 = calc_all_metrics(is_mask(ret_v18), hs300_ret)

    print(f"\n  {'指标':<12} {'v17':>12} {'v18':>12} {'Δ':>12}")
    print("  " + "-"*54)
    for k, fmt in [("ann","{:+.2%}"),("sr","{:.3f}"),("mdd","{:.2%}"),
                   ("psr","{:.3f}"),("ci_low","{:.2f}"),("ci_high","{:.2f}"),
                   ("calmar","{:.3f}"),("wr","{:.2%}"),("excess","{:+.2%}")]:
        v17 = m17.get(k, np.nan); v18 = m18.get(k, np.nan)
        if isinstance(v17,(int,float)) and isinstance(v18,(int,float)):
            d = v18 - v17
            d_fmt = f"{d:+.2%}" if "%" in fmt else f"{d:+.3f}"
        else:
            d_fmt = "—"
        print(f"  {k:<12} {fmt.format(v17):>12} {fmt.format(v18):>12} {d_fmt:>12}")

    n17, _ = gate_check(m17, "v17")
    n18, _ = gate_check(m18, "v18 (regime)")

    # 分年度
    y17 = year_by_year(is_mask(ret_v17))
    y18 = year_by_year(is_mask(ret_v18))
    print(f"\n  分年度:")
    print(f"  {'年':<6} {'v17 年化':>10} {'v18 年化':>10} {'Δ':>8} | {'v17 SR':>8} {'v18 SR':>8}")
    for y in sorted(set(y17) | set(y18)):
        a17 = y17.get(y,{}).get("ann",np.nan); a18 = y18.get(y,{}).get("ann",np.nan)
        s17 = y17.get(y,{}).get("sr",np.nan); s18 = y18.get(y,{}).get("sr",np.nan)
        d = a18-a17 if not np.isnan(a17) and not np.isnan(a18) else np.nan
        print(f"  {y:<6} {a17:>+10.2%} {a18:>+10.2%} {d:>+8.2%} | {s17:>8.3f} {s18:>8.3f}")

    # 报告
    out = ROOT / "journal" / f"v18_regime_overlay_{date.today().strftime('%Y%m%d')}.md"
    lines = [
        f"# v18 Regime Overlay 评估 — {date.today()}",
        "",
        f"窗口: {IS_START} ~ {IS_END}",
        f"Regime: HS300 RSRS (upper={RSRS_UPPER}, lower={RSRS_LOWER}), bullish 占比 {bull_days:.1%}",
        "",
        "## 指标对比 (IS 全期)",
        "",
        "| 指标 | v17 | v18 | Δ |",
        "| --- | ---: | ---: | ---: |",
    ]
    for k, fmt in [("ann","{:+.2%}"),("sr","{:.3f}"),("mdd","{:.2%}"),
                   ("psr","{:.3f}"),("ci_low","{:.2f}"),("ci_high","{:.2f}"),
                   ("calmar","{:.3f}"),("wr","{:.2%}"),("excess","{:+.2%}")]:
        v17 = m17.get(k, np.nan); v18 = m18.get(k, np.nan)
        d = v18-v17 if isinstance(v17,(int,float)) and isinstance(v18,(int,float)) else np.nan
        d_fmt = f"{d:+.2%}" if "%" in fmt else f"{d:+.3f}"
        lines.append(f"| {k} | {fmt.format(v17)} | {fmt.format(v18)} | {d_fmt} |")

    lines += ["", "## Admission Gate", "", f"- v17: {n17}/5", f"- v18: {n18}/5", ""]

    lines += ["", "## 分年度", "", "| 年 | v17 | v18 | Δ | v17 SR | v18 SR |",
              "| --- | ---: | ---: | ---: | ---: | ---: |"]
    for y in sorted(set(y17) | set(y18)):
        a17 = y17.get(y,{}).get("ann",np.nan); a18 = y18.get(y,{}).get("ann",np.nan)
        s17 = y17.get(y,{}).get("sr",np.nan); s18 = y18.get(y,{}).get("sr",np.nan)
        d = a18-a17 if not np.isnan(a17) and not np.isnan(a18) else np.nan
        lines.append(f"| {y} | {a17:+.2%} | {a18:+.2%} | {d:+.2%} | {s17:.3f} | {s18:.3f} |")

    lines += ["", "## 决策", ""]
    if n18 >= 5:
        lines.append("- 5/5 PASS → v18 replace/augment paper-trade spec")
    elif n18 == 4:
        lines.append("- 4/5 → WF 二次验证后决定")
    else:
        lines.append("- ≤3/5 → 放弃 regime overlay, 用 v17 原方案进 paper-trade (option E)")

    out.write_text("\n".join(lines), encoding="utf-8")
    print(f"\n[报告] {out}")

    curves = pd.DataFrame({"v17": is_mask(ret_v17), "v18_regime": is_mask(ret_v18)})
    curves.to_parquet(ROOT / "research/factors/crowding_filter/v18_regime_returns.parquet")
    print(f"[收益] research/factors/crowding_filter/v18_regime_returns.parquet")
    print(f"\n总用时 {time.time()-t0:.1f}s")
    print("="*70)


if __name__ == "__main__":
    main()
