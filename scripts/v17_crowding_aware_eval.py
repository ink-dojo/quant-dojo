"""
v17 候选：v9 五因子 + (-composite_crowding) 合成

背景：
    F5 拥挤度复合因子（-composite_crowding）独立测出 ICIR 0.73 / HAC t 6.33，
    主导来自 turnover 反转 + attention 反转。本脚本验证：把它加入 v9 五因子
    ICIR 加权体系后，IS (2022-2025) 综合表现是否提升。

窗口选择：
    composite_crowding 数据从 2022-01-04 起（F3 survey_attention 预热后），
    所以 v9 和 v17 都在 **2022-01-01 ~ 2025-12-31** 对标（apples-to-apples）。

对照组：
    - v9_5f  : 原 5 因子 (team_coin, low_vol_20d, cgo_simple, enhanced_mom_60, bp)
    - v17_6f : 5 因子 + (-composite_crowding)，ICIR 加权自动决定权重

输出：
    - journal/v17_crowding_aware_eval_<date>.md
    - 权重分配、IS 指标对比、分年度表现

运行：python scripts/v17_crowding_aware_eval.py
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

# ── 常量 ─────────────────────────────────────────────────────────
WARMUP_START = "2020-01-01"   # 预热因子：team_coin/enhanced_mom 需要 ~1 年
IS_START     = "2022-01-01"   # crowding 数据起始
IS_END       = "2025-12-31"
N_STOCKS     = 30
COST         = 0.003
FWD_DAYS     = 20
MIN_WEIGHT   = 0.05


def load_data():
    print("="*70)
    print("[1/6] 加载价格 / PB / HS300 / 可交易性 mask ...")
    t0 = time.time()
    symbols = get_all_symbols()
    price = load_price_wide(symbols, WARMUP_START, IS_END, field="close")
    valid = price.columns[price.notna().sum() > 300]
    price = price[valid]
    pb_raw = load_price_wide(list(valid), WARMUP_START, IS_END, field="pb")
    pb = pb_raw.reindex(index=price.index, columns=valid)

    hs300 = None
    try:
        hs300 = get_index_history(symbol="sh000300", start=WARMUP_START, end=IS_END)
        common = price.index.intersection(hs300.index)
        price = price.loc[common]
        pb = pb.reindex(index=price.index)
        hs300 = hs300.loc[common]
    except Exception as e:
        print(f"  HS300 不可用: {e}")

    tradable = apply_tradability_filter(price)
    print(f"  股票 {len(valid)} | 交易日 {len(price)} | 用时 {time.time()-t0:.1f}s")
    return price, pb, hs300, tradable


def build_v9_factors(price, pb):
    print("\n[2/6] 构建 v9 五因子 + 行业中性化 ...")
    factors = {
        "team_coin":       _team_coin(price),
        "low_vol_20d":     _low_vol_20d(price),
        "cgo_simple":      -(price / price.rolling(60).mean() - 1),
        "enhanced_mom_60": enhanced_momentum(price, window=60),
        "bp":              bp_factor(pb).reindex_like(price),
    }
    symbols = list(price.columns)
    industry_df = get_industry_classification(symbols=symbols, use_cache=True)
    neutral = {
        name: neutralize_factor_by_industry(fac, industry_df, show_progress=False)
        for name, fac in factors.items()
    }
    print(f"  5 因子 + 行业中性化完成 | 行业覆盖 {len(industry_df)}")
    return neutral, industry_df


def load_crowding_factor(price, industry_df):
    """加载 F5 产出的 composite_crowding 并中性化。返回 -composite (正向 alpha)。"""
    print("\n[3/6] 载入 F5 composite_crowding ...")
    path = ROOT / "research/factors/crowding_filter/composite_crowding.parquet"
    raw = pd.read_parquet(path)
    raw.index = pd.to_datetime(raw.index)
    raw = raw.reindex(index=price.index, columns=price.columns)
    # 反向作为正向 alpha
    inv = -raw
    # 行业中性化
    inv_neu = neutralize_factor_by_industry(inv, industry_df, show_progress=False)
    coverage = inv_neu.notna().sum(axis=1).mean()
    print(f"  -composite_crowding 行业中性化后日均覆盖 {coverage:.0f} 股")
    return inv_neu


def apply_signs(factors: dict, signs: dict) -> dict:
    return {name: fac * signs.get(name, 1) for name, fac in factors.items()}


def learn_and_backtest(label, factors, price, tradable):
    """在 IS_START~IS_END 上学 ICIR 权重，并做同窗口回测 (in-sample evaluation)。"""
    res = icir_weight(
        factors=factors,
        price_wide=price,
        train_start=IS_START,
        train_end=IS_END,
        fwd_days=FWD_DAYS,
        min_weight=MIN_WEIGHT,
    )
    w = res["weights"]
    signs = res["signs"]
    stats = res["ic_stats"]

    print(f"\n  [{label}] ICIR 学到的权重：")
    print(f"  {'因子':<22} {'IC均值':>9} {'IC标准差':>9} {'ICIR':>7} {'方向':>5} {'权重':>7}")
    print("  " + "-"*72)
    for name in factors:
        s = stats.get(name, {})
        print(f"  {name:<22} {s.get('ic_mean', np.nan):>+9.4f} {s.get('ic_std', np.nan):>9.4f} "
              f"{s.get('icir', 0):>+7.3f} {signs.get(name, 1):>+5d} {w.get(name, 0):>7.1%}")

    signed = apply_signs(factors, signs)
    ret = run_backtest(
        price, signed, w, n_stocks=N_STOCKS, cost=COST,
        mask=tradable, lag1=True,
    )
    return ret, w, signs, stats


def calc_metrics(ret, bench=None):
    if ret is None or len(ret) == 0:
        return {}
    m = {
        "ann":    annualized_return(ret),
        "vol":    annualized_volatility(ret),
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


def main():
    t0 = time.time()
    price, pb, hs300_full, tradable = load_data()
    neutral_5 = None
    neutral_5, industry_df = build_v9_factors(price, pb)
    crowding = load_crowding_factor(price, industry_df)

    hs300_ret = hs300_full["close"].pct_change().dropna() if hs300_full is not None else None

    print("\n[4/6] v9_5f 基准（仅 5 因子）...")
    ret_v9, w9, s9, st9 = learn_and_backtest("v9_5f", neutral_5, price, tradable)

    print("\n[5/6] v17_6f (5 因子 + -composite_crowding) ...")
    neutral_6 = {**neutral_5, "neg_crowding": crowding}
    ret_v17, w17, s17, st17 = learn_and_backtest("v17_6f", neutral_6, price, tradable)

    # IS 指标
    print("\n[6/6] IS 指标对比 (2022-01-01 ~ 2025-12-31)")
    is_mask = lambda r: r.loc[IS_START:IS_END]
    m9  = calc_metrics(is_mask(ret_v9),  hs300_ret)
    m17 = calc_metrics(is_mask(ret_v17), hs300_ret)

    print(f"\n  {'指标':<10} {'v9_5f':>12} {'v17_6f':>12} {'Δ':>10}")
    print("  " + "-"*50)
    for k, fmt in [("ann", "{:+.2%}"), ("sr", "{:.3f}"), ("mdd", "{:.2%}"),
                   ("calmar", "{:.3f}"), ("wr", "{:.2%}"), ("excess", "{:+.2%}")]:
        v9 = m9.get(k, np.nan)
        v17 = m17.get(k, np.nan)
        d = v17 - v9 if isinstance(v9, (int,float)) and isinstance(v17, (int,float)) else np.nan
        d_fmt = f"{d:+.2%}" if "%" in fmt else f"{d:+.3f}"
        print(f"  {k:<10} {fmt.format(v9):>12} {fmt.format(v17):>12} {d_fmt:>10}")

    # 分年度
    y9  = year_by_year(is_mask(ret_v9))
    y17 = year_by_year(is_mask(ret_v17))
    print(f"\n  分年度表现：")
    print(f"  {'年份':<6} {'v9 年化':>10} {'v17 年化':>10} {'Δ':>8} | {'v9 SR':>8} {'v17 SR':>8}")
    for y in sorted(set(y9) | set(y17)):
        a9  = y9.get(y, {}).get("ann", np.nan)
        a17 = y17.get(y, {}).get("ann", np.nan)
        s9v  = y9.get(y, {}).get("sr", np.nan)
        s17v = y17.get(y, {}).get("sr", np.nan)
        d = a17 - a9 if not np.isnan(a9) and not np.isnan(a17) else np.nan
        print(f"  {y:<6} {a9:>+10.2%} {a17:>+10.2%} {d:>+8.2%} | {s9v:>8.3f} {s17v:>8.3f}")

    # 报告
    out_dir = ROOT / "journal"
    out_dir.mkdir(exist_ok=True)
    report_path = out_dir / f"v17_crowding_aware_eval_{date.today().strftime('%Y%m%d')}.md"
    lines = [
        f"# v17 Crowding-Aware 集成评估 — {date.today()}",
        "",
        "## 方法",
        "",
        "在 v9 五因子（team_coin / low_vol_20d / cgo_simple / enhanced_mom_60 / bp）基础上，",
        "加入 F5 产出的反向拥挤度因子 `-composite_crowding`（原 ICIR 0.73 / HAC t 6.33）。",
        "所有因子行业中性化后，在 IS (2022-01-01~2025-12-31) 上由 `icir_weight` 自动学权重，",
        "再用 `run_backtest`（月频，N=30，双边 0.3%，lag1）跑同窗口回测。",
        "",
        "## v17 ICIR 权重分配",
        "",
        "| 因子 | IC 均值 | IC 标准差 | ICIR | 方向 | 权重 |",
        "| --- | ---: | ---: | ---: | :---: | ---: |",
    ]
    for name in neutral_6:
        s = st17.get(name, {})
        lines.append(
            f"| {name} | {s.get('ic_mean', np.nan):.4f} | {s.get('ic_std', np.nan):.4f} "
            f"| {s.get('icir', 0):.3f} | {s17.get(name, 1):+d} | {w17.get(name, 0):.2%} |"
        )

    lines += [
        "",
        "## IS 指标对比 (2022-01-01 ~ 2025-12-31)",
        "",
        "| 指标 | v9_5f | v17_6f | Δ |",
        "| --- | ---: | ---: | ---: |",
    ]
    for k, fmt in [("ann", "{:+.2%}"), ("sr", "{:.3f}"), ("mdd", "{:.2%}"),
                   ("calmar", "{:.3f}"), ("wr", "{:.2%}"), ("excess", "{:+.2%}")]:
        v9v = m9.get(k, np.nan)
        v17v = m17.get(k, np.nan)
        if isinstance(v9v, (int,float)) and isinstance(v17v, (int,float)):
            d = v17v - v9v
            d_fmt = f"{d:+.2%}" if "%" in fmt else f"{d:+.3f}"
        else:
            d_fmt = "—"
        lines.append(f"| {k} | {fmt.format(v9v)} | {fmt.format(v17v)} | {d_fmt} |")

    lines += [
        "",
        "## 分年度",
        "",
        "| 年份 | v9 年化 | v17 年化 | Δ | v9 夏普 | v17 夏普 |",
        "| --- | ---: | ---: | ---: | ---: | ---: |",
    ]
    for y in sorted(set(y9) | set(y17)):
        a9  = y9.get(y, {}).get("ann", np.nan)
        a17 = y17.get(y, {}).get("ann", np.nan)
        s9v = y9.get(y, {}).get("sr", np.nan)
        s17v = y17.get(y, {}).get("sr", np.nan)
        d = a17 - a9 if not np.isnan(a9) and not np.isnan(a17) else np.nan
        lines.append(f"| {y} | {a9:+.2%} | {a17:+.2%} | {d:+.2%} | {s9v:.3f} | {s17v:.3f} |")

    lines += [
        "",
        "## 结论",
        "",
    ]
    d_sr = m17.get("sr", np.nan) - m9.get("sr", np.nan)
    d_ann = m17.get("ann", np.nan) - m9.get("ann", np.nan)
    d_mdd = m17.get("mdd", np.nan) - m9.get("mdd", np.nan)
    if d_sr > 0.1 and d_ann > 0.02:
        lines.append(f"- ✅ v17 显著优于 v9：夏普 +{d_sr:.2f}，年化 +{d_ann:.2%}，回撤变化 {d_mdd:+.2%}")
        lines.append("- 推荐：将 -composite_crowding 纳入正式因子池，权重按 ICIR 自适应")
    elif d_sr > 0.03:
        lines.append(f"- ⚠️ v17 略优于 v9（夏普 +{d_sr:.2f}），但提升有限，需 OOS 验证")
    else:
        lines.append(f"- ❌ v17 未显著优于 v9（夏普 Δ {d_sr:+.3f}），不进正式因子池")
        lines.append("- 可能原因：crowding 与 low_vol_20d/cgo_simple 相关性高，ICIR 权重已摊薄")

    lines += [
        "",
        "## caveat",
        "",
        "- IS 同窗口既学权重又评估，存在 in-sample 过拟合。严格 OOS 需要 2026+ 数据",
        "- crowding 数据仅从 2022-01 起，regime 局限：样本期覆盖机构抱团回落+小微盘崩盘+政策转向，结论可迁移性待验证",
    ]
    report_path.write_text("\n".join(lines), encoding="utf-8")
    print(f"\n[报告] 写入 {report_path}")

    # 保存收益曲线
    curves = pd.DataFrame({"v9_5f": ret_v9, "v17_6f": ret_v17})
    curves.to_parquet(ROOT / "research/factors/crowding_filter/v17_vs_v9_returns.parquet")
    print(f"[收益] 写入 research/factors/crowding_filter/v17_vs_v9_returns.parquet")
    print(f"\n总用时 {time.time()-t0:.1f}s")
    print("="*70, "\nDONE")


if __name__ == "__main__":
    main()
