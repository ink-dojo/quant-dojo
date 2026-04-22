"""
RIAD Walk-Forward / Purged CV

样本仅 545 日 (2023-10 ~ 2025-12), 不够做标准 walk-forward.
改用 3 折 blocked time-series CV + 10 日 purge gap:

    Fold 1: Train=前 40%, OOS=中间 20% (gap=10d purge)
    Fold 2: Train=前 60%, OOS=中间 20% (gap=10d purge)
    Fold 3: Train=前 80%, OOS=末尾 20% (gap=10d purge)

目的: 验证 alpha 不是单一窗口 lucky, 每个 fold 的 OOS Sharpe 稳定性.

"Train" 期我们不实际 fit 参数 (RIAD 参数已锁), 仅用它检验 OOS 一致性.
这本质是 **3 个独立 OOS 窗口的 Sharpe 分布**.
"""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[3]
RIAD_PATH = ROOT / "research" / "factors" / "retail_inst_divergence" / "riad_ls_daily_returns.parquet"
FILTERED_PATH = ROOT / "logs" / "riad_tradable_universe_returns.parquet"


def summarize(series: pd.Series, label: str) -> dict:
    s = series.dropna()
    if s.empty:
        return {}
    ann = s.mean() * 252
    vol = s.std(ddof=1) * np.sqrt(252)
    sr = ann / vol if vol > 0 else np.nan
    cum_s = (1 + s).cumprod()
    mdd = float((cum_s / cum_s.cummax() - 1).min())
    return {
        "label": label, "n": len(s),
        "ann": float(ann), "vol": float(vol),
        "sharpe": float(sr) if not np.isnan(sr) else None,
        "mdd": mdd,
    }


def blocked_cv(series: pd.Series, n_folds: int = 3, purge_days: int = 10) -> list[dict]:
    """
    将 series 切分为 n_folds 等长 OOS 块, train 是每块之前部分.
    Fold k 的 OOS = 前 40% + k×20% ~ 前 40% + (k+1)×20% (0-indexed).
    """
    s = series.dropna().sort_index()
    n = len(s)
    train_frac0 = 0.4
    oos_frac = 0.2

    results = []
    for k in range(n_folds):
        train_end_idx = int(n * (train_frac0 + k * oos_frac))
        oos_start_idx = train_end_idx + purge_days
        oos_end_idx = min(int(n * (train_frac0 + (k + 1) * oos_frac)), n)
        if oos_end_idx <= oos_start_idx + 20:
            continue
        train = s.iloc[:train_end_idx]
        oos = s.iloc[oos_start_idx:oos_end_idx]
        tr = summarize(train, f"Fold{k+1} TRAIN ({train.index[0].date()}~{train.index[-1].date()})")
        oo = summarize(oos, f"Fold{k+1} OOS ({oos.index[0].date()}~{oos.index[-1].date()})")
        results.append({"fold": k + 1, "train": tr, "oos": oo})
    return results


def main() -> None:
    # 双版本: baseline unconstrained + filtered tradable
    baseline = pd.read_parquet(RIAD_PATH)["net_ls"]
    filtered = pd.read_parquet(FILTERED_PATH)["net_ls"]

    for name, ser in [("baseline (unconstrained)", baseline), ("filtered (tradable+margin)", filtered)]:
        print(f"\n======== {name} 3-fold blocked CV ========")
        folds = blocked_cv(ser, n_folds=3, purge_days=10)
        header = f"{'Fold':<6} {'Type':<30} {'n':>5} {'Ann%':>8} {'Vol%':>7} {'Sharpe':>7} {'MDD%':>8}"
        print(header)
        print("-" * len(header))
        oos_sharpes = []
        for fd in folds:
            for t in ["train", "oos"]:
                r = fd[t]
                if not r:
                    continue
                sr = r["sharpe"] if r["sharpe"] is not None else float("nan")
                if t == "oos":
                    oos_sharpes.append(sr)
                print(
                    f"{fd['fold']:<6} {t.upper():<30} "
                    f"{r['n']:>5} "
                    f"{r['ann']*100:>+7.2f} "
                    f"{r['vol']*100:>6.2f} "
                    f"{sr:>+7.2f} "
                    f"{r['mdd']*100:>+7.2f}"
                )
        if oos_sharpes:
            arr = np.array(oos_sharpes)
            print(f"OOS Sharpe 3 折: mean={arr.mean():+.3f} min={arr.min():+.3f} max={arr.max():+.3f}")

    stamp = datetime.now().strftime("%Y%m%d")
    out_json = ROOT / "logs" / f"riad_walk_forward_{stamp}.json"
    with open(out_json, "w") as f:
        json.dump(
            {
                "generated_at": datetime.now().isoformat(timespec="seconds"),
                "method": "3-fold blocked time-series CV with 10d purge gap",
                "baseline_folds": blocked_cv(baseline),
                "filtered_folds": blocked_cv(filtered),
            },
            f, indent=2, ensure_ascii=False,
        )
    print(f"\n保存: {out_json}")


if __name__ == "__main__":
    main()
