"""
Tushare 补充数据下载脚本（bulk_download_tushare.py 之外的高价值接口）
====================================================================

覆盖 bulk_download 未包含的事件驱动/机构行为/情绪类数据，主要补充：

    stk_limit        每日涨跌停价（event-driven 回测填单真实性的关键）
    suspend_d        每日停复牌（回测过滤必备）
    limit_list_d     涨跌停个股统计（封板强度/炸板，2019+）
    stk_surv         机构调研记录（事件驱动信号源，2017+）
    top10_floatholders 十大流通股东季度变动
    top10_holders    十大股东季度变动
    pledge_stat      股权质押统计
    broker_recommend 分析师推荐汇总（月频）
    stk_managers     管理层信息
    stock_company    公司详情（主营/行业/上市所）
    ths_hot          同花顺热股榜（情绪指标）
    dc_hot           东方财富热股榜（情绪指标）
    anns_d           公司公告索引（按交易日）

使用方式
--------
    # 全部模块（约 30 分钟~1 小时）
    python scripts/bulk_download_tushare_extras.py

    # 只下载一部分
    python scripts/bulk_download_tushare_extras.py --modules stk_limit suspend_d limit_list_d

数据存储
--------
    data/raw/tushare/
    ├── stk_limit/YYYY/stk_limit_YYYYMMDD.parquet      # 按日期
    ├── suspend/suspend_YYYYMMDD.parquet               # 按日期
    ├── limit_list/limit_list_YYYYMMDD.parquet         # 按日期
    ├── stk_surv/stk_surv_000001.parquet               # 按股票
    ├── top10_floatholders/tfh_000001.parquet          # 按股票
    ├── top10_holders/th_000001.parquet                # 按股票
    ├── pledge_stat/pledge_000001.parquet              # 按股票
    ├── stk_managers/stk_managers_000001.parquet       # 按股票
    ├── broker_recommend/YYYYMM.parquet                # 按月
    ├── stock_company.parquet                          # 全量
    ├── ths_hot/YYYY/ths_hot_YYYYMMDD.parquet          # 按日期
    ├── dc_hot/YYYY/dc_hot_YYYYMMDD.parquet            # 按日期
    └── anns_d/anns_YYYYMMDD.parquet                   # 按日期
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

# 不同接口的历史起点（根据 Tushare 实际覆盖）
STK_LIMIT_START     = "20150101"   # 涨跌停价
SUSPEND_START       = "20150101"   # 停复牌
LIMIT_LIST_START    = "20190101"   # 涨跌停个股统计（2019 起）
STK_SURV_START      = "20170101"   # 机构调研（2017 起）
HOLDERS_START       = "20150101"   # 十大股东（季度）
PLEDGE_START        = "20150101"   # 质押统计
BROKER_START        = "201501"     # 分析师推荐（月）
THS_HOT_START       = "20200101"   # 同花顺热榜（2020 起）
DC_HOT_START        = "20200101"   # 东财热榜（2020 起）
ANNS_D_START        = "20220101"   # 公告索引（过大，只拉近几年）

END_DATE            = datetime.now().strftime("%Y%m%d")
END_DATE_MONTH      = datetime.now().strftime("%Y%m")

SLEEP_PER_CALL = 0.3  # 与 bulk_download 并行跑时略放宽

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger(__name__)


# ─────────────────────────────────────────────
# Tushare 连接（复用 bulk_download 的模式）
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
        sys.exit("❌ 未找到 TUSHARE_TOKEN")
    try:
        import tushare as ts
    except ImportError:
        sys.exit("❌ 请先 pip install tushare==1.4.21")
    pro = ts.pro_api(token)
    pro._DataApi__token = token
    pro._DataApi__http_url = "http://jiaoch.site"
    return pro


# ─────────────────────────────────────────────
# 通用工具
# ─────────────────────────────────────────────

def _save(df: pd.DataFrame, path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(path, index=False)


def _already_done(path: Path) -> bool:
    return path.exists() and path.stat().st_size > 500


def _get_trade_dates(pro, start: str, end: str) -> list:
    cal = pro.trade_cal(exchange="SSE", start_date=start, end_date=end, is_open="1")
    time.sleep(SLEEP_PER_CALL)
    return sorted(cal["cal_date"].tolist())


def _get_all_symbols(pro) -> list:
    df = pro.stock_basic(list_status="L", fields="ts_code,name,list_date")
    time.sleep(SLEEP_PER_CALL)
    return df["ts_code"].tolist()


def _progress(done, total, name=""):
    pct = done / total * 100 if total else 100
    bar = "█" * int(pct / 2) + "░" * (50 - int(pct / 2))
    print(f"\r  [{bar}] {done}/{total} {pct:.0f}% {name:<16}", end="", flush=True)


def _month_range(start: str, end: str) -> list:
    """生成 YYYYMM 区间"""
    months = []
    s = datetime.strptime(start, "%Y%m")
    e = datetime.strptime(end, "%Y%m")
    cur = s
    while cur <= e:
        months.append(cur.strftime("%Y%m"))
        if cur.month == 12:
            cur = cur.replace(year=cur.year + 1, month=1)
        else:
            cur = cur.replace(month=cur.month + 1)
    return months


# ─────────────────────────────────────────────
# 模块：每日涨跌停价 stk_limit
# ─────────────────────────────────────────────

def download_stk_limit(pro, workers=2):
    """
    每日全市场涨跌停价（up_limit / down_limit / pre_close）
    用途：event-driven 回测中判断信号发出日是否涨跌停，不可买/不可卖
    """
    log.info("=== stk_limit 涨跌停价 ===")
    out = DATA_DIR / "stk_limit"
    dates = _get_trade_dates(pro, STK_LIMIT_START, END_DATE)

    def _fetch(td):
        year = td[:4]
        path = out / year / f"stk_limit_{td}.parquet"
        if _already_done(path):
            return "skip"
        try:
            df = pro.stk_limit(trade_date=td)
            time.sleep(SLEEP_PER_CALL)
            if df is not None and not df.empty:
                _save(df, path)
                return len(df)
            return 0
        except Exception as e:
            return f"err:{e}"

    done = 0
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futs = {pool.submit(_fetch, td): td for td in dates}
        for fut in as_completed(futs):
            done += 1
            _progress(done, len(dates), futs[fut])
    print()
    log.info("stk_limit 完成")


# ─────────────────────────────────────────────
# 模块：每日停复牌 suspend_d
# ─────────────────────────────────────────────

def download_suspend_d(pro, workers=2):
    """
    每日停牌列表（suspend_type='S' 停牌）
    用途：回测过滤——停牌日不交易
    """
    log.info("=== suspend_d 停复牌 ===")
    out = DATA_DIR / "suspend"
    dates = _get_trade_dates(pro, SUSPEND_START, END_DATE)

    def _fetch(td):
        path = out / f"suspend_{td}.parquet"
        if path.exists():  # 停牌可能空表，标记已拉取即可
            return "skip"
        try:
            df = pro.suspend_d(trade_date=td, suspend_type="S")
            time.sleep(SLEEP_PER_CALL)
            if df is None:
                df = pd.DataFrame()
            _save(df if not df.empty else pd.DataFrame({"trade_date": [td]}), path)
            return len(df)
        except Exception as e:
            return f"err:{e}"

    done = 0
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futs = {pool.submit(_fetch, td): td for td in dates}
        for fut in as_completed(futs):
            done += 1
            _progress(done, len(dates), futs[fut])
    print()
    log.info("suspend_d 完成")


# ─────────────────────────────────────────────
# 模块：涨跌停个股统计 limit_list_d
# ─────────────────────────────────────────────

def download_limit_list_d(pro, workers=2):
    """
    每日涨跌停/炸板统计（limit_amount 封板金额, first_time 首次封板时间等）
    用途：封板强度、炸板失败作为反转信号；龙头股识别
    """
    log.info("=== limit_list_d 涨跌停个股统计 ===")
    out = DATA_DIR / "limit_list"
    dates = _get_trade_dates(pro, LIMIT_LIST_START, END_DATE)

    def _fetch(td):
        path = out / f"limit_list_{td}.parquet"
        if _already_done(path):
            return "skip"
        try:
            df = pro.limit_list_d(trade_date=td)
            time.sleep(SLEEP_PER_CALL)
            if df is not None and not df.empty:
                _save(df, path)
                return len(df)
            _save(pd.DataFrame({"trade_date": [td]}), path)  # 空占位避免重拉
            return 0
        except Exception as e:
            return f"err:{e}"

    done = 0
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futs = {pool.submit(_fetch, td): td for td in dates}
        for fut in as_completed(futs):
            done += 1
            _progress(done, len(dates), futs[fut])
    print()
    log.info("limit_list_d 完成")


# ─────────────────────────────────────────────
# 模块：机构调研 stk_surv
# ─────────────────────────────────────────────

def download_stk_surv(pro, symbols, workers=2):
    """
    机构调研记录（调研机构、调研形式、提问内容摘要）
    用途：pre-event 信号——被多家机构密集调研的股票未来超额收益显著
    """
    log.info(f"=== stk_surv 机构调研 ({len(symbols)} 只) ===")
    out = DATA_DIR / "stk_surv"

    def _fetch(ts_code):
        symbol = ts_code.split(".")[0]
        path = out / f"stk_surv_{symbol}.parquet"
        if _already_done(path):
            return "skip"
        try:
            df = pro.stk_surv(
                ts_code=ts_code,
                start_date=STK_SURV_START,
                end_date=END_DATE,
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
    log.info("stk_surv 完成")


# ─────────────────────────────────────────────
# 模块：十大流通股东 top10_floatholders
# ─────────────────────────────────────────────

def download_top10_floatholders(pro, symbols, workers=2):
    """
    十大流通股东（季度）
    用途：机构持股变动 —— Δholding/prev_holding 作为聪明钱因子
    """
    log.info(f"=== top10_floatholders 十大流通股东 ({len(symbols)} 只) ===")
    out = DATA_DIR / "top10_floatholders"

    def _fetch(ts_code):
        symbol = ts_code.split(".")[0]
        path = out / f"tfh_{symbol}.parquet"
        if _already_done(path):
            return "skip"
        try:
            df = pro.top10_floatholders(
                ts_code=ts_code,
                start_date=HOLDERS_START,
                end_date=END_DATE,
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
    log.info("top10_floatholders 完成")


# ─────────────────────────────────────────────
# 模块：十大股东 top10_holders
# ─────────────────────────────────────────────

def download_top10_holders(pro, symbols, workers=2):
    """十大股东（含非流通，季度）"""
    log.info(f"=== top10_holders 十大股东 ({len(symbols)} 只) ===")
    out = DATA_DIR / "top10_holders"

    def _fetch(ts_code):
        symbol = ts_code.split(".")[0]
        path = out / f"th_{symbol}.parquet"
        if _already_done(path):
            return "skip"
        try:
            df = pro.top10_holders(
                ts_code=ts_code,
                start_date=HOLDERS_START,
                end_date=END_DATE,
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
    log.info("top10_holders 完成")


# ─────────────────────────────────────────────
# 模块：股权质押统计 pledge_stat
# ─────────────────────────────────────────────

def download_pledge_stat(pro, symbols, workers=2):
    """
    股权质押统计：pledge_ratio（质押占总股本比例）
    用途：高质押股票通常估值折价，平仓压力事件驱动
    """
    log.info(f"=== pledge_stat 股权质押 ({len(symbols)} 只) ===")
    out = DATA_DIR / "pledge_stat"

    def _fetch(ts_code):
        symbol = ts_code.split(".")[0]
        path = out / f"pledge_{symbol}.parquet"
        if _already_done(path):
            return "skip"
        try:
            df = pro.pledge_stat(ts_code=ts_code)
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
    log.info("pledge_stat 完成")


# ─────────────────────────────────────────────
# 模块：管理层信息 stk_managers
# ─────────────────────────────────────────────

def download_stk_managers(pro, symbols, workers=2):
    """
    管理层档案（姓名、职务、性别、学历、任期、薪酬）
    用途：管理层变动事件（董事长/总经理离任），女性CEO因子等
    """
    log.info(f"=== stk_managers 管理层信息 ({len(symbols)} 只) ===")
    out = DATA_DIR / "stk_managers"

    def _fetch(ts_code):
        symbol = ts_code.split(".")[0]
        path = out / f"stk_managers_{symbol}.parquet"
        if _already_done(path):
            return "skip"
        try:
            df = pro.stk_managers(ts_code=ts_code)
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
    log.info("stk_managers 完成")


# ─────────────────────────────────────────────
# 模块：分析师推荐 broker_recommend
# ─────────────────────────────────────────────

def download_broker_recommend(pro):
    """按月下载分析师推荐汇总"""
    log.info("=== broker_recommend 分析师推荐 ===")
    out = DATA_DIR / "broker_recommend"
    months = _month_range(BROKER_START, END_DATE_MONTH)

    for i, m in enumerate(months, 1):
        path = out / f"{m}.parquet"
        if _already_done(path):
            _progress(i, len(months), m)
            continue
        try:
            df = pro.broker_recommend(month=m)
            time.sleep(SLEEP_PER_CALL)
            if df is not None and not df.empty:
                _save(df, path)
            _progress(i, len(months), m)
        except Exception as e:
            log.warning(f"\n  {m} 失败: {e}")
    print()
    log.info("broker_recommend 完成")


# ─────────────────────────────────────────────
# 模块：公司详情 stock_company
# ─────────────────────────────────────────────

def download_stock_company(pro):
    """一次性拉取全市场公司详情（主营、行业、上市所、注册地）"""
    log.info("=== stock_company 公司详情 ===")
    path = DATA_DIR / "stock_company.parquet"
    if _already_done(path):
        log.info("  已存在，跳过")
        return
    frames = []
    for exch in ["SSE", "SZSE", "BSE"]:
        try:
            df = pro.stock_company(exchange=exch, fields=(
                "ts_code,chairman,manager,secretary,reg_capital,setup_date,"
                "province,city,introduction,website,email,employees,"
                "main_business,business_scope,exchange"
            ))
            time.sleep(SLEEP_PER_CALL)
            if df is not None and not df.empty:
                frames.append(df)
                log.info(f"  {exch}: {len(df)} 条")
        except Exception as e:
            log.warning(f"  {exch} 失败: {e}")
    if frames:
        _save(pd.concat(frames, ignore_index=True), path)
    log.info("stock_company 完成")


# ─────────────────────────────────────────────
# 模块：同花顺热股榜 ths_hot
# ─────────────────────────────────────────────

def download_ths_hot(pro, workers=2):
    """
    同花顺热股榜（daily）—— 散户情绪代理
    用途：过热反转因子候选
    """
    log.info("=== ths_hot 同花顺热股榜 ===")
    out = DATA_DIR / "ths_hot"
    dates = _get_trade_dates(pro, THS_HOT_START, END_DATE)

    def _fetch(td):
        year = td[:4]
        path = out / year / f"ths_hot_{td}.parquet"
        if path.exists():
            return "skip"
        try:
            df = pro.ths_hot(trade_date=td)
            time.sleep(SLEEP_PER_CALL)
            if df is not None and not df.empty:
                _save(df, path)
                return len(df)
            _save(pd.DataFrame({"trade_date": [td]}), path)
            return 0
        except Exception as e:
            return f"err:{e}"

    done = 0
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futs = {pool.submit(_fetch, td): td for td in dates}
        for fut in as_completed(futs):
            done += 1
            _progress(done, len(dates), futs[fut])
    print()
    log.info("ths_hot 完成")


# ─────────────────────────────────────────────
# 模块：东财热股榜 dc_hot
# ─────────────────────────────────────────────

def download_dc_hot(pro, workers=2):
    """东方财富热股榜（daily）—— 散户情绪代理"""
    log.info("=== dc_hot 东财热股榜 ===")
    out = DATA_DIR / "dc_hot"
    dates = _get_trade_dates(pro, DC_HOT_START, END_DATE)

    def _fetch(td):
        year = td[:4]
        path = out / year / f"dc_hot_{td}.parquet"
        if path.exists():
            return "skip"
        try:
            df = pro.dc_hot(trade_date=td)
            time.sleep(SLEEP_PER_CALL)
            if df is not None and not df.empty:
                _save(df, path)
                return len(df)
            _save(pd.DataFrame({"trade_date": [td]}), path)
            return 0
        except Exception as e:
            return f"err:{e}"

    done = 0
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futs = {pool.submit(_fetch, td): td for td in dates}
        for fut in as_completed(futs):
            done += 1
            _progress(done, len(dates), futs[fut])
    print()
    log.info("dc_hot 完成")


# ─────────────────────────────────────────────
# 模块：公告索引 anns_d
# ─────────────────────────────────────────────

def download_anns_d(pro, workers=2):
    """
    公司公告索引（每日，按交易日拉取）
    用途：事件驱动信号源——定增/回购/股权激励/董秘变更等
    """
    log.info("=== anns_d 公告索引 ===")
    out = DATA_DIR / "anns_d"
    dates = _get_trade_dates(pro, ANNS_D_START, END_DATE)

    def _fetch(td):
        path = out / f"anns_{td}.parquet"
        if path.exists():
            return "skip"
        try:
            df = pro.anns_d(
                start_date=td,
                end_date=td,
            )
            time.sleep(SLEEP_PER_CALL)
            if df is not None and not df.empty:
                _save(df, path)
                return len(df)
            _save(pd.DataFrame({"trade_date": [td]}), path)
            return 0
        except Exception as e:
            return f"err:{e}"

    done = 0
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futs = {pool.submit(_fetch, td): td for td in dates}
        for fut in as_completed(futs):
            done += 1
            _progress(done, len(dates), futs[fut])
    print()
    log.info("anns_d 完成")


# ─────────────────────────────────────────────
# 主程序
# ─────────────────────────────────────────────

ALL_MODULES = [
    "stock_company",        # 先跑这个，轻量 & 其他模块可能参考
    "stk_limit",
    "suspend_d",
    "limit_list_d",
    "broker_recommend",
    "ths_hot",
    "dc_hot",
    "stk_managers",
    "pledge_stat",
    "top10_holders",
    "top10_floatholders",
    "stk_surv",
    "anns_d",
]


def main():
    parser = argparse.ArgumentParser(description="Tushare 补充数据下载")
    parser.add_argument("--modules", nargs="+", default=ALL_MODULES,
                        help=f"要下载的模块。可选: {', '.join(ALL_MODULES)}")
    parser.add_argument("--workers", type=int, default=2,
                        help="并发线程数（与 bulk_download 并行跑时推荐 2）")
    args = parser.parse_args()

    log.info("连接 Tushare...")
    pro = get_pro()
    log.info("✅ 连接成功")

    log.info("获取股票列表...")
    symbols = _get_all_symbols(pro)
    log.info(f"在市股票: {len(symbols)} 只")

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    mods = set(args.modules)

    start_time = time.time()

    if "stock_company"       in mods: download_stock_company(pro)
    if "stk_limit"           in mods: download_stk_limit(pro, args.workers)
    if "suspend_d"           in mods: download_suspend_d(pro, args.workers)
    if "limit_list_d"        in mods: download_limit_list_d(pro, args.workers)
    if "broker_recommend"    in mods: download_broker_recommend(pro)
    if "ths_hot"             in mods: download_ths_hot(pro, args.workers)
    if "dc_hot"              in mods: download_dc_hot(pro, args.workers)
    if "stk_managers"        in mods: download_stk_managers(pro, symbols, args.workers)
    if "pledge_stat"         in mods: download_pledge_stat(pro, symbols, args.workers)
    if "top10_holders"       in mods: download_top10_holders(pro, symbols, args.workers)
    if "top10_floatholders"  in mods: download_top10_floatholders(pro, symbols, args.workers)
    if "stk_surv"            in mods: download_stk_surv(pro, symbols, args.workers)
    if "anns_d"              in mods: download_anns_d(pro, args.workers)

    elapsed = (time.time() - start_time) / 60
    log.info(f"\n✅ 全部补充下载完成，耗时 {elapsed:.0f} 分钟")

    total_size = sum(f.stat().st_size for f in DATA_DIR.rglob("*.parquet")) / 1024 / 1024 / 1024
    log.info(f"当前总磁盘占用: {total_size:.2f} GB")


if __name__ == "__main__":
    main()
