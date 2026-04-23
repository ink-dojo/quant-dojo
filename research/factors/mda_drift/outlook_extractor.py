"""
切 MD&A 的 "未来发展展望" section.

A 股年报 MD&A 一般分: 业务回顾 / 核心竞争力 / 经营情况 / **未来发展展望** / 接待调研.
"未来发展展望" 这个 section 通常包含: 行业趋势 + 公司战略 + 可能面对的风险,
是管理层真正讨论前景和风险的聚焦段, 信噪比远高于全文.

覆盖率测试 (n=100 随机 MD&A): "未来 发展 的? 展望" 关键词 94%.
"""
from __future__ import annotations

import re


_START_PATTERNS = [
    r"未来\s*发展\s*的?\s*展望",
    r"公司\s*未来\s*发展",
    r"未来\s*发展\s*战略",
    r"发展\s*规划",
    # wider fallbacks
    r"经营\s*计划",
    r"下\s*一\s*年?\s*度?\s*工作\s*计划",
    r"[一-鿿]?\s*[年度]\s*经营\s*目标",
    r"行业\s*格局\s*和?\s*发展\s*趋势",
]

# 结束 anchor 按常见后续 section 排优先级 (越"必出现"越排前)
_END_PATTERNS = [
    r"接待\s*调研",
    r"接待\s*机构",
    r"核心\s*竞争力\s*分析",
    r"重大\s*风险\s*提示",  # 某些年报结构化标题
    r"重要\s*事项",
    r"公司\s*治理",
    r"股东\s*[情况及]",
    r"监事\s*会",
    r"董事\s*会",
    r"第\s*[五六七八九]\s*节",  # 下一章标识
]


def extract_outlook_section(full_mda: str, min_len: int = 500, max_len: int = 15000) -> str:
    """
    从 MD&A 正文里切 "未来发展展望" section.

    参数:
        full_mda: MD&A 全文 (extract_mda_section 的输出)
        min_len: 最小接受长度; 若切出来 < min_len 视为失败
        max_len: 截断上限 (防止 end anchor 没找到时吃太多)

    返回:
        展望段文本. 失败返回空串.
    """
    if not full_mda:
        return ""

    def _try_cut(start: int) -> str:
        rest = full_mda[start:]
        end_rel = len(rest)
        for pat in _END_PATTERNS:
            m = re.search(pat, rest[50:])
            if m:
                end_rel = min(end_rel, m.start() + 50)
        section = rest[:end_rel]
        if len(section) > max_len:
            section = section[:max_len]
        return section

    # 找起点: 按优先级依次尝试
    primary_section = ""
    for pat in _START_PATTERNS:
        m = re.search(pat, full_mda)
        if m:
            cand = _try_cut(m.start())
            if len(cand) >= min_len:
                primary_section = cand
                break

    if primary_section:
        return primary_section

    # Fallback: primary match 失败 OR 切出来太短 → 取后 1/3
    fallback_start = int(len(full_mda) * 0.67)
    fallback_section = _try_cut(fallback_start)
    if len(fallback_section) < min_len:
        return ""
    return fallback_section


if __name__ == "__main__":
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))
    import pandas as pd

    # smoke: 10 个样本
    import random
    random.seed(7)
    files = list(Path("data/processed/mda_tokens").glob("*.parquet"))
    samples = random.sample(files, 10)
    print(f"{'sample':20s}  {'full_len':>10s}  {'outlook_len':>12s}  {'ratio':>6s}")
    for p in samples:
        df = pd.read_parquet(p)
        full = " ".join(df.token.tolist())
        outlook = extract_outlook_section(full)
        ratio = len(outlook) / len(full) if full else 0
        print(f"{p.stem:20s}  {len(full):>10d}  {len(outlook):>12d}  {ratio:.1%}")
