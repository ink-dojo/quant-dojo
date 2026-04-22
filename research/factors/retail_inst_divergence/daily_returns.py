"""
RIAD Q2Q3_minus_Q5 每日 L/S 返回序列生成器

和 cost_aware_ls.py 的区别:
    cost_aware_ls 每 period 一个 return (20d 持仓均值)
    本模块每日 mark-to-market 单独记录 → 方便做 corr / bootstrap CI / DSR

持仓规则 (pre-reg, 不可调):
    rebalance_days = 20
    long  = Q2Q3 (因子分位 [0.2, 0.6])
    short = Q5   (因子分位 [0.8, 1.0])
    因子 = RIAD size + SW1 industry neutral (shift 1)
    调仓日 D: 重置持仓为当日 signal top/bot, 按等权
    持有 D+1 ~ D+19 mark-to-market
    cost = turnover × 2 × 0.0015 扣在调仓日 daily return 上

输出 parquet: date index, columns = [gross_long, gross_short, gross_ls, cost, net_ls]
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[3]

from research.factors.retail_inst_divergence.factor import (  # noqa: E402
    build_attention_panel,
    compute_riad_factor,
)
from research.factors.retail_inst_divergence.industry_eval import load_industry_series  # noqa: E402
from research.factors.retail_inst_divergence.neutralize_eval import (  # noqa: E402
    load_circ_mv_wide,
    size_neutralize,
)
from utils.factor_analysis import industry_neutralize_fast  # noqa: E402

PRICE_PATH = ROOT / "data" / "processed" / "price_wide_close_2014-01-01_2025-12-31_qfq_5477stocks.parquet"
REBALANCE_DAYS = 20
LONG_LOW, LONG_HIGH = 0.2, 0.6
SHORT_LOW, SHORT_HIGH = 0.8, 1.0
COST_ONE_WAY = 0.0015


def _to_ts(sym: str) -> str:
    if sym.startswith(("60", "68")):
        return f"{sym}.SH"
    if sym.startswith(("00", "30")):
        return f"{sym}.SZ"
    return f"{sym}.SZ"


def build_riad_neutral(start: str, end: str, price: pd.DataFrame) -> pd.DataFrame:
    cal = price.loc[start:end].index
    panels = build_attention_panel(start, end, cal)
    raw = compute_riad_factor(panels["retail_attn"], panels["inst_attn"])
    circ_mv = load_circ_mv_wide(start, end)
    sn = size_neutralize(raw, circ_mv)
    ind = load_industry_series()
    return industry_neutralize_fast(sn, ind)


def generate_daily_ls(
    factor: pd.DataFrame,
    price: pd.DataFrame,
    start: str,
    end: str,
    rebalance_days: int = REBALANCE_DAYS,
) -> pd.DataFrame:
    """
    生成 daily long-short returns.

    注意: factor 应已经 shift(1) (signal 在 T 日可见 = 用 T-1 日及更早信息),
          在 T 日开盘进场; 这里简化为用收盘价, 不做 T+0.5 调整.
    """
    dates = price.loc[start:end].index
    rebal_dates = dates[::rebalance_days]

    long_sets: list[set[str]] = []
    short_sets: list[set[str]] = []
    rebal_ts: list[pd.Timestamp] = []

    prev_long: set[str] = set()
    prev_short: set[str] = set()
    for d in rebal_dates:
        if d not in factor.index:
            long_sets.append(prev_long); short_sets.append(prev_short); rebal_ts.append(d)
            continue
        s = factor.loc[d].dropna()
        if len(s) < 100:
            long_sets.append(prev_long); short_sets.append(prev_short); rebal_ts.append(d)
            continue
        q_ll = s.quantile(LONG_LOW); q_lh = s.quantile(LONG_HIGH)
        q_sl = s.quantile(SHORT_LOW); q_sh = s.quantile(SHORT_HIGH)
        new_long = set(s[(s >= q_ll) & (s <= q_lh)].index)
        new_short = set(s[(s >= q_sl) & (s <= q_sh)].index)
        long_sets.append(new_long); short_sets.append(new_short); rebal_ts.append(d)
        prev_long, prev_short = new_long, new_short

    # 每日: 根据当前 date 处于哪个 rebalance 周期, 取对应 long/short set
    rebal_idx = pd.DatetimeIndex(rebal_ts)
    daily_long_ret = []
    daily_short_ret = []
    daily_cost = []
    daily_ls_gross = []

    # 预计算日度 pct_chg
    pct = price.pct_change()

    prev_idx = -1  # 上一个 rebalance 位置
    for d in dates:
        # 当前所处的 rebalance 区间 idx
        pos = rebal_idx.searchsorted(d, side="right") - 1
        if pos < 0:
            daily_long_ret.append(np.nan); daily_short_ret.append(np.nan)
            daily_ls_gross.append(np.nan); daily_cost.append(0.0)
            continue

        cur_long = long_sets[pos]
        cur_short = short_sets[pos]
        # 调仓日? 比较 pos != prev_idx
        is_rebal = (pos != prev_idx)
        prev_idx = pos

        # 当日 long / short 平均收益 (等权)
        row = pct.loc[d] if d in pct.index else pd.Series(dtype=float)
        long_syms = [s for s in cur_long if s in row.index]
        short_syms = [s for s in cur_short if s in row.index]
        if long_syms:
            long_r = float(row[long_syms].mean(skipna=True))
        else:
            long_r = 0.0
        if short_syms:
            short_r = float(row[short_syms].mean(skipna=True))
        else:
            short_r = 0.0

        gross_ls = long_r - short_r

        # cost: 调仓日扣 turnover × 2 × 0.0015 (两腿 symmetric diff / union × cost_one_way)
        cost = 0.0
        if is_rebal and pos > 0:
            old_long, old_short = long_sets[pos - 1], short_sets[pos - 1]
            tl = len(cur_long.symmetric_difference(old_long)) / max(len(cur_long | old_long), 1)
            ts = len(cur_short.symmetric_difference(old_short)) / max(len(cur_short | old_short), 1)
            cost = (tl + ts) * COST_ONE_WAY
        elif is_rebal and pos == 0:
            # 首次建仓, 全仓换手
            cost = 2 * COST_ONE_WAY

        daily_long_ret.append(long_r)
        daily_short_ret.append(short_r)
        daily_ls_gross.append(gross_ls)
        daily_cost.append(cost)

    out = pd.DataFrame({
        "gross_long": daily_long_ret,
        "gross_short": daily_short_ret,
        "gross_ls": daily_ls_gross,
        "cost": daily_cost,
    }, index=dates)
    out["net_ls"] = out["gross_ls"] - out["cost"]
    return out


def main() -> None:
    start, end = "2023-10-01", "2025-12-31"
    price = pd.read_parquet(PRICE_PATH)
    price.columns = [_to_ts(c) for c in price.columns]

    print("构造 size+ind neutral RIAD...")
    factor_raw = build_riad_neutral(start, end, price)
    factor_shift = factor_raw.shift(1)

    print("生成 daily LS returns...")
    daily = generate_daily_ls(factor_shift, price, start, end)
    print(f"daily shape: {daily.shape}")
    print(daily.head(3))
    print("...")
    print(daily.tail(3))

    # 保存
    out_parquet = ROOT / "research" / "factors" / "retail_inst_divergence" / "riad_ls_daily_returns.parquet"
    daily.to_parquet(out_parquet)
    print(f"\n保存: {out_parquet}")

    # 统计摘要
    rets = daily["net_ls"].dropna()
    ann = rets.mean() * 252
    vol = rets.std(ddof=1) * np.sqrt(252)
    sr = ann / vol
    cum = float(np.prod(1 + rets) - 1)
    mdd_series = (1 + rets).cumprod()
    dd = mdd_series / mdd_series.cummax() - 1
    mdd = float(dd.min())
    print("\n=== RIAD Q2Q3_minus_Q5 daily LS 汇总 (net, 扣 0.3% 双边) ===")
    print(f"  样本天数       : {len(rets)}")
    print(f"  年化收益       : {ann*100:+.2f}%")
    print(f"  年化波动       : {vol*100:.2f}%")
    print(f"  Sharpe         : {sr:+.3f}")
    print(f"  最大回撤       : {mdd*100:+.2f}%")
    print(f"  累计净值       : {(1+cum)*100:.2f}  (基准 100)")

    # 分段
    for lab, s, e in [
        ("IS 2023-10~2024-12", "2023-10-01", "2024-12-31"),
        ("OOS 2025", "2025-01-01", "2025-12-31"),
    ]:
        sub = daily.loc[s:e, "net_ls"].dropna()
        ann2 = sub.mean() * 252
        vol2 = sub.std(ddof=1) * np.sqrt(252)
        sr2 = ann2 / vol2 if vol2 > 0 else np.nan
        print(f"  [{lab}] n={len(sub)} Ann={ann2*100:+.2f}% Vol={vol2*100:.2f}% Sharpe={sr2:+.3f}")


if __name__ == "__main__":
    main()
