# MD&A LLM drift mini-IC — 2024 cross-section (2026-04-22)

战略锚: `research/space_c_llm_alpha/alpha_theory_space_c_research_20260421.md`
Pre-reg: `scripts/mda_llm_drift_ic.py` (Tier 1b KILL 后的 Tier 2/3 方法论试验)

## 样本 & 方法

- 样本 n = 429 对 (t=2024, t-1=2023, 两年 mda_len >= 10k)
- LLM: claude -p (Opus 4.7),  prompt: 5 维度 drift + 脱敏 + 禁止训练知识
- Random-order normalization: 每对随机 fwd/swap, swap 组分数取反
- forward return: 20 交易日累乘扣 30 bp
- publish_date → as-of 交易日映射: as_of = publish_date 后第 1 个交易日

## 每维度 IC (monthly Spearman, 2024 年发布)

| 维度 | n_months | IC mean | IC std | ICIR | IC>0 % |
|---|---:|---:|---:|---:|---:|
| specificity | 2 | -0.0281 | 0.0149 | -1.889 | 0.0% |
| hedging | 2 | -0.1285 | 0.1741 | -0.738 | 0.0% |
| tone | 2 | -0.1146 | 0.1326 | -0.864 | 0.0% |
| forward | 2 | -0.0482 | 0.0540 | -0.892 | 0.0% |
| transparency | 2 | 0.1553 | 0.1056 | 1.470 | 100.0% |

## Pooled cross-section IC

| 维度 | pooled IC |
|---|---:|
| specificity | -0.0260 |
| hedging | -0.0513 |
| tone | -0.0514 |
| forward | -0.0677 |
| transparency | 0.0880 |

## Decile spread (top 10% - bot 10% by drift, forward return 差)

| 维度 | top 10% | bot 10% | spread |
|---|---:|---:|---:|
| specificity | 0.0508 | 0.0504 | **0.0004** |
| hedging | 0.0146 | 0.0291 | **-0.0145** |
| tone | 0.0308 | 0.0351 | **-0.0043** |
| forward | 0.0279 | 0.0412 | **-0.0133** |
| transparency | 0.0507 | 0.0307 | **0.0199** |

## Order group diagnostic (检测 random-order normalization 效果)

> 两组 IC 接近 → order bias 被平均掉, signal 真实; 差异大 → bias 主导

| 维度 | n_fwd | n_swap | IC_fwd | IC_swap | 差 |
|---|---:|---:|---:|---:|---:|
| specificity | 231 | 198 | -0.0539 | -0.0031 | 0.0508 |
| hedging | 231 | 198 | -0.0203 | -0.0983 | 0.0780 |
| tone | 231 | 198 | -0.0211 | -0.0869 | 0.0658 |
| forward | 231 | 198 | -0.0715 | -0.0676 | 0.0039 |
| transparency | 231 | 198 | 0.1137 | 0.0805 | 0.0332 |

## 决策 (autonomous judgment, 2026-04-22)

🔴 **Borderline KILL** — 不扩全量跨年.

**理由**:
1. **pooled IC 过 0.04 初判门槛, 但 bootstrap CI 全部跨 0** (transparency 95.3% >0 差一点点, 仍属严格意义不显著)
2. **时序覆盖极薄** — 仅 3 个月 (2025-02~04), 全部是 2024 年报发布潮, 零 regime 多样性. 严格 CI 审慎原则下不视为 signal
3. **53/482 failures** (11%) 仍存在, 可能是 MD&A 特别长/特别复杂样本被 claude CLI 拒绝返回, 存 selection bias 风险 — 这些样本可能恰好是最有信号的
4. **Lazy Prices (美股) 原 paper 需 40+ 年才显著**, 我们 3 个月样本根本无法判真假. 扩 2600 对跨年要 3h claude 开销, 在 borderline 证据下 ROI 低

**Transparency 线索保留** (供未来用):
- 方向 (+0.087) 有解释力: "MD&A 变坦率谈风险" → bullish. 符合 "诚实管理层" 假设
- Order group diag: IC_fwd 0.114 vs IC_swap 0.081, 差 0.033 (normalization 比 hedging/tone 干净, 信号真实性更高)
- Forward drift (mean -0.068, 方向稳但 CI 跨 0) 作为 secondary 线索

**下一步 (非紧急, 留给未来 sprint)**:
- 若重做, 应换数据源 (投资者互动平台 + 政策 top-down reasoning, 见之前讨论)
- 年报 MD&A 本身在 A 股信号弱是连续第二个 pipeline 实锤 (Tier 1 TF-IDF drift + Tier 1.5 LLM drift 都 marginal)
- Scoring pipeline (`scripts/mda_llm_drift_ic.py`) 保留可复用

## 成本结算

- claude -p 调用: 482 对 × 2 轮 = 964 次. 按 Opus 4.7 定价估 ~$15 session budget
- 工程时间: pilot + prompt 调优 + mini-IC + bootstrap 共 ~2.5h
- ROI: 负, 但换来了 "A 股 MD&A 无论怎么处理都信号弱" 的 Lesson — Tier 3 方向要彻底换数据源



## Bootstrap CI (1000 resamples, seed=42)

| 维度 | mean | CI_low (2.5%) | CI_high (97.5%) | %>0 | 显著 |
|---|---:|---:|---:|---:|:---:|
| specificity | -0.0262 | -0.1228 | +0.0657 | 28.3% | ❌ |
| hedging | -0.0509 | -0.1473 | +0.0472 | 13.4% | ❌ |
| tone | -0.0521 | -0.1477 | +0.0478 | 13.5% | ❌ |
| forward | -0.0681 | -0.1694 | +0.0306 | 9.6% | ❌ |
| transparency | +0.0871 | -0.0120 | +0.1834 | 95.3% | ❌ |

### Bootstrap 判读
- 所有维度 CI 跨 0, 无显著信号
