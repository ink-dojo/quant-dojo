"""
本地 CSV 数据加载器

从本地配置的数据目录加载 A 股行情数据，
支持 parquet 缓存、并行加载宽表等功能。
"""

import logging
import warnings
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pandas as pd

logger = logging.getLogger(__name__)

# 本地数据目录 fallback，仅在 runtime_config 不可用时使用。
# 与 runtime_config 默认值保持一致，避免绑死到单机路径。
_DEFAULT_FALLBACK_DATA_DIR = Path.home() / "quant-data"


def _resolve_local_data_dir() -> Path:
    """
    懒加载本地数据目录路径。

    优先从 utils.runtime_config.get_local_data_dir() 读取；
    若模块不可用则降级到默认 fallback 路径。
    若最终路径不存在，打印清晰错误提示。

    返回:
        Path 对象，指向本地行情数据目录
    """
    try:
        from utils.runtime_config import get_local_data_dir
        return get_local_data_dir()
    except Exception:
        path = _DEFAULT_FALLBACK_DATA_DIR
        if not path.exists():
            logger.error(
                "本地数据目录不存在: %s\n"
                "  请确认数据已下载，或在 config/config.yaml 的 phase5.local_data_dir 中修改路径。",
                path,
            )
        return path


def _get_local_data_dir() -> Path:
    """
    获取本地数据目录（模块级懒加载入口）。

    返回:
        Path 对象
    """
    return _resolve_local_data_dir()


# 保持向后兼容：LOCAL_DATA_DIR 属性访问仍可用，但建议用 _get_local_data_dir()
LOCAL_DATA_DIR = _DEFAULT_FALLBACK_DATA_DIR

# parquet 缓存目录
_CACHE_DIR = Path("data/cache/local")

# CSV 列名 -> 英文字段名映射
COLUMN_MAP = {
    "交易所行情日期": "date",
    "开盘价": "open",
    "最高价": "high",
    "最低价": "low",
    "收盘价": "close",
    "前收盘价": "prev_close",
    "成交量": "volume",
    "成交额": "amount",
    "换手率": "turnover",
    "涨跌幅": "pct_change",
    "滚动市盈率": "pe_ttm",
    "市净率": "pb",
    "滚动市销率": "ps_ttm",
    "滚动市现率": "pcf",
    "是否ST": "is_st",
}

# 合法的因子字段名
VALID_FACTORS = {"pe_ttm", "pb", "ps_ttm", "pcf", "turnover", "is_st", "prev_close", "pct_change"}


def get_all_symbols() -> list:
    """
    扫描本地数据目录，返回所有股票代码列表。

    Returns:
        list: 6 位股票代码列表，例如 ['600000', '000001', ...]
    """
    data_dir = _get_local_data_dir()
    if not data_dir.exists():
        logger.warning("本地数据目录不存在: %s", data_dir)
        return []

    symbols = []
    for csv_file in sorted(data_dir.glob("*.csv")):
        stem = csv_file.stem  # e.g. "sh.600000" or "sz.000001"
        # 去掉 sh. / sz. 前缀
        if "." in stem:
            code = stem.split(".", 1)[1]
        else:
            code = stem
        symbols.append(code)
    return symbols


def load_local_stock(symbol: str) -> pd.DataFrame:
    """
    加载单只股票的本地 CSV 数据，并缓存为 parquet 格式。

    优先读取 data/cache/local/{symbol}.parquet 缓存；
    若缓存不存在，则读取 CSV 并写入缓存。

    Args:
        symbol (str): 6 位股票代码，例如 '600000'

    Returns:
        pd.DataFrame: 以日期为索引，包含 COLUMN_MAP 中所有可用字段的 DataFrame
    """
    cache_path = _CACHE_DIR / f"{symbol}.parquet"

    # 读缓存（带损坏检测）
    if cache_path.exists():
        try:
            df = pd.read_parquet(cache_path)
            return df
        except Exception:
            # 缓存损坏，删除后重建
            cache_path.unlink(missing_ok=True)

    # 查找 CSV 文件（尝试 sh. 和 sz. 前缀）
    data_dir = _get_local_data_dir()
    csv_path = None
    for prefix in ("sh", "sz"):
        candidate = data_dir / f"{prefix}.{symbol}.csv"
        if candidate.exists():
            csv_path = candidate
            break

    if csv_path is None:
        # 模糊匹配（以防命名规则不一致）
        matches = list(data_dir.glob(f"*.{symbol}.csv"))
        if matches:
            csv_path = matches[0]

    if csv_path is None:
        raise FileNotFoundError(f"找不到股票 {symbol} 的本地 CSV 文件: {data_dir}")

    # 读 CSV（BOM 兼容）
    df = pd.read_csv(csv_path, encoding="utf-8-sig")

    # 重命名列
    df = df.rename(columns={k: v for k, v in COLUMN_MAP.items() if k in df.columns})

    # 解析日期并设为索引
    if "date" in df.columns:
        df["date"] = pd.to_datetime(df["date"])
        df = df.drop_duplicates(subset=["date"], keep="last")
        df = df.set_index("date").sort_index()

    # 写 parquet 缓存（原子写入：先写临时文件再 rename，防止中断导致损坏）
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        tmp_path = cache_path.with_suffix(".parquet.tmp")
        df.to_parquet(tmp_path)
        tmp_path.rename(cache_path)
    except Exception as exc:
        logger.warning("写 parquet 缓存失败 (%s): %s", symbol, exc)
        tmp_path.unlink(missing_ok=True)

    return df


def load_price_wide(
    symbols: list,
    start: str,
    end: str,
    field: str = "close",
) -> pd.DataFrame:
    """
    并行加载多只股票数据，返回宽表（日期 × 股票代码）。

    Args:
        symbols (list): 股票代码列表
        start (str): 开始日期，格式 'YYYY-MM-DD'
        end (str): 结束日期，格式 'YYYY-MM-DD'
        field (str): 要提取的字段，默认 'close'

    Returns:
        pd.DataFrame: 宽表，index 为日期，columns 为股票代码
    """
    def _load_one(sym):
        try:
            df = load_local_stock(sym)
            if field not in df.columns:
                return sym, None
            s = df[field]
            s = s.loc[start:end]
            return sym, s
        except Exception as exc:
            logger.warning("加载 %s 失败: %s", sym, exc)
            return sym, None

    with ThreadPoolExecutor(max_workers=16) as executor:
        results = list(executor.map(_load_one, symbols))

    series_dict = {sym: s for sym, s in results if s is not None}
    if not series_dict:
        return pd.DataFrame()

    wide = pd.DataFrame(series_dict)
    wide.index.name = "date"
    return wide


def load_adj_price_wide(
    symbols: list,
    start: str,
    end: str,
) -> pd.DataFrame:
    """
    从涨跌幅(pct_change)字段累积构建前复权调整价格宽表。

    本地 CSV 的 close 字段是不复权价格（复权状态=3），在权利落/送配股日
    会出现 -20%~-60% 的虚假单日跌幅。涨跌幅(pct_change)字段是 baostock
    已经处理过的实际日收益率（含分红再投资），不受此影响。

    此函数从涨跌幅累积复利，归一化到 100 作为起点，返回一个等效的
    "复权调整价格"宽表，专用于动量/波动率因子计算。

    **不能用于实际成交价格**（close 才是真实价格）。

    Args:
        symbols: 股票代码列表
        start: 开始日期，格式 'YYYY-MM-DD'
        end: 结束日期，格式 'YYYY-MM-DD'

    Returns:
        复权调整价格宽表 (date × symbol)，起始值约为 100

    使用场景:
        - enhanced_momentum / quality_momentum / ma_ratio_momentum
        - low_vol_20d / team_coin / amihud_illiquidity
        不适用: shadow_lower / bp_factor / ep_factor（这些用 close 或 fundamentals）
    """
    pct_wide = load_price_wide(symbols, start, end, field="pct_change")
    if pct_wide.empty:
        return pd.DataFrame()

    # 涨跌幅是百分比（如 -3.19 表示 -3.19%），转为小数
    ret_wide = pct_wide / 100.0

    # 累积复利，从首日开始，归一化起始值为 100
    # fillna(0) 处理缺失数据：停牌日等视为 0 收益
    adj = (1 + ret_wide.fillna(0)).cumprod() * 100.0

    # 恢复原始缺失位置（停牌日不应有价格）
    adj = adj.where(ret_wide.notna())
    adj.index.name = "date"
    return adj


def load_factor_wide(
    symbols: list,
    factor: str,
    start: str,
    end: str,
) -> pd.DataFrame:
    """
    加载多只股票的因子数据，返回宽表（日期 × 股票代码）。

    Args:
        symbols (list): 股票代码列表
        factor (str): 因子名称，可选: pe_ttm, pb, ps_ttm, pcf, turnover
        start (str): 开始日期，格式 'YYYY-MM-DD'
        end (str): 结束日期，格式 'YYYY-MM-DD'

    Returns:
        pd.DataFrame: 宽表，index 为日期，columns 为股票代码

    Raises:
        ValueError: factor 不在合法字段列表中
    """
    if factor not in VALID_FACTORS:
        raise ValueError(f"factor 必须是 {VALID_FACTORS} 之一，收到: {factor!r}")
    return load_price_wide(symbols, start, end, field=factor)


def get_hs300_symbols() -> list:
    """
    获取沪深 300 成分股代码列表（6 位数字）。

    优先通过 akshare 接口查询，失败时降级为本地前 300 只股票并打印警告。

    Returns:
        list: 6 位股票代码列表
    """
    try:
        import akshare as ak
        df = ak.index_stock_cons_weight_csindex(symbol="000300")
        # 提取 6 位代码列（优先匹配 '成分券代码'，避免匹配到 '指数代码'）
        code_col = None
        if "成分券代码" in df.columns:
            code_col = "成分券代码"
        else:
            for col in df.columns:
                if col != "指数代码" and ("代码" in col or "code" in col.lower()):
                    code_col = col
                    break
        if code_col is None:
            code_col = df.columns[0]
        codes = df[code_col].astype(str).str.zfill(6).tolist()
        return codes
    except Exception as exc:
        warnings.warn(
            f"akshare 获取沪深 300 成分股失败，降级为本地前 300 只: {exc}",
            stacklevel=2,
        )
        logger.warning("get_hs300_symbols 降级: %s", exc)
        return get_all_symbols()[:300]


if __name__ == "__main__":
    syms = get_all_symbols()
    print(f"本地数据共 {len(syms)} 只股票")
    if syms:
        print(f"示例: {syms[:5]}")
