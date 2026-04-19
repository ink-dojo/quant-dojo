"""
Tushare 数据加载器

使用 jiaoch.site 镜像接口，需在本地 .env 中设置：
    TUSHARE_TOKEN=<你的 token>

或直接设置环境变量：
    export TUSHARE_TOKEN=<你的 token>

Token 不入 git，每台机器本地配置。
"""

import os
import time
import warnings
from pathlib import Path
from functools import lru_cache

import pandas as pd

_MIRROR_URL = "http://jiaoch.site"
_CACHE_DIR = Path(__file__).parent.parent / "data" / "raw" / "tushare"
_CACHE_DIR.mkdir(parents=True, exist_ok=True)


def _load_dotenv():
    """从项目根目录的 .env 加载环境变量（不依赖 python-dotenv）"""
    env_path = Path(__file__).parent.parent / ".env"
    if not env_path.exists():
        return
    with open(env_path) as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, _, val = line.partition("=")
                os.environ.setdefault(key.strip(), val.strip())


@lru_cache(maxsize=1)
def get_pro():
    """
    获取 tushare pro 实例（单例，指向 jiaoch.site 镜像）

    返回
    ----
    tushare DataApi 实例
    """
    _load_dotenv()
    token = os.environ.get("TUSHARE_TOKEN", "")
    if not token:
        raise EnvironmentError(
            "未找到 TUSHARE_TOKEN。\n"
            "请在项目根目录创建 .env 文件并写入：\n"
            "    TUSHARE_TOKEN=<你的 token>\n"
            "或运行：export TUSHARE_TOKEN=<你的 token>"
        )
    try:
        import tushare as ts
    except ImportError:
        raise ImportError("请先安装 tushare: pip install tushare==1.4.21")

    pro = ts.pro_api(token)
    pro._DataApi__token = token
    pro._DataApi__http_url = _MIRROR_URL
    return pro


# ─────────────────────────────────────────────
# 财务数据
# ─────────────────────────────────────────────

def get_cashflow(symbol: str, use_cache: bool = True) -> pd.DataFrame:
    """
    获取现金流量表（含真实公告日 f_ann_date）

    参数
    ----
    symbol   : 股票代码，如 "000001"（自动转换为 tushare 格式 000001.SZ）
    use_cache: 是否使用本地 parquet 缓存（7天 TTL）

    返回
    ----
    DataFrame，含 end_date（报告期）、f_ann_date（实际公告日）、
    n_cashflow_act（经营现金流）、n_incl_extra_pfc_indo（净利润）等
    """
    ts_code = _to_ts_code(symbol)
    cache_path = _CACHE_DIR / f"cashflow_{symbol}.parquet"

    if use_cache and cache_path.exists():
        age = (pd.Timestamp.now() - pd.Timestamp(cache_path.stat().st_mtime, unit="s")).days
        if age < 7:
            return pd.read_parquet(cache_path)

    pro = get_pro()
    try:
        df = pro.cashflow(ts_code=ts_code, fields=(
            "ts_code,ann_date,f_ann_date,end_date,report_type,"
            "n_cashflow_act,n_cash_flows_fnc_act,free_cashflow"
        ))
        time.sleep(0.2)
    except Exception as e:
        warnings.warn(f"[tushare] {symbol} cashflow 拉取失败: {e}")
        return pd.DataFrame()

    if df is not None and not df.empty:
        df["end_date"] = pd.to_datetime(df["end_date"], errors="coerce")
        df["f_ann_date"] = pd.to_datetime(df["f_ann_date"], errors="coerce")
        df["ann_date"] = pd.to_datetime(df["ann_date"], errors="coerce")
        df = df.dropna(subset=["end_date"]).sort_values("end_date")
        df.to_parquet(cache_path)
    return df if df is not None else pd.DataFrame()


def get_income(symbol: str, use_cache: bool = True) -> pd.DataFrame:
    """
    获取利润表（含实际公告日）

    关键列：end_date, f_ann_date, n_income_attr_p（归母净利润）,
            revenue（营业收入）, operate_profit（营业利润）
    """
    ts_code = _to_ts_code(symbol)
    cache_path = _CACHE_DIR / f"income_{symbol}.parquet"

    if use_cache and cache_path.exists():
        age = (pd.Timestamp.now() - pd.Timestamp(cache_path.stat().st_mtime, unit="s")).days
        if age < 7:
            return pd.read_parquet(cache_path)

    pro = get_pro()
    try:
        df = pro.income(ts_code=ts_code, fields=(
            "ts_code,ann_date,f_ann_date,end_date,report_type,"
            "revenue,operate_profit,n_income_attr_p,ebit,ebitda"
        ))
        time.sleep(0.2)
    except Exception as e:
        warnings.warn(f"[tushare] {symbol} income 拉取失败: {e}")
        return pd.DataFrame()

    if df is not None and not df.empty:
        df["end_date"] = pd.to_datetime(df["end_date"], errors="coerce")
        df["f_ann_date"] = pd.to_datetime(df["f_ann_date"], errors="coerce")
        df = df.dropna(subset=["end_date"]).sort_values("end_date")
        df.to_parquet(cache_path)
    return df if df is not None else pd.DataFrame()


def get_balancesheet(symbol: str, use_cache: bool = True) -> pd.DataFrame:
    """
    获取资产负债表

    关键列：end_date, f_ann_date, total_assets（总资产）,
            total_liab（总负债）, total_hldr_eqy_inc_min_int（所有者权益）
    """
    ts_code = _to_ts_code(symbol)
    cache_path = _CACHE_DIR / f"balance_{symbol}.parquet"

    if use_cache and cache_path.exists():
        age = (pd.Timestamp.now() - pd.Timestamp(cache_path.stat().st_mtime, unit="s")).days
        if age < 7:
            return pd.read_parquet(cache_path)

    pro = get_pro()
    try:
        df = pro.balancesheet(ts_code=ts_code, fields=(
            "ts_code,ann_date,f_ann_date,end_date,report_type,"
            "total_assets,total_liab,total_hldr_eqy_inc_min_int,"
            "money_cap,accounts_receiv"
        ))
        time.sleep(0.2)
    except Exception as e:
        warnings.warn(f"[tushare] {symbol} balancesheet 拉取失败: {e}")
        return pd.DataFrame()

    if df is not None and not df.empty:
        df["end_date"] = pd.to_datetime(df["end_date"], errors="coerce")
        df["f_ann_date"] = pd.to_datetime(df["f_ann_date"], errors="coerce")
        df = df.dropna(subset=["end_date"]).sort_values("end_date")
        df.to_parquet(cache_path)
    return df if df is not None else pd.DataFrame()


def get_fina_indicator(symbol: str, use_cache: bool = True) -> pd.DataFrame:
    """
    获取财务指标（ROE、毛利率、资产周转率等预计算指标）

    关键列：end_date, ann_date, roe（净资产收益率）, grossprofit_margin,
            debt_to_assets, current_ratio, fcff（自由现金流/营收）
    """
    ts_code = _to_ts_code(symbol)
    cache_path = _CACHE_DIR / f"fina_{symbol}.parquet"

    if use_cache and cache_path.exists():
        age = (pd.Timestamp.now() - pd.Timestamp(cache_path.stat().st_mtime, unit="s")).days
        if age < 7:
            return pd.read_parquet(cache_path)

    pro = get_pro()
    try:
        df = pro.fina_indicator(ts_code=ts_code, fields=(
            "ts_code,ann_date,end_date,eps,roe,roe_dt,roa,roic,"
            "grossprofit_margin,netprofit_margin,debt_to_assets,"
            "current_ratio,quick_ratio,fcff,revenue_ps"
        ))
        time.sleep(0.2)
    except Exception as e:
        warnings.warn(f"[tushare] {symbol} fina_indicator 拉取失败: {e}")
        return pd.DataFrame()

    if df is not None and not df.empty:
        df["end_date"] = pd.to_datetime(df["end_date"], errors="coerce")
        df["ann_date"] = pd.to_datetime(df["ann_date"], errors="coerce")
        df = df.dropna(subset=["end_date"]).sort_values("end_date")
        df.to_parquet(cache_path)
    return df if df is not None else pd.DataFrame()


# ─────────────────────────────────────────────
# 资金流向
# ─────────────────────────────────────────────

def get_moneyflow(symbol: str, start: str, end: str, use_cache: bool = True) -> pd.DataFrame:
    """
    获取个股资金流向（大/中/小单净流入）

    参数
    ----
    symbol : 股票代码，如 "000001"
    start  : 开始日期 YYYY-MM-DD
    end    : 结束日期 YYYY-MM-DD

    返回
    ----
    DataFrame，关键列：
        trade_date, buy_lg_amount（大单买入额，万元）, sell_lg_amount,
        buy_md_amount（中单）, sell_md_amount,
        net_mf_amount（净流入总额，万元）
    """
    ts_code = _to_ts_code(symbol)
    sd = start.replace("-", "")
    ed = end.replace("-", "")
    cache_path = _CACHE_DIR / f"moneyflow_{symbol}_{sd}_{ed}.parquet"

    if use_cache and cache_path.exists():
        return pd.read_parquet(cache_path)

    pro = get_pro()
    try:
        df = pro.moneyflow(
            ts_code=ts_code,
            start_date=sd,
            end_date=ed,
        )
        time.sleep(0.2)
    except Exception as e:
        warnings.warn(f"[tushare] {symbol} moneyflow 拉取失败: {e}")
        return pd.DataFrame()

    if df is not None and not df.empty:
        df["trade_date"] = pd.to_datetime(df["trade_date"], errors="coerce")
        df = df.sort_values("trade_date")
        df.to_parquet(cache_path)
    return df if df is not None else pd.DataFrame()


def get_moneyflow_hsgt(start: str, end: str) -> pd.DataFrame:
    """
    获取北向资金每日汇总（沪股通 + 深股通净流入，亿元）

    返回
    ----
    DataFrame，列：trade_date, hgt（沪股通净流入）, sgt（深股通）,
                   north_money（北向合计）, south_money（南向合计）
    """
    sd = start.replace("-", "")
    ed = end.replace("-", "")
    pro = get_pro()
    try:
        df = pro.moneyflow_hsgt(start_date=sd, end_date=ed)
        time.sleep(0.2)
    except Exception as e:
        warnings.warn(f"[tushare] moneyflow_hsgt 拉取失败: {e}")
        return pd.DataFrame()

    if df is not None and not df.empty:
        df["trade_date"] = pd.to_datetime(df["trade_date"], errors="coerce")
        df = df.sort_values("trade_date")
    return df if df is not None else pd.DataFrame()


# ─────────────────────────────────────────────
# 事件数据
# ─────────────────────────────────────────────

def get_top_list(trade_date: str) -> pd.DataFrame:
    """龙虎榜（单日）"""
    td = trade_date.replace("-", "")
    pro = get_pro()
    try:
        df = pro.top_list(trade_date=td)
        time.sleep(0.2)
        return df if df is not None else pd.DataFrame()
    except Exception as e:
        warnings.warn(f"[tushare] top_list {trade_date} 失败: {e}")
        return pd.DataFrame()


def get_share_float(symbol: str) -> pd.DataFrame:
    """限售股解禁计划"""
    ts_code = _to_ts_code(symbol)
    pro = get_pro()
    try:
        df = pro.share_float(ts_code=ts_code)
        time.sleep(0.2)
        return df if df is not None else pd.DataFrame()
    except Exception as e:
        warnings.warn(f"[tushare] share_float {symbol} 失败: {e}")
        return pd.DataFrame()


def get_repurchase(ann_date: str = None, start: str = None, end: str = None) -> pd.DataFrame:
    """股票回购公告"""
    pro = get_pro()
    kwargs = {}
    if ann_date:
        kwargs["ann_date"] = ann_date.replace("-", "")
    if start:
        kwargs["start_date"] = start.replace("-", "")
    if end:
        kwargs["end_date"] = end.replace("-", "")
    try:
        df = pro.repurchase(**kwargs)
        time.sleep(0.2)
        return df if df is not None else pd.DataFrame()
    except Exception as e:
        warnings.warn(f"[tushare] repurchase 失败: {e}")
        return pd.DataFrame()


def get_disclosure_date(symbol: str, end_date: str) -> pd.DataFrame:
    """
    获取财报实际公告日（解决前视偏差的精确处理）

    返回
    ----
    DataFrame，列：ts_code, ann_date（预计公告日）, end_date（报告期），
                   actual_date（实际公告日）
    用 actual_date 替代 shift(1) 可消除前视偏差。
    """
    ts_code = _to_ts_code(symbol)
    pro = get_pro()
    try:
        df = pro.disclosure_date(ts_code=ts_code, end_date=end_date.replace("-", ""))
        time.sleep(0.2)
        return df if df is not None else pd.DataFrame()
    except Exception as e:
        warnings.warn(f"[tushare] disclosure_date {symbol} 失败: {e}")
        return pd.DataFrame()


# ─────────────────────────────────────────────
# 工具函数
# ─────────────────────────────────────────────

def get_stock_basic() -> pd.DataFrame:
    """获取 A 股基本信息（代码、名称、行业、上市日期）"""
    pro = get_pro()
    df = pro.stock_basic(list_status="L", fields="ts_code,name,industry,list_date,market")
    return df if df is not None else pd.DataFrame()


def _to_ts_code(symbol: str) -> str:
    """将 6 位代码转换为 tushare 格式（000001 → 000001.SZ，600000 → 600000.SH）"""
    symbol = str(symbol).zfill(6)
    if symbol.startswith("6"):
        return f"{symbol}.SH"
    elif symbol.startswith(("4", "8")):
        return f"{symbol}.BJ"
    else:
        return f"{symbol}.SZ"


# ─────────────────────────────────────────────
# 最小验证
# ─────────────────────────────────────────────

if __name__ == "__main__":
    print("验证 tushare_loader（需要本地 .env 中有 TUSHARE_TOKEN）...")

    pro = get_pro()
    print("✅ pro 实例获取成功")

    # 交易日历
    cal = pro.trade_cal(exchange="SSE", start_date="20250101", end_date="20250105")
    assert len(cal) > 0
    print(f"✅ trade_cal: {len(cal)} 条")

    # 财务数据
    cf = get_cashflow("000001")
    print(f"✅ cashflow(000001): {cf.shape}, 含公告日: {'f_ann_date' in cf.columns}")

    fi = get_fina_indicator("000001")
    print(f"✅ fina_indicator(000001): {fi.shape}")

    # 北向资金
    nb = get_moneyflow_hsgt("2025-01-01", "2025-01-10")
    print(f"✅ moneyflow_hsgt: {nb.shape}")

    print("\n✅ tushare_loader 验证通过")
    print("其他机器使用方法：")
    print("  1. 在项目根目录创建 .env 文件")
    print("  2. 写入：TUSHARE_TOKEN=<token>")
    print("  3. from utils.tushare_loader import get_pro, get_cashflow")
