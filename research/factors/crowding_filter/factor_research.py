"""
拥挤度复合因子 (Composite Crowding) — 研究

背景：
    中信金工 2023-2024 拥挤度模型、F3 机构调研反向发现均指向同一方向。
    高拥挤度（机构抱团 + 高换手 + 高北向 + 高调研）→ 未来跑输。

构造（五维合成）:
    1. attention_60d — 特定对象调研 60 日累计 (F3 已算)
    2. turnover_20d — 近 20 日平均换手率 (daily_basic.turnover_rate_f)
    3. northbound_ratio — 北向持股占流通股比例 (季度 ffill)
    4. inst_ratio — 机构型前十大合计 hold_ratio (F6 已算)
    5. funds_pct (placeholder，需基金持仓数据) — 暂缺，用 0

截面 z-score 后等权相加 → composite_crowding
测试方向：**反向** 作为 alpha，即 -composite → 高值为低拥挤 → 预期正 IC。

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
    """北向持股 ratio 季度数据 → 日频 ffill。"""
    files = list((RAW / "northbound").glob("*.parquet"))
    if not files:
        return pd.DataFrame(index=price_index, columns=codes, data=np.nan)
    code_set = set(codes)
    # 每个文件是一只股票
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
    print(f"[数据] 已加载 northbound {len(series)} 股")
    wide = pd.DataFrame(series)
    wide = wide.reindex(price_index, method="ffill").shift(1)
    return wide


def z_score_cross(wide: pd.DataFrame) -> pd.DataFrame:
    """截面 z-score + clip ±3。"""
    mu = wide.mean(axis=1)
    sd = wide.std(axis=1).replace(0, np.nan)
    z = wide.sub(mu, axis=0).div(sd, axis=0).clip(-3, 3)
    return z


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

    # 各维度
    print("\n[维度 1] attention_60d ...")
    att = pd.read_parquet(ROOT / "research/factors/survey_attention/att_60d.parquet")
    att = att.reindex(index=price.index, columns=codes).fillna(0)

    print("[维度 2] turnover_20d MA ...")
    turnover = load_turnover_panel(price.index, codes)
    turnover = turnover.reindex(index=price.index, columns=codes)

    print("[维度 3] northbound ratio ...")
    nb = load_northbound_panel(price.index, codes)
    nb = nb.reindex(index=price.index, columns=codes).fillna(0)

    print("[维度 4] inst_ratio ...")
    inst = pd.read_parquet(ROOT / "research/factors/institutional_holdings/inst_ratio_daily.parquet")
    inst = inst.reindex(index=price.index, columns=codes).fillna(0)

    # 合成：z-score 每维，等权相加
    z_att = z_score_cross(att)
    z_turn = z_score_cross(turnover)
    z_nb = z_score_cross(nb)
    z_inst = z_score_cross(inst)

    composite = (z_att + z_turn + z_nb + z_inst) / 4.0
    # 反向：-composite 作为正向 alpha
    inv_composite = -composite

    # fwd return
    ret_fwd = price.shift(-FWD) / price - 1

    print("\n[A] -composite_crowding → 20日前瞻 IC:")
    ic_a = compute_ic_series(inv_composite, ret_fwd, method="spearman", min_stocks=500)
    stats_a = ic_summary(ic_a, name="-composite_crowding_fwd20", fwd_days=FWD)

    print("\n[B] 单维度 IC 拆解（均为 -z 形式）:")
    for label, z in [("-att", -z_att), ("-turn", -z_turn), ("-nb", -z_nb), ("-inst", -z_inst)]:
        ic = compute_ic_series(z, ret_fwd, method="spearman", min_stocks=500)
        s = ic_summary(ic, name=label, fwd_days=FWD, verbose=False)
        print(f"    {label:<10} IC {s['IC_mean']:+.4f}  ICIR {s['ICIR']:+.3f}  HAC t {s['t_stat_hac']:+.2f}")

    print("\n[C] 分层回测 -composite 5 组:")
    grp, ls = quintile_backtest(inv_composite, ret_fwd, n_groups=5, long_short="Qn_minus_Q1")
    ann = ls.mean() * 252 / FWD
    vol = ls.std() * np.sqrt(252 / FWD)
    sr = ann / vol if vol > 0 else np.nan
    print(f"    多空年化 {ann:.2%}  夏普 {sr:.2f}")
    grp_ann = grp.mean() * 252 / FWD
    print(grp_ann)

    # 保存
    composite.to_parquet(OUT / "composite_crowding.parquet")

    # 报告
    with open(OUT / "report.md", "w") as f:
        f.write("# 拥挤度复合因子研究报告\n\n")
        f.write(f"**日期**：2026-04-21  **窗口**：{IS_START}~{IS_END}  **前瞻**：20 日\n\n")
        f.write("## 合成方法\n\n")
        f.write("composite = z(att_60d) + z(turnover_20d) + z(nb_ratio) + z(inst_ratio) / 4\n")
        f.write("测试方向：**反向** -composite 作为正向 alpha\n\n")
        f.write("## A. -composite_crowding 20日前瞻\n\n")
        f.write(f"- IC 均值 {stats_a['IC_mean']:.4f}\n")
        f.write(f"- ICIR {stats_a['ICIR']:.4f}\n")
        f.write(f"- HAC t {stats_a['t_stat_hac']:.4f}\n")
        f.write(f"- IC>0 占比 {stats_a['pct_pos']:.2%}\n")
        f.write(f"- 多空年化 {ann:.2%}  夏普 {sr:.2f}\n\n")
        f.write("## B. 各分位组年化\n\n")
        f.write(grp_ann.to_frame("ann").round(4).to_markdown())
        f.write("\n\n## 结论\n\n")
        if abs(stats_a["ICIR"]) > 0.3 and abs(stats_a["t_stat_hac"]) > 2:
            f.write("- ✅ 复合拥挤度因子通过 ICIR + HAC t 双门槛\n")
            f.write(f"- 推荐定位：**v16 候选因子，权重 10-15%**\n")
        else:
            f.write("- ⚠️ 复合因子未完全通过双门槛，仍有参考价值\n")
    print(f"\n[保存] -> {OUT}")
    print("="*70, "\nDONE")


if __name__ == "__main__":
    main()
