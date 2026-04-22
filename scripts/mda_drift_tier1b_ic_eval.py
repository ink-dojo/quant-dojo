"""MD&A drift factor — Tier 1b IC 评估 + kill 判读.

锁定参数 (不 tuning):
    forward_return: 发布日+1 交易日 起 20 个交易日累积, 扣 0.3% 双边成本
    IC 方法: Spearman rank IC, 按 **发布月** cross-section
    sub-period: pre-2023 (2019-2022 发布) vs post-2023 (2023-2026 发布)
    decile: 10 分位, 看 top-bottom 差值

kill criteria (来自 pre-reg, scripts/mda_drift_tier1_eval.py):
    IC 均值 < 0.015  → STOP, 空间 C MD&A 方向封死
    0.015 ~ 0.025     → 进 Tier 2 (LLM hedging 密度做增量)
    > 0.025          → Tier 2/3 暂缓, 推 paper-trade

输入:
    data/processed/mda_drift_scores.parquet    (fiscal_year × symbol)
    data/processed/mda_drift_manifest.parquet  (symbol, fiscal_year, publish_date, ...)
    utils.local_data_loader.load_adj_price_wide (价格)

输出:
    journal/mda_drift_tier1_result_<YYYYMMDD>.md
    (含: panel stats, IC summary, sub-period split, decile backtest, 决策)

用法:
    python scripts/mda_drift_tier1b_ic_eval.py
    python scripts/mda_drift_tier1b_ic_eval.py --min-stocks-per-month 20
"""
from __future__ import annotations

import argparse
import sys
import warnings
from datetime import date
from pathlib import Path

warnings.filterwarnings("ignore")
sys.path.insert(0, str(Path(__file__).parent.parent))

import numpy as np
import pandas as pd

from research.factors.mda_drift.factor import DEFAULT_DRIFT_PATH, DEFAULT_MANIFEST_PATH
from utils.factor_analysis import _newey_west_se
from utils.local_data_loader import load_adj_price_wide

KILL_IC_LOWER = 0.015
TIER2_IC_UPPER = 0.025
FWD_DAYS = 20
COST_BPS = 30  # 0.30% 双边


def _next_trading_day(prices_idx: pd.DatetimeIndex, after: pd.Timestamp) -> pd.Timestamp | None:
    """返回 after 之后的第一个交易日 (prices_idx 里最早大于 after 的日期)."""
    mask = prices_idx > after
    if not mask.any():
        return None
    return prices_idx[mask][0]


def build_panel(
    factor_wide: pd.DataFrame,
    manifest: pd.DataFrame,
    prices: pd.DataFrame,
) -> pd.DataFrame:
    """构建 (symbol, publish_date, as_of_date, drift, fwd_ret) 长面板.

    as_of_date = 发布日后第一个交易日 (无未来函数).
    fwd_ret = adj_price[as_of_date + 20交易日] / adj_price[as_of_date] - 1 - cost.
    """
    long = factor_wide.stack().rename("drift").reset_index()
    long.columns = ["fiscal_year", "symbol", "drift"]
    manifest_slim = manifest[["symbol", "fiscal_year", "publish_date"]].drop_duplicates(
        subset=["symbol", "fiscal_year"]
    )
    long = long.merge(manifest_slim, on=["symbol", "fiscal_year"], how="left")
    long["publish_date"] = pd.to_datetime(long["publish_date"])
    long = long.dropna(subset=["publish_date", "drift"])

    rows: list[dict] = []
    cost = COST_BPS / 1e4
    for _, r in long.iterrows():
        sym = r["symbol"]
        if sym not in prices.columns:
            continue
        as_of = _next_trading_day(prices.index, r["publish_date"])
        if as_of is None:
            continue
        # fwd 开始 (as_of) 和 结束 (as_of + 20 trading days)
        loc = prices.index.get_loc(as_of)
        end_loc = loc + FWD_DAYS
        if end_loc >= len(prices.index):
            continue
        p0 = prices.iloc[loc].get(sym)
        p1 = prices.iloc[end_loc].get(sym)
        if pd.isna(p0) or pd.isna(p1) or p0 <= 0:
            continue
        fwd_ret = (p1 / p0) - 1 - cost
        rows.append({
            "symbol": sym,
            "fiscal_year": int(r["fiscal_year"]),
            "publish_date": r["publish_date"],
            "as_of_date": as_of,
            "drift": float(r["drift"]),
            "fwd_ret_20d": fwd_ret,
        })
    return pd.DataFrame(rows)


def monthly_ic(panel: pd.DataFrame, min_stocks: int = 20) -> pd.Series:
    """按 publish 月 cross-section, Spearman rank IC."""
    panel = panel.copy()
    panel["ym"] = panel["publish_date"].dt.to_period("M")
    ic_rows = []
    for ym, grp in panel.groupby("ym"):
        if len(grp) < min_stocks:
            continue
        ic = grp[["drift", "fwd_ret_20d"]].corr(method="spearman").iloc[0, 1]
        ic_rows.append((ym.to_timestamp(), ic, len(grp)))
    s = pd.Series(
        [r[1] for r in ic_rows],
        index=pd.DatetimeIndex([r[0] for r in ic_rows], name="month"),
        name="ic",
    )
    # 用 attrs 记 n
    s.attrs["n_per_month"] = pd.Series([r[2] for r in ic_rows], index=s.index)
    return s


def ic_summary(ic: pd.Series, label: str) -> dict:
    if len(ic) == 0:
        return {"label": label, "n_months": 0, "ic_mean": np.nan}
    x = ic.dropna().values
    mean = float(np.mean(x))
    std = float(np.std(x, ddof=1)) if len(x) > 1 else float("nan")
    icir = mean / std if std and not np.isnan(std) else float("nan")
    # Newey-West, lag = 1 (月频, 短自相关)
    nw_se = _newey_west_se(x, lag=1)
    nw_t = mean / nw_se if nw_se and not np.isnan(nw_se) else float("nan")
    return {
        "label": label,
        "n_months": int(len(x)),
        "ic_mean": mean,
        "ic_std": std,
        "icir": icir,
        "nw_t": nw_t,
        "pct_gt_0": float((x > 0).mean()),
    }


def decile_spread(panel: pd.DataFrame, n_deciles: int = 10) -> dict:
    """按 drift 10 分位, top-bottom forward return 差 (越负越支持"高漂移→跑输")."""
    panel = panel.dropna(subset=["drift", "fwd_ret_20d"]).copy()
    if len(panel) < n_deciles * 2:
        return {"spread": float("nan"), "top_ret": float("nan"), "bot_ret": float("nan"), "n": len(panel)}
    panel["decile"] = pd.qcut(panel["drift"], n_deciles, labels=False, duplicates="drop")
    top_ret = float(panel.loc[panel["decile"] == n_deciles - 1, "fwd_ret_20d"].mean())
    bot_ret = float(panel.loc[panel["decile"] == 0, "fwd_ret_20d"].mean())
    return {"spread": top_ret - bot_ret, "top_ret": top_ret, "bot_ret": bot_ret, "n": len(panel)}


def decide(ic_full_mean: float) -> str:
    if np.isnan(ic_full_mean):
        return "❓ 无法判读 (IC 缺失)"
    a = abs(ic_full_mean)
    if a < KILL_IC_LOWER:
        return f"🔴 **KILL**. |IC|={a:.4f} < {KILL_IC_LOWER}. 空间 C MD&A 方向封死, 转 Tier 3 跨文档."
    if a < TIER2_IC_UPPER:
        return f"🟡 **Tier 2 进 (LLM hedging 增量)**. |IC|={a:.4f} ∈ [{KILL_IC_LOWER}, {TIER2_IC_UPPER})."
    return f"🟢 **推 paper-trade**. |IC|={a:.4f} > {TIER2_IC_UPPER}. Tier 2/3 暂缓."


def write_report(
    panel: pd.DataFrame,
    ic_full: pd.Series,
    summary_full: dict,
    summary_pre: dict,
    summary_post: dict,
    dec: dict,
    out_path: Path,
) -> None:
    reg_shift = "N/A"
    if summary_post["n_months"] >= 3 and summary_pre["n_months"] >= 3:
        if abs(summary_pre["ic_mean"]) > 1e-9:
            decay = 1 - abs(summary_post["ic_mean"]) / abs(summary_pre["ic_mean"])
            reg_shift = f"{decay:+.1%} (post vs pre, 衰减 > 50% → regime shift)"
    decision = decide(summary_full["ic_mean"])
    lines = [
        f"# MD&A drift Tier 1b — IC 评估结果 ({date.today():%Y-%m-%d})",
        "",
        "战略锚: `research/space_c_llm_alpha/alpha_theory_space_c_research_20260421.md`",
        "Pre-reg: `scripts/mda_drift_tier1_eval.py` + Issue #28",
        "",
        "## Panel 统计",
        "",
        f"- 观测数 (symbol × publish_date): **{len(panel)}**",
        f"- 覆盖 fiscal_year: {panel['fiscal_year'].min()}..{panel['fiscal_year'].max()}",
        f"- 覆盖 symbol: {panel['symbol'].nunique()}",
        f"- drift 分布: mean={panel['drift'].mean():.3f}, std={panel['drift'].std():.3f}, "
        f"q25={panel['drift'].quantile(.25):.3f}, q75={panel['drift'].quantile(.75):.3f}",
        f"- forward_20d_return 分布: mean={panel['fwd_ret_20d'].mean():.4f}, "
        f"std={panel['fwd_ret_20d'].std():.4f}",
        "",
        "## IC 总表 (Spearman rank, 月度 cross-section)",
        "",
        "| 区间 | N 月 | IC 均值 | IC std | ICIR | NW t | IC>0 占比 |",
        "|---|---:|---:|---:|---:|---:|---:|",
    ]
    for s in (summary_full, summary_pre, summary_post):
        lines.append(
            f"| {s['label']} | {s['n_months']} | {s.get('ic_mean', float('nan')):.4f} | "
            f"{s.get('ic_std', float('nan')):.4f} | {s.get('icir', float('nan')):.3f} | "
            f"{s.get('nw_t', float('nan')):.2f} | {s.get('pct_gt_0', float('nan')):.1%} |"
        )
    lines += [
        "",
        f"Regime shift (pre vs post 2023): {reg_shift}",
        "",
        "## Decile spread (10 分位, top - bottom forward return)",
        "",
        f"- N={dec['n']}, top 10%={dec['top_ret']:.4f}, bot 10%={dec['bot_ret']:.4f}",
        f"- spread = **{dec['spread']:.4f}** (正值 → 高 drift 跑赢, 与 Lazy Prices 预测相反)",
        "",
        "## 决策",
        "",
        decision,
        "",
        "## 备注",
        "",
        "- 本次 IC 计算只看 Spearman, 未做行业中性化. 如 |IC| ∈ [0.01, 0.025] 再加 sector-neutral 版本重测.",
        f"- 成本假设: 单边 {COST_BPS/2:.1f} bp, 双边 {COST_BPS} bp.",
        f"- forward window: {FWD_DAYS} 交易日; publish → as_of 用 T+1.",
    ]
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text("\n".join(lines), encoding="utf-8")
    print(f"[saved] {out_path}")


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--drift-path", default=str(DEFAULT_DRIFT_PATH))
    p.add_argument("--manifest-path", default=str(DEFAULT_MANIFEST_PATH))
    p.add_argument("--min-stocks-per-month", type=int, default=20)
    p.add_argument("--out-journal", default=None)
    args = p.parse_args()

    factor_wide = pd.read_parquet(args.drift_path)
    manifest = pd.read_parquet(args.manifest_path)
    print(f"[load] factor_wide shape={factor_wide.shape}  manifest rows={len(manifest)}")

    symbols = list(factor_wide.columns)
    start = str(manifest["publish_date"].min().date() - pd.Timedelta(days=5))[:10]
    # 要覆盖 publish_date + 20 交易日, 取到 2026 年底
    end = "2026-12-31"
    prices = load_adj_price_wide(symbols=symbols, start=start, end=end)
    print(f"[load] prices shape={prices.shape}  dates={prices.index.min().date()}..{prices.index.max().date()}")

    panel = build_panel(factor_wide, manifest, prices)
    print(f"[panel] n={len(panel)} symbols={panel['symbol'].nunique()}")
    if len(panel) == 0:
        print("[ABORT] 空 panel, 无法评估")
        return 1

    ic_full = monthly_ic(panel, min_stocks=args.min_stocks_per_month)
    ic_pre = monthly_ic(
        panel[panel["publish_date"] < "2023-01-01"],
        min_stocks=args.min_stocks_per_month,
    )
    ic_post = monthly_ic(
        panel[panel["publish_date"] >= "2023-01-01"],
        min_stocks=args.min_stocks_per_month,
    )
    summary_full = ic_summary(ic_full, "全样本 (2019-2026 发布)")
    summary_pre = ic_summary(ic_pre, "pre-2023 (2019-2022 发布)")
    summary_post = ic_summary(ic_post, "post-2023 (2023-2026 发布)")
    dec = decile_spread(panel)

    print("\n=== IC 全样本 ===")
    print(summary_full)
    print("=== 决策 ===")
    print(decide(summary_full["ic_mean"]))

    out = Path(args.out_journal or f"journal/mda_drift_tier1_result_{date.today():%Y%m%d}.md")
    write_report(panel, ic_full, summary_full, summary_pre, summary_post, dec, out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
