# C 路: roe_stability + HS300 composite regime overlay — 失败

_2026-04-30 — Issue #60. Regime overlay 反而恶化, 不 sweep, 转 D._

---

## TL;DR

加 HS300 composite (RSRS + vol_turnover) regime mask 在 bear 日子空仓, **不仅没救 T4 FAIL, 反而让情况更糟**:

| Slice | baseline sharpe | overlay sharpe | 变化 |
|---|---|---|---|
| T1 2020-23 | +1.77 PASS | +2.10 PASS | ↑ |
| T2 2024 | +0.85 PASS | **-0.08 FAIL** | **↓ overlay 由 PASS → FAIL** |
| T3 2025H1 | +1.91 PASS | +0.01 N/A | ↓ overlay 把 95% 日子 mask |
| **T4 2025H2** | -0.26 FAIL | **-1.48 FAIL_IC_FLIP** | **↓ overlay 更糟, IC 还翻号** |
| T5 2026Q1 | +0.32 MARGINAL | N/A | mask 掉 |
| F_full_sample | +1.44 PASS | +1.34 PASS | ↓ |

baseline: PASS 4 / FAIL 1
overlay : PASS 2 / FAIL 2

**HS300 composite 在样本里 60% 日子认为是 bear** (914/1523), 把 alpha 好的日子也 mask 掉. T4 本身是 mixed regime, mask 掉的不一定是失败那段.

---

## 数据

- 复用 Issue #47 / #44 路径: roe_stability 中性化 (size + SW-L1) + cross-section rank
- HS300: data/raw/tushare/index_daily_000300.parquet 2010-2026
- regime: utils.market_regime.composite_regime (RSRS upper=0.7/lower=-0.7 + vol_turnover 中位数分界)
- bull mask: 609 / 1523 days = 40.0%

## 方法

baseline: 不加 overlay, 跑 7 切片 sharpe + verdict (Issue #47 模式)
overlay: bear 日子的 fwd_ret 全设 NaN → quintile_spread 自动跳过, 等于不持仓

并列输出, 不 sweep 任何参数 (RSRS 阈值 / vol_turnover window 都默认).

---

## 为什么 overlay 失败

3 个观察 (诚实):

1. **HS300 60% 日子是 bear** — composite 信号过严. 任何 cross-sectional alpha
   每月 9 个 rebal 里平均只 4 个能持仓, n_periods 直接腰斩. T3/T5 直接 N/A.

2. **mask 不一定 mask 掉真正失败的日子**. T4 失败是质量风格被抛弃 (高低
   切换), 跟 HS300 自身的 RSRS/vol-turnover regime 不一致. HS300 可能是 bull
   但小盘股暴涨, 大蓝筹 (高 ROE 稳定) 跑输. composite mask 没识别这个.

3. **overlay 把 T2 由 PASS 弄成 FAIL** — T2 (2024) baseline 是 +0.85 PASS,
   overlay 后 -0.08 FAIL. overlay 把 T2 的好日子 mask 掉, 留下的少数日子里
   roe_stability 跑输. Worse than nothing.

---

## 决议

**C 路单 attempt (HS300 composite overlay) 失败**.

可能的下一步 attempt:
- 改 regime: 用 size factor regime 而非市场 regime (因为 T4 失败是 size 风格问题不是市场涨跌)
- 改 horizon: 21d → 60d (季度调仓, 减少 regime 切换敏感度)
- quality overlay: 净利润同比连续 4 季正 universe filter

**但每个 attempt 都需要 simplify cycle, 红线"不调参数凑显著"也限制了 sweep**.
诚实做法: 单 attempt 失败 = 这个具体 hypothesis 失败, 不无限尝试.

C 路改进 roe_stability 的尝试 = 不成功. roe_stability 仍卡在 framework 严格
门 (T4 FAIL). 但仍是当前最干净的候选 (5/7 PASS), 适合进 Tier 0 paper smoke
**作为本身**, 不带 regime overlay.

→ 转 **D 路 (paper-trade infra real use)**: 启动 Issue #51 (roe_stability +
v16 双 ledger 30 天 paper smoke). 用真钱前的 infra 验证 + tracking error
监控比再尝试 C 路 attempts 信息量大.

---

## 红线检查

- ✅ regime mask 用纯 HS300 价量 (外生信号), 没用 fwd_ret 反推
- ✅ 不调任何参数 (RSRS upper/lower 阈值 / vol_turnover window 全默认)
- ✅ baseline + overlay 并列报告, 没只挑 overlay 好的指标说事
- ✅ 单 attempt 失败 → 杀 this approach, 不 sweep
- ✅ honest 记录 overlay 把 T2 弄差了, 不掩盖

---

## 数据/代码

- 脚本: `research/factors/tushare_factors/roe_stability_regime_overlay.py`
- 复用: utils.market_regime.composite_regime + utils.factor_analysis.* + neutralize_and_cost.*
- 结果: research/factors/tushare_factors/roe_stability_regime_overlay_results.json (.gitignored)

— 记录: jialong
