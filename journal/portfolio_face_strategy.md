# Portfolio 门面策略选定 — 2026-04-16

> **作者**：jialong
> **关联 Issue**：[#18](https://github.com/ink-dojo/quant-dojo/issues/18)
> **前置**：[portfolio_data_audit_2026-04-16.md](./portfolio_data_audit_2026-04-16.md) · [portfolio_hero_factors.md](./portfolio_hero_factors.md)

## 问题

Portfolio 站点需要至少一个"当前策略"作为叙事中心（`/strategy`、`/validation`、`/live` 三个 section 全部围绕它）。可选：

- **v7** — 最早通过 admission 的基线（5 因子等权，`DEFAULT_STRATEGY` 在 `pipeline/active_strategy.py`）
- **v9** — ICIR 学习权重版，commit `02b9a3d` 评估报告 OOS +18%
- **v10** — v9 + 组合止损层，**正在跑**，未出结果
- **v16** — 9 因子挖掘组合，当前 `strategy_state.json` 里的 active_strategy

## 可用 run 数据（2022-01-04 → 2025-12-31，969 交易日）

| 版本 | 年化 | 夏普 | 最大回撤 | 总收益 | 备注 |
|------|------|------|---------|--------|------|
| v9   | 12.87% | 0.48 | -26.62% | 59.3% | Sharpe 最稳健，回撤最小 |
| v16  | **22.37%** | **0.73** | -43.06% | 117.4% | 年化最高，回撤承受度高 |
| v21  | 13.99% | 0.43 | -39.05% | 65.4% | 因子挖掘过程版本，非最终 |

> 上表是回测区间口径。v9 的 commit log（`02b9a3d`）报告的 **OOS Sharpe 1.60 / -17.83% 回撤 / WF 中位数 0.5256** 是 walk-forward 评估口径，来自 `journal/v9_icir_weighted_eval_20260416.md`，与此处 run_store 口径不同但互为补充。

## 决策：**双策略门面**，不是单策略

单选一个会丢故事。建议：

### **v9 → 研究方法论门面**
- 摆在 `/strategy/versions/v9` + `/validation/walk-forward`
- 讲的故事：**从手工权重到 ICIR 学习权重**
- 关键证据（commit `02b9a3d`）：
  - OOS 夏普 1.60（vs v7 的 1.35，+18%）
  - WF 中位数 0.5256（远超 0.20 门槛）
  - 权重演化展现 A 股风格切换（2013-2016 bp 主导 → 2018-2020 low_vol+momentum → 2024 bp 回归）
- 面试官关注点：**真正做了样本外验证而非 over-fit**

### **v16 → 生产门面**
- 摆在 `/live` + `/strategy/versions/v16` + 主页 Hero 数字
- 讲的故事：**因子挖掘落地生产**
- 关键证据：
  - 22.37% 年化 / 0.73 夏普 / 117.4% 总收益（4 年）
  - 9 因子组合（4 核心 + 5 新发现）
  - 当前 `live/strategy_state.json` active 就是 v16
- 面试官关注点：**因子挖掘不是 ad-hoc，有完整流水线**

### **v10 → 路线图占位**
- 摆在 `/strategy/versions/v10` + `/journey` Phase 8 预告
- 讲的故事：**下一步进化**
- 状态：跑完后补数据；页面上写"运行中 — 预计通过全部 Admission Gate"
- 诚实信号：公开展示未完成的研究，非只秀成品

## 对前端结构的影响

主页 Hero 区数字用 v16（22% 年化最有冲击力）
`/strategy/framework` 7 步构建用 v9（解释 ICIR 权重学习）
`/validation/results` 用 v9（WF 中位数 0.53 是核心亮点）
`/live` 持仓/NAV 用 v16（active 生产策略）
`/journey` Phase 6→7 讲 v9 方法论进化，Phase 8 留给 v10

## 切换规则

- v10 回测完成且通过 Admission Gate（年化>15% / 夏普>0.8 / IS 回撤<-30% / WF 中位数>0.20）→ **升级为"方法论门面"**，v9 退至 `/strategy/versions/` 版本史
- v16 出现重大退化（连续 3 周 NAV 跌破 -15%）→ 降级到 `/strategy/versions/`，启用下一版
- 切换操作只需改两处：`export_data.py` 顶部的 `FACE_RESEARCH_VERSION` / `FACE_PRODUCTION_VERSION` 常量

## 风险提示

v16 的 **-43% 回撤**对面试是双刃剑：
- 正向：诚实展示真实回测数据而非挑最好段
- 负向：保守型基金经理可能直接否掉

应对：在 `/strategy/versions/v16` 明确标注回撤发生区间（2024 年股灾？），附上归因分析。如果归因不出来，在页面加一行："此处正在做归因研究 → Issue #XX"——比硬塞解释更好。

## 验证

数据来源全部落在以下文件，`export_data.py` 可直接消费：

| 数据 | 来源 |
|------|------|
| v9 回测 run | `live/runs/multi_factor_v9_20260413_bc30d3da.json` + `*_equity.csv` |
| v9 WF 评估 | `journal/v9_icir_weighted_eval_20260416.md` |
| v16 回测 run | `live/runs/multi_factor_v16_20260414_36127e73.json` + `*_equity.csv` |
| v16 因子列表 | `live/strategy_state.json` note 字段 |
| v10 状态 | 运行中，暂无数据 |
