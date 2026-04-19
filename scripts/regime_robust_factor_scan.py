"""
Regime-Robust 因子扫描

目标：找出在熊市（HS300 < MA120）和牛市均保持正向 IC 的因子候选。
评判标准：
  - 熊市 IC > 0（方向不反转）
  - 熊市 IC t 统计量 > 1.5（有统计意义）
  - 熊市 IC / 牛市 IC > 0.3（熊市不比牛市差太多）
  - IC_bear - IC_bull 尽量小（越小越 regime-neutral）

输出：按"熊市 IC"降序排列的因子排名表，保存到 journal/
"""

import sys
import warnings
import numpy as np
import pandas as pd
from pathlib import Path
from scipy.stats import spearmanr

warnings.filterwarnings("ignore")
sys.path.insert(0, str(Path(__file__).parent.parent))

# ─────────────────────────────────────────────
# 1. 加载数据
# ─────────────────────────────────────────────
ROOT = Path(__file__).parent.parent

print("加载价格数据...")
close = pd.read_parquet(ROOT / "data/processed/price_wide_close_2014-01-01_2025-12-31_qfq_5477stocks.parquet")
close.index = pd.to_datetime(close.index)
close = close.sort_index()

hs300 = pd.read_parquet(ROOT / "data/raw/indices/sh000300.parquet")
hs300.index = pd.to_datetime(hs300.index)
hs300_close = hs300["close"].reindex(close.index).ffill()

# 成交量（如有）
try:
    vol_path = ROOT / "data/processed/volume_wide_2014-01-01_2025-12-31_5477stocks.parquet"
    volume = pd.read_parquet(vol_path)
    volume.index = pd.to_datetime(volume.index)
    HAS_VOL = True
    print(f"  成交量数据: {volume.shape}")
except Exception:
    HAS_VOL = False
    volume = None
    print("  ⚠️ 无成交量数据，跳过相关因子")

# ─────────────────────────────────────────────
# 2. Regime 定义（HS300 < MA120, shift(1)）
# ─────────────────────────────────────────────
EVAL_START = "2022-01-04"
EVAL_END   = "2025-12-31"
ma120 = hs300_close.rolling(120).mean()
bear_mask = (hs300_close < ma120).shift(1).reindex(close.index).fillna(False)
bull_mask = ~bear_mask

eval_dates = close.loc[EVAL_START:EVAL_END].index
bear_dates = eval_dates[bear_mask.reindex(eval_dates).fillna(False)]
bull_dates = eval_dates[bull_mask.reindex(eval_dates).fillna(False)]

print(f"\n评估区间: {EVAL_START} ~ {EVAL_END} ({len(eval_dates)} 天)")
print(f"  熊市天数: {len(bear_dates)} ({len(bear_dates)/len(eval_dates):.1%})")
print(f"  牛市天数: {len(bull_dates)} ({len(bull_dates)/len(eval_dates):.1%})")

# ─────────────────────────────────────────────
# 3. 前向收益（20 日）
# ─────────────────────────────────────────────
FWD_DAYS = 20
fwd_ret = close.pct_change(FWD_DAYS).shift(-FWD_DAYS)
fwd_ret = fwd_ret.reindex(eval_dates)

# 截尾防极端值
fwd_ret = fwd_ret.clip(
    fwd_ret.quantile(0.01, axis=1),
    fwd_ret.quantile(0.99, axis=1),
    axis=0
)

# ─────────────────────────────────────────────
# 4. IC 计算函数
# ─────────────────────────────────────────────

def cross_ic(factor_row: pd.Series, ret_row: pd.Series) -> float:
    """单截面 Spearman IC"""
    common = factor_row.dropna().index.intersection(ret_row.dropna().index)
    if len(common) < 30:
        return np.nan
    return spearmanr(factor_row[common], ret_row[common])[0]


def regime_ic_summary(factor_wide: pd.DataFrame, name: str) -> dict:
    """计算熊市/牛市 IC 汇总统计"""
    factor_eval = factor_wide.reindex(eval_dates)

    ic_all, ic_bear, ic_bull = [], [], []

    for date in eval_dates:
        if date not in factor_eval.index or date not in fwd_ret.index:
            continue
        ic = cross_ic(factor_eval.loc[date], fwd_ret.loc[date])
        if np.isnan(ic):
            continue
        ic_all.append(ic)
        if date in bear_dates:
            ic_bear.append(ic)
        else:
            ic_bull.append(ic)

    def _t(arr):
        if len(arr) < 5:
            return 0.0
        return np.mean(arr) / (np.std(arr) / np.sqrt(len(arr)))

    ic_bear_arr = np.array(ic_bear)
    ic_bull_arr = np.array(ic_bull)
    ic_all_arr  = np.array(ic_all)

    ic_bear_mean = np.mean(ic_bear_arr) if len(ic_bear_arr) > 0 else np.nan
    ic_bull_mean = np.mean(ic_bull_arr) if len(ic_bull_arr) > 0 else np.nan

    # 熊市/牛市 IC ratio（越接近 1 越 regime-neutral）
    ratio = ic_bear_mean / ic_bull_mean if ic_bull_mean != 0 else np.nan

    return {
        "factor":       name,
        "ic_all":       np.mean(ic_all_arr),
        "icir_all":     _t(ic_all_arr),
        "ic_bear":      ic_bear_mean,
        "t_bear":       _t(ic_bear_arr),
        "ic_bull":      ic_bull_mean,
        "t_bull":       _t(ic_bull_arr),
        "n_bear":       len(ic_bear_arr),
        "n_bull":       len(ic_bull_arr),
        "bear_bull_ratio": ratio,   # ic_bear / ic_bull
        "bear_bull_gap":   ic_bear_mean - ic_bull_mean if not np.isnan(ic_bear_mean) else np.nan,
    }


# ─────────────────────────────────────────────
# 5. 逐因子计算
# ─────────────────────────────────────────────

# 导入因子计算函数（绕过 utils/__init__.py 的 Python 3.8 兼容问题）
import importlib.util
spec = importlib.util.spec_from_file_location("alpha_factors", ROOT / "utils/alpha_factors.py")
af = importlib.util.module_from_spec(spec)
spec.loader.exec_module(af)

results = []
SKIP = []

def _run(name: str, factor_fn, *args, direction: int = 1):
    """运行因子计算，捕获异常，记录结果"""
    print(f"  计算 {name}...", end=" ", flush=True)
    try:
        f = factor_fn(*args)
        if direction == -1:
            f = -f
        r = regime_ic_summary(f, name)
        results.append(r)
        print(f"熊市IC={r['ic_bear']:.4f} t={r['t_bear']:.2f} | 牛市IC={r['ic_bull']:.4f}")
    except Exception as e:
        SKIP.append(name)
        print(f"跳过 ({e})")

print("\n计算纯价格因子...")

# 反转类
_run("reversal_1m",       af.reversal_1m,       close)
_run("reversal_5d",       af.reversal_5d,       close)
_run("reversal_skip1m",   af.reversal_skip1m,   close)

# 波动/风险类
_run("low_vol_20d",       af.low_vol_20d,       close)
_run("beta_factor",       af.beta_factor,       close, direction=-1)   # 低beta好
_run("idio_vol",          af.idiosyncratic_volatility, close, direction=-1)
_run("stock_maxdd_60d",   af.stock_max_drawdown_60d, close)             # 取负后高=跌少
_run("ret_skewness_20d",  af.return_skewness_20d, close)
_run("ret_autocorr_1d",   af.ret_autocorr_1d,   close)
_run("vol_asymmetry",     af.vol_asymmetry,     close)
_run("vol_regime",        af.vol_regime,        close, direction=-1)

# 动量类
_run("mom_6m_skip1m",     af.momentum_6m_skip1m, close)
_run("mom_3m_skip1m",     af.momentum_3m_skip1m, close)
_run("enhanced_mom_60",   af.enhanced_momentum,  close, 60)
_run("quality_mom",       af.quality_momentum,   close, 60)
_run("ma_ratio_120",      af.ma_ratio_momentum,  close, 120)
_run("price_mom_quality", af.price_momentum_quality, close, 20)
_run("high_52w",          af.high_52w_ratio,     close, direction=-1)   # 离52周高点远 = 低

# 量价关系类
_run("shadow_lower",      af.shadow_lower,       close, close)          # 下影线
_run("shadow_upper",      af.shadow_upper,       close, close, direction=-1)
_run("bollinger_pct",     af.bollinger_pct,      close, direction=-1)
_run("team_coin",         af.team_coin,          close)
_run("price_vol_div",     af.price_volume_divergence, close)
_run("apm_overnight",     af.apm_overnight,      close, close)          # 隔夜收益
_run("overnight_ret",     af.overnight_return,   close, close)
_run("sharpe_20d",        af.sharpe_20d,         close)
_run("win_rate_60d",      af.win_rate_60d,       close)
_run("w_reversal",        af.w_reversal,         close)
_run("cgo",               af.cgo,                close)
_run("return_zscore_20d", af.return_zscore_20d,  close)
_run("str_salience",      af.str_salience,       close.pct_change(),
     close.pct_change().mean(axis=1))

if HAS_VOL:
    print("\n计算量价因子...")
    _run("amihud_illiq",     af.amihud_illiquidity,   close, volume, direction=-1)
    _run("turnover_rev",     af.turnover_rev,          close)
    _run("turnover_accel",   af.turnover_acceleration, volume)
    _run("rel_turnover",     af.relative_turnover,     volume)
    _run("vol_surge",        af.volume_surge,          close, volume)
    _run("up_dn_vol",        af.up_down_volume_ratio,  close, volume)
    _run("vol_concentration",af.volume_concentration,  volume, direction=-1)
    _run("amplitude_hidden", af.amplitude_hidden,      close, close)

print("\n计算 CGO / chip 类因子...")
_run("chip_arc",           af.chip_arc,           close, close if not HAS_VOL else volume)
_run("chip_vrc",           af.chip_vrc,           close, close if not HAS_VOL else volume)

# ─────────────────────────────────────────────
# 6. 汇总输出
# ─────────────────────────────────────────────

df = pd.DataFrame(results)

# 判定 regime-robust：熊市 IC 正向且显著
df["regime_robust"] = (
    (df["ic_bear"] > 0.01) &
    (df["t_bear"].abs() > 1.5) &
    (df["bear_bull_ratio"] > 0.2)   # 熊市 IC 至少是牛市的 20%（同号）
)

df = df.sort_values("ic_bear", ascending=False).reset_index(drop=True)

print("\n" + "=" * 90)
print("Regime-Robust 因子扫描结果（按熊市 IC 降序）")
print("=" * 90)

display_cols = ["factor", "ic_all", "icir_all", "ic_bear", "t_bear",
                "ic_bull", "t_bull", "bear_bull_ratio", "regime_robust"]
print(df[display_cols].to_string(index=False, float_format=lambda x: f"{x:.4f}"))

print("\n\n✅ Regime-Robust 候选因子（ic_bear>0.01, t_bear>1.5, ratio>0.2）：")
robust = df[df["regime_robust"]].copy()
if len(robust) > 0:
    print(robust[display_cols].to_string(index=False, float_format=lambda x: f"{x:.4f}"))
else:
    print("  暂无明确通过所有标准的因子")

print("\n❗ 跳过的因子（数据不足或错误）：")
print(", ".join(SKIP) if SKIP else "  无")

# 保存
out_path = ROOT / "journal" / "regime_robust_factor_scan_20260419.md"
with open(out_path, "w") as f:
    f.write("# Regime-Robust 因子扫描报告 — 20260419\n\n")
    f.write(f"> 评估区间: {EVAL_START} ~ {EVAL_END}  \n")
    f.write(f"> 熊市定义: HS300 < MA120 (shift 1)  \n")
    f.write(f"> 前向收益: {FWD_DAYS} 日  \n")
    f.write(f"> 宇宙: {close.shape[1]} 只股票  \n\n")
    f.write("## 熊市/牛市分段 IC 全表\n\n")
    # 手写 markdown 表格，避免依赖 tabulate
    def _to_md(df_):
        cols = df_.columns.tolist()
        header = "| " + " | ".join(cols) + " |"
        sep = "| " + " | ".join(["---"] * len(cols)) + " |"
        rows = []
        for _, row in df_.iterrows():
            vals = []
            for c in cols:
                v = row[c]
                if isinstance(v, float):
                    vals.append(f"{v:.4f}")
                else:
                    vals.append(str(v))
            rows.append("| " + " | ".join(vals) + " |")
        return "\n".join([header, sep] + rows)

    f.write(_to_md(df[display_cols]))
    f.write("\n\n## Regime-Robust 候选（ic_bear>0.01, |t_bear|>1.5, ratio>0.2）\n\n")
    if len(robust) > 0:
        f.write(_to_md(robust[display_cols]))
    else:
        f.write("暂无通过全部标准的因子。\n")
    f.write("\n\n## 结论与下一步\n\n")
    f.write("见上方表格。regime-robust 候选因子是 v16 熊市 alpha 不足问题的最直接解药。\n")
    f.write("加入前需预注册权重方案，DSR n_trials 同步追加。\n")

print(f"\n报告已保存: {out_path}")
