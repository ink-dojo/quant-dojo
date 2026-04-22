"""
空间 C Tier 1 — MD&A drift factor 回归测试

覆盖三块:
1. text_processor: MD&A 段抽取 + 中文分词 + 停用词
2. similarity: TF-IDF cosine 的 drift 排序 (单调性回归)
3. factor: 端到端 panel → wide (用 in-memory tokens 绕开 PDF)

关键不变量:
- 改动大的年份应有更高 drift_score
- 两份完全相同 tokens 的文档应有 drift ≈ 0
- 两份完全无交集的文档应有 drift ≈ 1
- 宽表结构正确 (index=fiscal_year, columns=symbol)
"""
import numpy as np
import pandas as pd
import pytest

from research.factors.mda_drift.similarity import (
    DriftConfig,
    MDADriftComputer,
    compute_pairwise_drift,
)
from research.factors.mda_drift.text_processor import (
    extract_mda_section,
    tokenize_chinese,
)


# ─────────────────────────────────────────────
# text_processor
# ─────────────────────────────────────────────

class TestExtractMDASection:
    """MD&A 段抽取的几种典型年报布局"""

    def test_standard_mda_header(self):
        """最常见: 第三节 管理层讨论与分析"""
        text = (
            "第一节 重要提示\n公司声明...\n"
            "第三节 管理层讨论与分析\n"
            "报告期内业务稳健增长.\n"
            "第四节 公司治理\n"
            "公司严格遵守法规."
        )
        mda = extract_mda_section(text)
        assert "报告期内业务稳健增长" in mda
        assert "公司治理" not in mda, "终止锚之后不应包含"

    def test_alternative_header_jingyingqingkuang(self):
        """近年年报偏好: 经营情况讨论与分析"""
        text = (
            "第二节 公司简介\n略\n"
            "第三节 经营情况讨论与分析\n"
            "本年度营收大幅增长.\n"
            "第四节 重要事项\n无."
        )
        mda = extract_mda_section(text)
        assert "本年度营收大幅增长" in mda
        assert "重要事项" not in mda

    def test_no_mda_returns_empty(self):
        """没有 MD&A header 时返回空串, 不抛异常"""
        text = "这是一份什么都没有的文档, 没有章节标题."
        assert extract_mda_section(text) == ""

    def test_empty_input(self):
        assert extract_mda_section("") == ""

    def test_toc_doesnt_fool_extraction(self):
        """目录页会首先提到 "管理层讨论与分析", 但正文才是真正段落.
        抽取应跳过目录 (点引线 + 页码 特征), 选下一次出现.
        """
        text = (
            "目录\n"
            "第一节 重要提示 ..................... 1\n"
            "第三节 管理层讨论与分析 ............. 15\n"
            "第四节 公司治理 ..................... 30\n"
            "\n正文从这里开始...\n"
            "第三节 管理层讨论与分析\n"
            "这才是真正的 MD&A 内容, 详细描述了业务.\n"
            "第四节 公司治理\n"
            "略"
        )
        mda = extract_mda_section(text)
        assert "这才是真正的 MD&A 内容" in mda
        # 目录页中的 dots 填充不应混入 (至少目录条目不应是主内容)
        assert mda.count("......") == 0, "疑似抽到了目录页"

    def test_chapter_variant_with_repeated_page_headers(self):
        """回归 bug: A 股年报用 "第N章", 且每页页眉都重复章节标题.
        要求:
            - 识别 "第三章" (不只 "第三节")
            - 正文起点 = 第一页页眉后的内容 (而非最后一页页眉)
            - 正文终点 = 下一章第一次出现的位置
        """
        text = (
            "目录\n"
            "第三章 管理层讨论与分析 ............. 25\n"
            "第四章 公司治理 ..................... 78\n"
            "\n"
            # MD&A 第一页
            "平安银行股份有限公司 2022 年年度报告\n"
            "第三章 管理层讨论与分析\n"
            "一、报告期内公司主要业务\n"
            "本集团主要从事零售及对公银行业务...\n"
            # MD&A 第二页 (页眉重复)
            "平安银行股份有限公司 2022 年年度报告\n"
            "第三章 管理层讨论与分析\n"
            "二、经营情况讨论\n"
            "报告期内营业收入同比增长...\n"
            # 下一章 第一页
            "平安银行股份有限公司 2022 年年度报告\n"
            "第四章 公司治理\n"
            "公司严格按照证监会要求..."
        )
        mda = extract_mda_section(text)
        assert "本集团主要从事零售及对公银行业务" in mda, (
            "应从第一页页眉起点开始, 而不是最后一页"
        )
        assert "报告期内营业收入同比增长" in mda, "应包含第二页正文"
        assert "公司严格按照证监会要求" not in mda, "不应越过下一章"
        # 正文长度应显著大于单个页眉长度
        assert len(mda) > 100, f"MD&A 抽取疑似退化到单个页眉附近: len={len(mda)}"


class TestTokenizeChinese:
    def test_basic_tokenize(self):
        tokens = tokenize_chinese("公司本年度营业收入大幅增长")
        # "公司" 和 "本年度" 在停用词; 期待留下实义词
        assert "营业" in tokens or "收入" in tokens or "增长" in tokens
        assert "公司" not in tokens
        assert "本年度" not in tokens

    def test_filters_non_chinese(self):
        """数字和英文应被过滤 (通过 [一-鿿] 过滤边界)"""
        tokens = tokenize_chinese("2024 Q3 revenue 120 亿元 同比增长 15%")
        for t in tokens:
            assert all("一" <= c <= "鿿" for c in t), f"非中文 token 泄漏: {t}"

    def test_empty_returns_empty_list(self):
        assert tokenize_chinese("") == []
        assert tokenize_chinese("12345 !!!") == []

    def test_min_token_len_filter(self):
        tokens = tokenize_chinese("甲乙丙丁", min_token_len=2)
        for t in tokens:
            assert len(t) >= 2


# ─────────────────────────────────────────────
# similarity
# ─────────────────────────────────────────────

class TestMDADriftComputer:
    def test_identical_docs_drift_near_zero(self):
        """同样 tokens 两年 → cosine ≈ 1 → drift ≈ 0"""
        docs = {
            2021: ["营业", "收入", "增长", "稳定", "毛利率"],
            2022: ["营业", "收入", "增长", "稳定", "毛利率"],
        }
        scores = MDADriftComputer().compute(docs)
        assert 2022 in scores
        assert abs(scores[2022]) < 1e-6, f"相同 tokens 应 drift≈0, 实际={scores[2022]}"

    def test_disjoint_docs_drift_near_one(self):
        """完全无交集 tokens → cosine ≈ 0 → drift ≈ 1"""
        docs = {
            2021: ["营业", "收入", "毛利率", "行业", "稳定"],
            2022: ["海外", "并购", "算力", "云", "转型"],
        }
        scores = MDADriftComputer().compute(docs)
        assert abs(scores[2022] - 1.0) < 1e-6, f"无交集应 drift≈1, 实际={scores[2022]}"

    def test_monotonic_drift_ordering(self):
        """小改动 < 中改动 < 大改动, 按 token 重叠度单调"""
        base = ["营业", "收入", "增长", "主营", "业务", "稳定", "毛利率", "提升", "行业", "领先"]
        small_change = base[:-2] + ["竞争", "加剧"]  # 换 2 词
        medium_change = base[:5] + ["海外", "拓展", "并购", "战略", "新增"]  # 换一半
        big_change = ["海外", "拓展", "并购", "战略", "转型", "云", "计算", "算力", "生态", "创新"]

        docs = {
            2020: base,
            2021: small_change,
            2022: medium_change,
            2023: big_change,
        }
        scores = MDADriftComputer().compute(docs)
        assert scores[2021] < scores[2022] < scores[2023], (
            f"drift 应随改动程度单调增: got {scores}"
        )

    def test_insufficient_years_returns_empty(self):
        """只有 1 年 tokens → 无法算 drift (没有上一年)"""
        scores = MDADriftComputer().compute({2022: ["营业", "收入"]})
        assert scores == {}

    def test_empty_tokens_year_is_skipped(self):
        """某年 tokens 空 → 从 drift 计算里 skip"""
        docs = {
            2020: ["营业", "收入"],
            2021: [],  # 跳过
            2022: ["营业", "利润"],
        }
        scores = MDADriftComputer().compute(docs)
        # 2021 和 2022 都应该存在 (2022 vs 2020 作相邻)
        assert 2021 not in scores
        assert 2022 in scores

    def test_drift_is_in_valid_range(self):
        """drift score 数值范围应为 [0, 1] (cosine 在 TF-IDF L2 norm 后 ∈ [0,1])"""
        np.random.seed(42)
        vocab = [f"词{i}" for i in range(100)]

        def random_doc(n=50):
            return list(np.random.choice(vocab, size=n, replace=True))

        docs = {y: random_doc() for y in range(2018, 2024)}
        scores = MDADriftComputer().compute(docs)
        for y, d in scores.items():
            assert 0.0 - 1e-9 <= d <= 1.0 + 1e-9, f"year {y} drift 越界: {d}"


class TestComputePairwiseDrift:
    def test_wide_dataframe_shape(self):
        """panel long → wide: index=fiscal_year, columns=symbol"""
        panel = pd.DataFrame([
            {"symbol": "000001", "fiscal_year": 2020, "tokens": ["a", "b", "c"]},
            {"symbol": "000001", "fiscal_year": 2021, "tokens": ["a", "b", "d"]},
            {"symbol": "000001", "fiscal_year": 2022, "tokens": ["x", "y", "z"]},
            {"symbol": "000002", "fiscal_year": 2020, "tokens": ["p", "q"]},
            {"symbol": "000002", "fiscal_year": 2021, "tokens": ["p", "q"]},
        ])
        wide = compute_pairwise_drift(panel)
        assert wide.index.name == "fiscal_year"
        assert set(wide.columns) == {"000001", "000002"}
        # 2021: 000001 有 drift, 000002 有 drift (相同→0)
        # 2022: 000001 有 drift (大改动→~1), 000002 NaN (无 2022 数据)
        assert not pd.isna(wide.loc[2021, "000001"])
        assert abs(wide.loc[2021, "000002"]) < 1e-6, "相同 tokens 应 drift≈0"
        assert pd.isna(wide.loc[2022, "000002"])

    def test_missing_required_columns_raises(self):
        bad = pd.DataFrame({"foo": [1], "bar": [2]})
        with pytest.raises(ValueError, match="panel 缺列"):
            compute_pairwise_drift(bad)

    def test_empty_panel_returns_empty_df(self):
        empty = pd.DataFrame(columns=["symbol", "fiscal_year", "tokens"])
        wide = compute_pairwise_drift(empty)
        assert wide.empty


class TestDriftConfig:
    def test_as_dict_roundtrip(self):
        cfg = DriftConfig(ngram_min=1, ngram_max=3, min_df=2)
        d = cfg.as_dict()
        assert d["ngram_min"] == 1
        assert d["ngram_max"] == 3
        assert d["min_df"] == 2

    def test_config_affects_drift(self):
        """ngram_max 变化应影响 drift score (bigram 捕获更多结构)"""
        docs = {
            2020: ["营业", "收入", "增长", "主营", "业务"],
            2021: ["主营", "业务", "营业", "收入", "增长"],  # 同 tokens, 顺序不同
        }
        # unigram-only: 顺序无关, drift ≈ 0
        uni = MDADriftComputer(DriftConfig(ngram_min=1, ngram_max=1)).compute(docs)
        # unigram+bigram: 顺序变化会产生新 bigram, drift > 0
        bi = MDADriftComputer(DriftConfig(ngram_min=1, ngram_max=2)).compute(docs)
        assert uni[2021] < 1e-6
        assert bi[2021] > uni[2021], "bigram 应比 unigram 对顺序更敏感"
