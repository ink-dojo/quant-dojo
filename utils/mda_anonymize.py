"""
MD&A 文本脱敏 — 用于 LLM 评分时防未来函数 (LLM cutoff 污染).

脱敏策略 (保守,宁可脱不全也不过度破坏文本):
    1. 公司名 / 简称 / 全称 → "本公司"
    2. 常见后缀 (股份有限公司 / 集团 / 控股) 剥掉后再匹配
    3. 数字 / 百分比 **保留** (具体化程度是 specificity 信号源)
    4. 年份提及 (2023 年 / 本年度) → "Year T" (防止 LLM 激活年份记忆)
    5. 行业细分 (某某行业龙头) 保留 (申万三级脱敏到一级成本过高)

使用方式:
    from utils.mda_anonymize import anonymize_mda
    clean = anonymize_mda(mda_text, symbol="000001")
"""
from __future__ import annotations

import re
from functools import lru_cache

import pandas as pd

from utils.listing_metadata import load_listing_metadata


_SUFFIX_PATTERN = re.compile(r"(股份)?(有限)?公司$|集团(有限公司)?$|控股(集团)?(有限公司)?$")


@lru_cache(maxsize=1)
def _meta() -> pd.DataFrame:
    return load_listing_metadata().set_index("symbol")


def _name_variants(name: str) -> list[str]:
    """从公司 name 生成可能的变体 (全名 / 去后缀 / 2-4 字简称)."""
    variants = {name}
    core = _SUFFIX_PATTERN.sub("", name).strip()
    if len(core) >= 2:
        variants.add(core)
    # "传化智联股份有限公司" -> "传化智联" -> 也可能文中用 "传化"
    if len(core) >= 3:
        variants.add(core[:2])
    # 按长度降序返回 (长的先替换, 避免 "传化" 替换掉 "传化智联" 的前缀)
    return sorted(variants, key=len, reverse=True)


# 防止把 "本公司" 二次替换成 "本本公司" 之类
_PLACEHOLDER = "本公司"

# 年份模式: "2023 年" / "报告期" / "本年度" 等
_YEAR_PATTERN = re.compile(r"20\d{2}\s*年")
_YEAR_LASTYEAR_PATTERN = re.compile(r"(上年同期|去年同期|上一年度|本年度|报告期末|报告期内)")


def anonymize_mda(text: str, symbol: str, year_label: str = "Year T") -> str:
    """
    脱敏单份 MD&A 文本.

    参数:
        text: 原 MD&A 文本 (已 extract, jieba 前)
        symbol: 6 位股票代码 (用于查公司名)
        year_label: 文本中 "本年度" 的替换标签, 如 "Year T" 或 "Year T-1"

    返回:
        脱敏后文本. 长度基本不变 (regex 替换).
    """
    meta = _meta()
    if symbol in meta.index:
        name = str(meta.loc[symbol, "name"])
        for v in _name_variants(name):
            if v and len(v) >= 2:
                text = text.replace(v, _PLACEHOLDER)

    # 清理替换后残留: "本公司股份有限公司" → "本公司", "本公司集团" → "本公司"
    text = re.sub(r"本公司(股份)?(有限)?公司", "本公司", text)
    text = re.sub(r"本公司集团(有限公司)?", "本公司", text)
    text = re.sub(r"本公司控股(集团)?(有限公司)?", "本公司", text)
    # 合并连续 "本公司" 为单个
    text = re.sub(r"(本公司)+", "本公司", text)

    # 年份脱敏 — "2023 年" 类 → "{year_label}"
    text = _YEAR_PATTERN.sub(f"{year_label} ", text)
    # "本年度/报告期" 等相对表述不动 (它们指向文档内时序, 不泄漏绝对年份)

    # 把 "中国" / "A 股" / 省市地理标识保留 (对 specificity 判断有用且不唯一指向身份)

    return text


def anonymize_tokens(tokens: list[str], symbol: str, year_label: str = "Year T") -> list[str]:
    """对 jieba 切过的 tokens 做脱敏 (按整串 join → 脱敏 → re-tokenize 简化版: 直接 str.replace)."""
    # 对分词后的 tokens, 公司名被切成多 token, 直接匹配 token 层
    meta = _meta()
    out = list(tokens)
    if symbol in meta.index:
        name = str(meta.loc[symbol, "name"])
        variants = set(_name_variants(name))
        # 也把 name 切出的子字符加进去 (jieba 可能把 "传化智联" 切成 "传化 智联")
        for v in list(variants):
            if len(v) >= 2:
                # 加单字组合 (jieba 可能切成单字)
                pass  # 单字太激进, 会误伤
        out = [_PLACEHOLDER if tok in variants else tok for tok in out]
    return out


if __name__ == "__main__":
    # smoke
    test_text = "贵州茅台股份有限公司报告期内继续保持茅台酒核心地位, 2023 年营收同比增长. 本公司贵州茅台集团的协同效应显著."
    clean = anonymize_mda(test_text, symbol="600519", year_label="Year T")
    print("BEFORE:", test_text)
    print("AFTER: ", clean)
