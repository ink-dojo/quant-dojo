# MD&A drift factor — 空间 C Tier 1

**作者**: jialong
**日期**: 2026-04-21
**状态**: 🟡 框架就绪, 待跑全 A 股 IC 评估
**Issue**: #25
**战略锚**: `research/space_c_llm_alpha/alpha_theory_space_c_research_20260421.md`

---

## 核心思路

复刻 Cohen, Malloy, Nguyen (2020, *Journal of Finance*) "Lazy Prices" 到 A 股:

> 同一公司相邻两年年报 **MD&A (管理层讨论与分析)** 段的 TF-IDF cosine similarity,
> 低相似度 (高文本漂移) 的公司未来 underperform.

**公式**: `drift_score(symbol, year) = 1 - cosine(tfidf(mda_year), tfidf(mda_year-1))`

**排序方向**: drift 高 → 做空; drift 低 → 做多. 因子 sign 待 IC 测试确认后冻结.

---

## 为什么先做这个而不是 LLM 版本

详见 `research/space_c_llm_alpha/alpha_theory_space_c_research_20260421.md` §III 层分析.

简版: MD&A 漂移本身用 TF-IDF/embedding 就能挖, LLM 只有 marginal 增量.
必须先把最便宜的 baseline 做出来, 才看得见 LLM 的真正贡献 (hedging 语言, 跨文档 reasoning).
如果 baseline 就 work, Tier 2 LLM 不必做; 如果 baseline 不 work, Tier 2 也大概率徒劳.

---

## 模块组织

```
research/factors/mda_drift/
├── data_loader.py      # cninfo 年报 PDF 列表 + 下载 + 磁盘缓存
├── text_processor.py   # PDF → txt → MD&A 段 → 中文 tokens
├── similarity.py       # TF-IDF + cosine, drift = 1 - cos
└── factor.py           # 端到端 pipeline, 宽表输出

scripts/
└── mda_drift_tier1_eval.py  # pre-reg runner (锁参数, IC 评估)

tests/research/
└── test_mda_drift.py   # 单元测试
```

### 数据缓存

| 路径 | 内容 | git? |
|---|---|---|
| `data/raw/annual_reports/{symbol}_{year}.pdf` | PDF 原文 | ❌ (in .gitignore) |
| `data/processed/mda_tokens/{symbol}_{year}.parquet` | 分词后 tokens | ❌ |
| `data/processed/mda_drift_scores.parquet` | 因子宽表 | ❌ |

---

## 锁定参数 (Tier 1 pre-reg)

`DriftConfig`:

| 字段 | 值 | 理由 |
|---|---|---|
| `ngram_range` | `(1, 2)` | Lazy Prices 原文用 unigram+bigram 捕捉短语漂移 |
| `min_df` | `1` | 单公司 per-corpus fit, 语料小不做 df 过滤 |
| `max_df` | `1.0` | 同上 |
| `sublinear_tf` | `True` | 抑制长文档 dominate, 标准 text mining 做法 |
| `norm` | `"l2"` | cosine similarity 前提 |
| `corpus scope` | **per-symbol-all-years** | 跨公司 IDF 分布不可比, 和 Lazy Prices 对齐 |
| `tokenizer` | identity (token 预先由 jieba 完成) | 显式绕开 sklearn 默认 regex token_pattern |

MD&A 段抽取:

| 字段 | 值 |
|---|---|
| header 候选 | 管理层讨论与分析 / 经营情况讨论与分析 / 董事会报告 |
| 终止锚 | 重要事项 / 公司治理 / 股份变动 / 财务报告 / 监事会报告 |
| 选择策略 | 优先级 + 最后一次命中 (规避目录页首次命中) |
| 最大长度 fallback | 80000 字符 |

停用词: 内置小 list (~40 词), 聚焦 A 股 MD&A boilerplate ("公司"/"报告期"/"人民币" 等).

---

## Kill criteria (签死, 跑完不改)

评估区间: **2018-2025 财年** (对应 2019-2026 年报发布窗口), 全 A 股非 ST 非次新.

| 月度 rank IC (发布后 20 交易日 forward return) | 决策 |
|---|---|
| `< 0.015` | **停**. A 股 MD&A 漂移 anomaly 不活, 空间 C 的 MD&A 子方向封死, 转 Tier 3 (跨文档) |
| `0.015 ~ 0.025` | 进 Tier 2 (LLM hedging 密度做增量) |
| `> 0.025` | Tier 2/3 暂缓, 先把 Tier 1 推到 paper-trade |

附加必答:

- 前 5 年 (2018-2022) vs 后 3 年 (2023-2025) IC 衰减 ≥ 50% → 注册制后可能已被挤压, 标注但不单独 kill
- top 20 drift 公司出现明显**行业集中** (比如同一年电源/地产集体换 boilerplate) → 标注 confound, 需要行业中性化版本重测

---

## 使用示例

```python
from research.factors.mda_drift import compute_mda_drift_factor

symbols = ["000001", "600036", "600519"]
factor_wide, diag = compute_mda_drift_factor(
    symbols=symbols,
    start_year=2020,
    end_year=2023,
    download=True,         # 自动下载 PDF (首跑), 之后走缓存
)
print(factor_wide)     # index=fiscal_year, columns=symbol
print(diag["status"].value_counts())
```

对接现有回测:

```python
from utils.factor_analysis import compute_ic_series, quintile_backtest
# factor_wide 是 fiscal_year × symbol; 需要在 scripts/mda_drift_tier1_eval.py
# 里映射到 daily 并做 lag(1 trading day after publish_date)
```

---

## Next steps

Tier 1a (本 Issue, done):
- ✅ data_loader / text_processor / similarity / factor 四模块
- ✅ 单元测试
- ✅ Tier 1 pre-reg runner (locked params)

Tier 1b (下一 Issue):
- 全 A 股 ~5000 × 8 年 PDF 下载 (~40000 份, 预计 1-2 天)
- MD&A 段抽取覆盖率审计 (> 90% 才算 pipeline 健康)
- IC / ICIR / decile spread 评估 → kill criteria 判读
- 结果回流到 `journal/mda_drift_tier1_result_YYYYMMDD.md`

---

## 风险 / 已知 limitation

1. **扫描版老年报 (pre-2010) 抽不到文字**. 当前 skip, 不做 OCR. Tier 1 从 2018 开始本身回避了这个.
2. **Boilerplate 污染**: A 股年报有强模板, 基础相似度天然高. 如有需要, 后续可以加
   "去 boilerplate" 版本: 对全市场该年所有 MD&A 做 IDF, 减去"全市场都在说的词".
3. **Regime shift (2023 注册制)**: 披露质量阶跃可能造成 2023+ vs pre-2023 drift 分布 shift,
   IC 评估时需要分段报告, kill criteria 已包含该检查.
4. **公告日 → 交易日 mapping**: 年报发布日到 factor 可交易日需要 lag(1). runner 里做, 这里不做.
