"""
股票池（Universe）管理

支持指数成分股、全 A 股等多种股票池构建方式。
所有函数返回标准化的 6 位股票代码（如 "000001"）。
"""
import pandas as pd
import akshare as ak
from pathlib import Path

PROCESSED_DIR = Path(__file__).parent.parent / "data" / "processed"

# ─────────────────────────────────────────────
# 指数成分股
# ─────────────────────────────────────────────

INDEX_MAP = {
    "csi300":  "000300",   # 沪深300
    "csi500":  "000905",   # 中证500
    "csi1000": "000852",   # 中证1000
    "sse50":   "000016",   # 上证50
}


def get_index_components(index: str = "csi500") -> pd.DataFrame:
    """
    获取指数成分股列表

    参数:
        index: 'csi300' | 'csi500' | 'csi1000' | 'sse50'，或直接传6位指数代码

    返回:
        DataFrame，含 symbol（6位）、name、weight 列
    """
    code = INDEX_MAP.get(index, index)
    df = ak.index_stock_cons_weight_csindex(symbol=code)

    # 标准化列名（akshare 返回的列名可能因版本而异）
    rename = {}
    for col in df.columns:
        if any(k in col for k in ["代码", "成分券代码"]):
            rename[col] = "symbol"
        elif any(k in col for k in ["名称", "成分券名称"]):
            rename[col] = "name"
        elif any(k in col for k in ["权重", "占比"]):
            rename[col] = "weight"
    df = df.rename(columns=rename)

    if "symbol" in df.columns:
        df["symbol"] = df["symbol"].astype(str).str.zfill(6)

    return df[["symbol", "name", "weight"] if "weight" in df.columns else ["symbol", "name"]]


def get_all_ashare_symbols() -> pd.DataFrame:
    """
    获取全部 A 股股票代码列表（上交所 + 深交所主板/创业板）

    返回:
        DataFrame，含 symbol（6位）、name、exchange 列
    """
    # 用实时行情接口——最可靠，包含所有在市 A 股
    df = ak.stock_zh_a_spot_em()

    rename = {}
    for col in df.columns:
        if col in ("代码", "股票代码"):
            rename[col] = "symbol"
        elif col in ("名称", "股票名称"):
            rename[col] = "name"
    df = df.rename(columns=rename)

    df["symbol"] = df["symbol"].astype(str).str.zfill(6)

    # 推断交易所：6/9 开头 → SH，0/2/3 开头 → SZ
    df["exchange"] = df["symbol"].apply(
        lambda s: "SH" if s[0] in ("6", "9") else "SZ"
    )

    return df[["symbol", "name", "exchange"]].drop_duplicates("symbol").reset_index(drop=True)


# ─────────────────────────────────────────────
# 股票池构建入口
# ─────────────────────────────────────────────

def build_universe(
    mode: str = "csi500",
    custom_symbols: list = None,
) -> list:
    """
    构建研究用股票池，返回有序股票代码列表

    参数:
        mode: 'csi300' | 'csi500' | 'csi1000' | 'sse50' | 'all' | 'custom'
        custom_symbols: mode='custom' 时传入代码列表

    返回:
        list[str]，6位代码，已排序
    """
    if mode in INDEX_MAP or (len(mode) == 6 and mode.isdigit()):
        df = get_index_components(mode)
        symbols = sorted(df["symbol"].tolist())
        print(f"✅ {mode} 成分股: {len(symbols)} 只")
        return symbols

    elif mode == "all":
        df = get_all_ashare_symbols()
        symbols = sorted(df["symbol"].tolist())
        print(f"✅ 全 A 股: {len(symbols)} 只")
        return symbols

    elif mode == "custom":
        if not custom_symbols:
            raise ValueError("mode='custom' 时 custom_symbols 不能为空")
        symbols = sorted([str(s).zfill(6) for s in custom_symbols])
        print(f"✅ 自定义股票池: {len(symbols)} 只")
        return symbols

    else:
        raise ValueError(
            f"未知 mode: '{mode}'，可选: csi300 / csi500 / csi1000 / sse50 / all / custom"
        )


# ─────────────────────────────────────────────
# ST 股过滤（简单版：名称含 ST/退 则排除）
# ─────────────────────────────────────────────

def filter_st(symbols: list, name_map: dict = None) -> list:
    """
    过滤 ST / *ST / 退市股

    参数:
        symbols  : 股票代码列表
        name_map : {symbol: name} 映射；为 None 时自动从实时行情获取

    返回:
        过滤后的代码列表
    """
    if name_map is None:
        df = ak.stock_zh_a_spot_em()
        code_col = "代码" if "代码" in df.columns else "股票代码"
        name_col = "名称" if "名称" in df.columns else "股票名称"
        df[code_col] = df[code_col].astype(str).str.zfill(6)
        name_map = dict(zip(df[code_col], df[name_col]))

    filtered = [
        s for s in symbols
        if not any(kw in name_map.get(s, "") for kw in ["ST", "退", "退市"])
    ]
    removed = len(symbols) - len(filtered)
    if removed:
        print(f"⚠ 过滤 ST/退市股 {removed} 只，剩余 {len(filtered)} 只")
    return filtered
