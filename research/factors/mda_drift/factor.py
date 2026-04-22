"""
MD&A drift factor — 端到端 pipeline.

给定一组 symbols 和年份区间, 返回 drift_score 的年度宽表 (date × symbol).
复用:
    data_loader.list_annual_reports / batch_download_pdfs  (PDF 原文)
    text_processor.pdf_to_text / extract_mda_section / tokenize_chinese  (→ tokens)
    similarity.compute_pairwise_drift  (→ 因子值)

缓存策略:
    data/raw/annual_reports/{symbol}_{year}.pdf             — PDF 原文 (data_loader 管)
    data/processed/mda_tokens/{symbol}_{year}.parquet       — 分词 tokens (本模块管)
    data/processed/mda_drift_scores.parquet                 — 最终宽表 (本模块管)

factor 值 publish 日期:
    对每个 (symbol, fiscal_year), 因子在**年报发布日 (publish_date)** 起可用,
    统一以 fiscal_year+1 的年报发布日为 factor 值 as_of 日期, 保证无未来函数.
    粗略估计: 发布日 ~ fiscal_year+1 的 4 月底前. Tier 1 的输出用 fiscal_year
    索引, 在下游回测时再做 lag → 真实交易日 mapping.
"""
from __future__ import annotations

import logging
from pathlib import Path

import pandas as pd
from tqdm import tqdm

from research.factors.mda_drift.data_loader import (
    AnnualReportRef,
    DEFAULT_CACHE_DIR as PDF_CACHE_DIR,
    batch_download_pdfs,
    list_annual_reports,
)
from research.factors.mda_drift.similarity import (
    DriftConfig,
    compute_pairwise_drift,
)
from research.factors.mda_drift.text_processor import (
    extract_mda_section,
    pdf_to_text,
    tokenize_chinese,
)

DEFAULT_TOKENS_DIR = Path("data/processed/mda_tokens")
DEFAULT_DRIFT_PATH = Path("data/processed/mda_drift_scores.parquet")

logger = logging.getLogger(__name__)


def _tokens_cache_path(cache_dir: Path, symbol: str, fiscal_year: int) -> Path:
    return cache_dir / f"{symbol}_{fiscal_year}.parquet"


def process_single_pdf_to_tokens(
    symbol: str,
    fiscal_year: int,
    pdf_path: Path,
    tokens_cache_dir: Path = DEFAULT_TOKENS_DIR,
    overwrite: bool = False,
) -> dict:
    """
    单份 PDF → tokens, 写入 parquet 缓存, 返回诊断 dict.

    返回字段:
        symbol, fiscal_year, pdf_path, full_text_len, mda_text_len, token_count, status
        status ∈ {'ok', 'cached', 'no_mda', 'no_text', 'error'}
    """
    tokens_cache_dir.mkdir(parents=True, exist_ok=True)
    cache_path = _tokens_cache_path(tokens_cache_dir, symbol, fiscal_year)
    if cache_path.exists() and not overwrite:
        try:
            df = pd.read_parquet(cache_path)
            return {
                "symbol": symbol,
                "fiscal_year": fiscal_year,
                "pdf_path": str(pdf_path),
                "full_text_len": int(df.attrs.get("full_text_len", -1)),
                "mda_text_len": int(df.attrs.get("mda_text_len", -1)),
                "token_count": len(df),
                "status": "cached",
            }
        except Exception:
            pass  # fall through and recompute

    try:
        full = pdf_to_text(pdf_path)
    except Exception as e:
        return {
            "symbol": symbol,
            "fiscal_year": fiscal_year,
            "pdf_path": str(pdf_path),
            "full_text_len": 0,
            "mda_text_len": 0,
            "token_count": 0,
            "status": "error",
            "error": repr(e),
        }

    if not full:
        return {
            "symbol": symbol,
            "fiscal_year": fiscal_year,
            "pdf_path": str(pdf_path),
            "full_text_len": 0,
            "mda_text_len": 0,
            "token_count": 0,
            "status": "no_text",
        }

    mda = extract_mda_section(full)
    if not mda:
        return {
            "symbol": symbol,
            "fiscal_year": fiscal_year,
            "pdf_path": str(pdf_path),
            "full_text_len": len(full),
            "mda_text_len": 0,
            "token_count": 0,
            "status": "no_mda",
        }

    tokens = tokenize_chinese(mda)

    df = pd.DataFrame({"token": tokens})
    df.attrs["full_text_len"] = len(full)
    df.attrs["mda_text_len"] = len(mda)
    df.to_parquet(cache_path)

    return {
        "symbol": symbol,
        "fiscal_year": fiscal_year,
        "pdf_path": str(pdf_path),
        "full_text_len": len(full),
        "mda_text_len": len(mda),
        "token_count": len(tokens),
        "status": "ok",
    }


def load_tokens(symbol: str, fiscal_year: int, cache_dir: Path = DEFAULT_TOKENS_DIR) -> list[str]:
    """从 parquet 缓存读 tokens; 不存在返回空列表."""
    path = _tokens_cache_path(cache_dir, symbol, fiscal_year)
    if not path.exists():
        return []
    return pd.read_parquet(path)["token"].tolist()


def compute_mda_drift_factor(
    symbols: list[str],
    start_year: int,
    end_year: int,
    pdf_cache_dir: Path = PDF_CACHE_DIR,
    tokens_cache_dir: Path = DEFAULT_TOKENS_DIR,
    config: DriftConfig | None = None,
    download: bool = True,
    show_progress: bool = True,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """
    端到端 pipeline: symbols × [start_year, end_year] → drift_score 宽表.

    参数:
        symbols: 6 位股票代码列表
        start_year/end_year: 财年区间, 必须 end_year >= start_year + 1 (至少 2 年)
        download: True 则用 data_loader 自动爬 + 下载 PDF; False 则只读现有缓存
        config: TF-IDF 超参, 默认见 DriftConfig

    返回:
        (factor_wide, diagnostics)
            factor_wide: DataFrame index=fiscal_year (int), columns=symbol, value=drift
            diagnostics: DataFrame, 每 (symbol, year) 一行, 含 status / text_len / token_count
    """
    if end_year < start_year + 1:
        raise ValueError(f"end_year 必须 >= start_year+1, got {start_year}..{end_year}")

    config = config or DriftConfig()
    all_refs: list[AnnualReportRef] = []
    diagnostics_rows: list[dict] = []

    # Step 1: 列 PDF
    iterator = tqdm(symbols, desc="listing annual reports") if show_progress else symbols
    for sym in iterator:
        try:
            refs = list_annual_reports(sym, start_year, end_year)
            all_refs.extend(refs)
        except Exception as e:
            logger.warning("list_annual_reports failed for %s: %r", sym, e)
            diagnostics_rows.append(
                {"symbol": sym, "fiscal_year": -1, "status": "list_failed", "error": repr(e)}
            )

    # Step 2: 下载 PDF (可选)
    if download and all_refs:
        manifest = batch_download_pdfs(all_refs, cache_dir=pdf_cache_dir, show_progress=show_progress)
    else:
        # 只读现有缓存
        manifest = pd.DataFrame([
            {
                "symbol": r.symbol,
                "fiscal_year": r.fiscal_year,
                "publish_date": r.publish_date,
                "pdf_url": r.pdf_url,
                "file_path": str(pdf_cache_dir / f"{r.symbol}_{r.fiscal_year}.pdf"),
                "status": "cached" if (pdf_cache_dir / f"{r.symbol}_{r.fiscal_year}.pdf").exists() else "missing",
                "retry_count": 0,
            }
            for r in all_refs
        ])

    # Step 3: PDF → tokens
    ok_mask = manifest["status"].isin(["ok", "cached"])
    pending = manifest.loc[ok_mask]
    iterator2 = (
        tqdm(pending.to_dict("records"), desc="extracting MD&A tokens")
        if show_progress else pending.to_dict("records")
    )
    token_rows: list[dict] = []
    for rec in iterator2:
        diag = process_single_pdf_to_tokens(
            symbol=rec["symbol"],
            fiscal_year=int(rec["fiscal_year"]),
            pdf_path=Path(rec["file_path"]),
            tokens_cache_dir=tokens_cache_dir,
        )
        token_rows.append(diag)
        diagnostics_rows.append(diag)

    # Step 4: 装载 tokens + 算 drift
    panel_rows: list[dict] = []
    for diag in token_rows:
        if diag["status"] in ("ok", "cached") and diag["token_count"] > 0:
            toks = load_tokens(diag["symbol"], diag["fiscal_year"], tokens_cache_dir)
            if toks:
                panel_rows.append({
                    "symbol": diag["symbol"],
                    "fiscal_year": diag["fiscal_year"],
                    "tokens": toks,
                })

    if not panel_rows:
        logger.warning("no usable tokens; returning empty factor")
        return pd.DataFrame(), pd.DataFrame(diagnostics_rows)

    panel = pd.DataFrame(panel_rows)
    factor_wide = compute_pairwise_drift(panel, config=config)
    diagnostics = pd.DataFrame(diagnostics_rows)
    return factor_wide, diagnostics


if __name__ == "__main__":
    # 模块级 smoke: 仅确认 import + type; 真正 end-to-end 跑由
    # scripts/mda_drift_tier1_eval.py 负责
    print("mda_drift.factor — import ok")
    print("  entry: compute_mda_drift_factor(symbols, start_year, end_year)")
    print("  缓存目录: ")
    print(f"    PDF:     {PDF_CACHE_DIR}")
    print(f"    tokens:  {DEFAULT_TOKENS_DIR}")
