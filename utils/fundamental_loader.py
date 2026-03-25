"""
财务数据加载模块
提供个股估值指标（PE/PB/PS）、财务摘要、行业分类
数据源：akshare（百度股市通 + 新浪财经 + 东方财富）
"""
import time
import warnings
from pathlib import Path

import pandas as pd

RAW_DIR = Path(__file__).parent.parent / "data" / "raw" / "fundamentals"


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

def get_industry_classification(
    symbols: list = None,
    use_cache: bool = True,
) -> pd.DataFrame:
    """
    获取个股申万行业分类（一次拉取全量，速度快）

    参数:
        symbols  : 股票代码列表，如 ["000001", "600519"]；为 None 返回全部
        use_cache: 是否使用缓存

    返回:
        DataFrame，列：symbol, industry_code
    """
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    cache_path = RAW_DIR / "industry_sw.parquet"

    if use_cache and cache_path.exists():
        df = pd.read_parquet(cache_path)
    else:
        import akshare as ak
        # 申万行业分类：一次调用返回全部A股的行业归属历史
        raw = ak.stock_industry_clf_hist_sw()
        # 每只股票取最新的行业分类（按 start_date 最新）
        df = (
            raw.sort_values("start_date")
            .drop_duplicates(subset="symbol", keep="last")
            [["symbol", "industry_code"]]
            .reset_index(drop=True)
        )
        df.to_parquet(cache_path, index=False)

    if symbols is not None:
        return df[df["symbol"].isin(symbols)].reset_index(drop=True)
    return df


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

    print("✅ 全部测试通过")
