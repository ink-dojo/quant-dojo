"""
run_factor_evaluation.py — 通用因子评估 CLI

Usage:
    python scripts/run_factor_evaluation.py \
        research.factors.<name>.factor \
        --compute-fn compute_<name> \
        [--start 2023-10-01] [--end 2025-12-31] \
        [--neutralize size,industry] \
        [--sign auto] \
        [--fwd 20] [--sample-cadence 5]

输出:
    logs/<module>_eval_YYYYMMDD.json       (机器读)
    journal/<module>_eval_YYYYMMDD.md      (人读)

能做的:
    - IC (Spearman) + ICIR + HAC t 分段: FULL / IS / OOS 2025
    - 分层回测 (5 分位 Q1_minus_Q5 or Qn_minus_Q1 按 sign)
    - size 中性化 (用 daily_basic circ_mv)
    - industry 中性化 (用 SW1 前 2 位)
    - sign 自动判断 (根据 FULL IC 符号)

不做的:
    - cost-aware backtest (差异化策略各自规则不同, 专用脚本处理)
    - walk-forward (样本短时各因子 CV 策略不同, 专用脚本)
    - DSR / bootstrap CI (paper-trade 前门槛, 专用)
"""
from __future__ import annotations

import argparse
import importlib
import json
import sys
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from pipeline.rx_factor_monitor import compute_factor_ic_summary  # noqa: E402
from utils.factor_analysis import industry_neutralize_fast, quintile_backtest  # noqa: E402

PRICE_PATH = ROOT / "data" / "processed" / "price_wide_close_2014-01-01_2025-12-31_qfq_5477stocks.parquet"


def _to_ts(sym: str) -> str:
    if sym.startswith(("60", "68")):
        return f"{sym}.SH"
    if sym.startswith(("00", "30")):
        return f"{sym}.SZ"
    return f"{sym}.SZ"


def _zscore_row(df: pd.DataFrame) -> pd.DataFrame:
    mu = df.mean(axis=1)
    sd = df.std(axis=1).replace(0.0, np.nan)
    return df.sub(mu, axis=0).div(sd, axis=0)


def size_neutralize(factor: pd.DataFrame, circ_mv: pd.DataFrame, min_stocks: int = 200) -> pd.DataFrame:
    """按日 log(circ_mv) OLS 残差."""
    common_dates = factor.index.intersection(circ_mv.index)
    common_syms = factor.columns.intersection(circ_mv.columns)
    f = factor.loc[common_dates, common_syms]
    x = np.log(circ_mv.loc[common_dates, common_syms].clip(lower=1.0))
    mask = f.notna() & x.notna()
    f_m = f.where(mask); x_m = x.where(mask)
    f_mean = f_m.mean(axis=1, skipna=True)
    x_mean = x_m.mean(axis=1, skipna=True)
    fx_cov = ((f_m.sub(f_mean, axis=0)) * (x_m.sub(x_mean, axis=0))).sum(axis=1, skipna=True)
    xx_var = ((x_m.sub(x_mean, axis=0)) ** 2).sum(axis=1, skipna=True)
    beta = fx_cov / xx_var.replace(0.0, np.nan)
    alpha = f_mean - beta * x_mean
    predicted = x_m.mul(beta, axis=0).add(alpha, axis=0)
    residual = f_m - predicted
    daily_count = residual.notna().sum(axis=1)
    return residual.where(daily_count >= min_stocks, np.nan)


def load_circ_mv(start: str, end: str) -> pd.DataFrame:
    db_dir = ROOT / "data" / "raw" / "tushare" / "daily_basic"
    s_i = int(start.replace("-", "")); e_i = int(end.replace("-", ""))
    frames = []
    for f in sorted(db_dir.glob("*.parquet")):
        try:
            df = pd.read_parquet(f, columns=["ts_code", "trade_date", "circ_mv"])
        except Exception:
            continue
        if df.empty:
            continue
        df = df[df["trade_date"].astype(int).between(s_i, e_i)]
        if df.empty:
            continue
        frames.append(df)
    raw = pd.concat(frames, ignore_index=True)
    raw["trade_date"] = pd.to_datetime(raw["trade_date"].astype(str).str.strip(), format="%Y%m%d")
    return raw.pivot_table(index="trade_date", columns="ts_code", values="circ_mv", aggfunc="last")


def load_sw1_industry() -> pd.Series:
    ind_path = ROOT / "data" / "raw" / "fundamentals" / "industry_sw.parquet"
    df = pd.read_parquet(ind_path)

    def _to_ts_local(sym: str) -> str:
        s = str(sym).zfill(6)
        if s.startswith(("60", "68")):
            return f"{s}.SH"
        if s.startswith(("00", "30", "001", "002", "003")):
            return f"{s}.SZ"
        if s[:1] in ("4", "8"):
            return f"{s}.BJ"
        return f"{s}.SZ"

    df["ts_code"] = df["symbol"].apply(_to_ts_local)
    df["sw1"] = df["industry_code"].astype(str).str[:2]
    ser = df.set_index("ts_code")["sw1"]
    return ser[~ser.index.duplicated(keep="first")]


def fwd_returns(price: pd.DataFrame, fwd_days: int) -> pd.DataFrame:
    fwd = price.shift(-fwd_days) / price - 1.0
    fwd.columns = [_to_ts(c) for c in fwd.columns]
    return fwd


def _fmt(v, pat="{:+.4f}"):
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return "n/a"
    return pat.format(v)


def run(
    module: str, compute_fn: str, start: str, end: str,
    neutralize: str, sign: str, fwd: int, sample_cadence: int,
    min_stocks: int = 30,
) -> dict:
    # 1. 加载 factor
    mod = importlib.import_module(module)
    fn = getattr(mod, compute_fn)
    print(f"▶ {module}.{compute_fn}({start!r}, {end!r}) ...")
    factor_raw = fn(start, end)
    if factor_raw is None or factor_raw.empty:
        raise RuntimeError("factor returned empty")
    print(f"  raw factor: {factor_raw.shape}, 日均有效股: {factor_raw.notna().sum(axis=1).mean():.0f}")

    # 2. 中性化
    neut_steps = [s.strip() for s in neutralize.split(",") if s.strip() and s.strip() != "none"]
    factor = factor_raw.copy()
    applied = []
    if "size" in neut_steps:
        circ_mv = load_circ_mv(start, end)
        factor = size_neutralize(factor, circ_mv)
        applied.append("size")
        print(f"  size neutral: {factor.shape}, 有效股 {factor.notna().sum(axis=1).mean():.0f}")
    if "industry" in neut_steps:
        ind = load_sw1_industry()
        factor = industry_neutralize_fast(factor, ind)
        applied.append("industry")
        print(f"  industry neutral: {factor.shape}")

    # 3. price + fwd returns
    price = pd.read_parquet(PRICE_PATH)
    price_sub = price.loc[start:end]
    fwd_ret = fwd_returns(price_sub, fwd)

    # 4. IC 分段 (shift 1 防未来)
    factor_shift = factor.shift(1)
    segments = [
        ("FULL", start, end),
    ]
    if start < "2024-12-31" < end:
        segments.append(("IS (pre-2025)", start, "2024-12-31"))
    if "2025" in end or end > "2025-01-01":
        segments.append(("OOS 2025", "2025-01-01", min(end, "2025-12-31")))

    seg_results = {}
    for lab, s, e in segments:
        fac_seg = factor_shift.loc[s:e]
        if fac_seg.empty:
            continue
        summ = compute_factor_ic_summary(
            fac_seg, price_sub.loc[s:e], s, e,
            fwd_days=fwd, sample_cadence=sample_cadence,
            min_stocks=min_stocks,
        )
        seg_results[lab] = summ

    # 5. 判 sign
    full_ic = seg_results.get("FULL", {}).get("ic_mean", 0.0)
    if sign == "auto":
        sign_str = "negative" if full_ic is not None and full_ic < 0 else "positive"
    else:
        sign_str = sign

    # 6. 分层回测 (5 分位, 按 sign 决定 long-short 方向)
    ls_mode = "Q1_minus_Qn" if sign_str == "negative" else "Qn_minus_Q1"
    sample_dates = factor_shift.index[::sample_cadence]
    fac_qc = factor_shift.reindex(sample_dates)
    ret_qc = fwd_ret.reindex(sample_dates)
    try:
        group_ret, ls_ret = quintile_backtest(fac_qc, ret_qc, n_groups=5, long_short=ls_mode)
    except Exception as e:
        group_ret = pd.DataFrame(); ls_ret = pd.Series(dtype=float)
        print(f"  quintile_backtest failed: {e}")

    q_means = group_ret.mean(skipna=True).to_dict() if not group_ret.empty else {}
    ls_mean = float(ls_ret.mean(skipna=True)) if len(ls_ret) else None
    ls_std = float(ls_ret.std(ddof=1)) if len(ls_ret) > 1 else None
    ls_unit_sharpe = (ls_mean / ls_std) if ls_mean is not None and ls_std and ls_std > 0 else None

    result = {
        "module": module,
        "compute_fn": compute_fn,
        "start": start, "end": end,
        "fwd_days": fwd, "sample_cadence_days": sample_cadence,
        "neutralize_applied": applied,
        "sign_used": sign_str, "ls_mode": ls_mode,
        "segments": seg_results,
        "quintile_means_per_period": {k: (float(v) if pd.notna(v) else None) for k, v in q_means.items()},
        "ls_mean_per_period": ls_mean, "ls_std_per_period": ls_std,
        "ls_unit_sharpe": ls_unit_sharpe,
        "full_IC": full_ic,
    }
    return result


def render_markdown(result: dict) -> str:
    lines = [
        f"# 因子评估: {result['module']}.{result['compute_fn']}",
        "",
        f"> 生成时间: {datetime.now().isoformat(timespec='seconds')}",
        f"> 期间: {result['start']} ~ {result['end']}",
        f"> Fwd: {result['fwd_days']}d, 采样每 {result['sample_cadence_days']}d",
        f"> 中性化: {', '.join(result['neutralize_applied']) or 'none'}",
        f"> Sign: {result['sign_used']} (LS mode: {result['ls_mode']})",
        "",
        "## 分段 IC",
        "",
        "| 分段 | n | IC mean | ICIR | HAC t | Status |",
        "|---|---:|---:|---:|---:|---|",
    ]
    for lab, s in result["segments"].items():
        lines.append(
            f"| {lab} | {s.get('n_obs', 0)} | "
            f"{_fmt(s.get('ic_mean'), '{:+.4f}')} | "
            f"{_fmt(s.get('icir'), '{:+.3f}')} | "
            f"{_fmt(s.get('t_hac'), '{:+.2f}')} | "
            f"{s.get('status', '-')} |"
        )
    lines.append("")
    lines.append("## 分层回测 (5 分位, 每期均值)")
    lines.append("")
    if result["quintile_means_per_period"]:
        lines.append("| 分位 | 均值 |")
        lines.append("|---|---:|")
        for q, v in sorted(result["quintile_means_per_period"].items()):
            if v is None or (isinstance(v, float) and pd.isna(v)):
                lines.append(f"| {q} | n/a |")
            else:
                lines.append(f"| {q} | {v*100:+.4f}% |")
        lines.append("")
        ls_mean = result["ls_mean_per_period"]
        ls_sr = result["ls_unit_sharpe"]
        ls_mean_str = f"{ls_mean*100:+.4f}%" if ls_mean is not None and not (isinstance(ls_mean, float) and pd.isna(ls_mean)) else "n/a"
        lines.append(f"LS ({result['ls_mode']}) 每期: {ls_mean_str}, unit Sharpe: {_fmt(ls_sr, '{:+.3f}')}")
        lines.append("")
    lines.append("## 原始 JSON")
    lines.append("")
    lines.append(f"完整数字见 `logs/<module>_eval_YYYYMMDD.json`.")
    return "\n".join(lines)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("module", help="Python module path, e.g. research.factors.XYZ.factor")
    ap.add_argument("--compute-fn", default="compute_factor", help="function name in module")
    ap.add_argument("--start", default="2023-10-01")
    ap.add_argument("--end", default="2025-12-31")
    ap.add_argument("--neutralize", default="size,industry", help="none / size / industry / size,industry")
    ap.add_argument("--sign", default="auto", choices=["auto", "negative", "positive"])
    ap.add_argument("--fwd", type=int, default=20, help="forward return horizon (days)")
    ap.add_argument("--sample-cadence", type=int, default=5)
    ap.add_argument("--min-stocks", type=int, default=30,
                    help="每日截面最少股票数 (事件 factor 可降到 3-5)")
    args = ap.parse_args()

    result = run(
        args.module, args.compute_fn, args.start, args.end,
        args.neutralize, args.sign, args.fwd, args.sample_cadence,
        min_stocks=args.min_stocks,
    )

    # 打印分段汇总
    print("\n=== 分段 IC ===")
    for lab, s in result["segments"].items():
        print(
            f"  [{s.get('status', '-'):<18}] {lab:<20} "
            f"n={s.get('n_obs', 0):<4} "
            f"IC={_fmt(s.get('ic_mean'), '{:+.4f}')} "
            f"ICIR={_fmt(s.get('icir'), '{:+.3f}')} "
            f"HAC t={_fmt(s.get('t_hac'), '{:+.2f}')}"
        )
    print(f"\nSign: {result['sign_used']} (LS mode: {result['ls_mode']})")
    if result["quintile_means_per_period"]:
        qs = result["quintile_means_per_period"]
        parts = []
        for k, v in sorted(qs.items()):
            if v is None or (isinstance(v, float) and pd.isna(v)):
                parts.append(f"{k}=n/a")
            else:
                parts.append(f"{k}={v*100:+.3f}%")
        print("分层均值:  " + "  ".join(parts))
        print(f"LS unit Sharpe: {_fmt(result['ls_unit_sharpe'], '{:+.3f}')}")

    # 保存
    stamp = datetime.now().strftime("%Y%m%d")
    short_mod = result["module"].split(".")[-2] if "." in result["module"] else result["module"]
    json_path = ROOT / "logs" / f"{short_mod}_eval_{stamp}.json"
    json_path.write_text(json.dumps(result, indent=2, ensure_ascii=False, default=str))
    md_path = ROOT / "journal" / f"{short_mod}_eval_{stamp}.md"
    md_path.write_text(render_markdown(result))
    print(f"\n保存: {json_path}")
    print(f"保存: {md_path}")


if __name__ == "__main__":
    main()
