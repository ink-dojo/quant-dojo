# MCHG — Management Change

**状态**: 2026-04-22 首轮评估, IS/OOS regime 翻转, 单独不是 alpha, 但 OOS 轻微正方向值得记录.
**Issue**: #33

## 假设

A 股关键职位 (董事长/总经理/CFO/财务总监) 变动常伴随战略调整/业绩压力/重组, 对未来 20 日股价
有 cross-section 预测力. 先不设方向, 让 IC 判断.

## 数据

- `data/raw/tushare/stk_managers/stk_managers_<symbol6>.parquet`
- 关键词: 董事长 / 总经理 / 首席执行官 / 首席财务官 / 财务总监

## 构造

1. 扫描 4267 个 stk_managers_*.parquet, 保留 key titles
2. 按 (ts_code, ann_date) 聚合事件强度 (name@title 独立数)
3. `event_trade_date` = 公告日对齐到下一交易日 (若公告日非交易日)
4. `rolling_sum` = 过去 60 日事件强度累计
5. `factor` = log1p(rolling_sum) 若过去 60 日有事件, 否则 NaN

## 首轮结果 (2022-01 ~ 2025-12, fwd=20, size+industry neutral)

| 分段 | n | IC | ICIR | HAC t | Status |
|---|---:|---:|---:|---:|---|
| FULL | 156 | -0.006 | -0.127 | -1.04 | ❌ dead |
| IS (2022-2024) | 134 | -0.011 | -0.256 | **-2.07** | ⚠️ degraded (负方向显著) |
| **OOS 2025** | 22 | **+0.031** | +0.590 | +1.45 | ✅ healthy (正方向, 不显著) |

**关键发现: 和 SRR 一样 IS/OOS regime 翻转**.
- IS (2022-2024): 高管变动多 → 未来跑输 (HAC t -2.07 显著)
- OOS 2025: 高管变动多 → 未来跑赢 (但只有 22 采样点, 不显著)

## 与其他因子的关联

Fold 3 诊断 (Issue #36) 发现 RIAD 也在 2025 H2 失效; LULR 从反转变动量; MFD 短窗口失效.

**MCHG 和 SRR 都独立验证了 2024 → 2025 的 regime shift 存在**. 不是单个因子 decay, 是 structural.

## 结论

- 单独不适合做策略 (FULL dead + IS/OOS 方向翻转)
- 作为 regime indicator 有价值: 多因子方向翻转集体发生 = 市场结构变化信号
- 若要进一步挖: 拆 "新任" vs "离任" 事件类型 (需要 anns_d 公告分类或自行识别)
