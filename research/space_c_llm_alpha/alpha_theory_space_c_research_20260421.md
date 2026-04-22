# 空间 C (LLM-native alpha) 研究 memo

> 写作日期: 2026-04-21
> 作者: jialong
> 上游文档: `ALPHA_THEORY_2026.md` §2.C + §4.4
> 地位: 空间 C 的战略研究锚点。所有 Tier 1/2/3 的 pre-reg 必须回看本文件, 并在 commit 里显式引用。
> 核心结论: **方向对, 但 `ALPHA_THEORY_2026.md` §4.4 的原 POC (10-20 公司 × 3 年 MD&A) 设计错了**。真正能出 edge 的不是"LLM 读 MD&A", 而是"LLM 做跨文档 conditional reasoning"; 而且必须先用 embedding/TF-IDF baseline 把容易的部分挖掉, 才看得见 LLM 的真正增量。

---

## I. 学术/实务 state-of-the-art

### 1.1 MD&A 文本 alpha 这件事, 西方已经挖了 15 年

**最相关的一篇 = Cohen, Malloy, Nguyen (2020, *Journal of Finance*) "Lazy Prices"**

- 方法: 对同一公司相邻两年 10-K/10-Q, 算 **TF-IDF cosine similarity**
- 发现: 文本变化大的公司 (Q5 − Q1) 月度 SR spread ~0.22%, 年化 ~2.6% 风险调整后 alpha
- 信号持续 5 年
- **关键点: 没用任何 NLP/LLM, 纯词频向量。这就是 `ALPHA_THEORY_2026.md` §2.C(1) 的 "语义漂移度"**

**衍生工作**

- Loughran & McDonald (2011, JoF): 负面词典 → sentiment tone
- Li (2010): MD&A tone predicts future earnings
- Bochkay et al. (2019): linguistic complexity
- Bybee/Kelly/Manela/Xiu (2020, AER): WSJ topic modeling → business cycle
- Lopez-Lira & Tang (2023, SSRN): ChatGPT 预测股价; 样本短, 后续 replication mixed

### 1.2 A 股语境

本土学术 (张学勇/廖理/罗金岩, 孙慧倩, 姜付秀 等) 已论证 A 股 MD&A 存在信息含量, 但有两个本土特征:

1. **Boilerplate 比例极高** — A 股年报 MD&A 有强模板, 同公司跨年"物理相似度"天然就很高 (vs 美股 10-K)
2. **注册制后 (2023+) 披露质量阶跃提升** — 意味着 pre-2023 的 training signal 和 post-2023 的应用环境 regime 不同

私募铺开情况: 幻方/明汯/九坤等已有中文 BERT + 字典 NLP 产线 (低频 sentiment), 但据 2024-2025 公开资料与业内交流, 很少做到"LLM + 跨文档 reasoning"级别。这是时间窗口 (12-24 个月), 不是永恒结构。

### 1.3 对 ALPHA_THEORY 的影响

`ALPHA_THEORY_2026.md` §2.C 把 LLM 捧成"唯一不对称工具"是**半对**:

- ✅ **跨文档 conditional reasoning** (公告 × 政策 × 宏观) 这件事, embedding 和 BERT 做不了, LLM 有 structural edge
- ❌ **单文档 sentiment / 漂移度** 这件事, TF-IDF/embedding 已经 good enough, LLM 贡献的是 marginal improvement, 不是 structural edge。而 §4.4 偏偏选了这个最没 edge 的版本。

---

## II. 五个子信号 re-scoring

按 "LLM 真实不对称度 × A 股数据可得 × 私募已做程度" 重排:

| 子信号 | LLM 真正不对称? | A 股数据可得 | 私募已做? | 推荐度 |
|---|---|---|---|---|
| **(2) 公告 × 政策 × 宏观 cross-ref** | ★★★★★ 真的需要 reasoning | ⚠️ 公告 OK(cninfo 免费), 政策需爬国常会/部委, 宏观 Wind | 几乎没人做 | **🔴 最高** |
| **(1) MD&A 语义漂移** | ★★ embedding 就够 | ✅ cninfo 抓 PDF + OCR | 部分做 | 🟡 做, 但先用 embedding baseline |
| **(5) 电话会议情绪** | ★★★★ | ❌ A 股大部分公司无公开电话会, 信息密度低 | N/A | ⚪ skip |
| **(3) 研报共识语言学** | ★★★★ 真正需要语义对齐 | ❌ 研报全付费 (Wind 几十万/年) | 少量做 | ⚪ skip (成本太高) |
| **(4) 新闻事件桶"已/未定价"** | ★★★ | ✅ 财联社/东财新闻 | **✅ 私募重仓区域** | ⚪ skip (正面竞争) |

**核心发现**: 5 个候选里, **只有 (2) 公告-政策 cross-ref 同时满足 "LLM 真正不可替代 + 数据可得 + 私募没铺"**。这是唯一值得长期押注的方向。其余 4 个要么可被 embedding 替代, 要么数据不通, 要么 head-to-head 竞争。

**§4.4 POC 选错了信号**。选了 (1) MD&A 漂移, 这是最容易被 embedding baseline 打平的那个。

---

## III. LLM 相对 BERT/embedding/TF-IDF 的真实增量

### 层 1: 理解否定和 hedging (BERT 部分能做, LLM 更好)

- "公司业务未受宏观影响" ≠ "公司业务受宏观影响"
- "预计 / 可能 / 存在不确定性" hedging 密度 → forward-looking pessimism
- 增量: vs BERT 提升可能 10-30%, vs dictionary 提升 50%+
- **但**: 这仍然是单文档任务, 不是结构性 edge

### 层 2: 结构化抽取 (LLM 显著好)

- 从公告抽: 交易对手方, 金额, 业务类别, 时间点
- 从财报抽: 产品线 revenue 分解, 管理层提到的风险点 list
- 增量: 让 unstructured → structured, 下游可以做 quant

### 层 3: 跨文档 conditional reasoning (LLM 唯一不可替代)

- 例: 公司 A 公告"签下 XX 新能源客户订单 5 亿" + 国常会"扩大充电桩补贴" + 宏观"M2 同比 +9%" → **条件性 bullish score**
- 例: 公司 B MD&A "芯片国产化推进顺利" × 该行业 1-2 级供应商实际出货数据偏弱 × 美国出口管制升级 → **矛盾信号, 下调 confidence**

**为什么私募没做**:

1. 需要 3-5 个异构数据源实时拼接, 工程成本高
2. 输出 unstructured score, 难以并入传统因子 pipeline
3. 可解释性差, 不符合机构合规要求

这是 §2.C 该押的版本, 不是 §4.4 MD&A 漂移。

---

## IV. POC 三阶梯 (有 kill criteria)

### Tier 1 — "Lazy Prices in A 股" (baseline, 1-2 周, ~$0)

**目的**: 把最便宜的版本先跑通, 建立 baseline。

- 样本: 全 A 股, 2017-2025, cninfo 年报文本 (txt 即可)
- 方法: TF-IDF on MD&A → 同公司相邻两年 cosine similarity → 低相似度 long / 高相似度 short
- 指标: 年度 rebalance, Fama-MacBeth IC, decile spread
- **Kill criteria**:
  - 月度 rank IC < 0.015 → 这个 anomaly 在 A 股可能不存在, 停整个 Tier 1/2 方向
  - 月度 rank IC > 0.025 → **立刻停止**所有"更复杂"的 LLM 工作, 先把 Tier 1 做到能 paper-trade
  - 0.015-0.025 之间 → 进 Tier 2
- **为什么重要**: 95% 概率 Tier 2/3 能产出的 MD&A alpha 已经被 Tier 1 抓住; 剩下 5% 的增量才值得花钱找

### Tier 2 — LLM "hedging density" 增量 (条件上, 3-4 周, ~$300)

只在 Tier 1 结果 ambiguous 时做。

- 样本: Tier 1 同样本
- 方法: Claude Haiku 批量读每份年报 MD&A, 输出 0-1 的 "hedging density score" (few-shot + 固定 rubric, temperature=0)
- 成本: 5000 × 8 × ~30k tokens ≈ 1.2B tokens ≈ Haiku 输入 ~$1/M × 1200 = $1200; 用 prompt caching 可压到 < $300
- 评估: 对 Tier 1 做**正交化**后看增量 IC
- **Kill criteria**:
  - 正交化后 IC < 0.005 → LLM 对 MD&A 只有 marginal vs embedding, 停
  - ≥ 0.005 → 保留此 factor, 加进组合, **但不**继续堆 MD&A 方向

### Tier 3 — 跨文档 conditional reasoning (2-3 个月, 中成本)

**这是空间 C 的真正押注**。必须等 Tier 1/2 给出数据纪律后才开。

架构:

```
[每日公告 → structured event extractor (Claude Haiku)]
       ↓
[event ⟂ industry policy db (爬国常会/发改委/部委)]
       ↓
[LLM reasoner (Claude Sonnet) → conditional score]
       ↓
[score 存库, 月末做 IC / decile backtest]
```

- 累计 3-6 个月实时数据后做**第一次**前瞻 IC 检验
- 不做 back-test-on-history (政策文本 training leakage 难以避免)
- Kill criteria: 6 个月后月度 rank IC < 0.02, 停

---

## V. 工程接口 — agent 如何输出因子

现在 `agents/` (debate, factor_analyst) 都是 **decision-support**, 不是 **factor-producing**。`ALPHA_THEORY_2026.md` §2.C 指出的"从未作为 factor 输出进入回测流"核心原因是接口缺失。

最小必要接口 (下一步任务, 不在本 Issue 范围):

```python
# agents/factor_protocol.py
class LLMFactorProducer(BaseAgent):
    """输出 cross-sectional factor score 的 agent 基类"""
    def score_universe(
        self,
        symbols: list[str],
        as_of_date: str,
    ) -> pd.DataFrame:  # index=symbol, columns=['score', 'confidence']
        ...

    def snapshot_hash(self) -> str:
        """prompt + model_id + rubric version 的 hash, 用于 pre-reg 和 reproducibility"""
        ...
```

`snapshot_hash` 的存在, 是让 LLM factor 能通过 `CLAUDE.md` 的 pre-reg 纪律的唯一办法。没有它, 所有 LLM factor 都是不可 audit 的 — 等同于 §3.3 "曲线拟合" 的 LLM 版本。

---

## VI. 成本 & 时间预算

| 阶段 | 时间 | 预算 | 出什么 |
|---|---|---|---|
| Tier 1 (TF-IDF baseline) | 1-2 周 | $0 + 爬虫时间 | 中文 Lazy Prices IC 数字 |
| Tier 2 (Haiku hedging) | 3-4 周 | ~$300 | LLM 相对 embedding 的边际 IC |
| Tier 3 (cross-doc reasoning) | 2-3 个月 (forward) | ~$500/月 Sonnet | 真正的不对称 alpha 第一组 IC 数据 |

总预算 3 个月内可 < $2000 做完全部三层。

---

## VII. §1 四问回答 (以 Tier 3 为答题对象)

1. **edge 还在吗**: 存在。死亡假设: "开源 LLM 2026 下半年能力追上 Claude/GPT → 私募开始铺 → 窗口关闭"。给自己 12-18 个月窗口。
2. **谁做不了**:
   - 私募工程文化: 向量化代码库为主, 不是 agent orchestration
   - 合规: score 不可解释, 机构难过 risk committee
   - 规模: 单次 inference 延迟高, 但容量不是瓶颈, **团队优先级**不在这
3. **空间归属**: §2.C (LLM-native), 清晰
4. **数据/工具优势**:
   - 数据: 公告/政策公开 — **不是**数据优势
   - 工具: Claude Code + agents/ 骨架 + jialong 金融 + Claude 工程配对 — **这是真工具优势, 但窗口期 12-18 个月**

通过四问。但前提是做 Tier 3 版本, 不是 §4.4 的 MD&A 漂移 POC。

---

## VIII. 行动总结

1. **§4.4 按原写法不开**。10-20 公司 × 3 年 = 600 条观察, IC 标准误掩盖一切真信号。
2. **先做 Tier 1 (A 股 Lazy Prices)**: 纯 sklearn TfidfVectorizer, 2 周出结果, 和 DSR #30 paper-trade 平行不冲突。
3. **§4.4 剩余篇幅改成 Tier 3 规划**: 6 个月时间, month-3 和 month-6 checkpoint。
4. **先建 `agents/factor_protocol.py` + snapshot_hash 机制**, 再做任何 LLM factor。

---

## 附录: Kill tree

```
Tier 1 跑完 →
  ├─ IC < 0.015 → A 股 MD&A anomaly 死, 空间 C 其他子方向优先 (cross-doc reasoning)
  ├─ IC 0.015-0.025 → 进 Tier 2 (LLM hedging 增量)
  │    ├─ 正交化 IC < 0.005 → MD&A 方向封死, 只 ship Tier 1
  │    └─ 正交化 IC ≥ 0.005 → Tier 2 factor 入库, 但不再加码
  └─ IC > 0.025 → Tier 2/3 暂缓, 先把 Tier 1 做到 paper-trade
```

---

— jialong, 2026-04-21
