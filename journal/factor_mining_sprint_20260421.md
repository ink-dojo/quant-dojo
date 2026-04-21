# 因子挖掘 2h Sprint — 2026-04-21

> 作者：jialong + Claude  |  时长：~2h  |  分支：`research/issue-factor-mining-20260421`

## 目标

围绕 tushare 全量数据做深度因子挖掘 + 策略集成。要求每个因子严格走 IC/ICIR/HAC t 流水线，
发现可用因子后深度集成到现有 v9 策略，完成 OOS 验证。

## 本 Sprint 跑完的因子（6 个）

| # | 因子 | 数据源 | IC | ICIR | HAC t | 判定 |
|---|---|---|---:|---:|---:|---|
| F1 | pledge_ratio | pledge_stat (周) | 0.0045 | 0.07 | 0.98 | ❌ 不是 alpha, 但可作 regime filter |
| F2 | limit_up_sleeve (封板强度) | limit_list | 0.19 / -0.037 | 1.10 / -0.19 | — | ❌ 可交易过滤后反转为负, 幸存者偏差 |
| F3 | attention_60d (特定对象调研) | stk_surv | -0.0401 | **-0.47** | **-4.08** | ✅ 反向 alpha (取负) |
| F5 | **composite_crowding (4 维)** | 合成 | **0.0895** | **0.73** | **6.33** | ✅ **合成合格, 多空年化 15.8% 夏普 1.20** |
| F6 | inst_ratio / inst_delta | top10_floatholders | 0.0013 | 0.04 | 0.77 | ❌ 季度数据吃掉 signal |
| — | (turnover_20d 作 F5 子维度) | daily_basic | — | 0.50 | 4.36 | ✅ F5 主导驱动 |

## S1 深度集成：v17 = v9 五因子 + (-composite_crowding)

### 方法
- 原 v9 五因子：team_coin / low_vol_20d / cgo_simple / enhanced_mom_60 / bp
- 新增 neg_crowding (= -composite_crowding), 全部行业中性化
- 用 ICIR 自动加权合成 + 月频换仓 + 30 股等权 + 双边 0.3% 成本

### IS (2022-01 ~ 2025-12) 同窗口
| 指标 | v9_5f | v17_6f | Δ |
|---|---:|---:|---:|
| 年化 | +5.01% | +5.98% | +0.97% |
| 夏普 | 0.241 | 0.279 | +0.038 |
| MDD | -36.56% | -39.55% | -3.00% |
| 超额 | +6.47% | +7.38% | +0.91% |

边际提升, MDD 恶化值得关注。

### **严格 OOS：2022-01~2024-12 学权重 → 2025 测试**
| 策略 | 阶段 | 年化 | 夏普 | MDD | 超额 |
|---|---|---:|---:|---:|---:|
| v9_5f | IS | -3.09% | -0.080 | -36.75% | +4.38% |
| v9_5f | OOS | +33.06% | 1.394 | -17.53% | +12.42% |
| v17_6f | IS | -2.39% | -0.051 | -39.20% | +5.07% |
| v17_6f | **OOS** | **+39.33%** | **1.580** | **-18.12%** | **+17.74%** |

**OOS 差异**：年化 +6.27%, 夏普 +0.186, MDD 仅恶化 0.59pp, 超额 +5.32%

### 结论
**✅ v17 严格 OOS 胜出，非过拟合**。-composite_crowding 带来真实增量 alpha。
训练期 neg_crowding ICIR 1.09 (六因子最高), 获 20.7% 权重, 在 2025 OOS 贡献 +5.32% 超额。

推荐：正式采纳 v17 取代 v9 基线，把 crowding 纳入标准因子池。

## 方法论收获

1. **F2 封板强度的幸存者偏差陷阱**：naive IC 0.19 看起来是超强因子，加入次日涨停可交易性过滤后
   IC 反转为 -0.037，Q5 下一日均值从 +4.51% 变 -1.84%。51.5% 的 Q5 样本因次日一字涨停无法买入。
   **教训**：任何涉及涨跌停的信号都必须做可交易性 audit。

2. **F3 反向发现**：预期"调研多 → 未来好"，实际反向，ICIR -0.47 说明 A 股在 2022-2025 regime 下
   机构抱团 → 估值过高 → 均值回归逻辑 dominate。与中信金工 2023-2024 拥挤度研究一致。

3. **F5 合成的价值**：单维度 ICIR 0.14~0.50 不高, 合成后 ICIR 0.73, 多空夏普 1.20。
   对角正交性是 free lunch, 但需要严格做截面 z-score + clip。

4. **OOS 规则**：只有严格的 train/test 时间切分才能区分真 alpha 与过拟合。
   v17 在 IS 同窗口只有 +0.04 Sharpe 提升，但 OOS 2025 有 +0.19 Sharpe，说明确实有用。

## 产出文件

- `research/factors/pledge_filter/`
- `research/factors/limit_up_sleeve/`
- `research/factors/survey_attention/`
- `research/factors/institutional_holdings/`
- `research/factors/crowding_filter/` (含 composite_crowding.parquet)
- `scripts/v17_crowding_aware_eval.py` (IS 同窗口)
- `scripts/v17_oos_eval.py` (严格 OOS)
- `journal/v17_crowding_aware_eval_20260421.md`
- `journal/v17_oos_eval_20260421.md`

## 下一步

1. **v17 并入主线**：在 TODO 里开 v17 正式化 ticket, 接入 portfolio 模拟盘
2. **继续挖掘**：
   - 大宗交易折价率 (block_trade)
   - 龙虎榜机构分化 (top_list / top_inst)
   - suspend 复牌事件 (suspend_d)
3. **因子池管理**：F5 + F3 + F2 (用作 avoid filter) 是否组合使用
4. **长周期 OOS**：等 2026 Q2 数据后在 2026 上再测 v17
