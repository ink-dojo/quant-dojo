"""
政府政策监控 — 12 个部委增量抓取
商务部 / 工信部 / 证监会 / 国家能源局 / 财政部 / 央行
发改委 / 交通运输部 / 国务院 / 生态环境部 / 市场监管总局 / 金融监管总局

用法:
    python scripts/policy_monitor.py          # 抓取所有来源
    python scripts/policy_monitor.py --list   # 只展示最新 20 条
    python scripts/policy_monitor.py --source 发改委  # 只抓单个来源
"""

import argparse
import json
import re
import sqlite3
import time
import urllib.parse
import urllib.request
from datetime import datetime
from pathlib import Path

DB_PATH = Path(__file__).parent.parent / "data" / "policy_monitor.db"

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
}

# ─────────────────────────────────────────────
# 各部委配置
# ─────────────────────────────────────────────

_CMS_SOURCES = {
    "商务部": {
        "base": "http://www.mofcom.gov.cn",
        "api": "http://www.mofcom.gov.cn/api-gateway/jpaas-publish-server/front/page/build/unit",
        "params": {
            "parseType": "bulidstatic",
            "webId": "8f43c7ad3afc411fb56f281724b73708",
            "tplSetId": "52551ea0e2c14bca8c84792f7aa37ead",
            "pageType": "column",
            "tagId": "分页列表",
            "editType": "null",
            "pageId": "fc8bdff48fa345a48b651c1285b70b8f",
            "pageNo": "1",
            "pageSize": "20",
        },
        "referer": "http://www.mofcom.gov.cn/zwgk/zcfb/index.html",
        "pattern": r'href="(/zwgk/zcfb/art/[^"]+)"\s+title="([^"]+)"[^>]*>[^<]+</a><span>\[(\d{4}-\d{2}-\d{2})\]</span>',
    },
    "工信部": {
        "base": "https://www.miit.gov.cn",
        "api": "https://www.miit.gov.cn/api-gateway/jpaas-publish-server/front/page/build/unit",
        "params": {
            "parseType": "buildstatic",
            "webId": "8d828e408d90447786ddbe128d495e9e",
            "tplSetId": "209741b2109044b5b7695700b2bec37e",
            "pageType": "column",
            "tagId": "右侧内容",
            "editType": "null",
            "pageId": "3e3ad1a3bec74939890a0d3e54815141",
            "pageNo": "1",
            "pageSize": "20",
        },
        "referer": "https://www.miit.gov.cn/zwgk/zcwj/wjfb/tz/index.html",
        "pattern": r'href="(/zwgk/[^"]+\.html)"\s[^>]*title="([^"]+)"[\s\S]{0,200}?(\d{4}-\d{2}-\d{2})',
    },
    "市场监管总局": {
        "base": "https://www.samr.gov.cn",
        "api": "https://www.samr.gov.cn/api-gateway/jpaas-publish-server/front/page/build/unit",
        "params": {
            "parseType": "bulidstatic",
            "webId": "29e9522dc89d4e088a953d8cede72f4c",
            "tplSetId": "5c30fb89ae5e48b9aefe3cdf49853830",
            "pageType": "column",
            "tagId": "内容区域",
            "editType": "null",
            "pageId": "39cd9de1f309431483ef3008309f39ca",
            "pageNo": "1",
            "pageSize": "20",
        },
        "referer": "https://www.samr.gov.cn/xw/zj/index.html",
        # 标题和日期分别在相邻的 li 里
        "pattern": r'<a href="(/xw/[^"]+\.html)"[^>]*title="([^"]+)"[^>]*>[^<]+</a></li>\s*'
                   r'<li class="nav04Left02_contenttime">(\d{4}-\d{2}-\d{2})</li>',
    },
}

# 证监会
_CSRC_HOME = "https://www.csrc.gov.cn/"
_CSRC_BASE = "https://www.csrc.gov.cn"
_CSRC_SECTIONS = {"c100028", "c106311"}

# 国家能源局
_NEA_HOME = "http://www.nea.gov.cn/"
_NEA_BASE = "http://www.nea.gov.cn"

# 财政部
_MOF_LIST = "http://www.mof.gov.cn/zhengwuxinxi/zhengcefabu/"
_MOF_BASE = "http://www.mof.gov.cn"

# 央行
_PBOC_LIST = "http://www.pbc.gov.cn/tiaofasi/144941/3581332/index.html"
_PBOC_BASE = "http://www.pbc.gov.cn"

# 发改委 Elasticsearch API
_NDRC_API = (
    "https://fwfx.ndrc.gov.cn/api/query"
    "?qt=&tab=all&page=1&pageSize=20&siteCode=bm04000fgk"
    "&key=CAB549A94CF659904A7D6B0E8FC8A7E9"
    "&startDateStr=&endDateStr=&timeOption=0&sort=dateDesc"
)
_NDRC_REFERER = "https://fwfx.ndrc.gov.cn/"

# 交通运输部 政策规章列表
_MOT_LIST = "https://xxgk.mot.gov.cn/zhengce/?gk=5"
_MOT_REFERER = "https://www.mot.gov.cn/"

# 国务院 最新政策 JSON (TRS CMS 静态导出)
_GOV_JSON = "https://www.gov.cn/zhengce/zuixin/ZUIXINZHENGCE.json"
_GOV_REFERER = "https://www.gov.cn/zhengce/zuixin/index.htm"

# 生态环境部 标准规范列表
_MEE_LIST = "https://www.mee.gov.cn/ywgz/fgbz/bz/index.shtml"
_MEE_BASE = "https://www.mee.gov.cn/ywgz/fgbz/bz/"
_MEE_REFERER = "https://www.mee.gov.cn/"

# 金融监管总局 监管动态 (itemId=915)
_NFRA_API = (
    "https://www.nfra.gov.cn/cbircweb/DocInfo/SelectDocByItemIdAndChild"
    "?itemId=915&pageIndex=1&pageSize=20&tabKey=1"
)
_NFRA_BASE = "https://www.nfra.gov.cn/cn/view/pages/ItemDetail.html"
_NFRA_REFERER = "https://www.nfra.gov.cn/"


# ─────────────────────────────────────────────
# 工具
# ─────────────────────────────────────────────

def _fetch(url: str, extra_headers: dict | None = None) -> str:
    headers = {**_HEADERS, **(extra_headers or {})}
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, timeout=15) as resp:
        raw = resp.read()
    for enc in ("utf-8", "gb2312", "gbk"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="replace")


def _init_db(conn: sqlite3.Connection) -> None:
    conn.execute("""
        CREATE TABLE IF NOT EXISTS policies (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            source     TEXT    NOT NULL,
            title      TEXT    NOT NULL,
            url        TEXT    NOT NULL UNIQUE,
            pub_date   TEXT,
            fetched_at TEXT    NOT NULL
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_pub_date ON policies(pub_date DESC)")
    conn.commit()


def _save(conn: sqlite3.Connection, items: list[dict]) -> int:
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    new_count = 0
    for item in items:
        try:
            conn.execute(
                "INSERT INTO policies (source, title, url, pub_date, fetched_at) VALUES (?,?,?,?,?)",
                (item["source"], item["title"], item["url"], item.get("pub_date"), now),
            )
            new_count += 1
        except sqlite3.IntegrityError:
            pass
    conn.commit()
    return new_count


def _clean_title(raw: str) -> str:
    text = re.sub(r"<[^>]+>", "", raw)
    return re.sub(r"\s+", " ", text).strip()


# ─────────────────────────────────────────────
# 商务部 / 工信部 / 市场监管总局（同款 jpaas CMS）
# ─────────────────────────────────────────────

def scrape_cms(name: str) -> list[dict]:
    cfg = _CMS_SOURCES[name]
    url = f"{cfg['api']}?{urllib.parse.urlencode(cfg['params'])}"
    raw = _fetch(url, extra_headers={"Referer": cfg["referer"]})
    resp = json.loads(raw)
    if not resp.get("success"):
        print(f"[{name}] API 失败: {resp.get('message')}")
        return []
    html = resp["data"]["html"]
    items = re.findall(cfg["pattern"], html)
    results = [
        {"source": name, "title": _clean_title(t), "url": cfg["base"] + path, "pub_date": date}
        for path, t, date in items
        if _clean_title(t)
    ]
    print(f"[{name}] 抓到 {len(results)} 条")
    return results


# ─────────────────────────────────────────────
# 证监会
# ─────────────────────────────────────────────

def _get_csrc_date(url: str, retries: int = 2) -> str | None:
    for attempt in range(retries + 1):
        try:
            html = _fetch(url)
            m = re.search(r"meta name=\"description\" content='[^']*?(\d{4}-\d{2}-\d{2})'", html)
            return m.group(1) if m else None
        except Exception as e:
            if attempt < retries:
                time.sleep(2)
            else:
                print(f"  [证监会] 日期获取失败 {url}: {e}")
    return None


def scrape_csrc(conn: sqlite3.Connection) -> list[dict]:
    html = _fetch(_CSRC_HOME)
    raw_items = re.findall(
        r'href="(/csrc/(c\d+)/c7\d+/content\.shtml)"[^>]*>\s*([\s\S]*?)\s*</a>',
        html,
    )
    seen: set[str] = set()
    results: list[dict] = []
    for path, section, raw_title in raw_items:
        if section not in _CSRC_SECTIONS:
            continue
        title = _clean_title(raw_title)
        if not title or len(title) < 5:
            continue
        url = _CSRC_BASE + path
        if url in seen:
            continue
        seen.add(url)
        if conn.execute("SELECT 1 FROM policies WHERE url=?", (url,)).fetchone():
            continue
        pub_date = _get_csrc_date(url)
        results.append({"source": "证监会", "title": title, "url": url, "pub_date": pub_date})
        time.sleep(0.5)
    print(f"[证监会] 新增 {len(results)} 条")
    return results


# ─────────────────────────────────────────────
# 国家能源局
# ─────────────────────────────────────────────

def scrape_nea() -> list[dict]:
    html = _fetch(_NEA_HOME)
    items = re.findall(
        r'href="(?:http://www\.nea\.gov\.cn/)?(\d{8})/([^"]+)/c\.html"[^>]*>([^<]{5,80})</a>',
        html,
    )
    seen: set[str] = set()
    results: list[dict] = []
    for date8, path, title in items:
        url = f"{_NEA_BASE}/{date8}/{path}/c.html"
        title = _clean_title(title)
        if not title or url in seen:
            continue
        seen.add(url)
        pub_date = f"{date8[:4]}-{date8[4:6]}-{date8[6:8]}"
        results.append({"source": "国家能源局", "title": title, "url": url, "pub_date": pub_date})
    print(f"[国家能源局] 抓到 {len(results)} 条")
    return results


# ─────────────────────────────────────────────
# 财政部
# ─────────────────────────────────────────────

def scrape_mof() -> list[dict]:
    html = _fetch(_MOF_LIST)
    items = re.findall(
        r'href="(https?://[a-z]+\.mof\.gov\.cn/[^"]+/t(\d{4})(\d{2})(\d{2})_[^"]+\.htm)"'
        r'[^>]*>([^<]{5,80})</a>',
        html,
    )
    seen: set[str] = set()
    results: list[dict] = []
    for url, y, m, d, title in items:
        title = _clean_title(title)
        if not title or url in seen:
            continue
        seen.add(url)
        results.append({"source": "财政部", "title": title, "url": url, "pub_date": f"{y}-{m}-{d}"})
    print(f"[财政部] 抓到 {len(results)} 条")
    return results


# ─────────────────────────────────────────────
# 央行
# ─────────────────────────────────────────────

def scrape_pboc() -> list[dict]:
    html = _fetch(_PBOC_LIST)
    items = re.findall(
        r'href="(/tiaofasi/[^"]+/(\d{8})\d+/index\.html)"[^>]*>([^<]{5,80})</a>',
        html,
    )
    seen: set[str] = set()
    results: list[dict] = []
    for path, date8, title in items:
        url = _PBOC_BASE + path
        title = _clean_title(title)
        if not title or url in seen:
            continue
        seen.add(url)
        pub_date = f"{date8[:4]}-{date8[4:6]}-{date8[6:8]}"
        results.append({"source": "央行", "title": title, "url": url, "pub_date": pub_date})
    print(f"[央行] 抓到 {len(results)} 条")
    return results


# ─────────────────────────────────────────────
# 发改委（Elasticsearch API）
# ─────────────────────────────────────────────

def scrape_ndrc() -> list[dict]:
    raw = _fetch(_NDRC_API, extra_headers={"Referer": _NDRC_REFERER})
    resp = json.loads(raw)
    result_list = resp.get("data", {}).get("resultList", [])
    seen: set[str] = set()
    results: list[dict] = []
    for item in result_list:
        url = item.get("url", "").strip()
        title = _clean_title(item.get("title", ""))
        pub_date = item.get("docDate", "")
        if not url or not title or url in seen:
            continue
        seen.add(url)
        results.append({"source": "发改委", "title": title, "url": url, "pub_date": pub_date})
    print(f"[发改委] 抓到 {len(results)} 条")
    return results


# ─────────────────────────────────────────────
# 交通运输部（政策规章，日期在 URL 里）
# ─────────────────────────────────────────────

def scrape_mot() -> list[dict]:
    html = _fetch(_MOT_LIST, extra_headers={"Referer": _MOT_REFERER})
    items = re.findall(
        r'href="(https://xxgk\.mot\.gov\.cn/gz/\d{6}/t(\d{8})_\d+\.html)"'
        r'[^>]*>\s*([^<]{5,80})\s*</a>',
        html,
    )
    seen: set[str] = set()
    results: list[dict] = []
    for url, date8, title in items:
        title = _clean_title(title)
        if not title or url in seen:
            continue
        seen.add(url)
        pub_date = f"{date8[:4]}-{date8[4:6]}-{date8[6:8]}"
        results.append({"source": "交通运输部", "title": title, "url": url, "pub_date": pub_date})
    print(f"[交通运输部] 抓到 {len(results)} 条")
    return results


# ─────────────────────────────────────────────
# 国务院（TRS CMS 静态导出 JSON，最新政策）
# ─────────────────────────────────────────────

def scrape_gov() -> list[dict]:
    raw = _fetch(_GOV_JSON, extra_headers={"Referer": _GOV_REFERER})
    items = json.loads(raw)
    seen: set[str] = set()
    results: list[dict] = []
    for item in items:
        url = item.get("URL", "").strip()
        title = _clean_title(item.get("TITLE", ""))
        pub_date = item.get("DOCRELPUBTIME", "")
        if not url or not title or url in seen:
            continue
        seen.add(url)
        results.append({"source": "国务院", "title": title, "url": url, "pub_date": pub_date})
    print(f"[国务院] 抓到 {len(results)} 条")
    return results


# ─────────────────────────────────────────────
# 生态环境部（环境标准规范列表，日期在 URL 里）
# ─────────────────────────────────────────────

def scrape_mee() -> list[dict]:
    html = _fetch(_MEE_LIST, extra_headers={"Referer": _MEE_REFERER})
    # URL 格式: ./bzwb/SECTION/SUBSECTION/202601/t20260129_XXXXXX.shtml
    items = re.findall(
        r'href="\./([^"]{5,120}/t(\d{8})_\d+\.shtml)"[^>]*>\s*([^<]{5,80})\s*</a>',
        html,
    )
    seen: set[str] = set()
    results: list[dict] = []
    for path, date8, title in items:
        url = _MEE_BASE + path
        title = _clean_title(title)
        if not title or url in seen:
            continue
        seen.add(url)
        pub_date = f"{date8[:4]}-{date8[4:6]}-{date8[6:8]}"
        results.append({"source": "生态环境部", "title": title, "url": url, "pub_date": pub_date})
    print(f"[生态环境部] 抓到 {len(results)} 条")
    return results


# ─────────────────────────────────────────────
# 金融监管总局（监管动态，cbircweb API）
# ─────────────────────────────────────────────

def scrape_nfra() -> list[dict]:
    raw = _fetch(_NFRA_API, extra_headers={"Referer": _NFRA_REFERER})
    resp = json.loads(raw)
    rows = resp.get("data", {}).get("rows", [])
    seen: set[str] = set()
    results: list[dict] = []
    for row in rows:
        doc_id = row.get("docId")
        title = _clean_title(row.get("docTitle", ""))
        pub_date = row.get("publishDate", "")[:10]
        if not doc_id or not title:
            continue
        url = f"{_NFRA_BASE}?docId={doc_id}&itemId=915"
        if url in seen:
            continue
        seen.add(url)
        results.append({"source": "金融监管总局", "title": title, "url": url, "pub_date": pub_date})
    print(f"[金融监管总局] 抓到 {len(results)} 条")
    return results


# ─────────────────────────────────────────────
# 展示
# ─────────────────────────────────────────────

def _print_latest(conn: sqlite3.Connection, n: int = 20) -> None:
    rows = conn.execute(
        "SELECT source, pub_date, title FROM policies "
        "ORDER BY pub_date DESC, id DESC LIMIT ?", (n,)
    ).fetchall()
    print(f"\n{'─'*76}")
    print(f"{'来源':<8}  {'日期':<12}  {'标题'}")
    print(f"{'─'*76}")
    for source, date, title in rows:
        print(f"[{source:<7}]  {(date or '?'):<10}  {title[:44]}")
    print(f"{'─'*76}")


# ─────────────────────────────────────────────
# 入口
# ─────────────────────────────────────────────

_ALL_SCRAPERS = {
    "商务部":     lambda conn: scrape_cms("商务部"),
    "工信部":     lambda conn: scrape_cms("工信部"),
    "市场监管总局": lambda conn: scrape_cms("市场监管总局"),
    "证监会":     scrape_csrc,
    "国家能源局": lambda conn: scrape_nea(),
    "财政部":     lambda conn: scrape_mof(),
    "央行":       lambda conn: scrape_pboc(),
    "发改委":     lambda conn: scrape_ndrc(),
    "交通运输部": lambda conn: scrape_mot(),
    "国务院":     lambda conn: scrape_gov(),
    "生态环境部": lambda conn: scrape_mee(),
    "金融监管总局": lambda conn: scrape_nfra(),
}


def main() -> None:
    parser = argparse.ArgumentParser(description="政府政策监控（12 部委）")
    parser.add_argument("--list",   action="store_true", help="只展示数据库最新记录")
    parser.add_argument("--source", type=str, help=f"只抓指定来源: {list(_ALL_SCRAPERS)}")
    args = parser.parse_args()

    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    _init_db(conn)

    if args.list:
        _print_latest(conn)
        conn.close()
        return

    sources = [args.source] if args.source else list(_ALL_SCRAPERS)
    all_items: list[dict] = []

    for name in sources:
        if name not in _ALL_SCRAPERS:
            print(f"未知来源: {name}，可选: {list(_ALL_SCRAPERS)}")
            continue
        try:
            all_items += _ALL_SCRAPERS[name](conn)
        except Exception as e:
            print(f"[{name}] 抓取异常: {e}")
        time.sleep(1)

    new = _save(conn, all_items)
    total = conn.execute("SELECT COUNT(*) FROM policies").fetchone()[0]
    print(f"\n✅ 新增 {new} 条 | 数据库累计 {total} 条 | {DB_PATH}")

    _print_latest(conn)
    conn.close()


if __name__ == "__main__":
    main()
