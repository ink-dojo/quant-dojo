"""
英雄因子深度分析 — Phase B.prep

为 portfolio 站点的 8 个英雄因子批量生成：
  - IC 时序（日频 + 月度聚合用于前端展示）
  - IC 汇总统计（mean / std / ICIR / t / pos%）
  - 因子衰减（ic_by_lag 1-20 天 + 半衰期 + 推荐调仓频率）
  - 分层回测（5 分位组合 + 多空累积收益 + 多空年化/夏普）

输入：
  - 本地 price / pb / volume / turnover 数据（utils/local_data_loader）
  - 行业分类（utils/fundamental_loader）
  - 因子定义（utils/alpha_factors）

输出：
  journal/hero_factor_stats_YYYYMMDD.json
    → 被 portfolio/scripts/export_data.py 消费写到
      portfolio/public/data/factors/hero_detail.json

运行：
  python scripts/deep_analysis_hero_factors.py

窗口与 v9 评估对齐：WARMUP 2018-01 / 分析区间 2020-01 ~ 2024-12。
universe 过滤沿用 v9：必须有 >500 个有效价格点。
"""
from __future__ import annotations

import json
import sys
import time
import warnings
from datetime import datetime
from pathlib import Path

warnings.filterwarnings("ignore")

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import numpy as np
import pandas as pd

from utils.alpha_factors import (
    amihud_illiquidity,
    bp_factor,
    cgo,
    enhanced_momentum,
    low_vol_20d,
    momentum_6m_skip1m,
    roe_factor,
    team_coin,
)
from utils.factor_analysis import (
    compute_ic_series,
    factor_decay_analysis,
    neutralize_factor_by_industry,
    quintile_backtest,
)
from utils.fundamental_loader import get_industry_classification
from utils.local_data_loader import get_all_symbols, load_price_wide

# ── 常量 ─────────────────────────────────────────────────────────
WARMUP_START = "2018-01-01"
ANALYSIS_START = "2020-01-01"
ANALYSIS_END = "2024-12-31"
FWD_DAYS = 20      # 未来 20 日收益（与 v7/v9 口径一致）
MIN_VALID_POINTS = 500

HERO_FACTORS = [
    "enhanced_momentum",
    "bp_factor",
    "low_vol_20d",
    "roe_factor",
    "team_coin",
    "cgo",
    "amihud_illiquidity",
    "momentum_6m_skip1m",
]

# 每个因子的方向标签（True = 正向，越大越好；False = 反转，越小越好）
# 这只影响分层展示的多空方向选择（Q5-Q1 or Q1-Q5），不影响 IC 数值。
FACTOR_DIRECTION_POSITIVE = {
    "enhanced_momentum": True,
    "bp_factor": True,
    "low_vol_20d": True,     # 因子定义里已取负，越大越好
    "roe_factor": True,
    "team_coin": True,
    "cgo": True,              # 因子定义里已取负
    "amihud_illiquidity": True,
    "momentum_6m_skip1m": True,
}

OUT_JSON = ROOT / "journal" / f"hero_factor_stats_{datetime.utcnow():%Y%m%d}.json"


# ══════════════════════════════════════════════════════════════════
# 数据加载
# ══════════════════════════════════════════════════════════════════

def load_all_data():
    print(f"[1/5] 加载数据 ({WARMUP_START} → {ANALYSIS_END})...")
    t0 = time.time()
    symbols = get_all_symbols()

    price = load_price_wide(symbols, WARMUP_START, ANALYSIS_END, field="close")
    valid = price.columns[price.notna().sum() > MIN_VALID_POINTS]
    price = price[valid]

    pb = load_price_wide(list(valid), WARMUP_START, ANALYSIS_END, field="pb")
    pb = pb.reindex(index=price.index, columns=valid)

    pe = load_price_wide(list(valid), WARMUP_START, ANALYSIS_END, field="pe")
    pe = pe.reindex(index=price.index, columns=valid)

    volume = load_price_wide(list(valid), WARMUP_START, ANALYSIS_END, field="volume")
    volume = volume.reindex(index=price.index, columns=valid)

    turnover = load_price_wide(list(valid), WARMUP_START, ANALYSIS_END, field="turn")
    turnover = turnover.reindex(index=price.index, columns=valid)

    print(f"  股票 {len(valid)} | 交易日 {len(price)} | 用时 {time.time()-t0:.1f}s")
    return price, pb, pe, volume, turnover


def build_factors(price, pb, pe, volume, turnover):
    print("\n[2/5] 构建 8 个英雄因子...")
    factors = {
        "enhanced_momentum":  enhanced_momentum(price, window=60),
        "bp_factor":          bp_factor(pb).reindex_like(price),
        "low_vol_20d":        low_vol_20d(price),
        "roe_factor":         roe_factor(pe, pb).reindex_like(price),
        "team_coin":          team_coin(price),
        "cgo":                cgo(price, turnover=turnover),
        "amihud_illiquidity": amihud_illiquidity(price, volume),
        "momentum_6m_skip1m": momentum_6m_skip1m(price),
    }
    # 行业中性化（与 v9 对齐）
    symbols = list(price.columns)
    industry = get_industry_classification(symbols=symbols, use_cache=True)
    print(f"  行业覆盖: {len(industry)} / {len(symbols)}")
    neutral = {}
    for name, fac in factors.items():
        if fac is None or fac.empty:
            print(f"  [skip] {name}: empty factor")
            continue
        try:
            neutral[name] = neutralize_factor_by_industry(
                fac, industry, show_progress=False
            )
            print(f"  [ok]   {name}")
        except Exception as e:
            print(f"  [warn] {name}: neutralize failed ({e}) — fallback to raw")
            neutral[name] = fac
    return neutral


# ══════════════════════════════════════════════════════════════════
# 分析
# ══════════════════════════════════════════════════════════════════

def slice_analysis_window(fac: pd.DataFrame, ret: pd.DataFrame):
    """裁剪到分析窗口（丢掉 warmup 期）。"""
    f = fac.loc[ANALYSIS_START:ANALYSIS_END]
    r = ret.loc[ANALYSIS_START:ANALYSIS_END]
    return f, r


def _ic_summary(ic_series: pd.Series) -> dict:
    s = ic_series.dropna()
    if len(s) == 0:
        return {"ic_mean": None, "ic_std": None, "icir": None, "t_stat": None, "pct_pos": None, "n": 0}
    mean = float(s.mean())
    std = float(s.std())
    icir = mean / std if std > 0 else None
    t_stat = mean / (std / np.sqrt(len(s))) if std > 0 else None
    return {
        "ic_mean": mean,
        "ic_std": std,
        "icir": icir,
        "t_stat": t_stat,
        "pct_pos": float((s > 0).mean()),
        "n": int(len(s)),
    }


def _monthly_ic(ic_series: pd.Series) -> list[dict]:
    """把日度 IC 聚合到月末，前端少画点但不丢故事。"""
    s = ic_series.dropna()
    if len(s) == 0:
        return []
    mm = s.resample("ME").mean()
    return [
        {"date": d.strftime("%Y-%m-%d"), "ic": float(v)}
        for d, v in mm.items()
        if not np.isnan(v)
    ]


def _quintile_monthly(group_ret: pd.DataFrame) -> list[dict]:
    """分层组合累积收益（复利）每月采样一次，减少前端数据量。"""
    cum = (1 + group_ret.fillna(0)).cumprod() - 1
    cum_monthly = cum.resample("ME").last()
    out = []
    for d, row in cum_monthly.iterrows():
        rec = {"date": d.strftime("%Y-%m-%d")}
        for col in group_ret.columns:
            val = row.get(col)
            rec[col] = float(val) if val is not None and not np.isnan(val) else None
        out.append(rec)
    return out


def _ls_stats(ls_ret: pd.Series) -> dict:
    s = ls_ret.dropna()
    if len(s) == 0:
        return {}
    ann = float(s.mean() * 252)
    vol = float(s.std() * np.sqrt(252))
    sr = (ann / vol) if vol > 0 else None
    cum = (1 + s).cumprod()
    mdd = float((cum / cum.cummax() - 1).min())
    return {
        "ann_return": ann,
        "ann_vol": vol,
        "sharpe": sr,
        "max_drawdown": mdd,
        "total_return": float(cum.iloc[-1] - 1),
        "n_days": int(len(s)),
    }


def analyze_one(name: str, fac: pd.DataFrame, ret: pd.DataFrame) -> dict:
    fac_w, ret_w = slice_analysis_window(fac, ret)

    # IC：对 t+1 ~ t+FWD_DAYS 累积收益做相关
    fwd_ret = (1 + ret_w).rolling(FWD_DAYS).apply(np.prod, raw=True).shift(-FWD_DAYS) - 1
    ic_s = compute_ic_series(fac_w, fwd_ret, method="spearman")

    # 分层回测
    positive = FACTOR_DIRECTION_POSITIVE.get(name, True)
    ls_direction = "Qn_minus_Q1" if positive else "Q1_minus_Qn"
    group_ret, ls_ret = quintile_backtest(fac_w, ret_w, n_groups=5, long_short=ls_direction)

    # 衰减（用日度收益）
    decay = factor_decay_analysis(fac_w, ret_w, max_lag=20, smooth=True)
    # 衰减结果需要 JSON 可序列化
    decay_json = {
        "ic_by_lag": [
            {"lag": lag, "ic": (None if pd.isna(v) else float(v))}
            for lag, v in decay["ic_by_lag"].items()
        ],
        "half_life_days": (None if decay["half_life_days"] is None else float(decay["half_life_days"])),
        "decay_rate": (None if decay["decay_rate"] is None else float(decay["decay_rate"])),
        "ic_0": (None if decay["ic_0"] is None else float(decay["ic_0"])),
        "fit_quality": (None if decay["fit_quality"] is None else float(decay["fit_quality"])),
        "recommended_rebalance_freq": decay["recommended_rebalance_freq"],
    }

    return {
        "name": name,
        "direction": "positive" if positive else "reversal",
        "fwd_days": FWD_DAYS,
        "ic": {
            "summary": _ic_summary(ic_s),
            "monthly": _monthly_ic(ic_s),
        },
        "decay": decay_json,
        "quintile": {
            "direction": ls_direction,
            "cum_monthly": _quintile_monthly(group_ret),
            "ls_stats": _ls_stats(ls_ret),
        },
    }


# ══════════════════════════════════════════════════════════════════
# 主流程
# ══════════════════════════════════════════════════════════════════

def main():
    t_main = time.time()
    price, pb, pe, volume, turnover = load_all_data()
    neutral = build_factors(price, pb, pe, volume, turnover)

    print(f"\n[3/5] 计算日度收益（shift 前向 {FWD_DAYS}d）...")
    ret = price.pct_change()
    # 裁剪到 analysis window 由 analyze_one 内部处理

    print(f"\n[4/5] 对 {len(neutral)} 个因子跑 IC / 分层 / 衰减...")
    results = {}
    for name in HERO_FACTORS:
        if name not in neutral:
            print(f"  [skip] {name} — factor not built")
            continue
        print(f"  → {name} ...", end="", flush=True)
        t0 = time.time()
        try:
            results[name] = analyze_one(name, neutral[name], ret)
            print(f" done ({time.time()-t0:.1f}s)")
        except Exception as e:
            print(f" FAILED: {e}")
            results[name] = {"name": name, "error": str(e)}

    print("\n[5/5] 写结果...")
    OUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "generated_at": datetime.utcnow().strftime("%Y-%m-%d"),
        "window": {
            "warmup_start": WARMUP_START,
            "analysis_start": ANALYSIS_START,
            "analysis_end": ANALYSIS_END,
        },
        "fwd_days": FWD_DAYS,
        "universe_size": int(price.shape[1]),
        "trading_days": int(price.loc[ANALYSIS_START:ANALYSIS_END].shape[0]),
        "factors": results,
    }
    OUT_JSON.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"  wrote {OUT_JSON.relative_to(ROOT)}")
    print(f"\n总用时: {time.time()-t_main:.1f}s")


if __name__ == "__main__":
    main()
