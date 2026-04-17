"""
时序动量 (Time-Series Momentum, TSM) 独立策略 — 预注册研究。

动机:
  v16 (long-only A 股 top-30 因子组合) 已探索到 admission/DSR 瓶颈。
  合规下一步是 "多策略集成", 需要与 v16 **真正独立** 的信号源。
  TSM 是 managed futures 行业的经典 α (Moskowitz-Ooi-Pedersen 2012):
    信号类型 = 时序 (vs v16 的截面)
    资产 = 指数 (vs v16 的个股)
    方向 = 可能做空 (vs v16 的 long-only)

预注册 (行业标准参数, 不调优):
  - 信号: sign(rolling_126d_return)  (~ 半年动量, Moskowitz et al 经典)
  - 执行: shift(1) 避免偷看
  - 指数: HS300 (399300), ZZ500 (399905) 各自独立
  - 杠杆: 无 (exposure ∈ {-1, 0, +1})
  - 交易成本: 双边 0.15% (A 股指数 ETF 实盘保守估计)
  - eval 期: 2022-01-04 ~ 2025-12-31 (与 v16 对齐, 保持可比)
  - warmup: 2019-01-01 (保证 126d 有充足历史)

Admission 门槛: ann>15%, sharpe>0.80, mdd>-30%, PSR0>0.95
DSR: 本实验为独立研究, n_trials=2 (HS300/ZZ500 同时测, 各作一次 trial)
     若后续要合进 v16 多策略, n_trials 再追加

红线 (不调参):
  - 不扫 window ∈ {60, 126, 252} 找最佳
  - 不换 signal (MA crossover, breakout) 重试
  - 不加 vol-targeting / regime filter 等 overlay
  - 若失败, 诚实记录, 不做 ad-hoc 修改
"""
from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import numpy as np
import pandas as pd

from utils.local_data_loader import load_price_wide
from utils.metrics import (
    annualized_return, annualized_volatility, sharpe_ratio,
    max_drawdown, win_rate, probabilistic_sharpe, deflated_sharpe,
    bootstrap_sharpe_ci, min_track_record_length,
)

WARMUP = "2019-01-01"
START = "2022-01-01"
END = "2025-12-31"
LOOKBACK = 126  # 半年, Moskowitz 经典
COST_PER_TURN = 0.0015  # 单边 0.15%
N_TRIALS = 2


def tsm_signal(close: pd.Series, lookback: int = 126) -> pd.Series:
    """信号 = sign(过去 lookback 天 log 收益), shift(1) 防偷看。"""
    log_close = np.log(close)
    past_ret = log_close - log_close.shift(lookback)
    sig = np.sign(past_ret)
    return sig.shift(1).fillna(0)


def tsm_return(close: pd.Series, sig: pd.Series, cost_per_turn: float) -> pd.Series:
    daily_ret = close.pct_change()
    gross = (sig * daily_ret).fillna(0)
    # 交易成本: 每次 |Δexposure| 扣 cost
    turn = sig.diff().abs().fillna(0)
    net = gross - cost_per_turn * turn
    return net


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
    print("[1/4] 加载 HS300, ZZ500 收盘…")
    hs300 = load_price_wide(["399300"], WARMUP, END, field="close")["399300"].dropna()
    zz500 = load_price_wide(["399905"], WARMUP, END, field="close")["399905"].dropna()
    print(f"  HS300 n={len(hs300)}  ZZ500 n={len(zz500)}")

    print(f"[2/4] 计算 TSM 信号 (lookback={LOOKBACK}d, shift(1))…")
    sig_h = tsm_signal(hs300, LOOKBACK)
    sig_z = tsm_signal(zz500, LOOKBACK)

    print(f"[3/4] 计算净收益 (cost/turn={COST_PER_TURN:.3%})…")
    r_h = tsm_return(hs300, sig_h, COST_PER_TURN).loc[START:END].dropna()
    r_z = tsm_return(zz500, sig_z, COST_PER_TURN).loc[START:END].dropna()
    r_h = r_h[r_h.index >= pd.Timestamp(START)]
    r_z = r_z[r_z.index >= pd.Timestamp(START)]

    # 基准 (buy-and-hold)
    bh_h = hs300.pct_change().loc[START:END].dropna()
    bh_z = zz500.pct_change().loc[START:END].dropna()

    print("[4/4] metrics…")
    m_h = metrics(r_h, "TSM HS300")
    m_z = metrics(r_z, "TSM ZZ500")
    m_bhh = metrics(bh_h, "HS300 buy-hold")
    m_bhz = metrics(bh_z, "ZZ500 buy-hold")

    a_h = admission(m_h)
    a_z = admission(m_z)

    # 50/50 组合 (预注册, 不调权)
    common = r_h.index.intersection(r_z.index)
    r_combo = 0.5 * r_h.loc[common] + 0.5 * r_z.loc[common]
    m_c = metrics(r_combo, "TSM 50/50")
    a_c = admission(m_c)

    # DSR for HS300 TSM, ZZ500 TSM, and combo
    def dsr_for(r, n_trials):
        std_pool = float(np.std([m_h["sharpe"], m_z["sharpe"], m_c["sharpe"]], ddof=1))
        return deflated_sharpe(r, n_trials=n_trials, trials_sharpe_std=max(std_pool, 0.1))

    dsr_h = dsr_for(r_h, N_TRIALS)
    dsr_z = dsr_for(r_z, N_TRIALS)
    dsr_c = dsr_for(r_combo, N_TRIALS + 1)

    ci_h = bootstrap_sharpe_ci(r_h, n_boot=2000, alpha=0.05, seed=42)
    ci_z = bootstrap_sharpe_ci(r_z, n_boot=2000, alpha=0.05, seed=42)
    ci_c = bootstrap_sharpe_ci(r_combo, n_boot=2000, alpha=0.05, seed=42)

    # Switch counts
    sw_h = int((sig_h.diff().abs() > 0).sum())
    sw_z = int((sig_z.diff().abs() > 0).sum())

    today = date.today().strftime("%Y%m%d")
    out_md = Path(f"journal/tsm_index_{today}.md")
    L: list[str] = []
    L.append(f"# 时序动量 (TSM) 独立策略 — 预注册研究 — {today}")
    L.append("")
    L.append(f"> 预注册: sign(126d return), shift(1), cost={COST_PER_TURN:.2%}/turn")
    L.append(f"> eval {r_h.index[0].date()}~{r_h.index[-1].date()} n_HS300={len(r_h)} n_ZZ500={len(r_z)}")
    L.append(f"> DSR n_trials={N_TRIALS} (独立与 v16 体系, 若未来合并再追加)")
    L.append("")

    L.append("## 1. Metrics 对比")
    L.append("")
    df = pd.DataFrame([m_h, m_z, m_c, m_bhh, m_bhz])
    L.append(df.to_markdown(index=False, floatfmt=".4f"))
    L.append("")

    L.append("## 2. Admission 判定")
    L.append("")
    L.append(f"- TSM HS300: {a_h}")
    L.append(f"- TSM ZZ500: {a_z}")
    L.append(f"- TSM 50/50: {a_c}")
    L.append("")

    L.append("## 3. 统计推断")
    L.append("")
    L.append(f"| 策略 | Bootstrap CI | CI>0.80 | DSR | DSR>0.95 |")
    L.append(f"|:---|:---|:---:|---:|:---:|")
    L.append(f"| TSM HS300 | [{ci_h['ci_low']:.3f}, {ci_h['ci_high']:.3f}] | {'✅' if ci_h['ci_low']>0.80 else '❌'} | {dsr_h:.4f} | {'✅' if dsr_h>=0.95 else '❌'} |")
    L.append(f"| TSM ZZ500 | [{ci_z['ci_low']:.3f}, {ci_z['ci_high']:.3f}] | {'✅' if ci_z['ci_low']>0.80 else '❌'} | {dsr_z:.4f} | {'✅' if dsr_z>=0.95 else '❌'} |")
    L.append(f"| TSM 50/50 | [{ci_c['ci_low']:.3f}, {ci_c['ci_high']:.3f}] | {'✅' if ci_c['ci_low']>0.80 else '❌'} | {dsr_c:.4f} | {'✅' if dsr_c>=0.95 else '❌'} |")
    L.append("")

    L.append("## 4. 换手诊断")
    L.append("")
    L.append(f"- HS300 TSM switch 次数: {sw_h} ({sw_h/len(sig_h):.2%} 日")
    L.append(f"- ZZ500 TSM switch 次数: {sw_z} ({sw_z/len(sig_z):.2%} 日")
    L.append("")

    L.append("## 5. 分年 (TSM 50/50)")
    L.append("")
    yrs = sorted(set(r_combo.index.year))
    yrows = []
    for y in yrs:
        ry = r_combo[r_combo.index.year == y]
        yrows.append({
            "year": int(y), "n": len(ry),
            "ann": float(annualized_return(ry)),
            "sharpe": float(sharpe_ratio(ry)),
            "mdd": float(max_drawdown(ry)),
        })
    L.append(pd.DataFrame(yrows).to_markdown(index=False, floatfmt=".4f"))
    L.append("")

    L.append("## 6. 与 v16 相关性 (独立性验证)")
    L.append("")
    try:
        from pipeline.strategy_registry import get_strategy
        from utils.local_data_loader import get_all_symbols
        symbols = get_all_symbols()
        price_wide = load_price_wide(symbols, WARMUP, END, field="close")
        valid = price_wide.columns[price_wide.notna().sum() > 500]
        price_wide = price_wide[list(valid)]
        entry = get_strategy("multi_factor_v16")
        strat = entry.factory({"n_stocks": 30})
        res = strat.run(price_wide)
        col = "portfolio_return" if "portfolio_return" in res.columns else "returns"
        r_v16 = res[col].astype(float).loc[START:END].dropna()
        common_v = r_v16.index.intersection(r_combo.index)
        corr = float(r_v16.loc[common_v].corr(r_combo.loc[common_v]))
        L.append(f"- corr(v16, TSM-50/50) = **{corr:.3f}** (n={len(common_v)})")
        if abs(corr) < 0.2:
            L.append(f"- 独立性✅ 低相关 (|corr|<0.2), 适合做 diversifier")
        elif abs(corr) < 0.5:
            L.append(f"- 独立性⚠️ 中等相关, 组合 benefit 有限")
        else:
            L.append(f"- 独立性❌ 高相关, 并无 diversification 价值")
    except Exception as e:
        L.append(f"- (v16 相关性计算失败: {e})")
    L.append("")

    L.append("## 7. 诚实结论")
    L.append("")
    pass_stand = a_h["all_pass"] or a_z["all_pass"]
    pass_combo = a_c["all_pass"]
    combo_dsr = dsr_c >= 0.95
    if pass_combo and combo_dsr:
        L.append("**TSM 50/50 独立过门 + DSR 显著**: 可作为 diversifier 入池。")
        L.append("下一步 (预注册): v16 + TSM 等权 / 风险平价组合, 测双策略 admission + DSR。")
    elif pass_stand and not pass_combo:
        L.append("**单边 TSM 过门但组合未过**: 等权配不合理, 暂不合并。")
    elif pass_combo and not combo_dsr:
        L.append("**TSM admission 过, DSR 不过**: 与 v16 同病, 需要累积 OOS 样本。")
    else:
        L.append("**TSM 独立 admission 未过**: 单纯 TSM 也不够, 但可能仍有低相关 diversification 价值。")
        L.append("若 corr(v16, TSM) 低, 仍值得合并做相关性分散; 否则此方向失败。")
    L.append("")

    L.append("## 8. 严禁 (红线)")
    L.append("")
    L.append("- 不扫 lookback ∈ {60, 126, 252} 找最佳")
    L.append("- 不换信号 (MA crossover / breakout / time-series reversal)")
    L.append("- 不加 vol-targeting / regime filter 等 overlay")
    L.append("- 若失败, 记录结果, 不 ad-hoc 修改参数")
    L.append("")

    out_md.write_text("\n".join(L), encoding="utf-8")
    print(f"\n✓ 写出 {out_md}")
    print("\n=== 速览 ===")
    print(f"  TSM HS300: ann={m_h['ann_return']:.2%} sr={m_h['sharpe']:.3f} mdd={m_h['mdd']:.2%}  adm={a_h['all_pass']}")
    print(f"  TSM ZZ500: ann={m_z['ann_return']:.2%} sr={m_z['sharpe']:.3f} mdd={m_z['mdd']:.2%}  adm={a_z['all_pass']}")
    print(f"  TSM 50/50: ann={m_c['ann_return']:.2%} sr={m_c['sharpe']:.3f} mdd={m_c['mdd']:.2%}  adm={a_c['all_pass']}")
    print(f"  DSR combo: {dsr_c:.4f}")


if __name__ == "__main__":
    main()
