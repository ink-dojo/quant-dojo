"""
基于 Tushare 数据设计并测试四个新因子

Factor 1: inst_flow_20d  — 机构资金净流入因子
    (大单+超大单净买入额的20日累计) / 流通市值
    数据来源: moneyflow + daily_basic

Factor 2: nb_ratio_chg   — 北向持股变化因子
    外资持股比例的季度变化（前向填充至日频）
    数据来源: northbound

Factor 3: roe_stability  — ROE稳定性因子
    -std(过去8个季度ROE) → 低波动 = 高质量
    数据来源: fina_indicator (ann_date对齐，避免前视偏差)

Factor 4: cfoni_precise  — 精确公告日盈利质量因子
    CFO / |归母净利润| (用 f_ann_date 对齐，消除1-3月前视偏差)
    数据来源: cashflow + income

运行方式:
    python research/factors/tushare_factors/factor_research.py
"""
import sys
import warnings
from pathlib import Path

import numpy as np
import pandas as pd
from scipy import stats

# 项目根目录
ROOT = Path(__file__).parent.parent.parent.parent
sys.path.insert(0, str(ROOT))
DATA = ROOT / "data" / "raw" / "tushare"

warnings.filterwarnings("ignore")


# ─────────────────────────────────────────────────────────────
# 0. 工具函数
# ─────────────────────────────────────────────────────────────

def load_token() -> str:
    """从 .env 读取 TUSHARE_TOKEN"""
    env_path = ROOT / ".env"
    with open(env_path) as f:
        for line in f:
            if "TUSHARE_TOKEN" in line:
                return line.strip().split("=", 1)[1].strip()
    raise EnvironmentError("TUSHARE_TOKEN not found in .env")


def get_pro():
    """获取 tushare pro 实例（指向 jiaoch.site 镜像）"""
    import tushare as ts
    token = load_token()
    pro = ts.pro_api(token)
    pro._DataApi__token = token
    pro._DataApi__http_url = "http://jiaoch.site"
    return pro


def winsorize_cross(series: pd.Series, n_sigma: float = 3.0) -> pd.Series:
    """截面去极值"""
    mu, sigma = series.mean(), series.std()
    return series.clip(mu - n_sigma * sigma, mu + n_sigma * sigma)


def ic_summary(ic: pd.Series, name: str = "") -> dict:
    """计算 IC 统计摘要"""
    ic_clean = ic.dropna()
    if len(ic_clean) == 0:
        return {}
    ic_mean = ic_clean.mean()
    ic_std = ic_clean.std()
    icir = ic_mean / ic_std if ic_std > 0 else np.nan
    t_stat = icir * np.sqrt(len(ic_clean))
    pct_pos = (ic_clean > 0).mean()
    return {
        "factor": name,
        "ic_mean": round(ic_mean, 4),
        "ic_std": round(ic_std, 4),
        "icir": round(icir, 3),
        "t_stat": round(t_stat, 2),
        "pct_pos": round(pct_pos, 3),
        "n_periods": len(ic_clean),
    }


def compute_ic_series(
    factor_wide: pd.DataFrame,
    ret_wide: pd.DataFrame,
    min_stocks: int = 5,
) -> pd.Series:
    """
    计算每日截面 Spearman IC

    参数:
        factor_wide : 因子宽表 (date × symbol)
        ret_wide    : 收益率宽表 (date × symbol)
        min_stocks  : 最低有效股票数
    """
    common_dates = factor_wide.index.intersection(ret_wide.index)
    common_stocks = factor_wide.columns.intersection(ret_wide.columns)
    fac = factor_wide.loc[common_dates, common_stocks]
    ret = ret_wide.loc[common_dates, common_stocks]

    ic_list = []
    for date in common_dates:
        f_vals = fac.loc[date].dropna()
        r_vals = ret.loc[date].dropna()
        idx = f_vals.index.intersection(r_vals.index)
        if len(idx) < min_stocks:
            ic_list.append(np.nan)
            continue
        corr, _ = stats.spearmanr(f_vals[idx], r_vals[idx])
        ic_list.append(corr)

    return pd.Series(ic_list, index=common_dates, name="IC_spearman")


def regime_split(ic: pd.Series, hs300: pd.DataFrame, window: int = 120) -> dict:
    """
    按牛熊市场拆分 IC（HS300 < MA120 为熊市）

    参数:
        ic     : IC 时间序列
        hs300  : HS300 日收盘价 DataFrame（index为date）
        window : MA 窗口
    """
    ma = hs300["close"].rolling(window).mean()
    is_bear = (hs300["close"] < ma).rename("is_bear")
    ic_df = pd.DataFrame({"ic": ic, "is_bear": is_bear}).dropna()

    bear = ic_df.loc[ic_df["is_bear"], "ic"]
    bull = ic_df.loc[~ic_df["is_bear"], "ic"]

    def _stat(s, label):
        if len(s) == 0:
            return {"regime": label, "ic_mean": np.nan, "t": np.nan, "n": 0}
        t = s.mean() / s.std() * np.sqrt(len(s))
        return {"regime": label, "ic_mean": round(s.mean(), 4), "t": round(t, 2), "n": len(s)}

    return {"bear": _stat(bear, "bear"), "bull": _stat(bull, "bull")}


# ─────────────────────────────────────────────────────────────
# 1. 价格数据（用于计算前向收益率）
# ─────────────────────────────────────────────────────────────

def load_price_panel(stocks: list, start: str = "20200101", end: str = "20251231") -> pd.DataFrame:
    """
    下载所有股票的日收盘价，拼成宽表

    返回: DataFrame (date × symbol)，date 为 datetime index
    """
    cache_path = DATA / "price_panel.parquet"
    if cache_path.exists():
        print("  [价格] 读取缓存...")
        df = pd.read_parquet(cache_path)
        return df

    print(f"  [价格] 从 tushare 下载 {len(stocks)} 只股票...")
    pro = get_pro()
    frames = {}
    import time

    for i, sym in enumerate(stocks):
        # 转换为 tushare 格式
        if sym.startswith("6"):
            ts_code = sym + ".SH"
        elif sym.startswith(("4", "8")):
            ts_code = sym + ".BJ"
        else:
            ts_code = sym + ".SZ"

        try:
            tmp = pro.daily(ts_code=ts_code, start_date=start, end_date=end,
                            fields="trade_date,close")
            if tmp is not None and not tmp.empty:
                frames[sym] = tmp.set_index("trade_date")["close"]
            time.sleep(0.2)
        except Exception as e:
            print(f"    ⚠️  {sym}: {e}")

        if (i + 1) % 10 == 0:
            print(f"    {i+1}/{len(stocks)} done")

    panel = pd.DataFrame(frames)
    panel.index = pd.to_datetime(panel.index, format="%Y%m%d")
    panel = panel.sort_index()
    panel.to_parquet(cache_path)
    print(f"  [价格] 完成，shape: {panel.shape}")
    return panel


def compute_forward_returns(price_wide: pd.DataFrame, horizon: int = 21) -> pd.DataFrame:
    """
    计算 horizon 日前向对数收益率（月频）

    返回: 宽表 (date × symbol)，date 为 t 日，值为 t → t+horizon 日收益
    """
    log_ret = np.log(price_wide).diff(horizon).shift(-horizon)
    return log_ret


# ─────────────────────────────────────────────────────────────
# 2. Factor 1: inst_flow_20d — 机构资金净流入
# ─────────────────────────────────────────────────────────────

def build_inst_flow(stocks: list) -> pd.DataFrame:
    """
    构建机构资金净流入因子宽表

    公式: (大单净买入 + 超大单净买入) 的20日滚动总和 / 流通市值
    大单净买入 = buy_lg_amount - sell_lg_amount
    超大单净买入 = buy_elg_amount - sell_elg_amount
    流通市值单位: 万元

    返回: 宽表 (date × symbol)
    """
    print("  [Factor 1] 构建 inst_flow_20d...")
    factor_frames = {}

    for sym in stocks:
        mf_path = DATA / "moneyflow" / f"{sym}.parquet"
        db_path = DATA / "daily_basic" / f"{sym}.parquet"

        if not mf_path.exists() or not db_path.exists():
            continue

        mf = pd.read_parquet(mf_path)
        db = pd.read_parquet(db_path)

        if mf.empty or db.empty:
            continue

        mf["date"] = pd.to_datetime(mf["trade_date"], format="%Y%m%d")
        db["date"] = pd.to_datetime(db["trade_date"], format="%Y%m%d")

        mf = mf.set_index("date").sort_index()
        db = db.set_index("date").sort_index()

        # 大单 + 超大单净买入（万元）
        lg_net = mf["buy_lg_amount"] - mf["sell_lg_amount"]
        elg_net = mf["buy_elg_amount"] - mf["sell_elg_amount"]
        net_inst = (lg_net + elg_net).rename("net_inst")

        # 与流通市值对齐
        combined = pd.concat([net_inst, db["circ_mv"]], axis=1).dropna()
        if combined.empty:
            continue

        # 20日滚动累计 / 流通市值
        rolling_net = combined["net_inst"].rolling(20, min_periods=10).sum()
        factor = rolling_net / combined["circ_mv"]

        # 去极值（截面操作，此处做股票层面简化）
        factor_frames[sym] = factor

    panel = pd.DataFrame(factor_frames).sort_index()
    print(f"  [Factor 1] shape: {panel.shape}")
    return panel


# ─────────────────────────────────────────────────────────────
# 3. Factor 2: nb_ratio_chg — 北向持股变化
# ─────────────────────────────────────────────────────────────

def build_nb_ratio_chg(stocks: list, price_idx: pd.DatetimeIndex) -> pd.DataFrame:
    """
    构建北向持股变化因子宽表

    公式: 外资持股比例的季度变化（quarter-over-quarter），前向填充至日频
    数据频率: 季报级（每季度末一条记录）

    返回: 宽表 (date × symbol)
    """
    print("  [Factor 2] 构建 nb_ratio_chg...")
    factor_frames = {}

    for sym in stocks:
        nb_path = DATA / "northbound" / f"{sym}.parquet"
        if not nb_path.exists():
            continue

        nb = pd.read_parquet(nb_path)
        if nb.empty or "ratio" not in nb.columns:
            continue

        nb["date"] = pd.to_datetime(nb["trade_date"], format="%Y%m%d")
        nb = nb.set_index("date").sort_index()
        # 同日多档/多通道记录: 留最后一条, 否则后续 reindex 报 duplicate-label
        nb = nb[["ratio"]].loc[~nb.index.duplicated(keep="last")]

        # 季度变化
        nb["ratio_chg"] = nb["ratio"].diff()

        # 前向填充至日频（使用 price_idx 作为基准）
        daily = nb["ratio_chg"].reindex(price_idx, method="ffill")
        factor_frames[sym] = daily

    panel = pd.DataFrame(factor_frames).sort_index()
    print(f"  [Factor 2] shape: {panel.shape}, stocks: {len(factor_frames)}")
    return panel


# ─────────────────────────────────────────────────────────────
# 4. Factor 3: roe_stability — ROE稳定性
# ─────────────────────────────────────────────────────────────

def build_roe_stability(stocks: list, price_idx: pd.DatetimeIndex) -> pd.DataFrame:
    """
    构建 ROE 稳定性因子宽表

    公式: -std(过去8个季度 ROE)（负号：方差小 = 质量高）
    时间对齐: 用 ann_date（财报公告日），数据在公告日才能使用
    前向填充至日频

    返回: 宽表 (date × symbol)
    """
    print("  [Factor 3] 构建 roe_stability...")
    factor_frames = {}

    for sym in stocks:
        fi_path = DATA / "financial" / f"fina_indicator_{sym}.parquet"
        if not fi_path.exists():
            continue

        fi = pd.read_parquet(fi_path)
        if fi.empty or "roe" not in fi.columns:
            continue

        fi["ann_date"] = pd.to_datetime(fi["ann_date"], errors="coerce")
        fi["end_date"] = pd.to_datetime(fi["end_date"], errors="coerce")
        fi = fi.dropna(subset=["ann_date", "roe"])
        fi = fi.sort_values("end_date").drop_duplicates(subset=["end_date"])

        # 过去8个季度滚动标准差
        fi["roe_std8q"] = fi["roe"].rolling(8, min_periods=4).std()
        # 负号：越稳定 → 值越高
        fi["roe_stability"] = -fi["roe_std8q"]

        # 以公告日为时间轴（避免前视偏差）
        ann_series = fi.set_index("ann_date")["roe_stability"]
        # ann_date 与 end_date 顺序常不一致 (财报披露延迟不一); dedup 后必须 sort_index 才能 ffill reindex
        ann_series = ann_series[~ann_series.index.duplicated(keep="last")].sort_index()
        daily_signal = ann_series.reindex(price_idx, method="ffill")
        factor_frames[sym] = daily_signal

    panel = pd.DataFrame(factor_frames).sort_index()
    print(f"  [Factor 3] shape: {panel.shape}, stocks: {len(factor_frames)}")
    return panel


# ─────────────────────────────────────────────────────────────
# 5. Factor 4: cfoni_precise — 精确公告日盈利质量
# ─────────────────────────────────────────────────────────────

def build_cfoni_precise(stocks: list, price_idx: pd.DatetimeIndex) -> pd.DataFrame:
    """
    构建精确公告日盈利质量因子 (CFO / NI)

    公式: n_cashflow_act（经营现金流） / |n_income_attr_p（归母净利润）|
    时间对齐: 用 f_ann_date（实际公告日），比 shift(1) 精确 1-3 个月
    前向填充至日频

    返回: 宽表 (date × symbol)
    """
    print("  [Factor 4] 构建 cfoni_precise...")
    factor_frames = {}

    for sym in stocks:
        cf_path = DATA / "financial" / f"cashflow_{sym}.parquet"
        ic_path = DATA / "financial" / f"income_{sym}.parquet"

        if not cf_path.exists() or not ic_path.exists():
            continue

        cf = pd.read_parquet(cf_path)
        ic = pd.read_parquet(ic_path)

        if cf.empty or ic.empty:
            continue

        # 标准化列名
        cf["end_date"] = pd.to_datetime(cf["end_date"], errors="coerce")
        cf["f_ann_date"] = pd.to_datetime(cf["f_ann_date"], errors="coerce")
        ic["end_date"] = pd.to_datetime(ic["end_date"], errors="coerce")
        ic["f_ann_date"] = pd.to_datetime(ic["f_ann_date"], errors="coerce")

        cf = cf.dropna(subset=["end_date", "f_ann_date", "n_cashflow_act"])
        ic = ic.dropna(subset=["end_date"])

        # 合并现金流和净利润
        cf = cf.sort_values("end_date").drop_duplicates(subset=["end_date"])
        ic = ic.sort_values("end_date").drop_duplicates(subset=["end_date"])

        # 找净利润列（income 表可能有不同字段名）
        ni_col = None
        for col in ["n_income_attr_p", "net_profit", "n_income"]:
            if col in ic.columns:
                ni_col = col
                break

        if ni_col is None:
            continue

        merged = cf[["end_date", "f_ann_date", "n_cashflow_act"]].merge(
            ic[["end_date", ni_col]], on="end_date", how="inner"
        )

        # 盈利质量 = CFO / |NI|，排除 NI 接近零的情况
        abs_ni = merged[ni_col].abs()
        valid = abs_ni > abs_ni.quantile(0.1)
        merged = merged[valid]
        merged["cfoni"] = merged["n_cashflow_act"] / merged[ni_col].abs()

        # Winsorize: 排除极端值
        q_low, q_high = merged["cfoni"].quantile(0.05), merged["cfoni"].quantile(0.95)
        merged = merged[(merged["cfoni"] >= q_low) & (merged["cfoni"] <= q_high)]

        # 以 f_ann_date 为时间轴（精确公告日）
        merged = merged.sort_values("f_ann_date")
        cfoni_series = merged.set_index("f_ann_date")["cfoni"]
        cfoni_series = cfoni_series[~cfoni_series.index.duplicated(keep="last")]
        daily_signal = cfoni_series.reindex(price_idx, method="ffill")
        factor_frames[sym] = daily_signal

    panel = pd.DataFrame(factor_frames).sort_index()
    print(f"  [Factor 4] shape: {panel.shape}, stocks: {len(factor_frames)}")
    return panel


# ─────────────────────────────────────────────────────────────
# 6. 主函数：加载数据，运行 IC 分析，输出结果
# ─────────────────────────────────────────────────────────────

def run_analysis():
    """运行完整的因子设计与测试流程"""
    print("=" * 60)
    print("Tushare 因子设计与测试")
    print("=" * 60)

    # 确定股票池（有 moneyflow + daily_basic + fina + cashflow + income 的股票）
    mf_stocks = set(f.stem for f in (DATA / "moneyflow").glob("*.parquet"))
    db_stocks = set(f.stem for f in (DATA / "daily_basic").glob("*.parquet"))
    fi_stocks = set(f.stem.replace("fina_indicator_", "") for f in (DATA / "financial").glob("fina_indicator_*.parquet"))
    cf_stocks = set(f.stem.replace("cashflow_", "") for f in (DATA / "financial").glob("cashflow_*.parquet"))
    ic_stocks = set(f.stem.replace("income_", "") for f in (DATA / "financial").glob("income_*.parquet"))
    nb_stocks = set(f.stem for f in (DATA / "northbound").glob("*.parquet"))

    # 核心因子1&2需要 mf + db
    core_stocks = sorted(mf_stocks & db_stocks)
    # 因子3需要 fina
    quality_stocks = sorted(mf_stocks & db_stocks & fi_stocks)
    # 因子4需要 cashflow + income
    cfoni_stocks = sorted(cf_stocks & ic_stocks)

    print(f"\n股票池: core={len(core_stocks)}, quality={len(quality_stocks)}, cfoni={len(cfoni_stocks)}")
    print(f"北向数据: {len(nb_stocks)} 只")

    # 1. 加载价格数据
    print("\n[Step 1] 加载价格数据...")
    price_wide = load_price_panel(core_stocks, start="20200101", end="20251231")
    price_idx = price_wide.index

    # 2. 计算前向 21 日收益率（月频）
    print("\n[Step 2] 计算月频前向收益率（21日）...")
    fwd_ret = compute_forward_returns(price_wide, horizon=21)
    print(f"  fwd_ret shape: {fwd_ret.shape}")

    # 3. 加载 HS300 用于熊牛判断
    print("\n[Step 3] 加载 HS300 指数...")
    hs300_path = ROOT / "data" / "raw" / "indices" / "sh000300.parquet"
    hs300 = pd.read_parquet(hs300_path)
    hs300.index = pd.to_datetime(hs300.index)
    print(f"  HS300 shape: {hs300.shape}")

    # 4. 构建因子
    print("\n[Step 4] 构建因子...")
    f1 = build_inst_flow(core_stocks)
    f2 = build_nb_ratio_chg(list(nb_stocks & mf_stocks), price_idx)
    f3 = build_roe_stability(quality_stocks, price_idx)
    f4 = build_cfoni_precise(cfoni_stocks, price_idx)

    # 5. 截面标准化（截面 rank → 百分比）
    print("\n[Step 5] 截面 rank 标准化...")
    factors = {"inst_flow_20d": f1, "nb_ratio_chg": f2, "roe_stability": f3, "cfoni_precise": f4}
    factors_ranked = {}
    for name, fac in factors.items():
        # 截面 rank（每日对各股票排名）
        ranked = fac.rank(axis=1, pct=True)
        factors_ranked[name] = ranked
        print(f"  {name}: {ranked.shape}, non-NaN stocks avg: "
              f"{ranked.notna().sum(axis=1).mean():.1f}")

    # 6. IC 分析
    print("\n[Step 6] IC 分析...")
    all_results = []
    all_ic_series = {}

    for name, fac in factors_ranked.items():
        ic = compute_ic_series(fac, fwd_ret, min_stocks=5)
        all_ic_series[name] = ic
        summary = ic_summary(ic, name=name)
        all_results.append(summary)

    # 7. 牛熊拆分
    print("\n[Step 7] 牛熊市场拆分 IC...")
    regime_results = []
    for name, ic in all_ic_series.items():
        r = regime_split(ic, hs300, window=120)
        regime_results.append({
            "factor": name,
            "ic_bear": r["bear"]["ic_mean"],
            "t_bear": r["bear"]["t"],
            "n_bear": r["bear"]["n"],
            "ic_bull": r["bull"]["ic_mean"],
            "t_bull": r["bull"]["t"],
            "n_bull": r["bull"]["n"],
        })

    # 8. 打印结果
    print("\n" + "=" * 60)
    print("IC 分析结果（Spearman，21日前向收益）")
    print("=" * 60)
    hdr = f"{'Factor':<20} {'IC_mean':>8} {'IC_std':>7} {'ICIR':>6} {'t-stat':>7} {'pct>0':>6} {'N':>5}"
    print(hdr)
    print("-" * 60)
    for r in all_results:
        print(f"{r['factor']:<20} {r.get('ic_mean', 'nan'):>8.4f} {r.get('ic_std', 'nan'):>7.4f} "
              f"{r.get('icir', 'nan'):>6.3f} {r.get('t_stat', 'nan'):>7.2f} "
              f"{r.get('pct_pos', 'nan'):>6.3f} {r.get('n_periods', 0):>5}")

    print("\n" + "=" * 60)
    print("牛熊市场 IC 拆分")
    print("=" * 60)
    hdr2 = f"{'Factor':<20} {'IC_bear':>8} {'t_bear':>7} {'N_bear':>7} {'IC_bull':>8} {'t_bull':>7} {'N_bull':>7}"
    print(hdr2)
    print("-" * 75)
    for r in regime_results:
        bear_ic = r['ic_bear'] if r['ic_bear'] is not None else float('nan')
        bull_ic = r['ic_bull'] if r['ic_bull'] is not None else float('nan')
        print(f"{r['factor']:<20} {bear_ic:>8.4f} {r['t_bear']:>7.2f} {r['n_bear']:>7} "
              f"{bull_ic:>8.4f} {r['t_bull']:>7.2f} {r['n_bull']:>7}")

    # 9. 每月 IC 变化
    print("\n" + "=" * 60)
    print("月度 IC 均值（近12个月）")
    print("=" * 60)
    for name, ic in all_ic_series.items():
        monthly = ic.resample("M").mean().tail(12)
        vals = " ".join(f"{v:+.3f}" for v in monthly.values)
        print(f"{name:<20}: {vals}")

    # 10. 保存结果
    results_path = ROOT / "research" / "factors" / "tushare_factors" / "results.csv"
    results_path.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(all_results).to_csv(results_path, index=False)
    pd.DataFrame(regime_results).to_csv(
        results_path.with_name("regime_results.csv"), index=False
    )
    print(f"\n✅ 结果已保存到 {results_path}")

    return all_results, regime_results, all_ic_series


if __name__ == "__main__":
    run_analysis()
