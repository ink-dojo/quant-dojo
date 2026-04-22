"""
年报 PDF 数据加载 (cninfo / 巨潮资讯)

职责:
1. list_annual_reports: 用 akshare 列出指定公司指定年份区间的年报公告
2. download_annual_report: 下载单个 PDF, parquet cache 不适用 (PDF 是二进制), 用磁盘文件直接缓存
3. batch_download_pdfs: 批量下载 + rate-limit

cache 规则:
    data/raw/annual_reports/{symbol}_{year}.pdf            - PDF 原文件
    data/raw/annual_reports/_manifest.parquet              - 下载清单 (symbol, year, pdf_url, file_path, downloaded_at)

NB: data/ 在 .gitignore 中, 下载产物不入 git. 本模块只负责下载, 不做文本抽取.
"""
from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path

import pandas as pd
import requests
from tqdm import tqdm

DEFAULT_CACHE_DIR = Path("data/raw/annual_reports")
DEFAULT_TIMEOUT = 30
DEFAULT_RATE_LIMIT_S = 0.5  # 2 req/s, 对 cninfo 友好

# akshare 返回的列名 (经过 normalize 后)
_COL_SYMBOL = "代码"
_COL_TITLE = "公告标题"
_COL_DATE = "公告时间"
_COL_URL = "公告链接"


@dataclass(frozen=True)
class AnnualReportRef:
    """一份年报的定位信息."""

    symbol: str            # 6 位数字, 如 "000001"
    fiscal_year: int       # 对应财年, 如 2023
    publish_date: str      # YYYY-MM-DD
    title: str             # 公告标题
    pdf_url: str           # 下载链接


def list_annual_reports(
    symbol: str,
    start_year: int,
    end_year: int,
    market: str = "沪深京",
) -> list[AnnualReportRef]:
    """
    列出指定公司在 [start_year, end_year] 财年的**年度报告正文**公告 (排除摘要/更正).

    参数:
        symbol: 6 位股票代码, 如 "000001"
        start_year: 起始财年 (inclusive)
        end_year: 结束财年 (inclusive)
        market: akshare 市场过滤, 默认 "沪深京"

    返回:
        list[AnnualReportRef], 按 publish_date 升序

    备注:
        - 年报一般在 T+1 年 4 月前后发布, 所以查询区间要扩到 end_year+1
        - 过滤掉 "摘要" / "更正" / "补充" 标题, 只要主报告
    """
    import akshare as ak

    # 年报在下一年 1-6 月发布, 查询时间要多扩一年
    query_start = f"{start_year}0101"
    query_end = f"{end_year + 1}0731"

    df = ak.stock_zh_a_disclosure_report_cninfo(
        symbol=symbol,
        market=market,
        category="年报",
        start_date=query_start,
        end_date=query_end,
    )
    if df is None or df.empty:
        return []

    # 过滤非正文年报
    df = df.copy()
    mask_exclude = df[_COL_TITLE].str.contains(
        r"摘要|更正|补充|英文版|英文|Summary|已取消|取消", regex=True, na=False
    )
    df = df.loc[~mask_exclude]

    out: list[AnnualReportRef] = []
    for _, row in df.iterrows():
        title = str(row[_COL_TITLE])
        publish_date = str(row[_COL_DATE])[:10]  # "YYYY-MM-DD"
        # 财年 = 公告年份 - 1 (如 2024-04 发的是 2023 年报)
        pub_year = int(publish_date[:4])
        fiscal_year = pub_year - 1
        if not (start_year <= fiscal_year <= end_year):
            continue
        out.append(
            AnnualReportRef(
                symbol=symbol,
                fiscal_year=fiscal_year,
                publish_date=publish_date,
                title=title,
                pdf_url=str(row[_COL_URL]),
            )
        )

    # 去重 (同财年多次发布时保留最早的原版)
    seen: dict[int, AnnualReportRef] = {}
    for ref in sorted(out, key=lambda r: r.publish_date):
        seen.setdefault(ref.fiscal_year, ref)
    return sorted(seen.values(), key=lambda r: r.fiscal_year)


def download_annual_report(
    ref: AnnualReportRef,
    cache_dir: Path = DEFAULT_CACHE_DIR,
    timeout: int = DEFAULT_TIMEOUT,
    overwrite: bool = False,
) -> Path:
    """
    下载单个年报 PDF 到本地缓存, 返回文件路径.

    参数:
        ref: AnnualReportRef
        cache_dir: 下载目录, 默认 data/raw/annual_reports/
        overwrite: True 则强制重下

    返回:
        Path 指向落盘的 PDF 文件

    异常:
        requests.HTTPError 上抛, 由上层决定是否重试
    """
    cache_dir.mkdir(parents=True, exist_ok=True)
    target = cache_dir / f"{ref.symbol}_{ref.fiscal_year}.pdf"
    if target.exists() and not overwrite:
        return target

    headers = {
        # cninfo 对默认 UA 有限流
        "User-Agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
        ),
    }
    resp = requests.get(ref.pdf_url, headers=headers, timeout=timeout)
    resp.raise_for_status()
    target.write_bytes(resp.content)
    return target


def batch_download_pdfs(
    refs: list[AnnualReportRef],
    cache_dir: Path = DEFAULT_CACHE_DIR,
    rate_limit_s: float = DEFAULT_RATE_LIMIT_S,
    max_retries: int = 3,
    show_progress: bool = True,
) -> pd.DataFrame:
    """
    批量下载年报 PDF, 返回 manifest DataFrame.

    参数:
        refs: AnnualReportRef 列表
        cache_dir: 下载目录
        rate_limit_s: 每请求之间 sleep 秒数 (对 cninfo 友好)
        max_retries: 单个请求失败重试次数
        show_progress: 是否显示 tqdm 进度条

    返回:
        DataFrame 包含列: symbol, fiscal_year, publish_date, title,
                          pdf_url, file_path, status, retry_count
        status ∈ {'ok', 'cached', 'failed'}
    """
    records: list[dict] = []
    iterator = tqdm(refs, desc="downloading annual reports") if show_progress else refs

    for ref in iterator:
        target = cache_dir / f"{ref.symbol}_{ref.fiscal_year}.pdf"
        rec = {
            "symbol": ref.symbol,
            "fiscal_year": ref.fiscal_year,
            "publish_date": ref.publish_date,
            "title": ref.title,
            "pdf_url": ref.pdf_url,
            "file_path": str(target),
            "status": "pending",
            "retry_count": 0,
        }
        if target.exists():
            rec["status"] = "cached"
            records.append(rec)
            continue

        last_err: Exception | None = None
        for attempt in range(max_retries):
            rec["retry_count"] = attempt
            try:
                download_annual_report(ref, cache_dir=cache_dir)
                rec["status"] = "ok"
                break
            except Exception as e:
                last_err = e
                time.sleep(rate_limit_s * (attempt + 1))
        else:
            rec["status"] = "failed"
            rec["error"] = repr(last_err) if last_err else "unknown"
        records.append(rec)

        time.sleep(rate_limit_s)

    return pd.DataFrame(records)


if __name__ == "__main__":
    # 最小验证: 列一家公司 2022-2023 年报, 不真实下载 (避免 __main__ 引入网络依赖)
    print("mda_drift.data_loader — smoke test (list-only, no download)")
    try:
        refs = list_annual_reports("000001", 2022, 2023)
        print(f"  found {len(refs)} reports for 000001:")
        for r in refs:
            print(f"    fiscal_year={r.fiscal_year}  publish={r.publish_date}  title={r.title[:40]}")
    except Exception as e:
        print(f"  list failed (network?): {e!r}")
    print("✅ module importable")
