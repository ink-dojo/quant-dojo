"""
机构调研热度因子 (Institutional Survey Attention) — 研究

背景：
    stk_surv 2021-08~2026 记录机构对上市公司的调研事件。
    特定对象调研 (占 24.5%) 被认为是最强 alpha 信号 (Cheng et al. 2018)。
    预期：调研频率高 + 近期突增 → 未来跑赢。

构造：
    (A) attention_60d: 滚动 60 日调研次数 (仅特定对象调研)
    (B) attention_surge: 近 30 日调研次数 / 前 90 日调研次数 (突增信号)

测试：
    - 20日前瞻 IC / ICIR / HAC t
    - 5 组分层回测

运行：python research/factors/survey_attention/factor_research.py
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
OUT = ROOT / "research" / "factors" / "survey_attention"
# 预热期：events 从 2021-08 起，滚动 60d + surge 基线 90d 需 ~150 日预热
WARMUP_START = "2021-08-01"
IS_START = "2022-01-01"
IS_END = "2025-12-31"
FWD = 20


def load_survey_events():
    """加载所有 stk_surv 事件，过滤到特定对象调研。"""
    files = list((RAW / "stk_surv").glob("*.parquet"))
    print(f"[数据] stk_surv 文件 {len(files)} 个")
    dfs = []
    for f in files:
        try:
            df = pd.read_parquet(f)
            if len(df) > 0:
                dfs.append(df)
        except Exception:
            continue
    df = pd.concat(dfs, ignore_index=True)
    df["code"] = df["ts_code"].str[:6]
    df["date"] = pd.to_datetime(df["surv_date"].astype(str), errors="coerce")
    df = df.dropna(subset=["date"])
    # 过滤到特定对象调研（含复合类型，如"特定对象调研,现场参观"）
    df["is_specific"] = df["rece_mode"].fillna("").str.contains("特定对象")
    print(f"[数据] 总调研事件 {len(df):,}，特定对象调研 {df['is_specific'].sum():,}")
    return df


def build_attention_panel(events: pd.DataFrame, all_dates: pd.DatetimeIndex, codes: list) -> dict:
    """构造每日调研事件 × 股票 宽表 + 滚动窗口统计。"""
    # 只保留特定对象调研
    events = events[events["is_specific"]].copy()
    # 每日每股事件数
    daily = (events.groupby(["date", "code"]).size().unstack(fill_value=0)
             .reindex(index=all_dates, columns=codes, fill_value=0))
    print(f"[面板] daily_events 形状 {daily.shape}")
    # 滚动 60 日调研次数
    att_60d = daily.rolling(60, min_periods=20).sum()
    # surge: 30 日 / 前 90 日（T-30 ~ T-120）
    recent = daily.rolling(30, min_periods=10).sum()
    baseline = daily.shift(30).rolling(90, min_periods=30).sum()
    surge = (recent + 1) / (baseline + 1)  # +1 避免除 0
    return {"att_60d": att_60d, "surge_30_90": surge}


def main():
    print("="*70)
    print("机构调研热度因子研究")
    print("="*70)
    OUT.mkdir(parents=True, exist_ok=True)

    # 价格 —— 含预热期 (warmup) 避免滚动窗口截断
    price_full = pd.read_parquet(ROOT / "data/processed/price_wide_close_2014-01-01_2025-12-31_qfq_5477stocks.parquet")
    price_full.index = pd.to_datetime(price_full.index)
    price_warm = price_full.loc[WARMUP_START:IS_END]  # 预热期 + IS
    price = price_warm.loc[IS_START:IS_END]           # 评估期
    print(f"[价格] 预热期 {WARMUP_START} ~ IS_END 含 {len(price_warm)} 交易日 | IS 评估区间 {len(price)} 日")

    events = load_survey_events()

    # 在预热期+IS 上构造滚动面板（关键修复：不再丢 2021 Q3/Q4 事件）
    panel = build_attention_panel(events, price_warm.index, list(price_warm.columns))
    att_60d_full = panel["att_60d"]
    surge_full = panel["surge_30_90"]

    # shift 1 避免未来函数 (基于 T 日数据在 T+1 交易)
    att_60d_full = att_60d_full.shift(1)
    surge_full = surge_full.shift(1)

    # 切回 IS 窗口做 IC / 分层评估；保留全 panel 供下游消费（F5 合成）
    att_60d = att_60d_full.loc[IS_START:IS_END]
    surge = surge_full.loc[IS_START:IS_END]

    # fwd return
    ret_fwd = price.shift(-FWD) / price - 1

    # 限定 universe：只对 att_60d > 0 的股票进入 universe（其他无调研）
    # 通过 align + 对 att_60d NaN 的不排除但截面排序会排末位
    # 替换 0 为 NaN，让 rank 只在"有调研"股票间
    print("\n[A] attention_60d (特定对象调研 60 日累计) → 20 日前瞻 IC:")
    att_masked = att_60d.where(att_60d > 0)
    ic_a = compute_ic_series(att_masked, ret_fwd, method="spearman", min_stocks=100)
    stats_a = ic_summary(ic_a, name="att_60d_fwd20", fwd_days=FWD)

    print("\n[B] surge_30_over_90 (调研突增) → 20 日前瞻 IC:")
    # 只考虑有一定 baseline 调研的股票
    surge_masked = surge.where(att_60d >= 2)
    ic_b = compute_ic_series(surge_masked, ret_fwd, method="spearman", min_stocks=100)
    stats_b = ic_summary(ic_b, name="surge_fwd20", fwd_days=FWD)

    print("\n[C] 分层回测 attention_60d 5 组:")
    try:
        grp, ls = quintile_backtest(att_masked, ret_fwd, n_groups=5, long_short="Qn_minus_Q1")
        # annualize (fwd=20d overlap)
        ann = ls.mean() * 252 / FWD
        vol = ls.std() * np.sqrt(252 / FWD)
        print(f"    多空年化 {ann:.2%}  夏普 {ann/vol if vol>0 else np.nan:.2f}")
        grp_ann = grp.mean() * 252 / FWD
        print(f"    各组年化:")
        print(grp_ann)
    except Exception as e:
        print(f"    分层回测失败: {e}")
        ann = vol = np.nan
        grp_ann = pd.Series()

    print("\n[D] 分层回测 surge 5 组:")
    try:
        grp2, ls2 = quintile_backtest(surge_masked, ret_fwd, n_groups=5, long_short="Qn_minus_Q1")
        ann2 = ls2.mean() * 252 / FWD
        vol2 = ls2.std() * np.sqrt(252 / FWD)
        print(f"    多空年化 {ann2:.2%}  夏普 {ann2/vol2 if vol2>0 else np.nan:.2f}")
        grp_ann2 = grp2.mean() * 252 / FWD
        print(grp_ann2)
    except Exception as e:
        print(f"    分层回测 surge 失败: {e}")
        grp_ann2 = pd.Series()

    # save —— 保存 IS 切片（保持下游字段一致）+ 完整窗口（便于 F5 合成避免再预热）
    att_60d.to_parquet(OUT / "att_60d.parquet")
    surge.to_parquet(OUT / "surge_30_90.parquet")
    att_60d_full.to_parquet(OUT / "att_60d_full.parquet")
    surge_full.to_parquet(OUT / "surge_30_90_full.parquet")

    with open(OUT / "report.md", "w") as f:
        f.write("# 机构调研热度因子研究报告\n\n")
        f.write(f"**日期**：2026-04-21  \n")
        f.write(f"**数据**：stk_surv 2021-08~2026，特定对象调研事件\n\n")
        f.write("## 因子 A: attention_60d (滚动 60 日调研次数)\n\n")
        f.write(f"- IC 均值 {stats_a['IC_mean']:.4f}\n")
        f.write(f"- ICIR {stats_a['ICIR']:.4f}\n")
        f.write(f"- HAC t {stats_a['t_stat_hac']:.4f}\n")
        f.write(f"- IC>0 占比 {stats_a['pct_pos']:.2%}\n")
        f.write(f"- n_days {stats_a['n']}\n\n")
        f.write("## 因子 B: surge (近 30d / 前 90d)\n\n")
        f.write(f"- IC 均值 {stats_b['IC_mean']:.4f}\n")
        f.write(f"- ICIR {stats_b['ICIR']:.4f}\n")
        f.write(f"- HAC t {stats_b['t_stat_hac']:.4f}\n\n")
        f.write("## 结论\n\n")
        if abs(stats_a["ICIR"]) > 0.3 and abs(stats_a["t_stat_hac"]) > 2:
            f.write("- ✅ attention_60d **合格**：ICIR > 0.3 且 HAC t > 2，可进入 v16 候选\n")
        elif abs(stats_a["IC_mean"]) > 0.02:
            f.write("- ⚠️ attention_60d IC 显著但 ICIR 不稳，需要样本外验证\n")
        else:
            f.write("- ❌ attention_60d 未通过 IC 门槛\n")
        if abs(stats_b["ICIR"]) > 0.3 and abs(stats_b["t_stat_hac"]) > 2:
            f.write("- ✅ surge 因子也合格\n")
        else:
            f.write("- ❌ surge 因子未通过\n")

    print(f"\n[保存] -> {OUT}")
    print("="*70, "\nDONE")


if __name__ == "__main__":
    main()
