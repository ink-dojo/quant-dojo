"""
v34 = v16 baseline 策略在修好元数据后的长历史 OOS — 预注册单次实验。

动机 (2026-04-17 下午):
  今天彻底修好了 data/raw/listing_metadata.parquet 的 delist_date 字段
  (从 scraper 伪造的 2026-03-26 快照, 改为 tushare 真实 1999-2026 分布)。
  现在可以做正经的长历史 OOS: v16 原始预注册 2022-2025 只有 ~970 个交易日,
  扩展到 2018-2025 有 ~1900 个交易日, 统计功效翻倍。

预注册 (单次实验, 零参数搜索):
  - 策略: multi_factor_v16 (原样, 9 因子, top-30 等权 long-only)
  - warmup: 2015-01-01 (给 750 天 lookback)
  - eval:   2018-01-01 ~ 2025-12-31 (8 年, vs 原 4 年)
  - txn:    strategy engine 内建 0.003 双边 (和 v16 原一致)
  - admission: ann>15%, sharpe>0.8, mdd>-30%, psr0>0.95
  - DSR:    n_trials = 11 (昨日 10 + 本次 1)
  - 幸存者: 用修好的元数据, universe 含期内死亡股 (每只到其死亡日)

严禁 (不调参, 不 ad-hoc 闭环):
  - 不换因子集
  - 不换 n_stocks (30 固定)
  - 不换 commission
  - 不换 eval 区间
  - 失败就诚实写结论, 不换 region, 不换策略, 不 re-run

附加幸存者偏差控制:
  - 显式构造 universe: listing_metadata.parquet 中 list_date < eval_start &
    (not is_delisted OR delist_date >= eval_start)
  - backtest engine 会自动把死亡股在死亡后的 NaN 收益忽略 (skipna)
  - 记录期内死亡股对 trade_log 的影响, 报告死亡股对收益的贡献占比

输出:
  journal/v34_v16_long_history_{date}.md
"""
from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import numpy as np
import pandas as pd

from utils.local_data_loader import load_price_wide, get_all_symbols
from utils.metrics import (
    annualized_return, annualized_volatility, sharpe_ratio,
    max_drawdown, win_rate, probabilistic_sharpe, deflated_sharpe,
    bootstrap_sharpe_ci, min_track_record_length,
)

WARMUP = "2015-01-01"
EVAL_START = "2018-01-01"
EVAL_END = "2025-12-31"
N_STOCKS = 30
N_TRIALS = 11  # 昨日 10 + 本次 1
DSR_TARGET = 0.95


def build_universe(start: pd.Timestamp, end: pd.Timestamp,
                   meta_path: str = "data/raw/listing_metadata.parquet") -> list:
    """
    构造 PIT universe: 在 start 时已上市, 且 (未退市 OR 退市在 eval_start 之后).
    这样 eval 期间可选股票池不包含 "期初就已退市的" 假幸存者, 但保留 "期内死亡" 的.
    """
    meta = pd.read_parquet(meta_path)
    meta["list_date"] = pd.to_datetime(meta["list_date"])
    meta["delist_date"] = pd.to_datetime(meta["delist_date"])

    listed_before = meta["list_date"] <= start
    alive_in_period = (~meta["is_delisted"]) | (meta["delist_date"] > start)
    eligible = meta[listed_before & alive_in_period]

    # 只保留本地有 CSV 数据的
    on_disk = set(get_all_symbols())
    eligible_syms = eligible[eligible["symbol"].isin(on_disk)]["symbol"].tolist()

    # 统计期内死亡
    died = eligible[
        eligible["is_delisted"]
        & (eligible["delist_date"] > start)
        & (eligible["delist_date"] <= end)
    ]
    print(f"  期初可投资 universe: {len(eligible)}")
    print(f"  其中本地有数据: {len(eligible_syms)}")
    print(f"  期内死亡: {len(died)}")

    return sorted(eligible_syms), list(died["symbol"])


def metrics(r: pd.Series, name: str) -> dict:
    return {
        "策略": name,
        "n": len(r),
        "ann_return": float(annualized_return(r)),
        "sharpe": float(sharpe_ratio(r)),
        "mdd": float(max_drawdown(r)),
        "vol": float(annualized_volatility(r)),
        "psr_0": float(probabilistic_sharpe(r, sr_benchmark=0.0)),
        "psr_0.5": float(probabilistic_sharpe(r, sr_benchmark=0.5)),
        "win_rate": float(win_rate(r)),
    }


def admission(m: dict) -> dict:
    return {
        "ann_pass": m["ann_return"] > 0.15,
        "sharpe_pass": m["sharpe"] > 0.80,
        "mdd_pass": m["mdd"] > -0.30,
        "psr0_pass": m["psr_0"] > 0.95,
        "all_pass": (m["ann_return"] > 0.15 and m["sharpe"] > 0.80
                     and m["mdd"] > -0.30 and m["psr_0"] > 0.95),
    }


def main():
    print(f"[1/6] 构造 PIT universe ({EVAL_START})...")
    eval_start_ts = pd.Timestamp(EVAL_START)
    eval_end_ts = pd.Timestamp(EVAL_END)
    universe, died_syms = build_universe(eval_start_ts, eval_end_ts)

    print(f"\n[2/6] 加载 {len(universe)} 只股票的 close 宽表 (warmup={WARMUP} ~ {EVAL_END})...")
    price = load_price_wide(universe, WARMUP, EVAL_END, field="close")
    print(f"  shape: {price.shape}")
    # 去除整列 NaN 的 (应该没有, 因为 universe 都有数据)
    price = price.dropna(axis=1, how="all")

    print(f"\n[3/6] 实例化 v16 策略 (n_stocks={N_STOCKS})...")
    from pipeline.strategy_registry import get_strategy
    entry = get_strategy("multi_factor_v16")
    strat = entry.factory({"n_stocks": N_STOCKS})

    print(f"\n[4/6] 运行回测 (warmup + eval, ~{len(price)} 交易日)...")
    result = strat.run(price)
    returns = strat.results["returns"]
    print(f"  全区间 returns shape: {returns.shape}")

    # 截取 eval 区间
    eval_ret = returns.loc[EVAL_START:EVAL_END].dropna()
    print(f"  eval 区间 ({EVAL_START}~{EVAL_END}): {len(eval_ret)} 天")

    print(f"\n[5/6] 计算指标 + 统计推断...")
    m = metrics(eval_ret, "v34 = v16 long-history")
    a = admission(m)

    # DSR — sharpe pool 昨日 10 + 本次 1
    sharpe_pool = [
        0.676,   # v16 baseline 2022-2025
        0.835, 1.050, 0.668, -0.216, 0.490, 0.368, 0.836,
        1.497,   # reversal gross (prior)
        0.121,   # v33 net
        float(m["sharpe"]),  # v34 this trial
    ]
    sharpe_std = float(np.std(sharpe_pool, ddof=1))

    ci = bootstrap_sharpe_ci(eval_ret, n_boot=2000, alpha=0.05, seed=42)
    dsr = deflated_sharpe(eval_ret, n_trials=N_TRIALS,
                          trials_sharpe_std=max(sharpe_std, 0.1))
    mintrl_05 = min_track_record_length(eval_ret, sr_target=0.5)
    mintrl_08 = min_track_record_length(eval_ret, sr_target=0.8)

    # 分年
    years = sorted(set(eval_ret.index.year))
    yrows = []
    for y in years:
        ry = eval_ret[eval_ret.index.year == y]
        yrows.append({
            "year": int(y), "n": len(ry),
            "sharpe": float(sharpe_ratio(ry)),
            "ann": float(annualized_return(ry)),
            "mdd": float(max_drawdown(ry)),
        })
    y_df = pd.DataFrame(yrows)

    # 死亡股贡献诊断: adapter 没暴露 trade_log, 简化只统计数量
    died_hit = 0
    total_rebals = 0
    print(f"  期内死亡股 {len(died_syms)} 只 (factor signals 在其死亡日后自动消失)")

    print(f"\n[6/6] 写 journal...")
    today = date.today().strftime("%Y%m%d")
    out_md = Path(f"journal/v34_v16_long_history_{today}.md")
    L: list[str] = []
    L.append(f"# v34 = v16 长历史 OOS — 预注册单次实验 — {today}")
    L.append("")
    L.append(f"> 预注册: v16 原样 9 因子 top-{N_STOCKS} 等权 long-only")
    L.append(f"> warmup {WARMUP} / eval {EVAL_START}~{EVAL_END} n={len(eval_ret)}")
    L.append(f"> DSR n_trials={N_TRIALS}, sharpe_std={sharpe_std:.3f}")
    L.append(f"> Universe: PIT {len(universe)} 只, 期内死亡 {len(died_syms)} 只")
    L.append("")

    L.append("## 1. 整体指标")
    L.append("")
    L.append(pd.DataFrame([m]).to_markdown(index=False, floatfmt=".4f"))
    L.append("")

    L.append("## 2. Admission 判定")
    L.append("")
    L.append(f"- 结果: {a}")
    L.append("")

    L.append("## 3. 统计推断")
    L.append("")
    L.append(f"- Bootstrap 95% CI: [{ci['ci_low']:.3f}, {ci['ci_high']:.3f}]")
    L.append(f"- CI 下界 > 0.80: {'OK' if ci['ci_low'] > 0.80 else 'FAIL'}")
    L.append(f"- DSR (n_trials={N_TRIALS}, std={sharpe_std:.3f}): **{dsr:.4f}**")
    L.append(f"- DSR > 0.95: {'OK' if dsr >= DSR_TARGET else 'FAIL'}")
    L.append(f"- MinTRL vs sr=0.5: {mintrl_05:.0f} 日 ({mintrl_05/252:.1f} 年)")
    L.append(f"- MinTRL vs sr=0.8: {mintrl_08:.0f} 日 ({mintrl_08/252:.1f} 年)")
    L.append("")

    L.append("## 4. 分年诊断")
    L.append("")
    L.append(y_df.to_markdown(index=False, floatfmt=".4f"))
    L.append("")

    L.append("## 5. 幸存者偏差诊断")
    L.append("")
    L.append(f"- PIT universe: {len(universe)}")
    L.append(f"- 期内死亡 (真实 delist_date): {len(died_syms)}")
    L.append(f"- 死亡股处理: engine 内部 `.mean(skipna=True)`, 死亡日后自动退出权重")
    L.append(f"- 与原 2022-2025 对比: 上次 universe 隐含 4797, 本次 PIT {len(universe)} 含期内死亡")
    L.append("")

    L.append("## 6. 诚实结论")
    L.append("")
    pass_adm = a["all_pass"]
    pass_dsr = dsr >= DSR_TARGET
    pass_ci = ci["ci_low"] > 0.80
    L.append(f"- admission 四门 (net): {'OK' if pass_adm else 'FAIL'}")
    L.append(f"- DSR (n_trials={N_TRIALS}): {'OK' if pass_dsr else 'FAIL'}")
    L.append(f"- CI 下界 > 0.80: {'OK' if pass_ci else 'FAIL'}")
    L.append("")
    if pass_adm and pass_dsr and pass_ci:
        L.append("**三重过门**: v16 长历史仍然稳健, admission + DSR + CI 全过。")
        L.append("下一步: paper-trading 累积 forward OOS, 确认不是 in-sample lucky。")
    elif pass_adm and not pass_dsr:
        L.append("**admission 过, DSR 不过**: 长历史样本量帮到了 CI, 但仍被 selection bias 压住。")
        L.append("合规: 不声称过门, 转 paper-trading, 不重试。")
    elif not pass_adm:
        L.append("**admission 未过**: 即使扩展到 8 年历史, v16 仍过不了门。")
        L.append(f"  sharpe={m['sharpe']:.3f} (需 >0.80), ann={m['ann_return']:.2%} (需 >15%)")
        L.append(f"  mdd={m['mdd']:.2%} (需 >-30%), psr0={m['psr_0']:.4f} (需 >0.95)")
        L.append("合规: 停止 v16 方向调优, 不重试其他 v## 变体。")
    L.append("")

    L.append("## 7. 严禁 (红线)")
    L.append("")
    L.append("- 不调 n_stocks (换 20/40/50)")
    L.append("- 不换因子集 (加减因子)")
    L.append("- 不换 eval 区间 (截取 lucky 段)")
    L.append("- 不加 overlay (regime / vol target)")
    L.append("- 失败就写结论, 不 ad-hoc 重试")
    L.append("")

    out_md.write_text("\n".join(L), encoding="utf-8")
    print(f"\n写出 {out_md}")
    print("\n=== 汇总 ===")
    print(f"  v34: ann={m['ann_return']:.2%} sr={m['sharpe']:.3f} mdd={m['mdd']:.2%}")
    print(f"  admission: {a['all_pass']}")
    print(f"  DSR: {dsr:.4f} (target {DSR_TARGET})")
    print(f"  CI: [{ci['ci_low']:.3f}, {ci['ci_high']:.3f}]")


if __name__ == "__main__":
    main()
