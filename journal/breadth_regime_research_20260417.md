# Market breadth regime 指标研究 — 20260417

> 目的: regime 指标质量分析 (非策略过门测试)
> breadth 规则 (预注册, 不调参): (rising-falling)/(rising+falling), 20 日平滑, <0 → bear, shift(1)
> HS300 基线: MA120, shift(1)
> eval 段: 2022-01-04 ~ 2025-12-31, n=969

## 1. 覆盖率对比

- bear_breadth 覆盖: **59.1%**
- bear_hs300   覆盖: **53.9%**

## 2. 日历一致性 (2×2)

| | bear_hs300=T | bear_hs300=F |
|:--|--:|--:|
| bear_breadth=T | 395 | 178 |
| bear_breadth=F | 127 | 269 |

- 一致率 (两者相同的天数比例): **68.5%**
- Cohen's κ: **0.361** (0 = 随机一致, 1 = 完全一致)

## 3. 2022 首次进入 bear

- bear_breadth 首次 True: 2022-01-17
- bear_hs300   首次 True: 2022-01-05
- **HS300 领先 breadth 12 天** (breadth 滞后)

## 4. 切换频次 (噪声度)

- bear_breadth 切换次数: 75
- bear_hs300   切换次数: 34
- 说明: 次数越多噪声越大, 换仓成本越高 (同切换成本 0.1%/次)

## 5. 诚实结论 (非过门判定)

- breadth 在 2022 滞后于 HS300 MA120 — 不作为升级候选
- 一致率 68.5%, κ=0.36: 相对独立, breadth 可能提供额外信号

## 6. 不抄近道的下一步

1. 本文件只定性评估 regime 指标独立性, **不跑** breadth+v16 过门测试 (那会复制 v27 的 DSR 问题)
2. 若要做 v28 候选 (breadth-gated v16 half position), 必须:
   (a) 用 2026 Q1+ 独立 live 样本, 不重用 2022-2025 backtest 样本
   (b) 严禁按本文件结果反向选择 window=20 (这本身就是一个自由度)
   (c) 若要改 window, 必须预注册多个候选, 用 DSR 修正
3. 严禁: 并排跑 breadth-window-{5,10,20,40,60} × threshold-{0, -0.1, -0.2} 做 15 组扫描 — 典型 p-hack
