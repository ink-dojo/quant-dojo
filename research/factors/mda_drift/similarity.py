"""
同公司跨年份 MD&A 的 TF-IDF cosine similarity → drift score.

核心定义:
    drift_score(symbol, year) = 1 - cosine(mda_year, mda_year-1)
高 drift = 文本改动多 = 按 Cohen/Malloy/Nguyen (2020 JoF) 方法论, 未来 underperform 预期.

关键工程决定:
- TfidfVectorizer 用 **per-symbol-all-years corpus** fit, 不全市场共享.
  原因: 跨公司的 IDF 分布差异会让"公司 A 的独特词"和"公司 B 的独特词"权重不可比.
  Lazy Prices 原文同样 per-document-pair 相似度, 不用跨公司 IDF.
- analyzer='word', token 已在 text_processor.tokenize_chinese 里做好, 这里用自定义
  tokenizer=lambda x: x (因为输入已是 list[str]).
- ngram_range=(1, 2) 捕捉短语漂移, 是 Lazy Prices 原文的 setup.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd


@dataclass(frozen=True)
class DriftConfig:
    """TF-IDF + cosine 的参数打包, 便于 snapshot_hash."""

    ngram_min: int = 1
    ngram_max: int = 2
    min_df: int = 1                 # 单公司语料小, min_df=1
    max_df: float = 1.0             # 单公司语料小, 不 filter 高频
    sublinear_tf: bool = True       # 抑制长文档 dominate
    norm: str = "l2"

    def as_dict(self) -> dict:
        return {
            "ngram_min": self.ngram_min,
            "ngram_max": self.ngram_max,
            "min_df": self.min_df,
            "max_df": self.max_df,
            "sublinear_tf": self.sublinear_tf,
            "norm": self.norm,
        }


class MDADriftComputer:
    """
    对单家公司的多年 MD&A tokens 列表, 计算相邻年份的 drift_score.

    使用示例:
        computer = MDADriftComputer()
        year_to_tokens = {2020: [...], 2021: [...], 2022: [...]}
        scores = computer.compute(year_to_tokens)
        # scores = {2021: 0.15, 2022: 0.08}  # 相对前一年的 drift
    """

    def __init__(self, config: DriftConfig | None = None):
        self.config = config or DriftConfig()

    def compute(self, year_to_tokens: dict[int, list[str]]) -> dict[int, float]:
        """
        参数:
            year_to_tokens: {fiscal_year: [tokens]}, 至少 2 年才能出 drift

        返回:
            {fiscal_year: drift_score} — 对每个 year (除最早年份), 返回 1 - cosine(y, y-1)
            若某年 tokens 为空或不足, 该年不在输出中
        """
        from sklearn.feature_extraction.text import TfidfVectorizer
        from sklearn.metrics.pairwise import cosine_similarity

        years = sorted(y for y, tokens in year_to_tokens.items() if tokens)
        if len(years) < 2:
            return {}

        docs = [year_to_tokens[y] for y in years]

        # 关键: 我们的 input 已经是 tokens list, 用 identity tokenizer
        vectorizer = TfidfVectorizer(
            tokenizer=_identity,
            preprocessor=_identity,
            token_pattern=None,        # 禁用默认 regex
            lowercase=False,
            ngram_range=(self.config.ngram_min, self.config.ngram_max),
            min_df=self.config.min_df,
            max_df=self.config.max_df,
            sublinear_tf=self.config.sublinear_tf,
            norm=self.config.norm,
        )
        # 避免 sklearn 警告: ngram>1 对 custom tokenizer 下的 list 也是 OK 的
        mat = vectorizer.fit_transform(docs)
        sim = cosine_similarity(mat)

        out: dict[int, float] = {}
        for i in range(1, len(years)):
            y = years[i]
            out[y] = float(1.0 - sim[i, i - 1])
        return out


def _identity(x):
    """Identity passthrough for TfidfVectorizer tokenizer/preprocessor."""
    return x


def compute_pairwise_drift(
    panel: pd.DataFrame,
    config: DriftConfig | None = None,
) -> pd.DataFrame:
    """
    从 (symbol, fiscal_year, tokens) 长表计算 drift_score 宽表.

    参数:
        panel: DataFrame, 必须列 ['symbol', 'fiscal_year', 'tokens'],
               tokens 列为 list[str]
        config: DriftConfig

    返回:
        DataFrame: index=fiscal_year (int), columns=symbol (str), values=drift_score
        该年某公司无上一年数据时为 NaN
    """
    required = {"symbol", "fiscal_year", "tokens"}
    missing = required - set(panel.columns)
    if missing:
        raise ValueError(f"panel 缺列: {missing}")

    computer = MDADriftComputer(config=config)
    per_symbol: dict[str, dict[int, float]] = {}

    for symbol, grp in panel.groupby("symbol"):
        y2t = {int(r.fiscal_year): r.tokens for r in grp.itertuples(index=False)}
        per_symbol[symbol] = computer.compute(y2t)

    # 长 → 宽
    rows: list[dict] = []
    for symbol, y2d in per_symbol.items():
        for y, d in y2d.items():
            rows.append({"symbol": symbol, "fiscal_year": y, "drift": d})
    if not rows:
        return pd.DataFrame()

    long = pd.DataFrame(rows)
    wide = long.pivot(index="fiscal_year", columns="symbol", values="drift")
    wide.index = wide.index.astype(int)
    wide = wide.sort_index()
    return wide


if __name__ == "__main__":
    # Smoke: 构造 3 年 tokens, 验证相邻年 drift 单调关系
    docs = {
        2021: ["营业", "收入", "增长", "主营", "业务", "稳定", "毛利率", "提升"],
        # 2022 与 2021 高度相似 (小改动)
        2022: ["营业", "收入", "增长", "主营", "业务", "稳定", "毛利率", "小幅", "下滑"],
        # 2023 大改动 (很多新词)
        2023: ["海外", "拓展", "并购", "战略", "转型", "云", "计算", "算力"],
    }
    comp = MDADriftComputer()
    scores = comp.compute(docs)
    print("drift scores:", scores)
    assert 2022 in scores and 2023 in scores
    assert scores[2023] > scores[2022], "大改动年应有更高 drift"
    print(f"✅ similarity smoke pass (2022 drift={scores[2022]:.3f}, 2023 drift={scores[2023]:.3f})")
