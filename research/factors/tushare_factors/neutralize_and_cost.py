"""
四因子第二阶段：size + 申万一级行业中性化 + cost-aware 多空回测

输入:
    research/factors/tushare_factors/factor_research.py 里的 build_* 函数
    SSD parquet (data/raw/tushare/daily_basic + moneyflow + financial + northbound)
    申万一级行业映射 (data/raw/fundamentals/industry_sw.parquet)

输出:
    research/factors/tushare_factors/neutralized_ic.csv
    research/factors/tushare_factors/cost_aware_backtest.csv

执行:
    python research/factors/tushare_factors/neutralize_and_cost.py

数据全部走 SSD parquet, 不调 live tushare
(jiaoch 高权限 token 已在 2026-04-22 被官方吊销).
"""
import sys
import warnings
from pathlib import Path
from typing import Literal

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent.parent.parent
sys.path.insert(0, str(ROOT))

from research.factors.tushare_factors.factor_research import (  # noqa: E402
    build_inst_flow,
    build_nb_ratio_chg,
    build_roe_stability,
    build_cfoni_precise,
    compute_forward_returns,
)
from utils.factor_analysis import (  # noqa: E402
    compute_ic_series,
    cross_section_rank,
    ic_summary,
    neutralize_factor,
)

warnings.filterwarnings("ignore")

DATA = ROOT / "data" / "raw" / "tushare"
INDUSTRY_PATH = ROOT / "data" / "raw" / "fundamentals" / "industry_sw.parquet"
OUT = ROOT / "research" / "factors" / "tushare_factors"

# 双边总 cost 0.3% (单边 0.15%); 多空 = 多腿 + 空腿, 各按周转率扣
COST_PER_SIDE = 0.0015
HORIZON = 21               # 月频前向收益
MIN_STOCKS_PER_GROUP = 5   # qcut 单档最少股票数 (low → 用 utils.factor_analysis 默认 30)
MIN_STOCKS_FOR_IC = 30     # compute_ic_series 截面最少股票数

Direction = Literal["Q1_minus_Qn", "Qn_minus_Q1"]


# ─────────────────────────────────────────────────────────────
# 1. 本地数据面板 (close + circ_mv 都来自 daily_basic)
# ─────────────────────────────────────────────────────────────

def _read_daily_basic(symbol: str, cols: list[str]) -> pd.DataFrame | None:
    """读单股 daily_basic parquet, 返回 datetime 索引的 DataFrame."""
    path = DATA / "daily_basic" / f"{symbol}.parquet"
    if not path.exists():
        return None
    df = pd.read_parquet(path, columns=["trade_date"] + cols)
    if df.empty:
        return None
    df["trade_date"] = pd.to_datetime(df["trade_date"], format="%Y%m%d")
    return df.set_index("trade_date").sort_index()


def build_price_panel(stocks: list[str], start: str, end: str) -> pd.DataFrame:
    """从 daily_basic.close 拼价格面板 (避开被吊销的 pro.daily 权限).

    返回 date × symbol 的宽表.
    """
    print(f"  [价格] 从本地 daily_basic 拼 {len(stocks)} 只股票...")
    frames = {}
    start_ts, end_ts = pd.Timestamp(start), pd.Timestamp(end)
    for sym in stocks:
        df = _read_daily_basic(sym, ["close"])
        if df is None or df.empty:
            continue
        s = df.loc[start_ts:end_ts, "close"]
        if not s.empty:
            frames[sym] = s
    panel = pd.DataFrame(frames).sort_index()
    print(f"  [价格] shape: {panel.shape}")
    return panel


def build_size_panel(stocks: list[str], dates: pd.DatetimeIndex) -> pd.DataFrame:
    """流通市值 (circ_mv, 万元) 宽表, 与因子价格日历对齐."""
    print(f"  [size] 拼 circ_mv 面板 ({len(stocks)} 只)...")
    frames = {}
    start_ts, end_ts = dates.min(), dates.max()
    for sym in stocks:
        df = _read_daily_basic(sym, ["circ_mv"])
        if df is None or df.empty:
            continue
        s = df.loc[start_ts:end_ts, "circ_mv"]
        if not s.empty:
            frames[sym] = s
    panel = pd.DataFrame(frames).reindex(dates).sort_index()
    print(f"  [size] shape: {panel.shape}")
    return panel


# ─────────────────────────────────────────────────────────────
# 2. 股票池 + 中性化输入 (df_info 长表)
# ─────────────────────────────────────────────────────────────

def resolve_stock_pools() -> dict[str, list[str]]:
    """从 SSD parquet 文件名反推 4 类股票池, 与 4 个因子对应.

    返回 dict, keys: core / quality / cfoni / nb. 改文件命名 (例如
    fina_indicator_ rename) 时只需要改这一处.
    """
    mf = {f.stem for f in (DATA / "moneyflow").glob("*.parquet")}
    db = {f.stem for f in (DATA / "daily_basic").glob("*.parquet")}
    fi = {f.stem.replace("fina_indicator_", "")
          for f in (DATA / "financial").glob("fina_indicator_*.parquet")}
    cf = {f.stem.replace("cashflow_", "")
          for f in (DATA / "financial").glob("cashflow_*.parquet")}
    inc = {f.stem.replace("income_", "")
           for f in (DATA / "financial").glob("income_*.parquet")}
    nb = {f.stem for f in (DATA / "northbound").glob("*.parquet")}
    return {
        "core":    sorted(mf & db),
        "quality": sorted(mf & db & fi),
        "cfoni":   sorted(cf & inc & db),
        "nb":      sorted(nb & db),
    }


def load_industry_l1() -> pd.Series:
    """申万一级行业 (industry_code 前 2 位).

    返回 pd.Series, index=symbol(6位), value=industry_l1_code.
    """
    df = pd.read_parquet(INDUSTRY_PATH)
    df = df.dropna(subset=["industry_code"]).copy()
    df["l1"] = df["industry_code"].astype(str).str[:2]
    return df.drop_duplicates(subset="symbol", keep="last").set_index("symbol")["l1"]


def build_df_info(size_panel: pd.DataFrame, industry_l1: pd.Series) -> pd.DataFrame:
    """把 size 宽表 + 行业映射转成 neutralize_factor 需要的长表."""
    long = size_panel.stack().rename("mv_float").reset_index()
    long.columns = ["trade_date", "symbol", "mv_float"]
    long = long.dropna(subset=["mv_float"])
    long["ind_code"] = long["symbol"].map(industry_l1)
    long = long.dropna(subset=["ind_code"])
    return long


# ─────────────────────────────────────────────────────────────
# 3. cost-aware 多空回测 (月频抽样, 周转率扣 cost)
# ─────────────────────────────────────────────────────────────

def monthly_rebalance_dates(dates: pd.DatetimeIndex, step: int = HORIZON) -> pd.DatetimeIndex:
    """每 step 个交易日取一次 → 模拟月度调仓."""
    return dates[::step]


def long_short_periods(
    factor_wide: pd.DataFrame,
    fwd_ret_wide: pd.DataFrame,
    long_short: Direction,
    n_groups: int = 5,
    cost_per_side: float = COST_PER_SIDE,
) -> pd.DataFrame:
    """月频抽样的逐 rebal 多空 DataFrame (date 索引, 列 gross/net/cost/turn_long/turn_short).

    给 cost_aware_long_short (年化汇总) + stacking_analysis (gross 序列 corr) 共用.
    空结果返回空 DataFrame, 列名一致.
    """
    common_dates = factor_wide.index.intersection(fwd_ret_wide.index)
    common_stocks = factor_wide.columns.intersection(fwd_ret_wide.columns)
    fac = factor_wide.loc[common_dates, common_stocks]
    ret = fwd_ret_wide.loc[common_dates, common_stocks]

    rebal = monthly_rebalance_dates(common_dates, step=HORIZON)

    prev_long: set[str] = set()
    prev_short: set[str] = set()
    period_rows = []

    for date in rebal:
        f_vals = fac.loc[date].dropna()
        r_vals = ret.loc[date].dropna()
        idx = f_vals.index.intersection(r_vals.index)
        if len(idx) < n_groups * MIN_STOCKS_PER_GROUP:
            continue

        labels = pd.qcut(f_vals[idx], q=n_groups, labels=False, duplicates="drop")
        if labels.isna().all():
            continue
        q_low = set(idx[labels == 0])
        q_high = set(idx[labels == labels.max()])

        if long_short == "Q1_minus_Qn":
            long_set, short_set = q_low, q_high
        else:
            long_set, short_set = q_high, q_low

        if not long_set or not short_set:
            continue

        long_ret = r_vals.loc[list(long_set)].mean()
        short_ret = r_vals.loc[list(short_set)].mean()
        gross = long_ret - short_ret

        # 周转率 = 新组合中需要新建仓的比例 (= |new \ old| / |new|).
        # 与 utils/ls_costs.leg_turnover 的 0.5*Σ|Δw| 公式不等价: ls_costs 是
        # 日频 + 等权权重差 L1, 这里是月频 rebal + 集合差比例. 等权且双腿同
        # 大小时两公式数值接近; A 股 quintile 名单稳定时差异 < 5%. 故意保
        # 留集合差版本以便跟 spec v3/v4 历史 turnover 数字直接对得上.
        turn_long = len(long_set - prev_long) / len(long_set) if prev_long else 1.0
        turn_short = len(short_set - prev_short) / len(short_set) if prev_short else 1.0
        cost = (turn_long + turn_short) * cost_per_side
        net = gross - cost

        period_rows.append({
            "date": date,
            "gross": gross,
            "net": net,
            "cost": cost,
            "turn_long": turn_long,
            "turn_short": turn_short,
        })
        prev_long, prev_short = long_set, short_set

    if not period_rows:
        return pd.DataFrame(columns=["date", "gross", "net", "cost", "turn_long", "turn_short"]).set_index("date")
    return pd.DataFrame(period_rows).set_index("date")


def cost_aware_long_short(
    factor_wide: pd.DataFrame,
    fwd_ret_wide: pd.DataFrame,
    long_short: Direction,
    n_groups: int = 5,
    cost_per_side: float = COST_PER_SIDE,
) -> dict:
    """月频抽样多空回测 + 周转率 × cost_per_side 扣减, 返回年化汇总字典.

    流程:
        1. 抽样每 HORIZON 天的 rebalance 日, 按因子分 n_groups 档, 多空两腿等权.
        2. 期间收益 = fwd_ret_wide 的 horizon 日收益均值.
        3. 周转率 = |new \ old| / |new|, 双腿分别算; cost = (tl + ts) * cost_per_side.
        4. 净期间收益 = gross − cost; 年化按 252/HORIZON 期估.

    与 `utils/ls_costs.tradable_ls_pnl` 的关键差异:
        - 月频 rebal 而非日频 (因子是 21d 前向收益评估的, 日频 cost 会过度扣).
        - 不算融券年化 borrow drag (8% 那条) — 跟 spec v3/v4 评估一致, 不在
          中段引入新 baseline; 真要 go-live 再单算.
    返回字典: gross_ann / net_ann / sharpe_gross / sharpe_net / avg_turnover / n_periods.
    """
    df = long_short_periods(factor_wide, fwd_ret_wide, long_short, n_groups, cost_per_side)
    if df.empty:
        return {"gross_ann": np.nan, "net_ann": np.nan, "sharpe_gross": np.nan,
                "sharpe_net": np.nan, "avg_turnover": np.nan, "n_periods": 0,
                "ann_cost_drag": np.nan}

    periods_per_year = 252 / HORIZON
    gross_mean, gross_std = df["gross"].mean(), df["gross"].std()
    net_mean, net_std = df["net"].mean(), df["net"].std()
    return {
        "gross_ann": gross_mean * periods_per_year,
        "net_ann": net_mean * periods_per_year,
        "sharpe_gross": gross_mean / gross_std * np.sqrt(periods_per_year) if gross_std > 0 else np.nan,
        "sharpe_net": net_mean / net_std * np.sqrt(periods_per_year) if net_std > 0 else np.nan,
        "avg_turnover": ((df["turn_long"] + df["turn_short"]) / 2).mean(),
        "n_periods": len(df),
        "ann_cost_drag": (gross_mean - net_mean) * periods_per_year,
    }


# ─────────────────────────────────────────────────────────────
# 4. 主流程
# ─────────────────────────────────────────────────────────────

def run() -> tuple[pd.DataFrame, pd.DataFrame]:
    print("=" * 72)
    print("四因子 size + SW-L1 行业中性化 + cost-aware 回测  (Issue #44)")
    print("=" * 72)

    # 4.1 股票池
    pools = resolve_stock_pools()
    core_stocks, quality_stocks = pools["core"], pools["quality"]
    cfoni_stocks, nb_core = pools["cfoni"], pools["nb"]
    print(f"\n股票池: core={len(core_stocks)} quality={len(quality_stocks)} "
          f"cfoni={len(cfoni_stocks)} nb={len(nb_core)}")

    # 4.2 价格面板
    print("\n[Step 1] 价格面板 (close from daily_basic)")
    price_wide = build_price_panel(core_stocks, "20200101", "20251231")
    price_idx = price_wide.index
    assert price_wide.shape[0] > 100, f"价格面板行数异常: {price_wide.shape[0]}"

    # 4.3 前向收益
    print("\n[Step 2] 前向 21 日 log return")
    fwd_ret = compute_forward_returns(price_wide, horizon=HORIZON)

    # 4.4 size + 行业 长表
    print("\n[Step 3] size 面板 + SW-L1 映射 → df_info")
    size_panel = build_size_panel(core_stocks, price_idx)
    industry_l1 = load_industry_l1()
    print(f"  industry SW-L1 unique: {industry_l1.nunique()}, mapped stocks: {len(industry_l1)}")
    df_info = build_df_info(size_panel, industry_l1)
    print(f"  df_info rows: {len(df_info):,}")

    # 4.5 构造四因子 raw
    print("\n[Step 4] 构造原始因子")
    f1 = build_inst_flow(core_stocks)
    f2 = build_nb_ratio_chg(nb_core, price_idx)
    f3 = build_roe_stability(quality_stocks, price_idx)
    f4 = build_cfoni_precise(cfoni_stocks, price_idx)

    # 因子在原始量纲上中性化, 再 rank → IC; 这样 size 系数估计更稳
    raw_factors = {
        "inst_flow_20d": f1,
        "nb_ratio_chg":  f2,
        "roe_stability": f3,
        "cfoni_precise": f4,
    }

    # 4.6 中性化 + IC 对比
    print("\n[Step 5] 中性化 (size + SW-L1) + IC 对比")
    ic_rows = []
    neutral_cache = {}

    for name, fac in raw_factors.items():
        print(f"\n  ─── {name} ───")
        fac_aligned = fac.reindex(index=price_idx)

        ranked_raw = cross_section_rank(fac_aligned)
        ic_raw = compute_ic_series(ranked_raw, fwd_ret, method="spearman", min_stocks=MIN_STOCKS_FOR_IC)
        s_raw = ic_summary(ic_raw, name=f"{name}_raw", fwd_days=HORIZON, verbose=False)

        # 中性化在原始量纲上做, 再 rank — size 系数在原始量纲上估计更稳
        fac_neutral = neutralize_factor(fac_aligned, df_info, n_sigma=3.0)
        ranked_n = cross_section_rank(fac_neutral)
        ic_n = compute_ic_series(ranked_n, fwd_ret, method="spearman", min_stocks=MIN_STOCKS_FOR_IC)
        s_n = ic_summary(ic_n, name=f"{name}_neutral", fwd_days=HORIZON, verbose=False)

        neutral_cache[name] = ranked_n

        ic_rows.append({
            "factor": name,
            "ic_raw": round(s_raw["IC_mean"], 4),
            "icir_raw": round(s_raw["ICIR"], 3),
            "t_hac_raw": round(s_raw["t_stat_hac"], 2),
            "ic_neutral": round(s_n["IC_mean"], 4),
            "icir_neutral": round(s_n["ICIR"], 3),
            "t_hac_neutral": round(s_n["t_stat_hac"], 2),
            "ic_decay": round(s_n["IC_mean"] - s_raw["IC_mean"], 4),
            "n": s_n["n"],
        })

    ic_df = pd.DataFrame(ic_rows)
    print("\n" + "=" * 72)
    print("IC 对比 (HAC t, NW lag = 自动)")
    print("=" * 72)
    print(ic_df.to_string(index=False))

    # 4.7 cost-aware 多空回测 (用中性化后因子)
    print("\n" + "=" * 72)
    print("cost-aware 多空回测 (月频, 双边 0.3%, 中性化后因子)")
    print("=" * 72)
    bt_rows = []
    for name, ranked_n in neutral_cache.items():
        # 方向: nb_ratio_chg raw IC 负 → 反转, Q1 做多 (低值=高未来收益); 其余正向因子: Qn 做多
        direction = "Q1_minus_Qn" if name == "nb_ratio_chg" else "Qn_minus_Q1"
        res = cost_aware_long_short(ranked_n, fwd_ret, long_short=direction)
        res["factor"] = name
        res["direction"] = direction
        bt_rows.append(res)

    bt_df = pd.DataFrame(bt_rows)[
        ["factor", "direction", "n_periods", "avg_turnover",
         "gross_ann", "ann_cost_drag", "net_ann", "sharpe_gross", "sharpe_net"]
    ].copy()
    for col in ["avg_turnover", "gross_ann", "ann_cost_drag", "net_ann", "sharpe_gross", "sharpe_net"]:
        bt_df[col] = bt_df[col].round(4)
    print(bt_df.to_string(index=False))

    # 4.8 落盘
    OUT.mkdir(parents=True, exist_ok=True)
    ic_df.to_csv(OUT / "neutralized_ic.csv", index=False)
    bt_df.to_csv(OUT / "cost_aware_backtest.csv", index=False)
    print(f"\n✅ 写入 {OUT/'neutralized_ic.csv'}")
    print(f"✅ 写入 {OUT/'cost_aware_backtest.csv'}")

    return ic_df, bt_df


if __name__ == "__main__":
    run()
