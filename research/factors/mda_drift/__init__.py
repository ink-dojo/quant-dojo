"""
空间 C Tier 1 — MD&A 语义漂移因子

复刻 Cohen/Malloy/Nguyen (2020, JoF) "Lazy Prices" 到 A 股:
同一公司相邻两年年报 MD&A 段的 TF-IDF cosine similarity, 低相似度 (高漂移) 做多,
高相似度 (低漂移) 做空.

上游文档: research/space_c_llm_alpha/alpha_theory_space_c_research_20260421.md
Issue: #25

模块组织:
    data_loader   — cninfo 年报列表 + PDF 下载 + 磁盘缓存
    text_processor — PDF → txt, MD&A 段抽取, 中文 tokenize
    similarity    — TF-IDF + cosine, drift_score = 1 - cosine
    factor        — 端到端 pipeline, 输出 date × symbol 宽表
"""
from research.factors.mda_drift.data_loader import (
    list_annual_reports,
    download_annual_report,
)
from research.factors.mda_drift.text_processor import (
    pdf_to_text,
    extract_mda_section,
    tokenize_chinese,
)
from research.factors.mda_drift.similarity import (
    DriftConfig,
    MDADriftComputer,
    compute_pairwise_drift,
)
from research.factors.mda_drift.factor import (
    compute_mda_drift_factor,
    load_tokens,
    process_single_pdf_to_tokens,
)

__all__ = [
    "list_annual_reports",
    "download_annual_report",
    "pdf_to_text",
    "extract_mda_section",
    "tokenize_chinese",
    "DriftConfig",
    "MDADriftComputer",
    "compute_pairwise_drift",
    "compute_mda_drift_factor",
    "load_tokens",
    "process_single_pdf_to_tokens",
]
