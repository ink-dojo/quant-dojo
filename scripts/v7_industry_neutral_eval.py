"""
v7 候选研究：raw vs industry-neutral 对照评估

目标：
  不继续 patch v6，而是在同一 5 因子 / 同一择时 / 同一持仓规则下，
  只比较“是否引入行业中性化”这一唯一主变量。
"""
import sys
import time
import warnings
from pathlib import Path

warnings.filterwarnings("ignore")
sys.path.insert(0, str(Path(__file__).parent.parent))

from datetime import date

import pandas as pd

from utils.local_data_loader import get_all_symbols, load_price_wide
from utils.data_loader import get_index_history
from utils.metrics import (
    annualized_return, annualized_volatility, sharpe_ratio,
    max_drawdown, calmar_ratio, win_rate,
)
from utils.factor_analysis import (
    compute_ic_series,
    ic_summary,
    neutralize_factor_by_industry,
)
from utils.fundamental_loader import get_industry_classification
from utils.tradability_filter import apply_tradability_filter
from utils.market_regime import rsrs_regime_mask, llt_timing, higher_moment_timing
from utils.alpha_factors import (
    team_coin as _team_coin,
    low_vol_20d as _low_vol_20d,
    enhanced_momentum,
    bp_factor,
)
from scripts.v6_admission_eval import run_backtest

WARMUP_START = "2013-01-01"
IS_START = "2015-01-01"
IS_END = "2024-12-31"
OOS_START = "2025-01-01"
OOS_END = "2025-12-31"
N_STOCKS = 30
COST = 0.003

V6_WEIGHTS = {
    "team_coin": 0.30,
    "low_vol_20d": 0.25,
    "cgo_simple": 0.20,
    "enhanced_mom_60": 0.15,
    "bp": 0.10,
}


def load_core_data():
    print("[1/6] 加载数据...")
    t0 = time.time()
    symbols = get_all_symbols()
    price = load_price_wide(symbols, WARMUP_START, OOS_END, field="close")
    hs300_full = None
    hs300 = None
    try:
        hs300_full = get_index_history(symbol="sh000300", start=WARMUP_START, end=OOS_END)
        hs300 = hs300_full["close"]
        common = price.index.intersection(hs300.index)
        price = price.loc[common]
        hs300_full = hs300_full.loc[common]
        hs300 = hs300.loc[common]
        print("  指数基准: HS300（真实）")
    except Exception as exc:
        print(f"  指数基准不可用，降级为无 benchmark / 无择时: {exc}")
    valid = price.columns[price.notna().sum() > 500]
    price = price[valid]

    cache_dir = Path(__file__).parent.parent / "data" / "cache"
    pb = pd.read_parquet(cache_dir / "pb_wide.parquet")
    pb = pb.reindex(index=price.index, columns=valid)

    tradable = apply_tradability_filter(price)
    print(f"  股票: {len(valid)} | 交易日: {len(price)} | 耗时: {time.time()-t0:.1f}s")
    return price, hs300_full, hs300, pb, tradable


def build_regime(hs300_full, hs300_close):
    print("[2/6] 构建择时...")
    if hs300_full is None or hs300_close is None:
        print("  跳过择时：当前运行使用无指数 fallback")
        return None
    rsrs = rsrs_regime_mask(hs300_full["high"], hs300_full["low"])
    llt = llt_timing(hs300_close)
    hm = higher_moment_timing(hs300_close, order=5)
    common = rsrs.index.intersection(llt.index).intersection(hm.index)
    vote = rsrs.loc[common].astype(int) + llt.loc[common].astype(int) + hm.loc[common].astype(int)
    majority = vote >= 2
    print(f"  多数投票看多: {majority.mean():.0%}")
    return majority


def build_factors(price, pb):
    print("[3/6] 构建 5 因子...")
    factors = {
        "team_coin": _team_coin(price),
        "low_vol_20d": _low_vol_20d(price),
        "cgo_simple": -(price / price.rolling(60).mean() - 1),
        "enhanced_mom_60": enhanced_momentum(price, window=60),
        "bp": bp_factor(pb).reindex_like(price),
    }
    return factors


def build_industry_neutral_factors(factors):
    print("[4/6] 行业中性化...")
    symbols = list(next(iter(factors.values())).columns)
    industry_df = get_industry_classification(symbols=symbols, use_cache=True)
    neutralized = {
        name: neutralize_factor_by_industry(fac, industry_df, show_progress=False)
        for name, fac in factors.items()
    }
    print(f"  行业覆盖: {len(industry_df)} 只 | 行业数: {industry_df['industry_code'].nunique()}")
    return neutralized, industry_df


def summarize_factor_ic(label, factors, price):
    print(f"\n[{label}] 因子 IC 对照")
    fwd = price.pct_change(5).shift(-5)
    rows = []
    print(f"{'因子':<20} {'IC均值':>8} {'ICIR':>8} {'IC>0%':>8}")
    print("-" * 50)
    for name, fac in factors.items():
        ic_s = compute_ic_series(
            fac.loc[IS_START:IS_END],
            fwd.loc[IS_START:IS_END],
            method="spearman",
            min_stocks=50,
        )
        s = ic_summary(ic_s, name=name)
        rows.append({
            "factor": name,
            "ic_mean": s["IC_mean"],
            "icir": s["ICIR"],
            "pct_pos": s["pct_pos"],
        })
        print(f"{name:<20} {s['IC_mean']:>8.4f} {s['ICIR']:>8.4f} {s['pct_pos']:>7.1%}")
    return pd.DataFrame(rows)


def calc_metrics(ret):
    return {
        "ann": annualized_return(ret),
        "vol": annualized_volatility(ret),
        "sr": sharpe_ratio(ret),
        "mdd": max_drawdown(ret),
        "calmar": calmar_ratio(ret),
        "wr": win_rate(ret),
        "days": len(ret),
    }


def compare_portfolios(price, factors_raw, factors_neutral, tradable_mask, regime_mask, hs300):
    print("\n[5/6] 组合层对照回测...")
    raw_full = run_backtest(
        price, factors_raw, V6_WEIGHTS, n_stocks=N_STOCKS, cost=COST,
        mask=tradable_mask, regime_mask=regime_mask, lag1=True,
    )
    neutral_full = run_backtest(
        price, factors_neutral, V6_WEIGHTS, n_stocks=N_STOCKS, cost=COST,
        mask=tradable_mask, regime_mask=regime_mask, lag1=True,
    )

    outputs = {}
    for label, ret in [("raw", raw_full), ("industry_neutral", neutral_full)]:
        is_ret = ret.loc[IS_START:IS_END]
        oos_ret = ret.loc[OOS_START:OOS_END]
        is_bench = hs300.loc[IS_START:IS_END].pct_change().dropna() if hs300 is not None else None
        oos_bench = hs300.loc[OOS_START:OOS_END].pct_change().dropna() if hs300 is not None else None
        outputs[label] = {
            "is": calc_metrics(is_ret),
            "oos": calc_metrics(oos_ret) if len(oos_ret) > 20 else None,
            "is_excess": annualized_return(is_ret.loc[is_ret.index.intersection(is_bench.index)] - is_bench.loc[is_ret.index.intersection(is_bench.index)]) if is_bench is not None else None,
            "oos_excess": annualized_return(oos_ret.loc[oos_ret.index.intersection(oos_bench.index)] - oos_bench.loc[oos_ret.index.intersection(oos_bench.index)]) if (len(oos_ret) > 20 and oos_bench is not None) else None,
        }
    return outputs


def _fmt_pct_or_na(value):
    return f"{value:+.2%}" if value is not None else "N/A"


def write_report(ic_raw, ic_neutral, portfolio_metrics, regime_mask, hs300):
    report_path = Path(__file__).parent.parent / "journal" / f"v7_industry_neutral_eval_{date.today().strftime('%Y%m%d')}.md"
    raw_is = portfolio_metrics["raw"]["is"]
    neu_is = portfolio_metrics["industry_neutral"]["is"]
    raw_oos = portfolio_metrics["raw"]["oos"]
    neu_oos = portfolio_metrics["industry_neutral"]["oos"]

    lines = [
        f"# v7 行业中性候选研究报告",
        "",
        f"- **日期**: {date.today()}",
        f"- **唯一主变量**: 是否对当前 5 因子组合启用行业中性化",
        f"- **保持不变**: 因子集、权重、持仓数、成本、lag1、过滤条件",
        f"- **择时**: {'多数投票（真实 HS300）' if regime_mask is not None else '本次运行未启用（本地无指数缓存，且在线接口不可用）'}",
        f"- **基准**: {'HS300' if hs300 is not None else '无（本次运行未取指数基准）'}",
        "",
        "## 因子层 IC 对照",
        "",
        "| 因子 | raw IC均值 | raw ICIR | neutral IC均值 | neutral ICIR |",
        "| --- | ---: | ---: | ---: | ---: |",
    ]
    merged = ic_raw.merge(ic_neutral, on="factor", suffixes=("_raw", "_neutral"))
    for _, row in merged.iterrows():
        lines.append(
            f"| {row['factor']} | {row['ic_mean_raw']:.4f} | {row['icir_raw']:.4f} | {row['ic_mean_neutral']:.4f} | {row['icir_neutral']:.4f} |"
        )

    lines += [
        "",
        "## 组合层 IS / OOS 对照",
        "",
        "| 版本 | 区间 | 年化 | 波动 | 夏普 | 回撤 | 卡玛 | 胜率 | 年化超额 |",
        "| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
        f"| raw | IS | {raw_is['ann']:+.2%} | {raw_is['vol']:.2%} | {raw_is['sr']:.4f} | {raw_is['mdd']:.2%} | {raw_is['calmar']:.2f} | {raw_is['wr']:.2%} | {_fmt_pct_or_na(portfolio_metrics['raw']['is_excess'])} |",
        f"| industry-neutral | IS | {neu_is['ann']:+.2%} | {neu_is['vol']:.2%} | {neu_is['sr']:.4f} | {neu_is['mdd']:.2%} | {neu_is['calmar']:.2f} | {neu_is['wr']:.2%} | {_fmt_pct_or_na(portfolio_metrics['industry_neutral']['is_excess'])} |",
    ]
    if raw_oos and neu_oos:
        lines += [
            f"| raw | OOS | {raw_oos['ann']:+.2%} | {raw_oos['vol']:.2%} | {raw_oos['sr']:.4f} | {raw_oos['mdd']:.2%} | {raw_oos['calmar']:.2f} | {raw_oos['wr']:.2%} | {_fmt_pct_or_na(portfolio_metrics['raw']['oos_excess'])} |",
            f"| industry-neutral | OOS | {neu_oos['ann']:+.2%} | {neu_oos['vol']:.2%} | {neu_oos['sr']:.4f} | {neu_oos['mdd']:.2%} | {neu_oos['calmar']:.2f} | {neu_oos['wr']:.2%} | {_fmt_pct_or_na(portfolio_metrics['industry_neutral']['oos_excess'])} |",
        ]

    lines += [
        "",
        "## 初步结论",
        "",
        "- 本轮只回答：行业中性化是否值得成为新 candidate line 的组成部分。",
        "- 若行业中性化改善了回撤/稳定性但没有把 alpha 完全削空，则值得继续推进到下一轮候选策略定义。",
        "- 若行业中性化让组合表现整体塌陷，则说明当前问题不只是行业暴露，后续应回到因子与组合定义本身。",
        "",
        "## 注意",
        "",
        "- 本轮是**行业中性**，不是行业+市值双中性；当前仓库没有可直接复用的 `mv_float` 缓存，故不硬做市值中性。",
        "- 若本报告显示为“无 benchmark / 无择时”，这是一次明确的离线 fallback，不得和带真实 HS300 择时的 admission 结果混写。",
        "- 本结果不等于 admission 结论，只决定是否形成 `v7 industry-neutral candidate`。",
    ]

    report_path.write_text("\n".join(lines), encoding="utf-8")
    return report_path


def main():
    price, hs300_full, hs300, pb, tradable = load_core_data()
    regime = build_regime(hs300_full, hs300)
    factors_raw = build_factors(price, pb)
    factors_neutral, _ = build_industry_neutral_factors(factors_raw)
    ic_raw = summarize_factor_ic("raw", factors_raw, price)
    ic_neutral = summarize_factor_ic("industry-neutral", factors_neutral, price)
    portfolio_metrics = compare_portfolios(price, factors_raw, factors_neutral, tradable, regime, hs300)
    report_path = write_report(ic_raw, ic_neutral, portfolio_metrics, regime, hs300)
    print(f"\n[6/6] 报告已写入: {report_path}")


if __name__ == "__main__":
    main()
