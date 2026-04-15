"""
财务数据加载模块
提供个股估值指标（PE/PB/PS）、财务摘要、行业分类
数据源：akshare（百度股市通 + 新浪财经 + 东方财富）
"""
import logging
import time
import warnings
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd

RAW_DIR = Path(__file__).parent.parent / "data" / "raw" / "fundamentals"
WIDE_DIR = RAW_DIR / "wide"
LEGACY_INDUSTRY_CSV = Path(__file__).parent.parent / "data" / "raw" / "industry_baostock.csv"

_INDUSTRY_CACHE_PATH = RAW_DIR / "industry_sw.parquet"
# 申万行业调整频率低（季度级别），30 天 TTL 足够
_INDUSTRY_CACHE_TTL = timedelta(days=30)

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────
# 估值指标（PE/PB/PS）
# ─────────────────────────────────────────────

def get_pe_pb(
    symbol: str,
    start: str = "2020-01-01",
    end: str = "2024-12-31",
    use_cache: bool = True,
) -> pd.DataFrame:
    """
    获取个股估值指标时序数据（PE_TTM, PB, PCF）

    参数:
        symbol   : 股票代码，如 "000001"
        start    : 开始日期，如 "2020-01-01"
        end      : 结束日期，如 "2024-12-31"
        use_cache: 是否使用 parquet 缓存

    返回:
        DataFrame，列：pe_ttm, pb, pcf（市现率）
        index 为 date（DatetimeIndex），forward-fill 对齐
    """
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    cache_path = RAW_DIR / f"{symbol}_pe_pb.parquet"

    if use_cache and cache_path.exists():
        df = pd.read_parquet(cache_path)
        return df.loc[start:end]

    # 从百度股市通分别拉取各估值指标
    indicator_map = {
        "市盈率(TTM)": "pe_ttm",
        "市净率": "pb",
        "市现率": "pcf",  # 市现率 Price/Cash Flow（非市销率）
    }

    import akshare as ak
    dfs = []
    for cn_name, en_name in indicator_map.items():
        try:
            raw = ak.stock_zh_valuation_baidu(
                symbol=symbol,
                indicator=cn_name,
                period="全部",
            )
            raw = raw.rename(columns={"date": "date", "value": en_name})
            raw["date"] = pd.to_datetime(raw["date"])
            raw = raw.set_index("date")[[en_name]]
            dfs.append(raw)
            time.sleep(0.3)  # 避免触发限速
        except Exception as e:
            warnings.warn(f"获取 {symbol} {cn_name} 失败: {e}")

    if not dfs:
        return pd.DataFrame(columns=["pe_ttm", "pb", "pcf"])

    # 合并后 forward-fill 对齐（估值指标在非交易日不变）
    result = pd.concat(dfs, axis=1, sort=True).sort_index()
    result = result.ffill()

    # 缓存完整数据
    result.to_parquet(cache_path)
    return result.loc[start:end]


# ─────────────────────────────────────────────
# 财务摘要
# ─────────────────────────────────────────────

def get_financials(
    symbol: str,
    periods: int = 8,
    use_cache: bool = True,
) -> pd.DataFrame:
    """
    获取个股财务摘要（最近 N 个季度）

    参数:
        symbol  : 股票代码，如 "000001"
        periods : 获取最近几个季度的数据，默认 8
        use_cache: 是否使用缓存

    返回:
        DataFrame，列：
            report_date          报告期
            roe                  净资产收益率（%）
            roa                  总资产净利润率（%）
            debt_ratio           资产负债率（%）
            total_assets         总资产（元）
            operating_profit     主营业务利润（元）
            net_profit_growth    净利润增长率（%）
            revenue_growth       营收增长率（%，非银行股有效）
            net_margin           销售净利率（%，非银行股有效）
            net_asset_growth     净资产增长率（%）
        index 为 report_date
    """
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    cache_path = RAW_DIR / f"{symbol}_financials.parquet"

    if use_cache and cache_path.exists():
        df = pd.read_parquet(cache_path)
        return df.tail(periods)

    import akshare as ak
    # 用新浪财经的财务分析指标接口
    raw = ak.stock_financial_analysis_indicator(symbol=symbol, start_year="2018")

    # 列名映射：中文 → 英文 snake_case
    # 注：银行股的 销售净利率/销售毛利率/主营业务收入增长率 天然为 NaN，属正常
    col_map = {
        "日期": "report_date",
        "净资产收益率(%)": "roe",
        "总资产净利润率(%)": "roa",
        "资产负债率(%)": "debt_ratio",
        "总资产(元)": "total_assets",
        "主营业务利润(元)": "operating_profit",
        "净利润增长率(%)": "net_profit_growth",
        "主营业务收入增长率(%)": "revenue_growth",
        "销售净利率(%)": "net_margin",
        "净资产增长率(%)": "net_asset_growth",
    }

    # 只保留存在的列
    available_cols = {k: v for k, v in col_map.items() if k in raw.columns}
    result = raw[list(available_cols.keys())].rename(columns=available_cols).copy()

    # 转换数据类型
    result["report_date"] = pd.to_datetime(result["report_date"])
    for col in result.columns:
        if col != "report_date":
            result[col] = pd.to_numeric(result[col], errors="coerce")

    result = result.set_index("report_date").sort_index()

    # 缓存
    result.to_parquet(cache_path)
    return result.tail(periods)


# ─────────────────────────────────────────────
# 行业分类
# ─────────────────────────────────────────────

def refresh_industry_classification(force: bool = False) -> pd.DataFrame:
    """
    从 akshare 拉取最新申万行业分类并写缓存。

    正常情况下调用方不需要直接调此函数——`get_industry_classification` 会在
    缓存过期（>30 天）时自动触发。仅在需要强制刷新时手动调用。

    参数:
        force: True 则忽略 TTL，强制从 akshare 重拉

    返回:
        DataFrame，列：symbol, industry_code（全 A 股）

    降级策略:
        akshare 不可用时使用旧缓存（如存在）；两者都没有则用 legacy CSV
    """
    RAW_DIR.mkdir(parents=True, exist_ok=True)

    # TTL 检查（非 force 模式）
    if not force and _INDUSTRY_CACHE_PATH.exists():
        mtime = datetime.fromtimestamp(_INDUSTRY_CACHE_PATH.stat().st_mtime)
        age = datetime.now() - mtime
        if age < _INDUSTRY_CACHE_TTL:
            logger.debug("申万行业缓存有效（age=%.1f 天），跳过刷新", age.days + age.seconds / 86400)
            return pd.read_parquet(_INDUSTRY_CACHE_PATH)

    logger.info("刷新申万行业分类（akshare）...")
    try:
        import akshare as ak
        raw = ak.stock_industry_clf_hist_sw()
        df = (
            raw.sort_values("start_date")
            .drop_duplicates(subset="symbol", keep="last")
            [["symbol", "industry_code"]]
            .reset_index(drop=True)
        )
        # 原子写：tmp + rename，防止拉取中途崩溃污染缓存
        tmp = _INDUSTRY_CACHE_PATH.with_suffix(".parquet.tmp")
        df.to_parquet(tmp, index=False)
        tmp.replace(_INDUSTRY_CACHE_PATH)
        logger.info("申万行业分类已刷新：%d 只股票，%d 个行业",
                    len(df), df["industry_code"].nunique())
        return df

    except Exception as exc:
        logger.warning("akshare 申万行业拉取失败: %s", exc)
        # 优先使用旧缓存（哪怕过期了，比没有强）
        if _INDUSTRY_CACHE_PATH.exists():
            mtime = datetime.fromtimestamp(_INDUSTRY_CACHE_PATH.stat().st_mtime)
            age_days = (datetime.now() - mtime).days
            logger.warning("使用旧缓存（age=%d 天）", age_days)
            return pd.read_parquet(_INDUSTRY_CACHE_PATH)
        # 最后降级：legacy baostock CSV
        if LEGACY_INDUSTRY_CSV.exists():
            logger.warning("回退到 legacy industry_baostock.csv")
            legacy = pd.read_csv(LEGACY_INDUSTRY_CSV)
            legacy["symbol"] = legacy["code"].astype(str).str.split(".").str[-1]
            legacy = legacy.rename(columns={"industry": "industry_code"})
            df = (
                legacy[["symbol", "industry_code"]]
                .dropna(subset=["industry_code"])
                .drop_duplicates(subset="symbol", keep="last")
                .reset_index(drop=True)
            )
            # 不写缓存（legacy 数据已经是旧的，不要假装它是新的）
            return df
        raise RuntimeError("申万行业分类不可用：akshare 失败，无缓存，无 legacy CSV") from exc


def get_industry_classification(
    symbols: list = None,
    use_cache: bool = True,
) -> pd.DataFrame:
    """
    获取申万行业分类。缓存 30 天自动刷新（不会永远用旧数据）。

    参数:
        symbols  : 股票代码列表，如 ["000001", "600519"]；None 返回全部
        use_cache: False 则强制从 akshare 重拉（等同于 refresh_industry_classification(force=True)）

    返回:
        DataFrame，列：symbol, industry_code

    调用逻辑:
        use_cache=True  → TTL 检查 → 未过期: 读缓存；过期: 自动刷新
        use_cache=False → 强制刷新
    """
    df = refresh_industry_classification(force=(not use_cache))
    if symbols is not None:
        return df[df["symbol"].isin(symbols)].reset_index(drop=True)
    return df


# ─────────────────────────────────────────────
# 估值宽表（日期 × 股票）
# ─────────────────────────────────────────────

def build_pe_pb_wide(
    symbols: list,
    start: str,
    end: str,
    fields: list = None,
    cache_dir: str = None,
    force_refresh: bool = False,
    max_workers: int = 8,
) -> dict:
    """
    批量构建估值宽表（日期行 × 股票列）。

    参数:
        symbols      : 股票代码列表，如 ["000001", "600519"]
        start        : 开始日期，格式 YYYY-MM-DD
        end          : 结束日期，格式 YYYY-MM-DD
        fields       : 需要的列，默认 ["pe_ttm", "pb"]；可选值来自 get_pe_pb() 返回列
        cache_dir    : parquet 缓存目录；默认 data/raw/fundamentals/wide/
        force_refresh: True 时忽略缓存，强制重新拉取所有股票
        max_workers  : 并行线程数（受 akshare 限速约束，建议不超过 8）

    返回:
        dict，键为 field 名称，值为 pd.DataFrame(index=DatetimeIndex, columns=股票代码)
        缺失数据处理：
          - ffill(limit=10)：补充节假日 / 季报更新延迟（最多 10 个交易日）
          - pe_ttm <= 0 的值置为 NaN（亏损股票剔除）
          - 各字段做 0.1% 双端截断（Winsorize），避免极端值破坏因子

    示例:
        wide = build_pe_pb_wide(["000001", "600519"], "2024-01-01", "2024-12-31")
        pe_df = wide["pe_ttm"]   # shape: (交易日数, 2)
    """
    if fields is None:
        fields = ["pe_ttm", "pb"]

    _cache_dir = Path(cache_dir) if cache_dir else WIDE_DIR
    _cache_dir.mkdir(parents=True, exist_ok=True)
    cache_path = _cache_dir / f"pe_pb_{start}_{end}.parquet"

    # ── 缓存命中：直接读 parquet，按 fields 筛列 ──────────────────────────
    if not force_refresh and cache_path.exists():
        cached = pd.read_parquet(cache_path)
        # 列格式：MultiIndex (field, symbol) —— 见下方写缓存逻辑
        available = set(cached.columns.get_level_values(0))
        missing_fields = [f for f in fields if f not in available]
        if not missing_fields:
            return {f: cached[f] for f in fields}
        # 缓存里缺字段时不复用，直接重拉
        warnings.warn(
            f"缓存 {cache_path} 缺少字段 {missing_fields}，忽略缓存重新拉取"
        )

    # ── 并行拉取每只股票 ──────────────────────────────────────────────────
    per_symbol: dict[str, pd.DataFrame] = {}
    failed: list[str] = []

    def _fetch_one(sym: str) -> tuple[str, pd.DataFrame | None]:
        """拉取单只股票的 pe_pb 数据，失败返回 None。"""
        try:
            df = get_pe_pb(sym, start=start, end=end, use_cache=True)
            time.sleep(0.05)  # akshare 轻量频控
            return sym, df
        except Exception as exc:
            warnings.warn(f"build_pe_pb_wide: {sym} 拉取失败，跳过。原因: {exc}")
            return sym, None

    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        futures = {pool.submit(_fetch_one, s): s for s in symbols}
        for fut in as_completed(futures):
            sym, df = fut.result()
            if df is not None and not df.empty:
                per_symbol[sym] = df
            else:
                failed.append(sym)

    if failed:
        warnings.warn(f"build_pe_pb_wide: 以下股票无数据，已跳过: {failed}")

    if not per_symbol:
        raise ValueError("build_pe_pb_wide: 所有股票拉取失败，无法构建宽表。")

    # ── 按 field 拼接宽表 ─────────────────────────────────────────────────
    result: dict[str, pd.DataFrame] = {}
    for field in fields:
        cols = {}
        for sym, df in per_symbol.items():
            if field in df.columns:
                cols[sym] = df[field]

        if not cols:
            warnings.warn(f"build_pe_pb_wide: 字段 {field} 在所有股票中均不存在，跳过。")
            continue

        wide = pd.DataFrame(cols).sort_index()

        # 补充节假日 / 数据延迟（季报最多约 10 个交易日才更新）
        wide = wide.ffill(limit=10)

        # pe_ttm <= 0（亏损股票）置为 NaN，不参与因子计算
        if field == "pe_ttm":
            wide = wide.where(wide > 0)

        # 0.1% 双端 Winsorize，防止极端值
        lower = wide.stack().quantile(0.001)
        upper = wide.stack().quantile(0.999)
        wide = wide.clip(lower=lower, upper=upper)

        result[field] = wide

    if not result:
        raise ValueError("build_pe_pb_wide: 所有 fields 均无法构建，请检查数据源。")

    # ── 写缓存（MultiIndex columns: (field, symbol)）───────────────────────
    try:
        combined = pd.concat(result.values(), axis=1, keys=result.keys())
        combined.to_parquet(cache_path)
    except Exception as exc:
        warnings.warn(f"build_pe_pb_wide: 缓存写入失败（不影响返回值）: {exc}")

    return result


# ─────────────────────────────────────────────
# 财务宽表（日期 × 股票）
# ─────────────────────────────────────────────

def build_financials_wide(
    symbols: list,
    start: str,
    end: str,
    fields: list = None,
    cache_dir: str = None,
    force_refresh: bool = False,
    max_workers: int = 8,
) -> dict:
    """
    批量构建财务指标宽表（报告期行 × 股票列）。

    参数:
        symbols      : 股票代码列表，如 ["000001", "600519"]
        start        : 开始报告期（含），格式 YYYY-MM-DD
        end          : 结束报告期（含），格式 YYYY-MM-DD
        fields       : 需要的列，默认 ["roe", "roa", "debt_ratio"]；
                       可选值来自 get_financials() 返回列
        cache_dir    : parquet 缓存目录；默认 data/raw/fundamentals/wide/
        force_refresh: True 时忽略缓存，强制重新拉取
        max_workers  : 并行线程数

    返回:
        dict，键为 field 名称，值为 pd.DataFrame(index=DatetimeIndex, columns=股票代码)
        缺失数据处理：
          - ffill(limit=10)：相邻报告期之间的值沿用
          - 各字段做 0.1% 双端截断（Winsorize）

    注意:
        财务数据为季报频率（每年 4 次），宽表 index 不连续，调用方按需 reindex 对齐日历。

    示例:
        wide = build_financials_wide(["000001", "600519"], "2022-01-01", "2024-12-31")
        roe_df = wide["roe"]  # shape: (报告期数, 2)
    """
    if fields is None:
        fields = ["roe", "roa", "debt_ratio"]

    _cache_dir = Path(cache_dir) if cache_dir else WIDE_DIR
    _cache_dir.mkdir(parents=True, exist_ok=True)
    cache_path = _cache_dir / f"financials_{start}_{end}.parquet"

    # ── 缓存命中 ──────────────────────────────────────────────────────────
    if not force_refresh and cache_path.exists():
        cached = pd.read_parquet(cache_path)
        available = set(cached.columns.get_level_values(0))
        missing_fields = [f for f in fields if f not in available]
        if not missing_fields:
            return {f: cached[f] for f in fields}
        warnings.warn(
            f"缓存 {cache_path} 缺少字段 {missing_fields}，忽略缓存重新拉取"
        )

    # ── 估算需要拉取的 periods（季报，每年 4 期）────────────────────────────
    start_dt = pd.Timestamp(start)
    end_dt = pd.Timestamp(end)
    # 多拉 2 个季度作为缓冲，确保日期范围内数据完整
    periods = max(4, int((end_dt - start_dt).days / 90) + 2)

    # ── 并行拉取 ──────────────────────────────────────────────────────────
    per_symbol: dict[str, pd.DataFrame] = {}
    failed: list[str] = []

    def _fetch_one(sym: str) -> tuple[str, pd.DataFrame | None]:
        """拉取单只股票的财务摘要数据，失败返回 None。"""
        try:
            df = get_financials(sym, periods=periods, use_cache=True)
            time.sleep(0.05)  # akshare 轻量频控
            return sym, df
        except Exception as exc:
            warnings.warn(f"build_financials_wide: {sym} 拉取失败，跳过。原因: {exc}")
            return sym, None

    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        futures = {pool.submit(_fetch_one, s): s for s in symbols}
        for fut in as_completed(futures):
            sym, df = fut.result()
            if df is not None and not df.empty:
                # 按报告期日期范围截取
                per_symbol[sym] = df.loc[start:end]
            else:
                failed.append(sym)

    if failed:
        warnings.warn(f"build_financials_wide: 以下股票无数据，已跳过: {failed}")

    if not per_symbol:
        raise ValueError("build_financials_wide: 所有股票拉取失败，无法构建宽表。")

    # ── 按 field 拼接宽表 ─────────────────────────────────────────────────
    result: dict[str, pd.DataFrame] = {}
    for field in fields:
        cols = {}
        for sym, df in per_symbol.items():
            if field in df.columns:
                cols[sym] = df[field]

        if not cols:
            warnings.warn(f"build_financials_wide: 字段 {field} 在所有股票中均不存在，跳过。")
            continue

        wide = pd.DataFrame(cols).sort_index()
        wide = wide.ffill(limit=10)

        # 0.1% 双端 Winsorize
        stacked = wide.stack()
        if len(stacked) > 0:
            lower = stacked.quantile(0.001)
            upper = stacked.quantile(0.999)
            wide = wide.clip(lower=lower, upper=upper)

        result[field] = wide

    if not result:
        raise ValueError("build_financials_wide: 所有 fields 均无法构建，请检查数据源。")

    # ── 写缓存 ────────────────────────────────────────────────────────────
    try:
        combined = pd.concat(result.values(), axis=1, keys=result.keys())
        combined.to_parquet(cache_path)
    except Exception as exc:
        warnings.warn(f"build_financials_wide: 缓存写入失败（不影响返回值）: {exc}")

    return result


if __name__ == "__main__":
    # 最小验证：用平安银行（000001）测试
    print("=" * 40)
    print("测试 get_pe_pb")
    print("=" * 40)
    pe_pb = get_pe_pb("000001", start="2024-01-01", end="2024-12-31", use_cache=False)
    print(f"形状: {pe_pb.shape}")
    print(pe_pb.head(3))
    print()

    print("=" * 40)
    print("测试 get_financials")
    print("=" * 40)
    fin = get_financials("000001", periods=4, use_cache=False)
    print(f"形状: {fin.shape}")
    print(fin.to_string())
    print()

    print("=" * 40)
    print("测试 get_industry_classification")
    print("=" * 40)
    ind = get_industry_classification(["000001", "600519"], use_cache=False)
    print(ind.to_string())
    assert len(ind) == 2, f"应返回2行，实际{len(ind)}"
    assert "industry_code" in ind.columns
    print()

    # ── 宽表函数测试（3只股票：平安银行、贵州茅台、宁德时代）─────────────────
    TEST_SYMBOLS = ["000001", "600519", "300750"]
    TEST_START = "2024-01-01"
    TEST_END   = "2024-06-30"

    print("=" * 40)
    print("测试 build_pe_pb_wide")
    print("=" * 40)
    pe_pb_wide = build_pe_pb_wide(
        TEST_SYMBOLS,
        start=TEST_START,
        end=TEST_END,
        fields=["pe_ttm", "pb"],
        force_refresh=True,   # 测试时强制重拉，不用脏缓存
        max_workers=4,
    )
    assert set(pe_pb_wide.keys()) == {"pe_ttm", "pb"}, \
        f"返回 keys 错误: {set(pe_pb_wide.keys())}"
    for field, df in pe_pb_wide.items():
        assert isinstance(df, pd.DataFrame), f"{field} 应为 DataFrame"
        assert df.shape[1] <= len(TEST_SYMBOLS), f"{field} 列数超过股票数"
        assert df.shape[0] > 0, f"{field} 行数为 0"
        # pe_ttm 不应含 <= 0 的值（亏损股票已剔除）
        if field == "pe_ttm":
            assert (df.stack() > 0).all(), "pe_ttm 中仍含 <= 0 的值"
        print(f"  {field}: shape={df.shape}, NaN率={df.isnull().mean().mean():.1%}")
        print(df.head(3).to_string())
        print()

    print("=" * 40)
    print("测试 build_financials_wide")
    print("=" * 40)
    fin_wide = build_financials_wide(
        TEST_SYMBOLS,
        start="2022-01-01",
        end="2024-06-30",
        fields=["roe", "roa", "debt_ratio"],
        force_refresh=True,
        max_workers=4,
    )
    assert set(fin_wide.keys()) == {"roe", "roa", "debt_ratio"}, \
        f"返回 keys 错误: {set(fin_wide.keys())}"
    for field, df in fin_wide.items():
        assert isinstance(df, pd.DataFrame), f"{field} 应为 DataFrame"
        assert df.shape[0] > 0, f"{field} 行数为 0（日期范围内无季报数据？）"
        print(f"  {field}: shape={df.shape}, NaN率={df.isnull().mean().mean():.1%}")
        print(df.to_string())
        print()

    print("✅ 全部测试通过")
