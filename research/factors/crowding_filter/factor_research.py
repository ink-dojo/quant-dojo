"""
拥挤度复合因子 (Composite Crowding) v2 — 修复版

变更 (2026-04-21 code review 后):
  1. F3 warmup 修复后 att_60d 2022-01 已有真实信号（非零占比 301 股）
  2. F6 改用 ann_date 生效后 inst_ratio ICIR 从 0.04 → 0.30，合并意义增强
  3. nb/inst 不再 fillna(0)：保留 NaN → 仅对"机构有覆盖 universe"内的股票做 z-score，
     避免小盘股因数据缺失被填 0 后获得"低拥挤"虚假加分 (size 结构性偏差)
  4. 新增 size-neutralize 变体：-composite 对 log(circ_mv) 回归取残差，验证
     "拥挤度反转" vs "小盘 + 短期反转" 两种解释

四维合成:
    1. attention_60d — 特定对象调研 60 日累计
    2. turnover_20d  — 近 20 日平均换手率
    3. northbound_ratio — 北向持股占流通股比例 (HSC 标的)
    4. inst_ratio    — 机构型前十大合计 hold_ratio (ann_date 生效)

测试方向：**反向** -composite 作为正向 alpha。

运行：python research/factors/crowding_filter/factor_research.py
"""
import sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))

import warnings
import numpy as np
import pandas as pd

warnings.filterwarnings("ignore")

from utils.factor_analysis import compute_ic_series, ic_summary, quintile_backtest

RAW = ROOT / "data" / "raw" / "tushare"
OUT = ROOT / "research" / "factors" / "crowding_filter"
IS_START = "2022-01-01"   # attention 数据从 2021-08 起，真实预热后从 2022 起
IS_END = "2025-12-31"
FWD = 20


def load_turnover_panel(price_index: pd.DatetimeIndex, codes: list) -> pd.DataFrame:
    """从 daily_basic/ 构造 turnover_rate_f 20 日 MA 宽表。"""
    files = list((RAW / "daily_basic").glob("*.parquet"))
    print(f"[数据] daily_basic 文件 {len(files)} 个，按需加载...")
    # 仅加载 codes 覆盖的股票（提速）
    code_set = set(codes)
    series = {}
    for f in files:
        stem = f.stem  # 000001_daily_basic
        code = stem.split("_")[0]
        if code not in code_set:
            continue
        try:
            df = pd.read_parquet(f, columns=["trade_date", "turnover_rate_f"])
            df["trade_date"] = pd.to_datetime(df["trade_date"].astype(str), errors="coerce")
            s = df.dropna(subset=["trade_date"]).set_index("trade_date")["turnover_rate_f"].sort_index()
            s = s[~s.index.duplicated(keep="last")]
            s = s.loc["2021-01-01":IS_END]
            series[code] = s
        except Exception as e:
            continue
    print(f"[数据] 已加载 turnover {len(series)} 股")
    wide = pd.DataFrame(series).reindex(price_index)
    turnover_ma20 = wide.rolling(20, min_periods=10).mean().shift(1)
    return turnover_ma20


def load_northbound_panel(price_index: pd.DatetimeIndex, codes: list) -> pd.DataFrame:
    """北向持股 ratio 日频 ffill。非 HSC 标的保留 NaN（不填 0），避免 z-score 结构偏差。"""
    files = list((RAW / "northbound").glob("*.parquet"))
    if not files:
        return pd.DataFrame(index=price_index, columns=codes, data=np.nan)
    code_set = set(codes)
    series = {}
    for f in files:
        try:
            df = pd.read_parquet(f)
            if "ts_code" not in df.columns or "ratio" not in df.columns:
                continue
            code = df["ts_code"].iloc[0][:6]
            if code not in code_set:
                continue
            df["trade_date"] = pd.to_datetime(df["trade_date"].astype(str), errors="coerce")
            df = df.dropna(subset=["trade_date"]).sort_values("trade_date")
            df = df.drop_duplicates(subset=["trade_date"], keep="last")
            s = df.set_index("trade_date")["ratio"]
            series[code] = s
        except Exception:
            continue
    print(f"[数据] 已加载 northbound {len(series)} 股 (非标的保留 NaN)")
    wide = pd.DataFrame(series)
    # 先按股票 ffill（每股自己的历史）再 reindex + shift(1)
    wide = wide.sort_index().ffill()
    wide = wide.reindex(price_index).shift(1)
    return wide


def load_circ_mv_panel(price_index: pd.DatetimeIndex, codes: list) -> pd.DataFrame:
    """加载 daily_basic.circ_mv (万元) → 日频宽表，用于 size-neutralize。"""
    files = list((RAW / "daily_basic").glob("*.parquet"))
    code_set = set(codes)
    series = {}
    for f in files:
        if f.stem not in code_set:
            continue
        try:
            df = pd.read_parquet(f, columns=["trade_date", "circ_mv"])
            df["trade_date"] = pd.to_datetime(df["trade_date"].astype(str), errors="coerce")
            s = (df.dropna(subset=["trade_date"])
                   .set_index("trade_date")["circ_mv"].sort_index())
            s = s[~s.index.duplicated(keep="last")]
            series[f.stem] = s.loc["2021-01-01":IS_END]
        except Exception:
            continue
    wide = pd.DataFrame(series).reindex(price_index).shift(1)  # shift(1) 防未来函数
    print(f"[数据] 已加载 circ_mv {len(series)} 股")
    return wide


def size_neutralize(factor: pd.DataFrame, circ_mv: pd.DataFrame) -> pd.DataFrame:
    """对数市值截面回归取残差。逐日 OLS：factor = α + β·log(circ_mv) + ε，返回 ε。"""
    log_mv = np.log(circ_mv.replace(0, np.nan))
    # 向量化实现：对每日截面 (factor[T], log_mv[T]) 做简单 OLS
    # residual_i = factor_i - (mean(factor) + β·(log_mv_i - mean(log_mv)))
    # 其中 β = cov(factor, log_mv) / var(log_mv)
    x = log_mv
    y = factor
    x_mean = x.mean(axis=1)
    y_mean = y.mean(axis=1)
    x_c = x.sub(x_mean, axis=0)
    y_c = y.sub(y_mean, axis=0)
    var_x = (x_c ** 2).sum(axis=1)
    cov_xy = (x_c * y_c).sum(axis=1)
    beta = cov_xy / var_x.replace(0, np.nan)
    pred = y_mean + beta * x_c.T.T  # 广播：每日 β × 每股 (log_mv - mean)
    # 修正：beta 是 Series(index=date), x_c 是 (date×code) 需广播
    pred = x_c.mul(beta, axis=0).add(y_mean, axis=0)
    return y - pred


def z_score_cross(wide: pd.DataFrame) -> pd.DataFrame:
    """截面 z-score + clip ±3。NaN 保留（不参与 mean/std 计算也不填 0）。"""
    mu = wide.mean(axis=1, skipna=True)
    sd = wide.std(axis=1, skipna=True).replace(0, np.nan)
    z = wide.sub(mu, axis=0).div(sd, axis=0).clip(-3, 3)
    return z


def composite_mean_skipna(z_list: list) -> pd.DataFrame:
    """把若干 z-score 宽表按股票做可用维度均值 (skip NaN)，用于"有几维用几维"合成。"""
    # 堆叠为 3D: (factor, date, stock)，然后在 factor 维度求 nanmean
    stacked = pd.concat(z_list, keys=range(len(z_list)))
    composite = stacked.groupby(level=1).mean()  # 相当于 mean across factors, skip NaN
    return composite.sort_index()


def main():
    print("="*70)
    print("拥挤度复合因子研究")
    print("="*70)
    OUT.mkdir(parents=True, exist_ok=True)

    # 价格
    price = pd.read_parquet(ROOT / "data/processed/price_wide_close_2014-01-01_2025-12-31_qfq_5477stocks.parquet")
    price.index = pd.to_datetime(price.index)
    price = price.loc[IS_START:IS_END]
    codes = list(price.columns)

    # 各维度（nb/inst 不再 fillna(0)，保留 NaN 语义）
    print("\n[维度 1] attention_60d ...")
    att = pd.read_parquet(ROOT / "research/factors/survey_attention/att_60d.parquet")
    # att 0 表示"无调研事件"是真实值，保留 fillna(0)
    att = att.reindex(index=price.index, columns=codes).fillna(0)

    print("[维度 2] turnover_20d MA ...")
    turnover = load_turnover_panel(price.index, codes)
    turnover = turnover.reindex(index=price.index, columns=codes)

    print("[维度 3] northbound ratio (非 HSC 标的保留 NaN) ...")
    nb = load_northbound_panel(price.index, codes)
    nb = nb.reindex(index=price.index, columns=codes)

    print("[维度 4] inst_ratio (ann_date 生效，无机构覆盖保留 NaN) ...")
    inst = pd.read_parquet(ROOT / "research/factors/institutional_holdings/inst_ratio_daily.parquet")
    inst = inst.reindex(index=price.index, columns=codes)

    print("[维度 5] circ_mv (用于 size-neutralize 诊断) ...")
    circ_mv = load_circ_mv_panel(price.index, codes)

    # 合成：z-score 每维（NaN 不参与 mean/std）→ 可用维度均值
    z_att = z_score_cross(att)
    z_turn = z_score_cross(turnover)
    z_nb = z_score_cross(nb)
    z_inst = z_score_cross(inst)

    composite = composite_mean_skipna([z_att, z_turn, z_nb, z_inst])
    inv_composite = -composite

    # size-neutralize 变体：剔除小盘贡献
    inv_composite_sn = size_neutralize(inv_composite, circ_mv)

    # fwd return
    ret_fwd = price.shift(-FWD) / price - 1

    print("\n[A] -composite_crowding 20 日前瞻 IC:")
    ic_a = compute_ic_series(inv_composite, ret_fwd, method="spearman", min_stocks=500)
    stats_a = ic_summary(ic_a, name="-composite_crowding_fwd20", fwd_days=FWD)

    print("\n[A2] -composite_crowding_SIZE_NEUTRAL 20 日前瞻 IC:")
    ic_a2 = compute_ic_series(inv_composite_sn, ret_fwd, method="spearman", min_stocks=500)
    stats_a2 = ic_summary(ic_a2, name="-composite_SN_fwd20", fwd_days=FWD)

    print("\n[B] 单维度 IC 拆解（均为 -z 形式）:")
    dim_stats = {}
    for label, z in [("-att", -z_att), ("-turn", -z_turn), ("-nb", -z_nb), ("-inst", -z_inst)]:
        ic = compute_ic_series(z, ret_fwd, method="spearman", min_stocks=500)
        s = ic_summary(ic, name=label, fwd_days=FWD, verbose=False)
        dim_stats[label] = s
        print(f"    {label:<10} IC {s['IC_mean']:+.4f}  ICIR {s['ICIR']:+.3f}  HAC t {s['t_stat_hac']:+.2f}")

    print("\n[C] 分层回测 -composite 5 组:")
    grp, ls = quintile_backtest(inv_composite, ret_fwd, n_groups=5, long_short="Qn_minus_Q1")
    ann = ls.mean() * 252 / FWD
    vol = ls.std() * np.sqrt(252 / FWD)
    sr = ann / vol if vol > 0 else np.nan
    print(f"    原始 -composite 多空年化 {ann:.2%}  夏普 {sr:.2f}")
    grp_ann = grp.mean() * 252 / FWD
    print(grp_ann)

    print("\n[C2] 分层回测 size-neutral 变体 5 组:")
    grp_sn, ls_sn = quintile_backtest(inv_composite_sn, ret_fwd, n_groups=5, long_short="Qn_minus_Q1")
    ann_sn = ls_sn.mean() * 252 / FWD
    vol_sn = ls_sn.std() * np.sqrt(252 / FWD)
    sr_sn = ann_sn / vol_sn if vol_sn > 0 else np.nan
    print(f"    size-neutral 多空年化 {ann_sn:.2%}  夏普 {sr_sn:.2f}")
    grp_ann_sn = grp_sn.mean() * 252 / FWD
    print(grp_ann_sn)

    # 保存
    composite.to_parquet(OUT / "composite_crowding.parquet")
    (-inv_composite_sn).to_parquet(OUT / "composite_crowding_sn.parquet")  # 保存未反向的 SN 值

    # 报告
    with open(OUT / "report.md", "w") as f:
        f.write("# 拥挤度复合因子研究报告 v2 (修复版)\n\n")
        f.write(f"**日期**：2026-04-21 修订  **窗口**：{IS_START}~{IS_END}  **前瞻**：20 日\n\n")
        f.write("## 修复摘要\n\n")
        f.write("- F3 survey_attention 增加预热期 (2021-08 ~ 2022-01)，att_60d 在 IS 起点已有效\n")
        f.write("- F6 institutional_holdings 改用 ann_date 生效对齐（原 end_date+60d 过滞后），inst_ratio ICIR 0.04 → 0.30\n")
        f.write("- nb/inst 不再 `fillna(0)`：缺失值保留 NaN，仅在各自 universe 内 z-score；composite 用可用维度均值\n")
        f.write("- 新增 size-neutralize 变体：`-composite` 对 `log(circ_mv)` 回归取残差，验证真实 alpha\n\n")
        f.write("## A. -composite_crowding（原始）\n\n")
        f.write(f"- IC {stats_a['IC_mean']:+.4f}  ICIR {stats_a['ICIR']:+.3f}  HAC t {stats_a['t_stat_hac']:+.2f}  IC>0 {stats_a['pct_pos']:.1%}\n")
        f.write(f"- 多空年化 {ann:+.2%}  夏普 {sr:.2f}\n\n")
        f.write("## A2. -composite_crowding (size-neutralized)\n\n")
        f.write(f"- IC {stats_a2['IC_mean']:+.4f}  ICIR {stats_a2['ICIR']:+.3f}  HAC t {stats_a2['t_stat_hac']:+.2f}  IC>0 {stats_a2['pct_pos']:.1%}\n")
        f.write(f"- 多空年化 {ann_sn:+.2%}  夏普 {sr_sn:.2f}\n\n")
        f.write("## B. 单维度拆解（-z）\n\n")
        f.write("| 维度 | IC | ICIR | HAC t |\n| --- | ---: | ---: | ---: |\n")
        for label, s in dim_stats.items():
            f.write(f"| {label} | {s['IC_mean']:+.4f} | {s['ICIR']:+.3f} | {s['t_stat_hac']:+.2f} |\n")
        f.write("\n## C. 分层年化（原始）\n\n")
        f.write(grp_ann.to_frame("ann").round(4).to_markdown())
        f.write("\n\n## C2. 分层年化（size-neutral）\n\n")
        f.write(grp_ann_sn.to_frame("ann").round(4).to_markdown())
        f.write("\n\n## 结论\n\n")
        if abs(stats_a2["ICIR"]) > 0.3 and abs(stats_a2["t_stat_hac"]) > 2:
            f.write(f"- ✅ size-neutral 版本 ICIR {stats_a2['ICIR']:.3f} / HAC t {stats_a2['t_stat_hac']:.2f} 仍通过双门槛\n")
            f.write(f"- 去掉 size 后 IC 衰减 {(stats_a['IC_mean']-stats_a2['IC_mean'])/max(abs(stats_a['IC_mean']),1e-9):.0%}，"
                    f"但仍显著 → 拥挤度是真 alpha，不是单纯 size/reversal 伪装\n")
        else:
            f.write(f"- ⚠️ size-neutral 后 ICIR {stats_a2['ICIR']:.3f} / HAC t {stats_a2['t_stat_hac']:.2f}\n")
            f.write("- 原 -composite 的 alpha 很大程度来自 size 暴露，**需审视后续 v17 的因子归属**\n")
    print(f"\n[保存] -> {OUT}")
    print("="*70, "\nDONE")


if __name__ == "__main__":
    main()
