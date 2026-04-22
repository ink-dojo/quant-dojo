"""
年报 PDF → MD&A 段 → 中文分词 tokens

三步 pipeline:
1. pdf_to_text    : 用 pdfplumber 抽取所有页文字
2. extract_mda_section : 正则定位 "管理层讨论与分析" / "经营情况讨论与分析" 段
3. tokenize_chinese   : jieba 分词 + 去停用词 + 去非中文 token

设计决定:
- 不做 OCR. 扫描版老年报数量少, 目前 skip, 记录在 manifest 的 mda_len=0
- 不做公司名/专名词典, Tier 1 只做 baseline
- 停用词用最小内置列表, 后续如需扩大改为文件加载
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Iterable

# A 股年报 MD&A 部分的章节标题变体 (从严到宽)
# 过去 20 年常见表述: "管理层讨论与分析" (主流), "董事会报告" (含 MD&A, 老年报),
# "经营情况讨论与分析" (较新), "管理层分析" (简写)
_MDA_HEADER_PATTERNS = [
    r"第[一二三四五六七八九十]节\s*管理层讨论与分析",
    r"第[一二三四五六七八九十]节\s*经营情况讨论与分析",
    r"第[一二三四五六七八九十]节\s*董事会报告",
    r"管理层讨论与分析",
    r"经营情况讨论与分析",
    r"董事会报告",
]

# 下一章节, 作为 MD&A 段的终止锚
_NEXT_SECTION_PATTERNS = [
    r"第[一二三四五六七八九十]节\s*重要事项",
    r"第[一二三四五六七八九十]节\s*公司治理",
    r"第[一二三四五六七八九十]节\s*股份变动",
    r"第[一二三四五六七八九十]节\s*环境和社会责任",
    r"第[一二三四五六七八九十]节\s*财务报告",
    r"第[一二三四五六七八九十]节\s*监事会报告",
    r"重要事项",
    r"公司治理",
    r"股份变动及股东情况",
    r"财务报告",
]

# 中文停用词 — 保守的小 list, 避免过度清洗;
# 重点是把"公司""报告""本年度"这类 MD&A boilerplate 词汇去掉
_STOPWORDS = {
    "的", "了", "和", "是", "就", "都", "而", "及", "与", "或", "之", "其",
    "为", "在", "有", "对", "由", "以", "则", "从", "到", "于", "向",
    "本", "该", "等", "本年度", "本报告期", "报告期", "年度", "期间",
    "公司", "本公司", "集团", "本集团", "股份",
    "人民币", "万元", "亿元", "元", "个",
    "主要", "情况", "方面", "进行", "实现", "完成",
    "及其", "以及", "通过", "根据", "按照", "采用",
}


def pdf_to_text(pdf_path: Path | str, max_pages: int | None = None) -> str:
    """
    用 pdfplumber 抽取整份 PDF 的文字.

    参数:
        pdf_path: PDF 文件路径
        max_pages: 只读前 N 页, None 表示全部. 扫描版 PDF 抽不到文字返回空串.

    返回:
        str — 全文本, 页间用 "\n\n" 分隔
    """
    import pdfplumber  # 本地 import, 让模块在无 pdfplumber 时仍可 import (用于测试)

    pdf_path = Path(pdf_path)
    if not pdf_path.exists():
        raise FileNotFoundError(pdf_path)

    pages_text: list[str] = []
    with pdfplumber.open(str(pdf_path)) as pdf:
        for i, page in enumerate(pdf.pages):
            if max_pages is not None and i >= max_pages:
                break
            try:
                t = page.extract_text() or ""
            except Exception:
                t = ""
            pages_text.append(t)
    return "\n\n".join(pages_text)


def extract_mda_section(full_text: str) -> str:
    """
    从完整年报文本中抽取 MD&A 章节, 返回纯文字.

    算法:
        1. 按优先级尝试 _MDA_HEADER_PATTERNS 找到章节起点
        2. 从起点向后, 找最近的 _NEXT_SECTION_PATTERNS 作为终点
        3. 未找到终点时, 截取起点后 80k 字符 (A 股 MD&A 很少超过这个长度)

    参数:
        full_text: pdf_to_text 的输出

    返回:
        str — MD&A 段纯文字; 未找到时返回空串
    """
    if not full_text:
        return ""

    # 找 MD&A 起点: 只取**第一个**匹配后的靠后位置 (目录页会先命中, 选最靠后的一次)
    start: int | None = None
    for pat in _MDA_HEADER_PATTERNS:
        matches = list(re.finditer(pat, full_text))
        if matches:
            start = matches[-1].end()
            break

    if start is None:
        return ""

    # 找终点: 起点之后第一个章节 header
    tail = full_text[start:]
    end_rel: int | None = None
    for pat in _NEXT_SECTION_PATTERNS:
        m = re.search(pat, tail)
        if m and (end_rel is None or m.start() < end_rel):
            end_rel = m.start()

    if end_rel is None:
        end_rel = min(len(tail), 80000)

    return tail[:end_rel].strip()


def tokenize_chinese(
    text: str,
    stopwords: Iterable[str] | None = None,
    min_token_len: int = 2,
) -> list[str]:
    """
    中文分词 + 去停用词 + 过滤单字/数字/非中文.

    参数:
        text: 原文
        stopwords: 停用词集合, None 使用内置 _STOPWORDS
        min_token_len: 最短保留长度, 过滤噪音单字

    返回:
        list[str] — 有序 token 流, 可直接作为 TfidfVectorizer 的输入
    """
    import jieba

    if not text:
        return []

    sw = set(stopwords) if stopwords is not None else _STOPWORDS

    # 只保留汉字, 把数字/标点/字母/空白全转为空格 (分词边界)
    cleaned = re.sub(r"[^一-鿿]+", " ", text)

    tokens: list[str] = []
    for tok in jieba.cut(cleaned, cut_all=False):
        tok = tok.strip()
        if len(tok) < min_token_len:
            continue
        if tok in sw:
            continue
        tokens.append(tok)
    return tokens


def mda_pipeline(pdf_path: Path | str) -> dict:
    """
    PDF → MD&A section → tokens 的端到端辅助函数, 返回诊断信息.

    返回 dict 字段:
        pdf_path, full_text_len, mda_text_len, token_count,
        mda_text (截断到前 2000 字), tokens (完整列表)
    """
    pdf_path = Path(pdf_path)
    full = pdf_to_text(pdf_path)
    mda = extract_mda_section(full)
    tokens = tokenize_chinese(mda)
    return {
        "pdf_path": str(pdf_path),
        "full_text_len": len(full),
        "mda_text_len": len(mda),
        "token_count": len(tokens),
        "mda_text_head": mda[:2000],
        "tokens": tokens,
    }


if __name__ == "__main__":
    # 端到端模块级 smoke: 不需要真 PDF, 用字符串验证 extract + tokenize
    sample = """
    目录
    第一节 重要提示
    第二节 公司简介和主要财务指标
    第三节 管理层讨论与分析
    报告期内, 本公司围绕主营业务稳步推进, 实现营业收入 120 亿元,
    同比增长 15%. 主要产品毛利率小幅下滑, 管理层认为行业竞争加剧,
    未来存在不确定性. 公司将加强研发投入, 拓展海外市场.
    第四节 公司治理
    公司严格遵守公司法和证监会相关规定...
    """
    mda = extract_mda_section(sample)
    print("MD&A 段长度:", len(mda))
    print("MD&A 前 200 字:", mda[:200])
    toks = tokenize_chinese(mda)
    print("tokens (head 20):", toks[:20])
    assert len(mda) > 0, "MD&A 段抽取失败"
    assert len(toks) >= 5, f"token 数异常: {len(toks)}"
    print("✅ text_processor smoke pass")
