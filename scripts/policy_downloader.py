"""
政策文章批量下载器
从 policy_monitor.db 读取所有条目，下载正文保存到 SSD，生成 CSV 索引。

用法:
    python scripts/policy_downloader.py            # 下载全部（跳过已下载）
    python scripts/policy_downloader.py --source 发改委  # 只下载单个来源
    python scripts/policy_downloader.py --csv-only      # 只重建 CSV，不下载

输出:
    /Volumes/Crucial X10/quant-dojo-data/policy_monitor/
    ├── index.csv                  ← 全量索引
    ├── 宏观政策_国务院/
    │   ├── 2026-04-23_xxxx.txt
    │   └── ...
    ├── 宏观政策_发改委/
    ├── 货币金融_央行/
    └── ...（12 个文件夹）
"""

import argparse
import csv
import html
import io
import json
import re
import sqlite3
import time
import urllib.request
from datetime import datetime
from pathlib import Path

from pypdf import PdfReader

# ── 路径 ─────────────────────────────────────────────────────────────────────
SSD_ROOT   = Path("/Volumes/Crucial X10/quant-dojo-data/policy_monitor")
DB_PATH    = Path(__file__).parent.parent / "data" / "policy_monitor.db"
CSV_PATH   = SSD_ROOT / "index.csv"

# ── 分类映射 ──────────────────────────────────────────────────────────────────
CATEGORY = {
    "国务院":    "宏观政策",
    "发改委":    "宏观政策",
    "财政部":    "财税政策",
    "央行":      "货币金融",
    "证监会":    "资本市场",
    "金融监管总局": "金融监管",
    "工信部":    "产业科技",
    "市场监管总局": "市场监管",
    "商务部":    "贸易商务",
    "国家能源局": "能源政策",
    "生态环境部": "生态环保",
    "交通运输部": "交通基建",
}

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,*/*;q=0.8",
    "Accept-Language": "zh-CN,zh;q=0.9",
}

# ── 文件夹名 source → "分类_来源" ──────────────────────────────────────────────
def folder_name(source: str) -> str:
    cat = CATEGORY.get(source, "其他")
    return f"{cat}_{source}"

# ── 安全文件名（去掉 Windows/macOS 非法字符，截断）────────────────────────────
def safe_filename(pub_date: str, title: str) -> str:
    slug = re.sub(r'[\\/:*?"<>|\r\n\t]', "_", title)
    slug = re.sub(r"\s+", "_", slug.strip())[:60]
    return f"{pub_date}_{slug}.txt"

# ── HTTP 抓取（超时 15s，失败返回空字符串）──────────────────────────────────────
def fetch(url: str, referer: str = "") -> str:
    try:
        headers = dict(_HEADERS)
        if referer:
            headers["Referer"] = referer
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=15) as r:
            raw = r.read()
            enc = r.headers.get_content_charset() or "utf-8"
            return raw.decode(enc, errors="replace")
    except Exception:
        return ""

# ── HTML → 纯文本（保留段落结构）──────────────────────────────────────────────
_TAG_RE   = re.compile(r"<[^>]+>")
_SPACE_RE = re.compile(r"[ \t]{2,}")
_NL_RE    = re.compile(r"\n{3,}")

def html_to_text(raw_html: str) -> str:
    # 保留段落换行
    text = re.sub(r"<(?:br|p|div|li|tr|h\d)[^>]*>", "\n", raw_html, flags=re.I)
    text = _TAG_RE.sub("", text)
    text = html.unescape(text)
    text = _SPACE_RE.sub(" ", text)
    text = _NL_RE.sub("\n\n", text)
    return text.strip()

# ── 提取正文（中国政府网站常见结构）──────────────────────────────────────────
_CONTENT_PATTERNS = [
    re.compile(r'<div[^>]+class="[^"]*(?:article|content|TRS_Editor|pages_content|con_con|zwgk)[^"]*"[^>]*>(.*?)</div\s*>', re.S | re.I),
    re.compile(r'<div[^>]+id="[^"]*(?:zoom|content|article)[^"]*"[^>]*>(.*?)</div\s*>', re.S | re.I),
    re.compile(r'<article[^>]*>(.*?)</article>', re.S | re.I),
    re.compile(r'<div[^>]+class="p_content"[^>]*>(.*?)</div>', re.S | re.I),
]

# ── NFRA 专用：通过 cbircweb API 拿 PDF，pypdf 提取正文 ──────────────────────
_NFRA_LIST_API = (
    "https://www.nfra.gov.cn/cbircweb/DocInfo/SelectDocByItemIdAndChild"
    "?itemId=915&pageIndex=1&pageSize=100&tabKey=1"
)
_NFRA_PDF_BASE = "https://www.nfra.gov.cn"
_NFRA_REFERER  = "https://www.nfra.gov.cn/cn/view/pages/ItemDetail.html"

_nfra_pdf_map: dict[str, str] = {}  # docId → pdfFileUrl（懒加载）

def _ensure_nfra_map():
    if _nfra_pdf_map:
        return
    headers = dict(_HEADERS)
    headers["Referer"] = _NFRA_REFERER
    req = urllib.request.Request(_NFRA_LIST_API, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            data = json.loads(r.read())
        for row in data.get("data", {}).get("rows", []):
            doc_id = str(row.get("docId", ""))
            pdf    = row.get("pdfFileUrl", "")
            if doc_id and pdf:
                _nfra_pdf_map[doc_id] = pdf
    except Exception:
        pass

def fetch_nfra_pdf(detail_url: str) -> str:
    """从 NFRA 详情页 URL 提取 docId，下载 PDF，返回纯文本。"""
    _ensure_nfra_map()
    m = re.search(r"docId=(\d+)", detail_url)
    if not m:
        return ""
    doc_id = m.group(1)
    pdf_path = _nfra_pdf_map.get(doc_id)
    if not pdf_path:
        return ""
    pdf_url = _NFRA_PDF_BASE + pdf_path
    headers = dict(_HEADERS)
    headers["Referer"] = _NFRA_REFERER
    try:
        req = urllib.request.Request(pdf_url, headers=headers)
        with urllib.request.urlopen(req, timeout=20) as r:
            pdf_bytes = r.read()
        reader = PdfReader(io.BytesIO(pdf_bytes))
        return "\n".join(page.extract_text() or "" for page in reader.pages).strip()
    except Exception:
        return ""

def extract_content(raw_html: str, title: str, url: str, pub_date: str) -> str:
    text = ""
    for pat in _CONTENT_PATTERNS:
        m = pat.search(raw_html)
        if m:
            candidate = html_to_text(m.group(1))
            if len(candidate) > 100:
                text = candidate
                break
    if not text:
        # fallback: strip all tags
        text = html_to_text(raw_html)
        # 尝试截取正文区域（去掉导航/页脚噪音）
        lines = [l.strip() for l in text.splitlines() if len(l.strip()) > 15]
        text = "\n".join(lines)

    return text

# ── 主流程 ────────────────────────────────────────────────────────────────────
def build_csv(rows: list[dict]):
    """重新写 CSV 索引"""
    with open(CSV_PATH, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=[
            "分类", "来源", "发布日期", "标题", "原文链接", "本地路径", "字数", "下载时间"
        ])
        writer.writeheader()
        writer.writerows(rows)
    print(f"✅ CSV 已写入 {CSV_PATH}（{len(rows)} 条）")

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", default="", help="只下载指定来源，如 发改委")
    parser.add_argument("--csv-only", action="store_true", help="只重建 CSV，不下载文章")
    args = parser.parse_args()

    # 建目录
    SSD_ROOT.mkdir(parents=True, exist_ok=True)
    for src in CATEGORY:
        (SSD_ROOT / folder_name(src)).mkdir(exist_ok=True)

    # 读 DB
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    query = "SELECT source, title, url, pub_date, fetched_at FROM policies"
    if args.source:
        query += " WHERE source = ?"
        rows_db = conn.execute(query, (args.source,)).fetchall()
    else:
        rows_db = conn.execute(query + " ORDER BY pub_date DESC").fetchall()
    conn.close()
    print(f"DB 读取 {len(rows_db)} 条记录")

    csv_rows = []
    downloaded = skipped = failed = 0

    for i, rec in enumerate(rows_db, 1):
        source   = rec["source"]
        title    = rec["title"]
        url      = rec["url"]
        pub_date = rec["pub_date"] or "0000-00-00"
        cat      = CATEGORY.get(source, "其他")
        folder   = SSD_ROOT / folder_name(source)
        fname    = safe_filename(pub_date, title)
        fpath    = folder / fname
        rel_path = f"{folder_name(source)}/{fname}"

        word_count = 0
        dl_time    = ""

        # NFRA 是 Angular SPA，正文在 PDF 里；已有的旧文件若含模板标记则强制重下
        nfra_bad = (
            source == "金融监管总局"
            and fpath.exists()
            and "{{data." in fpath.read_text(encoding="utf-8", errors="replace")
        )

        if fpath.exists() and not nfra_bad:
            word_count = len(fpath.read_text(encoding="utf-8", errors="replace"))
            dl_time    = datetime.fromtimestamp(fpath.stat().st_mtime).strftime("%Y-%m-%d %H:%M")
            skipped += 1
        elif not args.csv_only and url:
            if source == "金融监管总局":
                body = fetch_nfra_pdf(url)
            else:
                html_raw = fetch(url, referer=url)
                body = extract_content(html_raw, title, url, pub_date) if html_raw else ""

            if body:
                header  = f"标题：{title}\n来源：{url}\n日期：{pub_date}\n{'─'*60}\n\n"
                content = header + body
                fpath.write_text(content, encoding="utf-8")
                word_count = len(content)
                dl_time    = datetime.now().strftime("%Y-%m-%d %H:%M")
                downloaded += 1
            else:
                failed += 1
            time.sleep(0.4)
        else:
            failed += 1

        csv_rows.append({
            "分类":   cat,
            "来源":   source,
            "发布日期": pub_date,
            "标题":   title,
            "原文链接": url,
            "本地路径": rel_path,
            "字数":   word_count,
            "下载时间": dl_time,
        })

        if i % 50 == 0 or i == len(rows_db):
            print(f"  进度 {i}/{len(rows_db)} | 新下载 {downloaded} | 跳过 {skipped} | 失败 {failed}")

    build_csv(csv_rows)
    print(f"\n{'='*60}")
    print(f"完成！新下载 {downloaded} 篇 | 已有跳过 {skipped} 篇 | 失败 {failed} 篇")
    print(f"存储位置：{SSD_ROOT}")
    print(f"CSV 索引：{CSV_PATH}")

if __name__ == "__main__":
    main()
