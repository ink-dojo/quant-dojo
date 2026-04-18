# research/event_driven — Next trial 候选评估

> 2026-04-18 PEAD 首次 OOS FAIL (admission 0/5 过门). 按 README 判读预案:
> "admission 不过 → 试下一个事件, 不重试 PEAD". 本文档是下一个 event 方向的
> 决策 scope, 供 jialong 确认后再开跑.

## PEAD FAIL 核心结论 (不重复论证)

- gross L/S sharpe = 0.05 (≈ 零 alpha)
- Top 30% 净利润 YoY 组合 vs 等权全样本 excess = **-0.39%**
- 净利润 YoY 单因子在 A 股不创造 cross-sectional 差异化
- 说明: 用 akshare 免费的 "后验财务数据" 做 surprise, 信息已 price in

## 候选方向评估 (2026-04-18 akshare API 扫描后)

| # | 方向 | 事件数/年 | 学术证据 | akshare API | 信号可得 | 首选度 |
|:-:|:-|-:|:-:|:-:|:-:|:-:|
| 1 | **限售股解禁** | ~2200 | 中 (A股独有) | `stock_restricted_release_detail_em` | ✅ 占流通市值比例 | ⭐ 建议下一个 |
| 2 | 大股东减持公告 | ~500-1000 | 厚 (US+CN) | `stock_gdfx_holding_change_em` + 董监高 sse/szse/bse | ⚠ 需 join 三交易所 | 备选 |
| 3 | 股份回购公告 | ~200 | 中 | `stock_buyback_em`* | ⚠ 注销率低噪声大 | 备选 |
| 4 | 指数调仓 | ~600 | 中 | akshare 成分股变更 | ✅ 纳入/剔除 | 备选 |

*回购 API 名称待确认; 非首选不细查.

### 为什么推荐 解禁 作为下一个试点

1. **数据最干净**: 解禁日 T 日早在 3-36 个月前公告, 零 future-function 风险.
   信号强度 = `占解禁前流通市值比例` 直接给 (0~100%).
2. **机制最单纯**: 流通盘突然增加 → 卖盘压力. 不涉及"公司基本面好坏"
   的主观判断, 纯供给冲击. 学术上比 earnings surprise 更稳健
   (Chen 2004 index inclusion supply shock 同机制).
3. **A 股独有**: 美股 IPO lock-up 180 天通常已 price in; A 股限售股周期更长
   (1~3 年), 市场定价可能有偏. 顶级私募有 well-known "解禁日前做空"策略.
4. **样本量合适**: 2200 事件/年 × 8 年 = 17600 事件, 远大于 PEAD 年化 17k.

### 预注册 spec (草案, 待 jialong 确认)

```
事件: stock_restricted_release_detail_em 解禁时间 = T
信号: 占解禁前流通市值比例 (越大 = 卖压越强)
持仓窗口: T-5 ~ T-1 (抢跑卖压) — 或 T+1 ~ T+5 (跟随卖压)
  两者择一预注册, 不两头跑.
  草案: T-5 ~ T-1 (抢跑更符合 "信息在 T 日前已扩散" 的市场微观结构假设)
分层: cross-sectional top 30% (短卖) / bottom 30% (多头对照)
成本: 单边 0.15%
Admission gates: 同 PEAD (ann>15%, sharpe>0.8, mdd>-30%, PSR>0.95, CI_low>0.5)
DSR n_trials 继续累加: PEAD 后 = 12, 解禁 = 13
```

### 红线 (重复 PEAD 的, 不软化)
- 不调持仓窗口
- 不调分层比例
- 不看中间结果就微调
- 失败就写结论换下一个 (减持 / 回购 / 指数调仓)

### 如果 jialong 确认走 解禁 → 下一步 (autonomous loop 可执行)

1. 在 `utils/event_loader.py` 加 `get_lockup_release()` 函数 (akshare 已实测可调)
2. backfill 2018-2025 解禁详情 → `data/raw/events/lockup_release_{year}.parquet`
   预计 akshare 限速下 20-30 分钟
3. `research/event_driven/lockup_strategy.py` (镜像 pead_strategy.py)
4. 单次 OOS → journal 结论

如果 jialong 想换方向 (直接跳到 减持 / 中频量价), 此文档仍是决策备忘.

## 不建议的方向 (避免 scope creep)

- **分钟级数据**: 需付费; Phase 3+ 再考虑
- **LLM 读公告判断 sentiment**: Phase 7 主题, 别和因子研究混
- **把失败的 PEAD re-tune**: 违反预注册红线
- **多事件组合**: 先有一个过门的单事件再说

## 对 A 股日频 alpha 可行性的更新判断

- v16 (cross-sectional factor premium): FAIL
- PEAD (earnings 事件): FAIL
- 还剩 3 个 event 方向 (解禁 / 减持 / 指数) + 中频量价

若 event-driven 三个都 fail → 说明 "akshare 免费 + 单人研究员 + 日频"
路径对 A 股 alpha 几乎不可得. 那时的选择:
- (a) 升级数据: tushare 2000 积分 / wind 试用 → 分钟级
- (b) 升级标的: 切美股 (jialong 目前人在美, 数据便宜)
- (c) 升级频率: 中频量价 (5~30 min), 需 order book 数据
- **(不选)**: crypto (jialong 已明确禁止, feedback_no_crypto_quant.md)
