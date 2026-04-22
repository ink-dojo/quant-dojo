"""
Tushare 全量数据批量下载脚本
=============================

使用前提
--------
1. 在项目根目录创建 .env 文件，写入：
       TUSHARE_TOKEN=<你的 token>
2. 安装依赖：
       pip install tushare==1.4.21 pandas pyarrow

运行方式
--------
    # 下载全部（推荐，约 1.6 GB，3线程约 1.5 小时）
    python scripts/bulk_download_tushare.py

    # 只下载特定模块
    python scripts/bulk_download_tushare.py --modules financial daily_basic moneyflow

    # 指定并发线程数（默认 3，不要超过 5，会触发限速）
    python scripts/bulk_download_tushare.py --workers 3

可用模块（--modules 参数）
--------------------------
    financial       财务四张表（现金流/利润/资产负债/财务指标），含真实公告日
    daily_basic     每日行情指标（PE/PB/总市值/流通市值），价值因子必备
    adj_factor      复权因子
    moneyflow       个股资金流向（大/中/小单净流入），5年历史
    margin          融资融券明细（融资余额/融券余量），5年历史
    northbound      北向持股个股快照历史（沪股通+深股通合并）
    dividend        分红历史
    share_float     限售解禁计划
    holder_num      股东人数变化（季度）
    top_list        龙虎榜明细+机构席位（按日期，2015-2025）
    block_trade     大宗交易记录（按日期，2015-2025）
    repurchase      股票回购公告
    index_data      主要指数日线行情（沪深300/中证500等）
    index_weight    指数成分权重历史（沪深300/中证500）
    northbound_agg  北向资金每日汇总（大盘择时参考）

数据存储位置
-----------
    data/raw/tushare/
    ├── financial/
    │   ├── cashflow_000001.parquet
    │   ├── income_000001.parquet
    │   ├── balancesheet_000001.parquet
    │   └── fina_indicator_000001.parquet
    ├── daily_basic/
    │   └── daily_basic_000001.parquet
    ├── adj_factor/
    │   └── adj_factor_000001.parquet
    ├── moneyflow/
    │   └── moneyflow_000001.parquet
    ├── margin/
    │   └── margin_000001.parquet
    ├── northbound/
    │   └── hk_hold_000001.parquet
    ├── dividend/
    │   └── dividend_000001.parquet
    ├── share_float/
    │   └── share_float_000001.parquet
    ├── holder_num/
    │   └── holder_num_000001.parquet
    ├── events/
    │   ├── top_list_20241231.parquet
    │   ├── top_inst_20241231.parquet
    │   └── block_trade_20241231.parquet
    ├── repurchase.parquet
    ├── northbound_agg.parquet
    ├── index_daily_000300.parquet
    └── index_weight_000300.parquet

使用下载好的数据
--------------
    import pandas as pd
    from pathlib import Path

    DATA = Path("data/raw/tushare")

    # 读某只股票的每日PE/PB/市值
    df = pd.read_parquet(DATA / "daily_basic/daily_basic_000001.parquet")

    # 读现金流量表（含真实公告日 f_ann_date）
    cf = pd.read_parquet(DATA / "financial/cashflow_000001.parquet")

    # 批量读取所有股票的财务指标
    import glob
    all_fi = pd.concat([pd.read_parquet(f) for f in glob.glob(str(DATA / "financial/fina_indicator_*.parquet"))])
"""

import os
import sys
import time
import argparse
import warnings
import logging
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime

import pandas as pd

warnings.filterwarnings("ignore")

# ─────────────────────────────────────────────
# 配置
# ─────────────────────────────────────────────

ROOT = Path(__file__).parent.parent
DATA_DIR = ROOT / "data" / "raw" / "tushare"

HISTORY_START = "20100101"   # 财务数据历史起点
PRICE_START   = "20140101"   # 行情数据起点（有前复权数据）
RECENT_START  = "20200101"   # 资金流向等起点（5年）
END_DATE      = datetime.now().strftime("%Y%m%d")

SLEEP_PER_CALL = 0.25        # 每次 API 调用间隔（秒），不要低于 0.2

# 主要指数列表
INDEX_CODES = {
    "000300.SH": "沪深300",
    "000905.SH": "中证500",
    "000852.SH": "中证1000",
    "000016.SH": "上证50",
    "399001.SZ": "深证成指",
    "399006.SZ": "创业板",
    "000688.SH": "科创50",
}

INDEX_WEIGHT_CODES = {
    "399300.SZ": "沪深300",
    "399905.SZ": "中证500",
}

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger(__name__)


# ─────────────────────────────────────────────
# Tushare 连接
# ─────────────────────────────────────────────

def _load_dotenv():
    env_path = ROOT / ".env"
    if not env_path.exists():
        return
    with open(env_path) as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, _, v = line.partition("=")
                os.environ.setdefault(k.strip(), v.strip())


def get_pro():
    _load_dotenv()
    token = os.environ.get("TUSHARE_TOKEN", "")
    if not token:
        sys.exit(
            "❌ 未找到 TUSHARE_TOKEN。\n"
            "请在项目根目录创建 .env 文件并写入：\n"
            "    TUSHARE_TOKEN=<你的 token>"
        )
    try:
        import tushare as ts
    except ImportError:
        sys.exit("❌ 请先安装 tushare: pip install tushare==1.4.21")

    pro = ts.pro_api(token)
    pro._DataApi__token = token
    pro._DataApi__http_url = "http://jiaoch.site"
    return pro


# ─────────────────────────────────────────────
# 通用工具
# ─────────────────────────────────────────────

def _to_ts_code(symbol: str) -> str:
    s = str(symbol).zfill(6)
    if s.startswith("6"):
        return f"{s}.SH"
    elif s.startswith(("4", "8")):
        return f"{s}.BJ"
    return f"{s}.SZ"


def _save(df: pd.DataFrame, path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(path, index=False)


def _already_done(path: Path) -> bool:
    """已下载且文件非空则跳过"""
    return path.exists() and path.stat().st_size > 500


def _get_all_symbols(pro) -> list:
    """获取全部在市 A 股代码"""
    df = pro.stock_basic(list_status="L", fields="ts_code,name,list_date")
    time.sleep(SLEEP_PER_CALL)
    return df["ts_code"].tolist()


def _progress(done, total, name=""):
    pct = done / total * 100
    bar = "█" * int(pct / 2) + "░" * (50 - int(pct / 2))
    print(f"\r  [{bar}] {done}/{total} {pct:.0f}% {name:<20}", end="", flush=True)


# ─────────────────────────────────────────────
# 模块：财务四张表
# ─────────────────────────────────────────────

def download_financial(pro, symbols, workers=3):
    """
    财务四张表：现金流量表、利润表、资产负债表、财务指标
    关键字段：f_ann_date（实际公告日，用于精确防前视偏差）
    存储：data/raw/tushare/financial/{table}_{symbol}.parquet
    """
    log.info(f"=== 财务四张表 ({len(symbols)} 只股票) ===")
    out = DATA_DIR / "financial"

    table_configs = [
        ("cashflow", lambda ts: pro.cashflow(
            ts_code=ts,
            fields="ts_code,ann_date,f_ann_date,end_date,report_type,"
                   "n_cashflow_act,n_cash_flows_fnc_act,free_cashflow,"
                   "c_pay_acq_const_fiolta,n_incr_cash_cash_equ"
        )),
        ("income", lambda ts: pro.income(
            ts_code=ts,
            fields="ts_code,ann_date,f_ann_date,end_date,report_type,"
                   "revenue,operate_profit,n_income_attr_p,ebit,ebitda,"
                   "basic_eps,diluted_eps,total_revenue"
        )),
        ("balancesheet", lambda ts: pro.balancesheet(
            ts_code=ts,
            fields="ts_code,ann_date,f_ann_date,end_date,report_type,"
                   "total_assets,total_liab,total_hldr_eqy_inc_min_int,"
                   "money_cap,accounts_receiv,inventories,fix_assets"
        )),
        ("fina_indicator", lambda ts: pro.fina_indicator(
            ts_code=ts,
            fields="ts_code,ann_date,end_date,eps,roe,roe_dt,roa,roic,"
                   "grossprofit_margin,netprofit_margin,debt_to_assets,"
                   "current_ratio,quick_ratio,fcff,revenue_ps,"
                   "assets_turn,inv_turn,ar_turn,op_yoy"
        )),
    ]

    def _fetch_one(ts_code):
        symbol = ts_code.split(".")[0]
        results = []
        for tname, fn in table_configs:
            path = out / f"{tname}_{symbol}.parquet"
            if _already_done(path):
                results.append((tname, "skip"))
                continue
            try:
                df = fn(ts_code)
                time.sleep(SLEEP_PER_CALL)
                if df is not None and not df.empty:
                    _save(df, path)
                    results.append((tname, len(df)))
                else:
                    results.append((tname, 0))
            except Exception as e:
                results.append((tname, f"err:{e}"))
        return ts_code, results

    done = 0
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futs = {pool.submit(_fetch_one, sym): sym for sym in symbols}
        for fut in as_completed(futs):
            done += 1
            sym, res = fut.result()
            _progress(done, len(symbols), sym)
    print()
    log.info("财务四张表 完成")


# ─────────────────────────────────────────────
# 模块：每日行情指标（PE/PB/市值）
# ─────────────────────────────────────────────

def download_daily_basic(pro, symbols, workers=3):
    """
    每日行情指标：PE/PB/PS/总市值/流通市值/换手率等
    用途：价值因子（EP/BP）、市值因子（市值中性化）、流动性指标
    存储：data/raw/tushare/daily_basic/{symbol}.parquet
    """
    log.info(f"=== 每日行情指标 ({len(symbols)} 只股票) ===")
    out = DATA_DIR / "daily_basic"

    def _fetch(ts_code):
        symbol = ts_code.split(".")[0]
        path = out / f"{symbol}.parquet"
        if _already_done(path):
            return "skip"
        try:
            df = pro.daily_basic(
                ts_code=ts_code,
                start_date=PRICE_START,
                end_date=END_DATE,
                fields="ts_code,trade_date,close,turnover_rate,turnover_rate_f,"
                       "volume_ratio,pe,pe_ttm,pb,ps,ps_ttm,dv_ratio,dv_ttm,"
                       "total_share,float_share,total_mv,circ_mv"
            )
            time.sleep(SLEEP_PER_CALL)
            if df is not None and not df.empty:
                _save(df, path)
                return len(df)
            return 0
        except Exception as e:
            return f"err:{e}"

    done = 0
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futs = {pool.submit(_fetch, sym): sym for sym in symbols}
        for fut in as_completed(futs):
            done += 1
            _progress(done, len(symbols), futs[fut])
    print()
    log.info("每日行情指标 完成")


# ─────────────────────────────────────────────
# 模块：复权因子
# ─────────────────────────────────────────────

def download_adj_factor(pro, symbols, workers=3):
    """
    复权因子：用于将不复权价格转换为前复权价格
    存储：data/raw/tushare/adj_factor/{symbol}.parquet
    """
    log.info(f"=== 复权因子 ({len(symbols)} 只股票) ===")
    out = DATA_DIR / "adj_factor"

    def _fetch(ts_code):
        symbol = ts_code.split(".")[0]
        path = out / f"{symbol}.parquet"
        if _already_done(path):
            return "skip"
        try:
            df = pro.adj_factor(ts_code=ts_code, start_date=PRICE_START, end_date=END_DATE)
            time.sleep(SLEEP_PER_CALL)
            if df is not None and not df.empty:
                _save(df, path)
                return len(df)
            return 0
        except Exception as e:
            return f"err:{e}"

    done = 0
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futs = {pool.submit(_fetch, sym): sym for sym in symbols}
        for fut in as_completed(futs):
            done += 1
            _progress(done, len(symbols), "")
    print()
    log.info("复权因子 完成")


# ─────────────────────────────────────────────
# 模块：个股资金流向
# ─────────────────────────────────────────────

def download_moneyflow(pro, symbols, workers=3):
    """
    个股资金流向：大/中/小单买卖金额，主力净流入
    用途：机构资金因子（大单净流入/流通市值）、散户情绪指标
    关键列：buy_lg_amount（大单买入），net_mf_amount（净流入）
    存储：data/raw/tushare/moneyflow/{symbol}.parquet
    """
    log.info(f"=== 个股资金流向 ({len(symbols)} 只股票) ===")
    out = DATA_DIR / "moneyflow"

    def _fetch(ts_code):
        symbol = ts_code.split(".")[0]
        path = out / f"{symbol}.parquet"
        if _already_done(path):
            return "skip"
        try:
            df = pro.moneyflow(ts_code=ts_code, start_date=RECENT_START, end_date=END_DATE)
            time.sleep(SLEEP_PER_CALL)
            if df is not None and not df.empty:
                _save(df, path)
                return len(df)
            return 0
        except Exception as e:
            return f"err:{e}"

    done = 0
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futs = {pool.submit(_fetch, sym): sym for sym in symbols}
        for fut in as_completed(futs):
            done += 1
            _progress(done, len(symbols), "")
    print()
    log.info("资金流向 完成")


# ─────────────────────────────────────────────
# 模块：融资融券
# ─────────────────────────────────────────────

def download_margin(pro, symbols, workers=3):
    """
    融资融券明细：每日融资余额/融券余量
    用途：融资比例因子（融资买入/流通市值）、空头情绪指标
    关键列：rzye（融资余额）, rqye（融券余额）, rzmre（融资买入额）
    存储：data/raw/tushare/margin/{symbol}.parquet
    """
    log.info(f"=== 融资融券 ({len(symbols)} 只股票) ===")
    out = DATA_DIR / "margin"

    def _fetch(ts_code):
        symbol = ts_code.split(".")[0]
        path = out / f"{symbol}.parquet"
        if _already_done(path):
            return "skip"
        try:
            df = pro.margin_detail(ts_code=ts_code, start_date=RECENT_START, end_date=END_DATE)
            time.sleep(SLEEP_PER_CALL)
            if df is not None and not df.empty:
                _save(df, path)
                return len(df)
            return 0
        except Exception as e:
            return f"err:{e}"

    done = 0
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futs = {pool.submit(_fetch, sym): sym for sym in symbols}
        for fut in as_completed(futs):
            done += 1
            _progress(done, len(symbols), "")
    print()
    log.info("融资融券 完成")


# ─────────────────────────────────────────────
# 模块：北向持股个股
# ─────────────────────────────────────────────

def download_northbound(pro, symbols, workers=2):
    """
    北向持股个股快照：每日外资持股数量/持股市值
    用途：北向资金因子（Δ持股比例/N日），外资增减持信号
    关键列：trade_date, ts_code, vol（持股量）, ratio（持股占A股比例）
    注意：只有纳入沪深港通的股票才有数据（约1500只）
    存储：data/raw/tushare/northbound/{symbol}.parquet
    """
    log.info(f"=== 北向持股 ({len(symbols)} 只股票，无数据的会跳过) ===")
    out = DATA_DIR / "northbound"

    def _fetch(ts_code):
        symbol = ts_code.split(".")[0]
        path = out / f"{symbol}.parquet"
        if _already_done(path):
            return "skip"
        try:
            df = pro.hk_hold(ts_code=ts_code, start_date=RECENT_START, end_date=END_DATE)
            time.sleep(SLEEP_PER_CALL)
            if df is not None and not df.empty:
                _save(df, path)
                return len(df)
            return 0  # 不在陆股通范围内，正常跳过
        except Exception as e:
            return f"err:{e}"

    done = 0
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futs = {pool.submit(_fetch, sym): sym for sym in symbols}
        for fut in as_completed(futs):
            done += 1
            _progress(done, len(symbols), "")
    print()
    log.info("北向持股 完成")


# ─────────────────────────────────────────────
# 模块：分红历史
# ─────────────────────────────────────────────

def download_dividend(pro, symbols, workers=3):
    """
    分红历史：每次分红的现金股息/股票股息
    用途：股息率因子（年化现金分红/股价）
    关键列：end_date（分红所属报告期）, cash_div（每股现金股息）
    存储：data/raw/tushare/dividend/{symbol}.parquet
    """
    log.info(f"=== 分红历史 ({len(symbols)} 只股票) ===")
    out = DATA_DIR / "dividend"

    def _fetch(ts_code):
        symbol = ts_code.split(".")[0]
        path = out / f"{symbol}.parquet"
        if _already_done(path):
            return "skip"
        try:
            df = pro.dividend(ts_code=ts_code)
            time.sleep(SLEEP_PER_CALL)
            if df is not None and not df.empty:
                _save(df, path)
                return len(df)
            return 0
        except Exception as e:
            return f"err:{e}"

    done = 0
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futs = {pool.submit(_fetch, sym): sym for sym in symbols}
        for fut in as_completed(futs):
            done += 1
            _progress(done, len(symbols), "")
    print()
    log.info("分红历史 完成")


# ─────────────────────────────────────────────
# 模块：限售解禁
# ─────────────────────────────────────────────

def download_share_float(pro, symbols, workers=3):
    """
    限售股解禁计划：未来各日期将解禁的股份数量
    用途：解禁压力因子（解禁量/流通市值），event driven 策略
    关键列：float_date（解禁日期）, float_share（解禁数量）, float_ratio（解禁比例）
    存储：data/raw/tushare/share_float/{symbol}.parquet
    """
    log.info(f"=== 限售解禁 ({len(symbols)} 只股票) ===")
    out = DATA_DIR / "share_float"

    def _fetch(ts_code):
        symbol = ts_code.split(".")[0]
        path = out / f"{symbol}.parquet"
        if _already_done(path):
            return "skip"
        try:
            df = pro.share_float(ts_code=ts_code)
            time.sleep(SLEEP_PER_CALL)
            if df is not None and not df.empty:
                _save(df, path)
                return len(df)
            return 0
        except Exception as e:
            return f"err:{e}"

    done = 0
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futs = {pool.submit(_fetch, sym): sym for sym in symbols}
        for fut in as_completed(futs):
            done += 1
            _progress(done, len(symbols), "")
    print()
    log.info("限售解禁 完成")


# ─────────────────────────────────────────────
# 模块：股东人数
# ─────────────────────────────────────────────

def download_holder_num(pro, symbols, workers=3):
    """
    股东人数变化（季度）：持股人数越少=筹码集中=机构控盘
    用途：筹码集中度因子，与机构持仓配合使用
    关键列：end_date, holder_num（股东人数）
    存储：data/raw/tushare/holder_num/{symbol}.parquet
    """
    log.info(f"=== 股东人数 ({len(symbols)} 只股票) ===")
    out = DATA_DIR / "holder_num"

    def _fetch(ts_code):
        symbol = ts_code.split(".")[0]
        path = out / f"{symbol}.parquet"
        if _already_done(path):
            return "skip"
        try:
            df = pro.stk_holdernumber(ts_code=ts_code,
                                       startdate=HISTORY_START,
                                       enddate=END_DATE)
            time.sleep(SLEEP_PER_CALL)
            if df is not None and not df.empty:
                _save(df, path)
                return len(df)
            return 0
        except Exception as e:
            return f"err:{e}"

    done = 0
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futs = {pool.submit(_fetch, sym): sym for sym in symbols}
        for fut in as_completed(futs):
            done += 1
            _progress(done, len(symbols), "")
    print()
    log.info("股东人数 完成")


# ─────────────────────────────────────────────
# 模块：龙虎榜（按日期）
# ─────────────────────────────────────────────

def download_top_list(pro):
    """
    龙虎榜明细 + 机构席位（2015-2025，按交易日逐日拉取）
    用途：机构席位买卖信号，event driven 策略
    关键列：ts_code, close, pct_change, net_amount（净买入额）
    存储：data/raw/tushare/events/top_list_YYYYMMDD.parquet
           data/raw/tushare/events/top_inst_YYYYMMDD.parquet
    """
    log.info("=== 龙虎榜（2015-2025）===")
    out = DATA_DIR / "events"
    out.mkdir(parents=True, exist_ok=True)

    # 获取交易日历
    cal = pro.trade_cal(exchange="SSE", start_date="20150101", end_date=END_DATE)
    time.sleep(SLEEP_PER_CALL)
    trade_days = cal[cal["is_open"] == 1]["cal_date"].tolist()
    log.info(f"  共 {len(trade_days)} 个交易日")

    done = 0
    errors = 0
    for td in trade_days:
        done += 1
        _progress(done, len(trade_days), td)

        path_tl = out / f"top_list_{td}.parquet"
        path_ti = out / f"top_inst_{td}.parquet"

        if not _already_done(path_tl):
            try:
                df = pro.top_list(trade_date=td)
                time.sleep(SLEEP_PER_CALL)
                if df is not None and not df.empty:
                    _save(df, path_tl)
            except Exception:
                errors += 1

        if not _already_done(path_ti):
            try:
                df = pro.top_inst(trade_date=td)
                time.sleep(SLEEP_PER_CALL)
                if df is not None and not df.empty:
                    _save(df, path_ti)
            except Exception:
                errors += 1

    print()
    log.info(f"龙虎榜 完成（错误: {errors}）")


# ─────────────────────────────────────────────
# 模块：大宗交易
# ─────────────────────────────────────────────

def download_block_trade(pro):
    """
    大宗交易记录（2015-2025，按月拉取）
    用途：大宗折价因子（大宗成交价/市价折扣），机构行为信号
    关键列：ts_code, trade_date, price, vol, amount, buyer, seller
    存储：data/raw/tushare/events/block_trade_YYYYMM.parquet
    """
    log.info("=== 大宗交易（2015-2025）===")
    out = DATA_DIR / "events"

    months = pd.date_range("2015-01", END_DATE, freq="MS").strftime("%Y%m").tolist()
    done = 0
    for ym in months:
        done += 1
        _progress(done, len(months), ym)
        path = out / f"block_trade_{ym}.parquet"
        if _already_done(path):
            continue
        try:
            start = ym + "01"
            end_dt = pd.Timestamp(ym + "01") + pd.offsets.MonthEnd(1)
            end = end_dt.strftime("%Y%m%d")
            df = pro.block_trade(start_date=start, end_date=end)
            time.sleep(SLEEP_PER_CALL)
            if df is not None and not df.empty:
                _save(df, path)
        except Exception:
            pass
    print()
    log.info("大宗交易 完成")


# ─────────────────────────────────────────────
# 模块：回购公告
# ─────────────────────────────────────────────

def download_repurchase(pro):
    """
    股票回购公告（全市场）
    用途：回购事件驱动因子，管理层信心信号
    关键列：ts_code, ann_date, end_date, proc（进度）, vol（回购量）
    存储：data/raw/tushare/repurchase.parquet
    """
    log.info("=== 回购公告 ===")
    path = DATA_DIR / "repurchase.parquet"
    if _already_done(path):
        log.info("  已存在，跳过")
        return

    months = pd.date_range("2015-01", END_DATE, freq="MS").strftime("%Y%m%d").tolist()
    frames = []
    for i, start in enumerate(months):
        _progress(i + 1, len(months), start)
        end_dt = (pd.Timestamp(start) + pd.offsets.MonthEnd(1)).strftime("%Y%m%d")
        try:
            df = pro.repurchase(start_date=start, end_date=end_dt)
            time.sleep(SLEEP_PER_CALL)
            if df is not None and not df.empty:
                frames.append(df)
        except Exception:
            pass

    print()
    if frames:
        _save(pd.concat(frames, ignore_index=True), path)
        log.info(f"回购公告 完成，共 {sum(len(f) for f in frames)} 条")


# ─────────────────────────────────────────────
# 模块：指数数据
# ─────────────────────────────────────────────

def download_index_data(pro):
    """
    主要指数日线行情（沪深300/中证500/中证1000等）
    用途：市场 regime 判断（MA120）、基准收益、beta 计算
    存储：data/raw/tushare/index_daily_{code}.parquet
    """
    log.info("=== 指数日线行情 ===")
    for code, name in INDEX_CODES.items():
        short = code.split(".")[0]
        path = DATA_DIR / f"index_daily_{short}.parquet"
        if _already_done(path):
            log.info(f"  {name} 已存在，跳过")
            continue
        try:
            df = pro.index_daily(ts_code=code, start_date=HISTORY_START, end_date=END_DATE)
            time.sleep(SLEEP_PER_CALL)
            if df is not None and not df.empty:
                _save(df, path)
                log.info(f"  {name}: {len(df)} 行")
        except Exception as e:
            log.warning(f"  {name} 失败: {e}")
    log.info("指数日线 完成")


# ─────────────────────────────────────────────
# 模块：指数成分权重
# ─────────────────────────────────────────────

def download_index_weight(pro):
    """
    指数成分权重历史（沪深300/中证500，按月）
    用途：行业配置分析、成分股过滤、benchmark 精确复制
    存储：data/raw/tushare/index_weight_{code}.parquet
    """
    log.info("=== 指数成分权重 ===")
    months = pd.date_range("2015-01", END_DATE, freq="MS").strftime("%Y%m%d").tolist()

    for code, name in INDEX_WEIGHT_CODES.items():
        short = code.split(".")[0]
        path = DATA_DIR / f"index_weight_{short}.parquet"
        if _already_done(path):
            log.info(f"  {name} 已存在，跳过")
            continue
        frames = []
        for i, start in enumerate(months):
            _progress(i + 1, len(months), f"{name} {start[:6]}")
            end_dt = (pd.Timestamp(start) + pd.offsets.MonthEnd(1)).strftime("%Y%m%d")
            try:
                df = pro.index_weight(index_code=code, start_date=start, end_date=end_dt)
                time.sleep(SLEEP_PER_CALL)
                if df is not None and not df.empty:
                    frames.append(df)
            except Exception:
                pass
        print()
        if frames:
            _save(pd.concat(frames, ignore_index=True).drop_duplicates(), path)
            log.info(f"  {name}: {sum(len(f) for f in frames)} 条")
    log.info("指数成分权重 完成")


# ─────────────────────────────────────────────
# 模块：北向汇总
# ─────────────────────────────────────────────

def download_northbound_agg(pro):
    """
    北向资金每日汇总（大盘净流入）
    用途：市场 regime 判断，北向资金择时信号
    关键列：trade_date, hgt（沪股通）, sgt（深股通）, north_money（北向合计）
    存储：data/raw/tushare/northbound_agg.parquet
    """
    log.info("=== 北向资金汇总 ===")
    path = DATA_DIR / "northbound_agg.parquet"
    if _already_done(path):
        log.info("  已存在，跳过")
        return
    try:
        df = pro.moneyflow_hsgt(start_date="20140101", end_date=END_DATE)
        time.sleep(SLEEP_PER_CALL)
        if df is not None and not df.empty:
            _save(df, path)
            log.info(f"  北向汇总: {len(df)} 行")
    except Exception as e:
        log.warning(f"  北向汇总失败: {e}")


# ─────────────────────────────────────────────
# 主程序
# ─────────────────────────────────────────────

ALL_MODULES = [
    "financial", "daily_basic", "adj_factor", "moneyflow",
    "margin", "northbound", "dividend", "share_float", "holder_num",
    "top_list", "block_trade", "repurchase",
    "index_data", "index_weight", "northbound_agg",
]

def main():
    parser = argparse.ArgumentParser(description="Tushare 全量数据下载")
    parser.add_argument("--modules", nargs="+", default=ALL_MODULES,
                        help=f"要下载的模块，默认全部。可选: {', '.join(ALL_MODULES)}")
    parser.add_argument("--workers", type=int, default=3,
                        help="并发线程数（默认3，不超过5）")
    args = parser.parse_args()

    log.info("连接 Tushare...")
    pro = get_pro()
    log.info("✅ 连接成功")

    # 获取全部股票列表
    log.info("获取股票列表...")
    symbols = _get_all_symbols(pro)
    log.info(f"在市股票: {len(symbols)} 只")

    DATA_DIR.mkdir(parents=True, exist_ok=True)

    start_time = time.time()
    mods = set(args.modules)

    if "financial"     in mods: download_financial(pro, symbols, args.workers)
    if "daily_basic"   in mods: download_daily_basic(pro, symbols, args.workers)
    if "adj_factor"    in mods: download_adj_factor(pro, symbols, args.workers)
    if "moneyflow"     in mods: download_moneyflow(pro, symbols, args.workers)
    if "margin"        in mods: download_margin(pro, symbols, args.workers)
    if "northbound"    in mods: download_northbound(pro, symbols, args.workers)
    if "dividend"      in mods: download_dividend(pro, symbols, args.workers)
    if "share_float"   in mods: download_share_float(pro, symbols, args.workers)
    if "holder_num"    in mods: download_holder_num(pro, symbols, args.workers)
    if "top_list"      in mods: download_top_list(pro)
    if "block_trade"   in mods: download_block_trade(pro)
    if "repurchase"    in mods: download_repurchase(pro)
    if "index_data"    in mods: download_index_data(pro)
    if "index_weight"  in mods: download_index_weight(pro)
    if "northbound_agg"in mods: download_northbound_agg(pro)

    elapsed = (time.time() - start_time) / 60
    log.info(f"\n✅ 全部完成，耗时 {elapsed:.0f} 分钟")
    log.info(f"数据存储位置: {DATA_DIR}")

    # 打印磁盘占用
    total_size = sum(f.stat().st_size for f in DATA_DIR.rglob("*.parquet")) / 1024 / 1024 / 1024
    log.info(f"总磁盘占用: {total_size:.2f} GB")


if __name__ == "__main__":
    main()
