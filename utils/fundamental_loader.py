"""
财务数据加载模块
提供个股估值指标（PE/PB/PS）、财务摘要、行业分类
数据源：akshare（百度股市通 + 新浪财经 + 东方财富）
"""
import time
import warnings
from pathlib import Path

import pandas as pd
import akshare as ak

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
    获取个股估值指标时序数据（PE_TTM, PB, PS_TTM）

    参数:
        symbol   : 股票代码，如 "000001"
        start    : 开始日期，如 "2020-01-01"
        end      : 结束日期，如 "2024-12-31"
        use_cache: 是否使用 parquet 缓存

    返回:
        DataFrame，列：date, pe_ttm, pb, ps_ttm
        index 为 date（DatetimeIndex）
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
        "市现率": "ps_ttm",  # 市现率近似替代市销率
    }

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
        return pd.DataFrame(columns=["pe_ttm", "pb", "ps_ttm"])

    result = pd.concat(dfs, axis=1, sort=True).sort_index()

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
            report_date    报告期
            net_profit     净利润（元）
            revenue        营业总收入（元）
            roe            净资产收益率（%）
            gross_margin   销售毛利率（%）
            debt_ratio     资产负债率（%）
        index 为 report_date
    """
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    cache_path = RAW_DIR / f"{symbol}_financials.parquet"

    if use_cache and cache_path.exists():
        df = pd.read_parquet(cache_path)
        return df.tail(periods)

    # 用新浪财经的财务分析指标接口
    raw = ak.stock_financial_analysis_indicator(symbol=symbol, start_year="2018")

    # 列名映射：中文 → 英文 snake_case
    col_map = {
        "日期": "report_date",
        "净资产收益率(%)": "roe",
        "销售毛利率(%)": "gross_margin",
        "资产负债率(%)": "debt_ratio",
        "总资产(元)": "total_assets",
        "主营业务利润(元)": "operating_profit",
        "净利润增长率(%)": "net_profit_growth",
        "主营业务收入增长率(%)": "revenue_growth",
        "销售净利率(%)": "net_margin",
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
    symbols: list,
    use_cache: bool = True,
) -> pd.DataFrame:
    """
    批量获取个股行业分类

    参数:
        symbols  : 股票代码列表，如 ["000001", "600519"]
        use_cache: 是否使用缓存

    返回:
        DataFrame，列：symbol, industry_name
    """
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    cache_path = RAW_DIR / "industry_classification.parquet"

    # 读取已有缓存，增量更新
    if use_cache and cache_path.exists():
        cached = pd.read_parquet(cache_path)
        cached_syms = set(cached["symbol"])
        missing = [s for s in symbols if s not in cached_syms]
        if not missing:
            return cached[cached["symbol"].isin(symbols)].reset_index(drop=True)
    else:
        cached = pd.DataFrame(columns=["symbol", "industry_name"])
        missing = list(symbols)

    # 逐只获取行业信息（用东方财富个股信息接口，带重试）
    new_rows = []
    for sym in missing:
        industry_name = "未知"
        for attempt in range(3):
            try:
                info = ak.stock_individual_info_em(symbol=sym)
                # info 是 item/value 格式，行业在 "行业" 行
                industry = info.loc[info["item"] == "行业", "value"].values
                industry_name = industry[0] if len(industry) > 0 else "未知"
                break
            except Exception as e:
                if attempt < 2:
                    time.sleep(1.0 * (attempt + 1))
                else:
                    warnings.warn(f"获取 {sym} 行业分类失败: {e}")
        new_rows.append({"symbol": sym, "industry_name": industry_name})
        time.sleep(0.3)

    if new_rows:
        new_df = pd.DataFrame(new_rows)
        cached = pd.concat([cached, new_df], ignore_index=True)
        cached = cached.drop_duplicates(subset="symbol", keep="last")
        cached.to_parquet(cache_path, index=False)

    return cached[cached["symbol"].isin(symbols)].reset_index(drop=True)


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
    print()

    print("✅ 全部测试通过")
