"""
因子审计脚本 — quant-dojo 全量因子验证

功能：
  1. 加载本地价量/基本面数据
  2. 计算所有可计算因子（build_fast_factors + 额外因子）
  3. 计算每个因子的月度 IC / ICIR / t-stat
  4. 输出因子相关矩阵并标记高相关对
  5. 基于 IC 和相关性推荐最优因子组合
  6. 将结果保存到 research/factor_audit_results.json

运行示例：
  python research/factor_audit.py
  python research/factor_audit.py --start 2022-01-01 --end 2025-12-31 --symbols-limit 300
"""
import argparse
import json
import sys
import warnings
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd

# ── 路径设置（确保从项目根目录可找到 utils）─────────────────────────────────
_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

# ── 结果输出目录 ──────────────────────────────────────────────────────────
RESEARCH_DIR = Path(__file__).resolve().parent


# =============================================================================
# 工具函数
# =============================================================================

def _safe_import_matplotlib():
    """懒加载 matplotlib，失败时返回 None。"""
    try:
        import matplotlib
        matplotlib.use("Agg")  # 无 GUI 环境兼容
        import matplotlib.pyplot as plt
        return plt
    except ImportError:
        return None


def _resample_monthly_ic(
    factor_wide: pd.DataFrame,
    fwd_ret_wide: pd.DataFrame,
) -> pd.Series:
    """
    计算月度截面 Spearman IC。

    为减少计算量，对因子宽表按月取最后一个交易日的截面，
    与对应的 21 日远期月收益做 Spearman 相关。

    参数:
        factor_wide   : 日频因子宽表（日期 × 股票）
        fwd_ret_wide  : 21 日远期收益宽表（日期 × 股票）

    返回:
        月度 IC 序列（pd.Series，index 为月末日期）
    """
    from scipy import stats

    # 按月取月末截面（period_end），避免前视偏误
    common_dates = factor_wide.index.intersection(fwd_ret_wide.index)
    if len(common_dates) == 0:
        return pd.Series(dtype=float)

    fac = factor_wide.loc[common_dates]
    ret = fwd_ret_wide.loc[common_dates]

    # 取每月最后一个交易日
    monthly_dates = fac.resample("ME").last().index
    # 过滤出在 common_dates 中实际存在的月末日期
    monthly_dates = [d for d in monthly_dates if d in fac.index]

    ic_list = []
    valid_dates = []

    for date in monthly_dates:
        f_row = fac.loc[date].dropna()
        r_row = ret.loc[date].dropna()
        common_stocks = f_row.index.intersection(r_row.index)

        if len(common_stocks) < 30:
            continue

        f_vals = f_row[common_stocks].values
        r_vals = r_row[common_stocks].values

        # 检查是否有足够方差（全为常数则跳过）
        if f_vals.std() < 1e-10 or r_vals.std() < 1e-10:
            continue

        corr, _ = stats.spearmanr(f_vals, r_vals)
        if not np.isnan(corr):
            ic_list.append(corr)
            valid_dates.append(date)

    if not ic_list:
        return pd.Series(dtype=float)

    return pd.Series(ic_list, index=pd.DatetimeIndex(valid_dates))


def _ic_stats(ic_series: pd.Series) -> dict:
    """
    从 IC 序列计算统计摘要。

    返回:
        ic_mean, ic_std, icir, t_stat, pct_positive（各为 float）
    """
    clean = ic_series.dropna()
    if len(clean) < 3:
        return {
            "ic_mean": np.nan,
            "ic_std": np.nan,
            "icir": np.nan,
            "t_stat": np.nan,
            "pct_positive": np.nan,
            "n_months": 0,
        }
    ic_mean = float(clean.mean())
    ic_std = float(clean.std())
    icir = ic_mean / ic_std if ic_std > 1e-10 else np.nan
    n = len(clean)
    t_stat = icir * np.sqrt(n) if not np.isnan(icir) else np.nan
    pct_positive = float((clean > 0).mean())

    return {
        "ic_mean": round(ic_mean, 6),
        "ic_std": round(ic_std, 6),
        "icir": round(icir, 6) if not np.isnan(icir) else None,
        "t_stat": round(t_stat, 4) if not np.isnan(t_stat) else None,
        "pct_positive": round(pct_positive, 4),
        "n_months": n,
    }


def _print_ic_table(stats_rows: list[dict]) -> None:
    """按 |t_stat| 降序打印因子 IC 汇总表。"""
    # 排序：t_stat 绝对值从大到小（None 排最后）
    def _sort_key(row):
        t = row.get("t_stat")
        return -abs(t) if t is not None else 0.0

    sorted_rows = sorted(stats_rows, key=_sort_key)

    header = f"{'Factor':<28} | {'IC_mean':>8} | {'IC_std':>7} | {'ICIR':>7} | {'t-stat':>7} | {'%pos':>6} | {'N':>4}"
    print(header)
    print("-" * len(header))

    for row in sorted_rows:
        name = row["name"]
        ic_m = row.get("ic_mean")
        ic_s = row.get("ic_std")
        icir = row.get("icir")
        t = row.get("t_stat")
        pp = row.get("pct_positive")
        n = row.get("n_months", 0)

        ic_m_str = f"{ic_m:+.4f}" if ic_m is not None else "   N/A "
        ic_s_str = f"{ic_s:.4f}" if ic_s is not None else "  N/A "
        icir_str = f"{icir:+.3f}" if icir is not None else "  N/A "
        t_str = f"{t:+.2f}" if t is not None else "  N/A "
        pp_str = f"{pp:.0%}" if pp is not None else "  N/A"

        print(f"{name:<28} | {ic_m_str:>8} | {ic_s_str:>7} | {icir_str:>7} | {t_str:>7} | {pp_str:>6} | {n:>4}")


# =============================================================================
# Section 1：数据加载
# =============================================================================

def load_data(symbols: list, start: str, end: str) -> dict:
    """
    从本地数据目录加载价量、基本面数据。

    返回包含以下键的字典（缺失数据的键值为 None）：
        close, open, high, low, volume, turnover, pe_ttm, pb
    """
    print("[1/6] Loading data...")

    data = {
        "close": None,
        "open": None,
        "high": None,
        "low": None,
        "volume": None,
        "turnover": None,
        "pe_ttm": None,
        "pb": None,
    }

    # ── 价量数据 ────────────────────────────────────────────────────────────
    try:
        from utils.local_data_loader import load_price_wide, load_factor_wide

        # 收盘价（核心，必须成功）
        close = load_price_wide(symbols, start=start, end=end, field="close")
        if close.empty:
            print("  [!] 收盘价宽表为空，请确认数据目录配置正确。")
            print("  提示：检查 config/config.yaml 中 phase5.local_data_dir 路径。")
            sys.exit(1)

        # 过滤掉几乎全空的股票（NaN 率 > 50%）
        nan_rate = close.isnull().mean()
        close = close.loc[:, nan_rate < 0.5]
        data["close"] = close
        print(f"  close: {close.shape[0]} 交易日 × {close.shape[1]} 只股票")

        # 可选价格字段
        for field in ("open", "high", "low", "volume"):
            try:
                wide = load_price_wide(list(close.columns), start=start, end=end, field=field)
                if not wide.empty:
                    data[field] = wide.reindex_like(close)
                    print(f"  {field}: OK ({wide.shape})")
                else:
                    print(f"  [!] {field}: 空数据，跳过依赖此字段的因子")
            except Exception as exc:
                print(f"  [!] {field}: 加载失败（{exc}），跳过")

        # 换手率
        try:
            turnover = load_factor_wide(list(close.columns), "turnover", start=start, end=end)
            if not turnover.empty:
                data["turnover"] = turnover.reindex_like(close)
                print(f"  turnover: OK ({turnover.shape})")
        except Exception as exc:
            print(f"  [!] turnover: {exc}")

    except ImportError as exc:
        print(f"  [!] 无法导入 local_data_loader: {exc}")
        print("  提示：请确认已运行 pip install -e . 且在项目根目录执行脚本。")
        sys.exit(1)
    except SystemExit:
        raise
    except Exception as exc:
        print(f"  [!] 价量数据加载失败: {exc}")
        sys.exit(1)

    # ── 基本面数据（PE/PB）──────────────────────────────────────────────────
    try:
        from utils.local_data_loader import load_factor_wide

        for field in ("pe_ttm", "pb"):
            try:
                wide = load_factor_wide(list(close.columns), field, start=start, end=end)
                if not wide.empty:
                    data[field] = wide.reindex_like(close)
                    print(f"  {field}: OK ({wide.shape})")
            except Exception as exc:
                # pe_ttm/pb 在本地 CSV 存在时会成功；不存在时静默跳过
                print(f"  [!] {field}: {exc}（将跳过 EP/BP/ROE 因子）")
    except Exception:
        pass

    print(f"  时间范围: {data['close'].index[0].date()} ~ {data['close'].index[-1].date()}")
    return data


# =============================================================================
# Section 2：因子计算
# =============================================================================

def compute_factors(data: dict) -> dict:
    """
    调用 build_fast_factors 计算基础因子集，然后补充额外因子。

    返回 {factor_name: factor_wide_df} 字典。
    """
    print("[2/6] Computing factors...")

    close = data["close"]
    computed: dict = {}
    skipped: dict = {}  # {因子名: 跳过原因}

    # ── build_fast_factors 调用 ──────────────────────────────────────────
    try:
        from utils.alpha_factors import build_fast_factors

        fast = build_fast_factors(
            price=close,
            high=data.get("high"),
            low=data.get("low"),
            open_price=data.get("open"),
            pe=data.get("pe_ttm"),
            pb=data.get("pb"),
            volume=data.get("volume"),
        )
        computed.update(fast)
        print(f"  build_fast_factors: 完成 {len(fast)} 个因子")
    except Exception as exc:
        print(f"  [!] build_fast_factors 失败: {exc}")

    # ── 额外因子：需要单独调用 ──────────────────────────────────────────────
    try:
        from utils.alpha_factors import (
            idiosyncratic_volatility,
            industry_momentum,
            price_volume_divergence,
            relative_turnover,
            roe_factor,
            insider_buying_proxy,
            cfo_accrual_quality,
        )

        # 特质波动率（仅需 close）
        try:
            computed["idiosyncratic_vol"] = idiosyncratic_volatility(close)
            print("  idiosyncratic_vol: OK")
        except Exception as exc:
            skipped["idiosyncratic_vol"] = str(exc)

        # ROE 因子（需要 pe + pb）
        if data.get("pe_ttm") is not None and data.get("pb") is not None:
            try:
                computed["roe"] = roe_factor(data["pe_ttm"], data["pb"])
                print("  roe: OK")
            except Exception as exc:
                skipped["roe"] = str(exc)
        else:
            skipped["roe"] = "缺少 pe_ttm 或 pb 数据"

        # 价量背离（需要 volume）
        if data.get("volume") is not None:
            try:
                computed["price_vol_divergence"] = price_volume_divergence(close, data["volume"])
                print("  price_vol_divergence: OK")
            except Exception as exc:
                skipped["price_vol_divergence"] = str(exc)
        else:
            skipped["price_vol_divergence"] = "缺少 volume 数据"

        # 相对换手率（需要 turnover）
        if data.get("turnover") is not None:
            try:
                computed["relative_turnover"] = relative_turnover(data["turnover"])
                print("  relative_turnover: OK")
            except Exception as exc:
                skipped["relative_turnover"] = str(exc)
        else:
            skipped["relative_turnover"] = "缺少 turnover 数据"

        # 行业动量（需要 industry_map）
        try:
            from utils.fundamental_loader import get_industry_classification
            ind_df = get_industry_classification(list(close.columns))
            if not ind_df.empty and "symbol" in ind_df.columns and "industry_code" in ind_df.columns:
                industry_map = dict(zip(ind_df["symbol"], ind_df["industry_code"]))
                computed["industry_momentum"] = industry_momentum(close, industry_map)
                print(f"  industry_momentum: OK（{len(ind_df)} 只股票有行业分类）")
            else:
                skipped["industry_momentum"] = "行业分类数据为空"
        except Exception as exc:
            skipped["industry_momentum"] = str(exc)

        # 增持代理因子（需要 close, high, low, volume）
        if all(data.get(k) is not None for k in ("high", "low", "volume")):
            try:
                computed["insider_buying_proxy"] = insider_buying_proxy(
                    close, data["high"], data["low"], data["volume"]
                )
                print("  insider_buying_proxy: OK")
            except Exception as exc:
                skipped["insider_buying_proxy"] = str(exc)
        else:
            skipped["insider_buying_proxy"] = "缺少 high / low / volume 数据"

        # CFO 应计利润质量因子（需要季报财务数据，本地 CSV 通常不含）
        skipped["cfo_accrual_quality"] = "需要季报财务数据（net_income / ocf / total_assets），本地 CSV 不含"

    except ImportError as exc:
        print(f"  [!] 额外因子导入失败: {exc}")

    # ── 汇总 ────────────────────────────────────────────────────────────────
    print(f"  成功计算: {len(computed)} 个因子")
    if skipped:
        print(f"  跳过: {len(skipped)} 个因子")
        for name, reason in skipped.items():
            print(f"    - {name}: {reason}")

    return computed, skipped


# =============================================================================
# Section 3：IC 分析
# =============================================================================

def run_ic_analysis(factors: dict, close: pd.DataFrame) -> list[dict]:
    """
    对每个因子计算月度 IC 统计。

    使用 21 日远期收益（近似月收益）作为预测目标。

    返回：
        stats_list：每个元素是一个字典，包含因子名和 IC 统计量
    """
    print("[3/6] Running IC analysis...")

    # 21 日远期收益（shift -21 得到 t+21 的价格，用于当前截面的预测目标）
    fwd_ret = close.pct_change(21).shift(-21)

    stats_list = []

    for name, fac in factors.items():
        try:
            # 对齐索引
            fac_aligned = fac.reindex_like(close)

            # 过滤全 NaN 的因子（例如数据窗口不足）
            valid_cols = fac_aligned.dropna(how="all").shape[0]
            if valid_cols < 10:
                print(f"  [!] {name}: 有效行数不足（{valid_cols}），跳过 IC 计算")
                continue

            ic_series = _resample_monthly_ic(fac_aligned, fwd_ret)
            stats = _ic_stats(ic_series)
            stats["name"] = name
            stats_list.append(stats)

        except Exception as exc:
            print(f"  [!] {name}: IC 计算失败（{exc}）")

    print(f"  完成 {len(stats_list)} 个因子的 IC 分析")
    print()
    print("  因子 IC 汇总表（按 |t-stat| 排序）：")
    _print_ic_table(stats_list)
    print()

    return stats_list


# =============================================================================
# Section 4：因子相关矩阵
# =============================================================================

def run_correlation_analysis(
    factors: dict,
    close: pd.DataFrame,
    output_path: Path,
) -> tuple[pd.DataFrame, list]:
    """
    计算因子间截面平均相关矩阵。

    策略：将所有因子宽表在时间维度 stack，得到 (date, symbol) × factor 的长表，
    再对每个交易日计算截面相关，最后取时间均值。
    为节省内存，采用每日截面相关的平均值近似全局相关。

    返回:
        (corr_df, high_corr_pairs)
    """
    print("[4/6] Computing factor correlation matrix...")

    if not factors:
        print("  [!] 无有效因子，跳过相关矩阵")
        return pd.DataFrame(), []

    from utils.factor_analysis import factor_correlation_matrix

    # 取每个因子的全表均值截面（按日压缩为股票维度的时序均值）
    # 以减少计算量，使用每日截面值堆叠为单列，再跨因子计算 Pearson 相关
    # 此处采用"对齐后 stack + corr"的做法

    factor_names = list(factors.keys())
    aligned = {}
    for name in factor_names:
        f = factors[name].reindex_like(close)
        # 每日截面 rank（转换到统一尺度，减少量纲影响）
        ranked = f.rank(axis=1, pct=True)
        aligned[name] = ranked

    # 构建 (date*stock) × factor 矩阵
    # 为节省内存，对日期下采样（每 5 个交易日取一次）
    sample_dates = close.index[::5]
    rows = []
    for date in sample_dates:
        row = {}
        for name in factor_names:
            series = aligned[name].loc[date] if date in aligned[name].index else pd.Series(dtype=float)
            row[name] = series
        # 横向拼接为一行（股票 × 因子）
        day_df = pd.DataFrame(row)
        rows.append(day_df)

    if not rows:
        print("  [!] 无法构建因子截面矩阵")
        return pd.DataFrame(), []

    # 垂直拼接（样本 × 因子）
    combined = pd.concat(rows, axis=0, ignore_index=True).dropna(how="all")

    if combined.empty or combined.shape[0] < 100:
        print(f"  [!] 有效样本不足（{combined.shape[0]}），跳过相关矩阵")
        return pd.DataFrame(), []

    try:
        corr_df, high_corr_pairs = factor_correlation_matrix(combined)
    except Exception as exc:
        print(f"  [!] factor_correlation_matrix 失败: {exc}")
        return pd.DataFrame(), []

    # 打印高相关对警告
    if high_corr_pairs:
        print(f"  警告：发现 {len(high_corr_pairs)} 对高相关因子（|corr| > 0.7）：")
        for a, b, c in sorted(high_corr_pairs, key=lambda x: -abs(x[2])):
            print(f"    {a:<25} <-> {b:<25}  corr={c:+.3f}")
    else:
        print("  未发现 |corr| > 0.7 的高相关因子对。")

    # ── 绘制热力图 ────────────────────────────────────────────────────────
    plt = _safe_import_matplotlib()
    if plt is not None:
        try:
            from utils.factor_analysis import plot_factor_correlation
            heatmap_path = str(output_path / "factor_correlation.png")
            plot_factor_correlation(corr_df, output_path=heatmap_path)
            print(f"  热力图已保存: {heatmap_path}")
        except Exception as exc:
            print(f"  [!] 热力图保存失败: {exc}")
    else:
        print("  [!] matplotlib 不可用，跳过热力图")

    return corr_df, high_corr_pairs


# =============================================================================
# Section 5：因子选择推荐
# =============================================================================

def recommend_factors(
    stats_list: list[dict],
    corr_df: pd.DataFrame,
    ic_threshold: float = 0.01,
    tstat_threshold: float = 2.0,
    corr_dedup_threshold: float = 0.6,
) -> tuple[list[str], str]:
    """
    基于 IC 过滤和相关性去重，推荐最优因子集合。

    算法：
      1. 过滤：|IC_mean| > ic_threshold 且 |t_stat| > tstat_threshold
      2. 按 |ICIR| 从高到低排序
      3. 贪心去重：若候选因子与已选因子的相关性 |corr| > corr_dedup_threshold，
         则保留 ICIR 更高者（即当前候选更弱时跳过）

    返回:
        (recommended_names, reasoning_text)
    """
    print("[5/6] Generating factor recommendations...")

    # 建立 name → stats 的映射
    stats_map = {r["name"]: r for r in stats_list}

    # Step 1：IC + t-stat 过滤
    passed = []
    failed_ic = []
    failed_tstat = []

    for row in stats_list:
        name = row["name"]
        ic_m = row.get("ic_mean")
        t = row.get("t_stat")

        if ic_m is None or np.isnan(ic_m):
            failed_ic.append(name)
            continue
        if abs(ic_m) <= ic_threshold:
            failed_ic.append(name)
            continue
        if t is None or np.isnan(t):
            failed_tstat.append(name)
            continue
        if abs(t) <= tstat_threshold:
            failed_tstat.append(name)
            continue
        passed.append(name)

    if not passed:
        reason = (
            f"过滤后无满足条件的因子（|IC_mean|>{ic_threshold} 且 |t_stat|>{tstat_threshold}）。"
            f"请降低阈值或检查数据质量。"
        )
        print(f"  {reason}")
        return [], reason

    # Step 2：按 |ICIR| 排序
    def _abs_icir(name):
        v = stats_map[name].get("icir")
        return abs(v) if v is not None and not (isinstance(v, float) and np.isnan(v)) else 0.0

    passed_sorted = sorted(passed, key=_abs_icir, reverse=True)

    # Step 3：贪心相关性去重
    selected = []
    skip_reason = {}

    for candidate in passed_sorted:
        if not selected:
            selected.append(candidate)
            continue

        # 若 corr_df 可用，检查候选因子与已选因子的最大相关
        dominated = False
        if not corr_df.empty and candidate in corr_df.index:
            for sel in selected:
                if sel not in corr_df.columns:
                    continue
                corr_val = abs(corr_df.loc[candidate, sel])
                if corr_val > corr_dedup_threshold:
                    # 保留 ICIR 更高者（已按 ICIR 排序，前面的总是更好）
                    dominated = True
                    skip_reason[candidate] = f"与 {sel} 高度相关（|corr|={corr_val:.2f} > {corr_dedup_threshold}）"
                    break

        if not dominated:
            selected.append(candidate)

    # ── 打印推荐结果 ──────────────────────────────────────────────────────
    print(f"  IC 过滤（|IC|≤{ic_threshold}）剔除: {failed_ic}")
    print(f"  t-stat 过滤（|t|≤{tstat_threshold}）剔除: {failed_tstat}")
    print(f"  相关性去重剔除: {list(skip_reason.keys())}")
    print()
    print(f"  推荐因子组合（{len(selected)} 个）：")
    for name in selected:
        row = stats_map[name]
        icir = row.get("icir")
        t = row.get("t_stat")
        print(f"    {name:<28}  ICIR={icir:+.3f}  t={t:+.2f}")

    # 生成说明文本
    reasoning = (
        f"筛选条件：|IC_mean|>{ic_threshold}（{len(failed_ic)} 个因子 IC 不足被剔除），"
        f"|t_stat|>{tstat_threshold}（{len(failed_tstat)} 个因子 t-stat 不足被剔除），"
        f"|corr|>{corr_dedup_threshold} 贪心去重（{len(skip_reason)} 个因子被去重）。"
        f"最终推荐 {len(selected)} 个因子：{selected}。"
    )

    return selected, reasoning


# =============================================================================
# Section 6：结果保存
# =============================================================================

def save_results(
    stats_list: list[dict],
    high_corr_pairs: list,
    recommended_factors: list,
    recommended_reason: str,
    skipped_factors: dict,
    output_dir: Path,
) -> Path:
    """将审计结果序列化为 JSON 文件并保存。"""
    print("[6/6] Saving results...")

    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / "factor_audit_results.json"

    # 将 corr pairs 转为可序列化格式
    corr_pairs_serializable = [
        {"factor_a": a, "factor_b": b, "corr": float(c)}
        for a, b, c in high_corr_pairs
    ]

    # stats_list 中 None/NaN 转为字符串 null 兼容 JSON
    def _clean(v):
        if v is None:
            return None
        if isinstance(v, float) and np.isnan(v):
            return None
        return v

    clean_stats = []
    for row in stats_list:
        clean_stats.append({k: _clean(v) for k, v in row.items()})

    result = {
        "run_date": datetime.now().isoformat(timespec="seconds"),
        "n_factors_computed": len(stats_list),
        "n_factors_skipped": len(skipped_factors),
        "skipped_factors": skipped_factors,
        "factor_stats": {row["name"]: {k: v for k, v in row.items() if k != "name"}
                         for row in clean_stats},
        "high_corr_pairs": corr_pairs_serializable,
        "recommended_factors": recommended_factors,
        "recommended_reason": recommended_reason,
    }

    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)

    print(f"  结果已保存: {output_path}")
    return output_path


# =============================================================================
# 命令行入口
# =============================================================================

def _parse_args():
    """解析命令行参数。"""
    parser = argparse.ArgumentParser(
        description="quant-dojo 因子审计脚本：验证 25 个因子的 IC / 相关性 / 推荐组合",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument(
        "--start",
        default="2020-01-01",
        help="数据起始日期（格式 YYYY-MM-DD）",
    )
    parser.add_argument(
        "--end",
        default="2025-12-31",
        help="数据截止日期（格式 YYYY-MM-DD）",
    )
    parser.add_argument(
        "--symbols-limit",
        type=int,
        default=0,
        help="最多使用多少只股票（0 = 全量，推荐调试时设为 200-500）",
    )
    parser.add_argument(
        "--ic-threshold",
        type=float,
        default=0.01,
        help="因子推荐的 IC 均值最低门槛（绝对值）",
    )
    parser.add_argument(
        "--tstat-threshold",
        type=float,
        default=2.0,
        help="因子推荐的 t-stat 最低门槛（绝对值）",
    )
    parser.add_argument(
        "--corr-dedup",
        type=float,
        default=0.6,
        help="相关性去重阈值：与已选因子相关超过此值则去除较弱因子",
    )
    return parser.parse_args()


if __name__ == "__main__":
    warnings.filterwarnings("ignore", category=FutureWarning)
    warnings.filterwarnings("ignore", category=UserWarning)

    args = _parse_args()

    print("=" * 65)
    print("  quant-dojo 因子审计脚本")
    print(f"  日期范围: {args.start} ~ {args.end}")
    if args.symbols_limit > 0:
        print(f"  股票数量上限: {args.symbols_limit}")
    print("=" * 65)
    print()

    # ── 获取股票列表 ─────────────────────────────────────────────────────
    try:
        from utils.local_data_loader import get_all_symbols
        all_symbols = get_all_symbols()
    except Exception as exc:
        print(f"[!] 无法获取股票列表: {exc}")
        sys.exit(1)

    if not all_symbols:
        print("[!] 本地股票列表为空。")
        print("  请确认数据目录配置正确（config/config.yaml 中 phase5.local_data_dir）。")
        sys.exit(1)

    if args.symbols_limit > 0:
        symbols = all_symbols[: args.symbols_limit]
    else:
        symbols = all_symbols

    print(f"  本地股票总数: {len(all_symbols)}，本次使用: {len(symbols)} 只")
    print()

    # ── 执行六个 Section ──────────────────────────────────────────────────
    # Section 1
    data = load_data(symbols, start=args.start, end=args.end)
    print()

    # Section 2
    computed_factors, skipped_factors = compute_factors(data)
    print()

    if not computed_factors:
        print("[!] 没有任何因子计算成功，审计终止。")
        sys.exit(1)

    # Section 3
    stats_list = run_ic_analysis(computed_factors, data["close"])
    print()

    # Section 4
    corr_df, high_corr_pairs = run_correlation_analysis(
        computed_factors, data["close"], RESEARCH_DIR
    )
    print()

    # Section 5
    recommended, reasoning = recommend_factors(
        stats_list,
        corr_df,
        ic_threshold=args.ic_threshold,
        tstat_threshold=args.tstat_threshold,
        corr_dedup_threshold=args.corr_dedup,
    )
    print()

    # Section 6
    result_path = save_results(
        stats_list=stats_list,
        high_corr_pairs=high_corr_pairs,
        recommended_factors=recommended,
        recommended_reason=reasoning,
        skipped_factors=skipped_factors,
        output_dir=RESEARCH_DIR,
    )
    print()

    # ── 最终摘要 ──────────────────────────────────────────────────────────
    print("=" * 65)
    print("  审计完成")
    print(f"  计算因子数:   {len(computed_factors)}")
    print(f"  有效 IC 因子: {len(stats_list)}")
    print(f"  推荐因子数:   {len(recommended)}")
    print(f"  高相关对数:   {len(high_corr_pairs)}")
    print(f"  结果文件:     {result_path}")
    print("=" * 65)
