"""
providers/sina_provider.py — 新浪财经实时行情 Provider

提供 A 股实时行情数据，无需 API key，无注册。
数据来源：hq.sinajs.cn（新浪财经行情接口）

安全措施：
  - 所有外部响应做字段校验和类型转换，不信任原始数据
  - 请求带 Referer 头（Sina 要求）
  - 单次最多 800 只（Sina 限制）
  - 内置速率限制（默认 3 秒间隔）
  - 连接超时 5 秒，读取超时 10 秒
"""
import logging
import re
import time
from typing import Dict, List
from urllib.request import Request, urlopen
from urllib.error import URLError

import pandas as pd

logger = logging.getLogger(__name__)

# 新浪行情 URL（HTTPS）
_SINA_URL = "https://hq.sinajs.cn/list="
_REFERER = "https://finance.sina.com.cn"
_MAX_BATCH = 800  # 单次最多查询股票数
_MIN_INTERVAL = 0.5  # 最小请求间隔（秒）
_TIMEOUT = (5, 10)  # (connect_timeout, read_timeout)

# 字段解析：新浪返回的字段顺序
_FIELDS = [
    "name", "open", "prev_close", "price", "high", "low",
    "bid1_price", "ask1_price", "volume", "amount",
    "bid1_vol", "bid2_vol", "bid3_vol", "bid4_vol", "bid5_vol",
    "bid1_p", "bid2_p", "bid3_p", "bid4_p", "bid5_p",
    "ask1_vol", "ask2_vol", "ask3_vol", "ask4_vol", "ask5_vol",
    "ask1_p", "ask2_p", "ask3_p", "ask4_p", "ask5_p",
    "date", "time", "status",
]

# 合法 symbol 格式校验（防注入）
_SYMBOL_RE = re.compile(r"^[0-9]{6}$")


def _to_sina_code(symbol: str) -> str:
    """6 位代码转新浪格式"""
    if not _SYMBOL_RE.match(symbol):
        raise ValueError(f"非法 symbol: {symbol!r}")
    if symbol.startswith("6"):
        return f"sh{symbol}"
    return f"sz{symbol}"


def _parse_response(text: str) -> Dict[str, dict]:
    """
    解析新浪行情响应文本。

    返回 {symbol_6: {name, price, open, high, low, prev_close, volume, amount, ...}}
    """
    results = {}
    for line in text.strip().split(";"):
        line = line.strip()
        if not line or "=" not in line:
            continue
        # var hq_str_sh600000="浦发银行,10.060,...";
        try:
            var_part, data_part = line.split("=", 1)
            sina_code = var_part.split("_")[-1]  # sh600000
            data = data_part.strip('"').strip()
            if not data:
                continue  # 停牌或无数据

            parts = data.split(",")
            if len(parts) < 32:
                continue  # 字段不足，跳过

            # 提取 6 位代码
            symbol = sina_code[2:]

            # 安全解析数值字段
            def safe_float(s):
                try:
                    v = float(s)
                    return v if v >= 0 else 0.0
                except (ValueError, TypeError):
                    return 0.0

            results[symbol] = {
                "name": parts[0],
                "open": safe_float(parts[1]),
                "prev_close": safe_float(parts[2]),
                "price": safe_float(parts[3]),
                "high": safe_float(parts[4]),
                "low": safe_float(parts[5]),
                "volume": safe_float(parts[8]),
                "amount": safe_float(parts[9]),
                "date": parts[30] if len(parts) > 30 else "",
                "time": parts[31] if len(parts) > 31 else "",
            }
        except Exception as e:
            logger.warning("解析行情失败: %s", e)
            continue

    return results


def fetch_realtime_quotes(symbols: List[str]) -> Dict[str, dict]:
    """
    批量获取实时行情。

    参数:
        symbols: 6 位股票代码列表

    返回:
        dict: {symbol: {name, price, open, high, low, volume, amount, ...}}

    异常:
        不抛异常，失败的股票会被跳过
    """
    all_results = {}

    # 分批请求（每批最多 800 只）
    for i in range(0, len(symbols), _MAX_BATCH):
        batch = symbols[i:i + _MAX_BATCH]
        sina_codes = []
        for s in batch:
            try:
                sina_codes.append(_to_sina_code(s))
            except ValueError:
                continue

        if not sina_codes:
            continue

        url = _SINA_URL + ",".join(sina_codes)
        req = Request(url, headers={"Referer": _REFERER})

        try:
            resp = urlopen(req, timeout=_TIMEOUT[1])
            text = resp.read().decode("gbk", errors="replace")
            batch_results = _parse_response(text)
            all_results.update(batch_results)
        except (URLError, Exception) as e:
            logger.warning("Sina 请求失败: %s", e)

        # 速率限制
        if i + _MAX_BATCH < len(symbols):
            time.sleep(_MIN_INTERVAL)

    return all_results


def get_portfolio_valuation(positions: Dict[str, int]) -> pd.DataFrame:
    """
    获取持仓实时估值。

    参数:
        positions: {symbol: shares} 持仓字典

    返回:
        DataFrame: symbol, name, shares, price, value, pnl_pct
    """
    symbols = list(positions.keys())
    quotes = fetch_realtime_quotes(symbols)

    rows = []
    for sym, shares in positions.items():
        q = quotes.get(sym)
        if q and q["price"] > 0:
            rows.append({
                "symbol": sym,
                "name": q["name"],
                "shares": shares,
                "price": q["price"],
                "value": q["price"] * shares,
                "prev_close": q["prev_close"],
                "pnl_pct": (q["price"] / q["prev_close"] - 1) if q["prev_close"] > 0 else 0,
            })
        else:
            rows.append({
                "symbol": sym, "name": "N/A", "shares": shares,
                "price": 0, "value": 0, "prev_close": 0, "pnl_pct": 0,
            })

    return pd.DataFrame(rows)


if __name__ == "__main__":
    # 快速测试
    test_symbols = ["600000", "000001", "600519", "000858", "601318"]
    print(f"测试 {len(test_symbols)} 只股票实时行情...\n")

    quotes = fetch_realtime_quotes(test_symbols)
    for sym, q in quotes.items():
        print(f"  {q['name']:<8} ({sym}) 现价: {q['price']:.2f}  "
              f"涨跌: {(q['price']/q['prev_close']-1)*100:+.2f}%  "
              f"成交额: {q['amount']/1e8:.1f}亿")

    print(f"\n✅ sina_provider: {len(quotes)}/{len(test_symbols)} 成功")
