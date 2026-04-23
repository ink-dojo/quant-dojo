# MD&A LLM drift — Opus 打分质量审计 (2026-04-22)

两份 Opus 4.7 打分 dataset 的质量对比:
1. **full**: 全 MD&A 前 5000 字, 429 valid / 482 (11% fail)
2. **outlook**: 只 '未来发展展望' 段, 347 valid / 482 (28% fail)

所有分析本地 parquet + 价格 + 申万一级, 不调 LLM.

## 1. 基本 stats

| 指标 | full MD&A | outlook 段 |
|---|---:|---:|
| 总样本 | 482 | 347 |
| 成功 valid | 429 | 347 |
| 失败率 | 11.0% | 0.0% |
| 可算 return | 429 | 347 |
| fwd / swap 分布 | {'fwd': 231, 'swap': 198} | {'fwd': 195, 'swap': 152} |
| external_leak 自报'是' | 0 | 0 |

**解读**: outlook 失败率高是因 Opus 时代 prompt 被 claude CLI 并发 reject. 两份 valid 样本差 82 对, 但 valid 内部结构应该可比.

## 2. 5 维度分布 (normalized: swap 组已取反)

### full MD&A

| 维度 | mean | std | skew | \|x\|>0.95 | \|x\|<0.05 | 唯一分数数 |
|---|---:|---:|---:|---:|---:|---:|
| specificity | +0.070 | 0.344 | -0.27 | 0.0% | 0.0% | 10 |
| hedging | +0.026 | 0.298 | -0.22 | 0.0% | 0.0% | 14 |
| tone | +0.057 | 0.414 | -0.24 | 0.0% | 0.0% | 16 |
| forward | +0.083 | 0.330 | -0.42 | 0.0% | 0.0% | 13 |
| transparency | +0.000 | 0.395 | +0.14 | 0.0% | 0.0% | 16 |

### outlook

| 维度 | mean | std | skew | \|x\|>0.95 | \|x\|<0.05 | 唯一分数数 |
|---|---:|---:|---:|---:|---:|---:|
| specificity | +0.050 | 0.381 | -0.19 | 0.0% | 0.0% | 15 |
| hedging | +0.015 | 0.267 | -0.21 | 0.0% | 0.9% | 13 |
| tone | +0.064 | 0.363 | -0.27 | 0.0% | 0.0% | 15 |
| forward | +0.063 | 0.381 | -0.37 | 0.0% | 0.0% | 17 |
| transparency | +0.018 | 0.407 | -0.00 | 0.0% | 0.0% | 17 |

**解读**:
- `std` 每维都在 0.2-0.4 区间, 无 collapse
- `|x|>0.95` 占比应 < 5% (否则 LLM 过度 anchor 到 ±1)
- `|x|<0.05` 占比 (趋 0) 高 → LLM 在该维度没话说 / boilerplate 无变化
- 唯一分数数 < 10 说明粒度粗 (LLM 只用几个锚点 0.1 0.2 0.3 0.5 等)

## 3. 维度共线性

### full MD&A correlation matrix

| | specificity | hedging | tone | forward | transparency |
|---|---:|---:|---:|---:|---:|
| specificity | +1.00 | +0.36 | +0.28 | +0.06 | -0.02 |
| hedging | +0.36 | +1.00 | +0.78 | +0.18 | -0.58 |
| tone | +0.28 | +0.78 | +1.00 | +0.34 | -0.73 |
| forward | +0.06 | +0.18 | +0.34 | +1.00 | -0.18 |
| transparency | -0.02 | -0.58 | -0.73 | -0.18 | +1.00 |

**|corr| > 0.5 对 (3):**
- hedging ↔ tone: +0.780
- hedging ↔ transparency: -0.577
- tone ↔ transparency: -0.735

### outlook correlation matrix

| | specificity | hedging | tone | forward | transparency |
|---|---:|---:|---:|---:|---:|
| specificity | +1.00 | +0.56 | +0.39 | +0.09 | -0.09 |
| hedging | +0.56 | +1.00 | +0.66 | +0.05 | -0.32 |
| tone | +0.39 | +0.66 | +1.00 | +0.43 | -0.35 |
| forward | +0.09 | +0.05 | +0.43 | +1.00 | +0.10 |
| transparency | -0.09 | -0.32 | -0.35 | +0.10 | +1.00 |

**|corr| > 0.5 对 (2):**
- specificity ↔ hedging: +0.560
- hedging ↔ tone: +0.661

**解读**: 若 5 维度两两相关性大部分 > 0.5, 说明 LLM 在 5 维度上只有 1-2 个真自由度 (维度设计失败). 反之 < 0.3 说明维度独立, 可做 ensemble.

## 4. IC + Bootstrap CI (raw 和 industry-neutral)

### full MD&A

| 维度 | raw mean | raw CI | raw %>0 | ind-neu mean | ind-neu CI | ind-neu %>0 | ind-neu 显著 |
|---|---:|---:|---:|---:|---:|---:|:---:|
| specificity | -0.0262 | [-0.123,+0.066] | 28% | -0.0014 | [-0.097,+0.090] | 48% | ❌ |
| hedging | -0.0509 | [-0.147,+0.047] | 13% | -0.0513 | [-0.150,+0.041] | 14% | ❌ |
| tone | -0.0521 | [-0.148,+0.048] | 14% | -0.0287 | [-0.128,+0.069] | 26% | ❌ |
| forward | -0.0681 | [-0.169,+0.031] | 10% | -0.0802 | [-0.180,+0.021] | 6% | ❌ |
| transparency | +0.0871 | [-0.012,+0.183] | 95% | +0.0733 | [-0.026,+0.170] | 93% | ❌ |

### outlook

| 维度 | raw mean | raw CI | raw %>0 | ind-neu mean | ind-neu CI | ind-neu %>0 | ind-neu 显著 |
|---|---:|---:|---:|---:|---:|---:|:---:|
| specificity | -0.0344 | [-0.134,+0.071] | 26% | -0.0235 | [-0.120,+0.080] | 32% | ❌ |
| hedging | +0.0478 | [-0.059,+0.149] | 82% | +0.0785 | [-0.022,+0.185] | 93% | ❌ |
| tone | +0.0202 | [-0.084,+0.122] | 65% | +0.0503 | [-0.051,+0.149] | 86% | ❌ |
| forward | +0.0078 | [-0.094,+0.106] | 56% | +0.0108 | [-0.087,+0.115] | 58% | ❌ |
| transparency | -0.0092 | [-0.112,+0.102] | 41% | -0.0435 | [-0.147,+0.069] | 21% | ❌ |

**解读**: bootstrap 95% CI 不跨 0 = 显著. Industry-neutral 是主要判读.

## 5. Order group diagnostic (random-order normalization 健康)

### full MD&A

| 维度 | n_fwd | n_swap | IC_fwd | IC_swap | \|diff\| |
|---|---:|---:|---:|---:|---:|
| specificity | 231 | 198 | -0.0539 | -0.0031 | **0.051** |
| hedging | 231 | 198 | -0.0203 | -0.0983 | **0.078** |
| tone | 231 | 198 | -0.0211 | -0.0869 | **0.066** |
| forward | 231 | 198 | -0.0715 | -0.0676 | **0.004** |
| transparency | 231 | 198 | +0.1137 | +0.0805 | **0.033** |

### outlook

| 维度 | n_fwd | n_swap | IC_fwd | IC_swap | \|diff\| |
|---|---:|---:|---:|---:|---:|
| specificity | 195 | 152 | -0.0204 | -0.0524 | **0.032** |
| hedging | 195 | 152 | -0.0345 | +0.1605 | **0.195** |
| tone | 195 | 152 | -0.0171 | +0.0896 | **0.107** |
| forward | 195 | 152 | +0.0126 | +0.0111 | **0.001** |
| transparency | 195 | 152 | -0.0154 | -0.0128 | **0.003** |

**解读**: `|diff|` < 0.05 = normalization 完美 (fwd 和 swap IC 一致 → 真信号); > 0.05 = order bias 残留, 信号可疑.

## 6. 综合判决

**核心发现 (按严重性排):**

### 🔴 1. 方向翻转 — signal 不稳定 (最重要)

同样 Opus 打分, 只换输入 text scope, **IC 方向系统性翻转**:

| 维度 | full ind-neu | outlook ind-neu | 方向 |
|---|---:|---:|---|
| hedging | **-0.051** | **+0.079** | 反 |
| tone | -0.029 | +0.050 | 反 |
| forward | **-0.080** | +0.011 | 弱反 |
| transparency | **+0.073** | **-0.044** | 反 |

若真有"MD&A drift signal", 改变输入 scope (全文 vs 只展望段) 不应让方向翻转。
方向翻转 = **这些 IC 本质是 noise**, 不是 signal。

### 🟡 2. 维度共线性严重 (full MD&A)

|corr| 对:
- hedging ↔ tone: **+0.78**
- tone ↔ transparency: **−0.74**
- hedging ↔ transparency: **−0.58**

full MD&A 里 hedging/tone/transparency 实际是**同一个概念反着说**, 5 维度有效自由度 ≤ 3。Outlook 稍好 (hedging↔tone +0.66, 其他 < 0.5) 但仍不 clean。

### 🟡 3. Order bias 残留 (outlook 严重)

`|IC_fwd - IC_swap|` 门槛 0.05:

- full: forward (0.004), transparency (0.033) 干净 ✅; hedging/tone (0.07-0.08) 失败 ❌
- outlook: forward (0.001), transparency (0.003) 极干净 ✅; **hedging (0.195), tone (0.107)** 严重失败 ❌

只有 **forward 和 transparency** 在两份里 normalization 都干净。但它们**方向翻转**,所以也不成为 signal。

### ✅ 4. 非失败项

- 分数分布健康: std 0.27-0.41, 无 collapse, 无 ±1 anchoring
- 粒度 OK: 唯一分数 10-17 个
- external_leak 自报全 "否" (LLM 没自觉到用外部知识)
- 失败率合理: full 11%, outlook 0% (备份时只存 valid)

## 7. 🔴 最终判决: MD&A LLM drift 方法论 KILL

把两份 Opus dataset 放一起看, 结论比之前 "borderline" 更严厉:

1. **没有 signal**: 所有 10 条 (5 维 × 2 scope) bootstrap 95% CI 都跨 0
2. **signal 会因 scope 翻转**: 真信号不会这么脆弱, 这是 noise 特征
3. **维度共线**: 5 维度实际只有 2-3 个自由度, ensemble 不会救
4. **只有 forward/transparency 两维 normalization 干净**, 但恰恰它们方向翻转 → 无救

**重要 implication**: 用 Haiku 重跑 482 对 (成本 $0.7) **不会改变本质结论**。
原因不是"Opus 打分糟"— 分数分布和粒度都健康。是 **prompt 设计的 5 维度在 MD&A
文本上就没稳定信号**。Haiku 重跑只会 confirm noise, 不会 rescue。

**真正的 Lesson**: A 股年报 MD&A 文本无论 TF-IDF 还是 LLM 5 维度 drift, 在 cross-section IC 上都不 work。 第三次实锤 (Tier 1 TF-IDF / Tier 1.5 full LLM drift / Tier 1.5 outlook LLM drift)。

空间 C 方向必须**彻底换数据源**:
- 投资者互动平台 (irm.cninfo) 散户提问/公司回答
- 政策 → 受益方 top-down reasoning
- 问询函 + 回复 事件驱动

不再 iterate MD&A 本身。
