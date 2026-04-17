"""
v16 九因子 regime-conditional IC 诊断。

目的: 找出 v16 中 "熊市段 IC 崩塌" 的弱因子, 为后续替换/剔除提供依据。
原则: 不做参数搜索, 只做 OOS 样本上的分段统计。
方法:
  1. 算 v16 全部 9 个因子 (与 _MultiFactorV16Adapter 一致)
  2. 算 5 日 / 21 日前瞻收益
  3. HS300<MA120 shift(1) 切 bear/bull (与 v25 一致)
  4. 对每个因子分 regime 算 IC 均值 + Newey-West t-stat
  5. 按因子原始方向 (d) 翻转, 使 "有效因子" 的 IC 为正

输出: journal/v16_regime_ic_{date}.md
"""
from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import numpy as np
import pandas as pd

from utils.alpha_factors import (
    low_vol_20d, team_coin, shadow_lower,
    amihud_illiquidity, price_volume_divergence,
    turnover_acceleration, high_52w_ratio,
    momentum_6m_skip1m, win_rate_60d,
)
from utils.factor_analysis import compute_ic_series, _newey_west_se
from utils.local_data_loader import get_all_symbols, load_price_wide, load_factor_wide
from utils.stop_loss import hs300_bear_regime

WARMUP = "2019-01-01"
START = "2022-01-01"
END = "2025-12-31"
FWD_HORIZONS = [5, 21]
V25_MA = 120


def build_v16_factors(price_wide: pd.DataFrame, symbols: list[str]) -> dict[str, tuple[pd.DataFrame, int]]:
    """返回 {factor_name: (wide_df, direction)}, 与 _MultiFactorV16Adapter 口径一致。"""
    start = str(price_wide.index[0].date())
    end = str(price_wide.index[-1].date())
    out: dict[str, tuple[pd.DataFrame, int]] = {}

    out["low_vol_20d"] = (low_vol_20d(price_wide), +1)
    out["team_coin"] = (team_coin(price_wide), +1)
    out["high_52w"] = (high_52w_ratio(price_wide), -1)
    out["mom_6m_skip1m"] = (momentum_6m_skip1m(price_wide), -1)
    out["win_rate_60d"] = (win_rate_60d(price_wide), -1)

    low_wide = load_price_wide(symbols, start, end, field="low").reindex_like(price_wide)
    out["shadow_lower"] = (shadow_lower(price_wide, low_wide), -1)

    vol_wide = load_price_wide(symbols, start, end, field="volume").reindex_like(price_wide)
    out["amihud_illiq"] = (amihud_illiquidity(price_wide, vol_wide), +1)
    out["price_vol_divergence"] = (price_volume_divergence(price_wide, vol_wide), +1)

    turnover_wide = load_factor_wide(symbols, "turnover", start, end).reindex_like(price_wide)
    out["turnover_accel"] = (turnover_acceleration(turnover_wide), -1)

    return out


def forward_returns(price_wide: pd.DataFrame, horizon: int) -> pd.DataFrame:
    """前瞻 h 日几何收益: price[t+h]/price[t] - 1, 存放在 index=t 上。"""
    shifted = price_wide.shift(-horizon)
    return (shifted / price_wide - 1.0)


def ic_stats(ic: pd.Series) -> dict:
    """IC 均值 / std / NW t / ICIR / 观测数。"""
    x = ic.dropna().values
    n = len(x)
    if n < 10:
        return {"n": n, "mean": np.nan, "std": np.nan, "t_nw": np.nan, "icir": np.nan}
    mu = float(np.mean(x))
    sd = float(np.std(x, ddof=1))
    nw_se = _newey_west_se(x, lag=max(int(np.floor(4 * (n / 100) ** (2 / 9))), 1))
    t_nw = mu / nw_se if nw_se and nw_se > 0 else np.nan
    icir = mu / sd * np.sqrt(252) if sd > 0 else np.nan
    return {"n": n, "mean": mu, "std": sd, "t_nw": float(t_nw), "icir": float(icir)}


def main():
    print(f"[1/5] 加载价格宽表 {WARMUP} ~ {END}…")
    symbols = get_all_symbols()
    price = load_price_wide(symbols, WARMUP, END, field="close")
    valid = price.columns[price.notna().sum() > 500]
    price = price[list(valid)]
    print(f"  股票: {len(valid)}, 交易日: {len(price)}")

    print("[2/5] 计算 v16 九因子…")
    factors = build_v16_factors(price, list(valid))
    print(f"  因子数: {len(factors)}")

    print("[3/5] 计算前瞻收益…")
    fwd_rets = {h: forward_returns(price, h) for h in FWD_HORIZONS}

    print("[4/5] 加载 HS300 regime 标志…")
    hs300 = load_price_wide(["399300"], "2018-01-01", END, field="close")["399300"].dropna()
    regime_full = hs300_bear_regime(hs300, ma_window=V25_MA, shift_days=1)
    eval_dates = price.loc[START:END].index
    regime = regime_full.reindex(eval_dates).fillna(False).astype(bool)
    print(f"  eval 段 {eval_dates[0].date()} ~ {eval_dates[-1].date()}, n={len(eval_dates)}, bear 覆盖 {regime.mean():.1%}")

    print("[5/5] 分 regime 算 IC…")
    rows = []
    for name, (fac_wide, d) in factors.items():
        if fac_wide is None or fac_wide.empty:
            print(f"  {name}: 因子空, 跳过")
            continue
        for h in FWD_HORIZONS:
            ret_wide = fwd_rets[h]
            ic = compute_ic_series(fac_wide, ret_wide, method="spearman", min_stocks=30)
            ic = ic.reindex(eval_dates)
            ic_dir = ic * d  # 方向对齐, 正数表示 "因子原方向有效"

            for seg_name, mask in [
                ("full", pd.Series(True, index=eval_dates)),
                ("bear", regime),
                ("bull", ~regime),
            ]:
                s = ic_dir[mask]
                st = ic_stats(s)
                rows.append({
                    "factor": name,
                    "direction": d,
                    "horizon": h,
                    "regime": seg_name,
                    **st,
                })

    df = pd.DataFrame(rows)

    # 分 horizon pivot 方便阅读
    today = date.today().strftime("%Y%m%d")
    out_md = Path(f"journal/v16_regime_ic_{today}.md")

    lines = []
    lines.append(f"# v16 因子 regime-conditional IC 诊断 — {today}")
    lines.append("")
    lines.append(f"> 数据: {len(valid)} 只股票, eval {eval_dates[0].date()}~{eval_dates[-1].date()} n={len(eval_dates)}")
    lines.append(f"> regime: HS300<MA{V25_MA} shift(1), bear 覆盖 {regime.mean():.1%}")
    lines.append(f"> IC: Spearman rank IC, 因子×方向对齐后, 正数表示原方向仍有效")
    lines.append(f"> t_nw: Newey-West HAC t-stat, Bartlett 核, lag=floor(4*(n/100)^(2/9))")
    lines.append("")

    for h in FWD_HORIZONS:
        sub = df[df["horizon"] == h].copy()
        lines.append(f"## 前瞻 {h} 日")
        lines.append("")

        # 关键信息表: full/bear/bull mean IC + t_nw + ICIR
        pivot = sub.pivot(index="factor", columns="regime", values="mean")[["full", "bull", "bear"]]
        pivot_t = sub.pivot(index="factor", columns="regime", values="t_nw")[["full", "bull", "bear"]]
        pivot_i = sub.pivot(index="factor", columns="regime", values="icir")[["full", "bull", "bear"]]

        tbl = pd.DataFrame(index=pivot.index)
        for col in ["full", "bull", "bear"]:
            tbl[f"IC_{col}"] = pivot[col]
            tbl[f"tNW_{col}"] = pivot_t[col]
            tbl[f"ICIR_{col}"] = pivot_i[col]

        tbl["bear_minus_bull"] = tbl["IC_bear"] - tbl["IC_bull"]
        tbl = tbl.sort_values("IC_bear", ascending=False)
        lines.append(tbl.to_markdown(floatfmt=".4f"))
        lines.append("")

    # 核心判定: 熊市段 IC 为负 / t_nw<-1 的因子建议剔除
    lines.append("## 熊市段失效因子判定")
    lines.append("")
    crit = df[(df["horizon"] == 5) & (df["regime"] == "bear")].set_index("factor")
    bad = crit[(crit["mean"] < 0) | (crit["t_nw"] < -1)].sort_values("mean")
    good = crit[crit["mean"] >= 0].sort_values("mean", ascending=False)
    lines.append("### 熊市段 IC < 0 或 t_NW < -1 (建议替换)")
    if len(bad) == 0:
        lines.append("- (无)")
    else:
        for f, row in bad.iterrows():
            lines.append(f"- **{f}**: IC_bear={row['mean']:+.4f}, t_NW={row['t_nw']:+.2f}, ICIR={row['icir']:+.2f}, n={int(row['n'])}")
    lines.append("")
    lines.append("### 熊市段 IC ≥ 0 (保留)")
    for f, row in good.iterrows():
        lines.append(f"- {f}: IC_bear={row['mean']:+.4f}, t_NW={row['t_nw']:+.2f}, ICIR={row['icir']:+.2f}, n={int(row['n'])}")
    lines.append("")
    lines.append("## 不抄近道的下一步")
    lines.append("")
    lines.append("1. 熊市段有效因子 (bear IC>0 且 t_NW 显著) 可以直接用作 v26 候选池基础。")
    lines.append("2. 熊市段 IC 崩塌因子不应立即删除, 应再看 ICIR_bear 稳定性; 稳定为负 → 翻转方向, 不稳定 → 降权或剔除。")
    lines.append("3. 禁止: 先看分年结果再回头选因子 (look-ahead into regime labels)。")
    lines.append("4. 下一步合规路径: 按本诊断结果设计 v26 = 熊市有效因子集 ∪ v16, IC 加权, 独立 OOS 验证 + DSR 跟踪。")
    lines.append("")

    out_md.write_text("\n".join(lines), encoding="utf-8")
    print(f"\n✓ 写出 {out_md}")

    # 终端摘要
    print("\n=== h=5 熊市段 IC 排序 (方向对齐后) ===")
    crit_sorted = crit.sort_values("mean", ascending=False)
    for f, row in crit_sorted.iterrows():
        flag = "✅" if row["mean"] >= 0 else "❌"
        print(f"  {flag} {f:22s} IC={row['mean']:+.4f}  tNW={row['t_nw']:+.2f}  ICIR={row['icir']:+.2f}")


if __name__ == "__main__":
    main()
