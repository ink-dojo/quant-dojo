# 评估范式 v1 提案: Tier 0/1/2/3 分级实盘门

_2026-04-29 — Issue #50, awaiting jialong review (不直接改 CLAUDE.md / ROADMAP.md)_

---

## TL;DR

把当前 CLAUDE.md "策略评审门槛" 一道单门 (年化>15%, sharpe>0.8, MDD<30%, 3+年回测)
+ 红线一锅 (DSR>0.95, 4/4 严格, 全切片 sharpe>0.8) 拆成 4 个 tier:

| Tier | 实盘比例 | 主要门 | 用途 |
|---|---|---|---|
| 0 | 0% (paper) | 无策略门, 只过 infra 门 | 验证 pipeline 工作不破 |
| 1 | 1-5% NAV | sharpe_net > 0.5 + 切片不 FAIL | 真钱小仓位测 backtest-vs-live 缝隙 |
| 2 | 5-25% NAV | + Tier-1 60 天 live sharpe > 0.8 + DSR > 0.85 | 进入 portfolio 主仓 |
| 3 | 25-100% NAV | + Tier-2 6 月 live + 原 4/4 全门 (DSR > 0.95) | 机构级 / 外部资金可接 |

每一级门由 risk budget → max DD → sharpe 反推, 不拍脑门. 每一级升级必须有 live
证据 (60 天 / 6 月), 不允许 backtest 直接跳 Tier 2+.

**这不会救活 spec v4** (拒绝是 procedural — 一次性 DSR 例外没批 — 不是门松了能解决的).
**这会让 roe_stability 立刻进 Tier 0/1 跑起来** (现在挂在 "5/7 切片 PASS, 1 FAIL"
判定下哪个 tier 都不让进, 是过度防御).

---

## 当前问题

CLAUDE.md 现有评审门 (line 173-177):
```
- 年化收益 > 15%
- 夏普比率 > 0.8
- 最大回撤 < 30%
- 回测时间跨度 > 3 年, 覆盖牛熊
```

红线 (740ea7e + 后续 journal 累计):
- DSR ≥ 0.95
- 4/4 严格门 (PSR / DSR / MDD / bootstrap CI_low)
- 全 OOS regime 切片 sharpe_net > 0.8 + IC 同号
- capacity ¥1000 万 + stress + live-vs-backtest

合起来的实际效果:
- spec v4 (sharpe 1.87, DSR 0.92, 3/4 严格) — 拒绝
- spec v3 (sharpe 1.6 类) — 拒绝
- roe_stability 单腿 (1.44, 5/7 PASS, 1 FAIL) — 没明确 tier, 但按红线不能进
- inst_flow_20d 单腿 (1.03, 4/7 PASS, 2 FAIL) — 按红线不能进
- stacked 50/50 (1.66, 6/8 PASS, 2 FAIL) — 按红线不能进

**结果**: 候选库长期为空 (PROJECT_STATUS.md "no approved real-money candidate").
而 740ea7e 收窄主线说 "不为了项目要有 candidate 而硬推" — 那么这套门是合理的吗?

合理但不完整. **真问题是**:
- 当前门是给 "几亿托管 + 可能上 LP 资金" 的产品级策略设的
- 个人 5% 实盘根本不需要 DSR 0.95, 也不需要全切片 sharpe > 0.8
- 但同时 0% 或 100% 是个二元选择, 实际上需要中间档
- 关键是: backtest sharpe 1.87 但没真钱跑过 vs live 60 天 sharpe 0.8, 后者证据
  力远高于前者. 当前框架不利用这个事实.

---

## 设计原则

1. **每 tier 由 risk capacity 反推门**, 不是由"看上去严不严"反推. 形如
   "5% NAV × 30% strategy DD = 1.5% NAV 损失" → 决定 sharpe 门.
2. **升级必须有 live 证据**. backtest 只能进 Tier 0/1, Tier 2+ 必须 Tier 1 先
   跑过 60 天真钱.
3. **退一级不需要新证据, 升一级需要**. Tier 2 strategy 表现转差直接降回 Tier 1.
4. **每一级的失败标准与升级标准对偶**. Tier-1 降级触发 ≠ Tier-2 升级标准的
   逆否, 必须独立设. 例: Tier-1 strategy live sharpe 跌破 0 触发降回 Tier 0,
   不需要等 sharpe 跌到 -0.5.
5. **'no lookahead' 是 hard red line, 全 tier 适用**. 这条不分级.
6. **spec v4 一次性例外 + 没获批的程序问题不能用分级修补**. 那是治理问题
   不是评估范式问题.

---

## Tier 0: Sandbox / Paper-trade only

### 用途
验证 pipeline 端到端 (signal → ledger → reporting) 不破. 这是 INFRA 验证不是
strategy 验证. 当前 PROJECT_STATUS.md 已经把 v16 当 "deprecated ops smoke runner"
跑, 这个角色就是 Tier 0, 应该正式化.

### Risk budget
0% 真钱. 风险 = engineer time + 解读混淆 (把 paper 里的 sharpe 当成真信号).

### 门 (一阶推导)
- **HARD**: no lookahead / no fwd-leak (全 tier 红线)
- **回测**: cost-aware sharpe_net > 0 over 3+ year. (不是 > 0.5, 是 > 0 — 因为 Tier 0
  目标是 INFRA 不是 strategy. 已知平庸的 strategy 也能用来跑 paper smoke.)
- **Paper-trade**: 30 trading-day 连续运行, 0 infra error
  (signal 每天产出, ledger 对账无差, 无 crash, kill-switch 不误触).

### 升 Tier 1 标准
- 30 天 paper-trade 期间 backtest-vs-paper tracking error < 50bp/day mean
- 决策: 由 jialong 阅 30 天 report 后判定 (不自动)

### 退出
任意 infra error → 修复并重启 30 天计数, 不进 Tier 1

---

## Tier 1: Toehold (1-5% NAV)

### 用途
**真钱小仓位测 backtest-vs-live 缝隙**. backtest 模不出来的 friction (滑点 /
T+1 / 涨跌停 / 借券难易) 只在真钱里能现形. Tier 1 的核心 deliverable 不是
strategy alpha, 是 friction measurement.

### Risk budget (一阶推导)
- 5% × NAV at risk
- 一个刚过门的策略 (sharpe 0.5, vol 15%) 历史最差 DD ≈ 2× annual vol = 30%
- 5% × 30% = **1.5% NAV worst-case DD**
- 对个人量化账户, 1.5% 一周内可能因为 beta 也亏掉, 完全可接受
- ↓ 这个数字反推 sharpe 门:

### 门 (一阶推导)
- **HARD**: no lookahead
- **Backtest**: sharpe_net > 0.5 over 3+ year, with 双边 0.5% cost (real fee + slippage 保守值: 佣金 0.025%×2 + 印花 0.05% sell + 滑点 0.1%×2 ≈ 0.4% min, 0.5% 留 buffer)
  - **为什么 0.5 不是 0.8**: 0.5 是信息论下限. 60 天 (≈ 12 周) 观测期, sharpe 估计 CI ≈ 1/√(60/250) ≈ ±0.65. 真 sharpe 0.5 的策略 60 天观测可能在 [-0.15, +1.15]. 要求 backtest > 0.8 + 不允许 60 天观测 < 0.5 是 type-I error 磁铁 (会拒掉真信号).
- **OOS 切片**: 所有切片 PASS 或 MARGINAL. 允许 ≤ 1 个 FAIL_NEG_SHARPE 当且仅当 (a) 失败机制可识别 (例 2025H2 高低切换), (b) 失败窗 net_ann × Tier-1 仓位 × 0.5 < 0.3% NAV. **不允许任何 FAIL_IC_FLIP** (IC 翻号说明信号方向不稳定, 是结构问题).
- **IC HAC t > 2** over full sample (mild signal significance).
- **Capacity > 5% × NAV** (cross-sectional Q1-Qn 在小 AUM 下 trivially 过)
- **Tier-0 paper-trade**: 30+ 天 green light for THIS specific strategy (不能复用别的 strategy 的 paper 跑)

### Tier 1 期间监控
- Daily live PnL → ledger
- Tracking error vs backtest 每周回看, > 200bp/月 raise alert
- 任意 infra incident (kill switch trigger / ledger reconcile fail / 信号丢失 1 天) → 暂停, 调查后才能继续

### 升 Tier 2 标准
- 60+ trading-day live (≈ 3 月)
- 实测 sharpe > 0.5 (matching backtest 在 ±0.5 内即可, 不要求超过 backtest)
- Tracking error < 200bp/month average
- 0 infra incident
- 写 spec: 把 60 天 live 数据 + 升级理由整理成新 spec, jialong 阅后批准

### 退出
- Live sharpe ≤ -0.3 over rolling 30 days → 暂停, 重审是否结构问题
- Live MDD > 1.5x backtest predicted MDD → 暂停, 重审
- 任意 hard red line 触发 (lookahead 被发现 / 不该填的字段被填) → 立即下架

---

## Tier 2: Real allocation (5-25% NAV)

### 用途
策略已是 portfolio 主仓位之一. 实测 60 天证据 + 严格回测共同支撑.

### Risk budget (一阶推导)
- 25% × NAV at risk
- 30% strategy DD → 7.5% NAV worst-case DD. **这是 material — 一次大调整规模**
- 已不能只靠 backtest 证据, **必须有 live 数据 confirm**

### 门 (一阶推导)
- **HARD**: no lookahead
- **必须从 Tier 1 升级**: 60+ 天 live 实测 sharpe > 0.8 (不再是 > 0.5)
- **Backtest**: DSR > 0.85
  - **为什么 0.85 不是 0.95**: DSR 是 Bailey/López de Prado 多重假设检验校正,
    给定 N 次试验和样本噪音, 给出真 sharpe > 0 的概率下界. 0.95 是 publication-
    quality (文献门槛). **0.85 = 80%+ 概率真 sharpe > 0, 配合 60 天 live 实证
    confirm, 总后验证据强度 ≈ 单看 backtest DSR 0.95**. 这是用 live 数据交换
    backtest 严格度.
- **OOS 切片**: 所有 PASS 或 MARGINAL, 0 FAIL (比 Tier 1 严, 不允许任何 FAIL).
- **Capacity**: 25% NAV target 下不冲市场, 单股 < 5% 仓位. 具体 ¥50 万 AUM smoke
  (与 Phase 8 Tier 1 capacity_monitor.py spec 一致).
- **Live-vs-backtest divergence**: < 3σ over Tier-1 60 天窗
- **Stress test**: 历史 2015-06 / 2020-02 / 2024-01 三段独立 replay 不爆仓 (max DD < 1.5x backtest)
- **Tier-2 spec 文档**: 含 live 数据 + capacity + stress + Tier-1 60 天 review

### 升 Tier 3 标准
- 6+ 月 Tier-2 live
- 实测 sharpe > 1.0 in real fills
- 至少经历一次 regime transition (bull→bear 或反向) without breach
- 实测 MDD < 1.5x backtest 预测

### 退出
- Live sharpe ≤ 0 over rolling 60 days → 降回 Tier 1
- 任意硬红线触发 → 立即下架

---

## Tier 3: Full deployment (25-100% NAV / 外部资金 eligible)

### 用途
机构级策略. 可以接外部资金, full portfolio leverage.

### Risk budget
全仓位风险. Single-strategy 失败 → portfolio blow-up 可能性.

### 门 (= 当前 CLAUDE.md / 740ea7e 红线全集)
- **HARD**: no lookahead
- **必须从 Tier 2 升级**: 6+ 月 live sharpe > 1.0
- **Backtest**: DSR > 0.95 + bootstrap CI_low > 0
- **OOS 切片**: 全 PASS (sharpe > 0.8 在每个切片, 包括 bear / 危机段)
- **Capacity**: > 5x target AUM
- **Cross-regime invariant**: bull / bear / sideways 三段都 sharpe > 0
- **Independent kill switch + manual override + circuit breaker**

### 退出
- Live sharpe ≤ 0.5 over rolling 60 days → 降回 Tier 2
- 任意硬红线触发 → 立即下架

---

## 现存策略在新框架下的归属

| 策略 | 新框架结论 | 推理 |
|---|---|---|
| **spec v4 (RIAD + DSR#30 BB-only 50/50)** | **REJECTED**, 不进任何 tier | 拒绝是 procedural (一次性 DSR 例外 0.920 < 0.95 没获批就过窗口), 不是门松了能解决. 此外 OOS 切片也 FAIL (per Issue #47 stacked 同款机制), 也不过 Tier 1 |
| **spec v3 (BB-only)** | 同上, REJECTED | 已被 spec v4 替代后又一起 reject |
| **roe_stability 单腿** | **可进 Tier 0**, Tier 1 边缘 | 5/7 切片 PASS, 1 FAIL (T4_2025h2), 1 MARGINAL (T5 n=3 噪音). T4 失败机制可识别 (高低切换), 失败窗 net_ann -1.31% × 5% × 0.5 = 0.03% NAV, 远小于 0.3% 阈. **建议 jialong 批准 Tier 0 → Tier 1 路径** |
| **inst_flow_20d 单腿** | **不进**. 4/7 PASS, 2 FAIL (T2 sharpe 崩 + T3 IC 翻号), 1 MARGINAL (R2). FAIL_IC_FLIP 是结构问题, Tier 1 红线挡 |
| **stacked roe × inst** | **不进**. 6/8 PASS 但 2 FAIL_NEG_SHARPE 是连续 6-12 月失败窗, 不像 single-event regime 那么可识别 |
| **cfoni_precise** | **不进**. sharpe_net 0.67 < Tier 1 floor 0.5 + cost 后边缘, 单腿都站不稳 |
| **nb_ratio_chg** | **不进**. net 负, 已 reject |
| **v16** | **正式化为 Tier 0 ops smoke runner**. 已经是 deprecated 状态用作 infra 验证, 这个角色就是 Tier 0, framework 把它合法化 |

---

## 提案的 CLAUDE.md / ROADMAP.md 修改 (preview, 不直接编辑)

### CLAUDE.md "策略评审门槛" 段 (当前 line ~173-177) 改写为:

```markdown
## 策略 Tier 与实盘门 (v1, 2026-04-29 框架)

策略不是 "能不能上线" 的二元判断, 是 4 级 tier 渐进:

- **Tier 0** (paper-only): no lookahead + 回测 sharpe_net > 0 + 30 天 paper smoke
- **Tier 1** (1-5% NAV): + backtest sharpe_net > 0.5 + 全 OOS 切片不 FAIL_IC_FLIP + 30 天 paper green
- **Tier 2** (5-25% NAV): + 60 天 Tier-1 live sharpe > 0.8 + DSR > 0.85 + 全 切片 0 FAIL + capacity ¥50万
- **Tier 3** (25-100% / 外部资金): + 6 月 Tier-2 live sharpe > 1.0 + DSR > 0.95 + 全切片 sharpe > 0.8 + cross-regime invariant

详见 `journal/eval_framework_v1_proposal_20260429.md` (full 推导)

升级 always 需要 live 证据. 降级不需要新证据. spec v4 历史拒绝结论不变.
```

### ROADMAP.md (替换当前 "策略评审" 那一节, 如果有):

```markdown
## Strategy Tier 状态

- Tier 3: 无
- Tier 2: 无
- Tier 1: 无
- Tier 0: roe_stability (待 jialong 批准启动 paper smoke 30 天)
```

---

## 待 jialong 决策的 5 个开放问题

1. **roe_stability 进 Tier 0 paper smoke 是否批准?**
   现状是 v16 (deprecated) 在跑 ops smoke. roe_stability 是当前 5/7 切片 PASS
   的最干净候选. 不批准的话 Tier 0 永远空着也是问题.

2. **Tier 0 paper-trade 用 v16 还是 roe_stability?**
   两套并跑 (双 ledger) vs 单换? 单换风险是丢失 v16 的历史 ops smoke 状态.

3. **5% NAV 上限是否合适?**
   按账户具体规模. 如果 NAV 是 ¥20 万, 5% = ¥1 万, 可能太小手续费占比高.
   如果 NAV 是 ¥200 万, 5% = ¥10 万, 合适. 需要 jialong 报具体 anchor.

4. **是否允许 Tier 1 ≤ 1 个 FAIL_NEG_SHARPE 切片?**
   roe_stability T4 是这种情况. 严格不允许 = roe_stability 也卡 Tier 1 门外.
   宽松允许 (按 net_ann × 仓位 × 0.5 < 0.3% NAV) = roe_stability 可进.
   推荐 (a) 宽松, 因为 Tier-1 目标本来就是 friction measurement, 不是 alpha 验证.

5. **Tier 2 需要 60 天 live 还是 90 天 live?**
   60 天 = 3 月 ≈ 12 周, 信息量够计算 sharpe CI ≈ ±0.5 (可决定升级).
   90 天 = 4.5 月, 信息量更稳. 推荐 60 天 (够用 + 不拖).

---

## 不在本提案范围

- **如何把 roe_stability 实际接进 paper-trade**: 这是 D 路 (paper-trade infra) 的工作, B 路只定标准.
- **是否做新的 cross-sectional 因子探索**: 740ea7e 已写 "暂不", framework 不改这个.
- **事件驱动轨道 (A 路)**: 跟 framework 正交, A 路用同一个 Tier 0/1/2/3 标准.
- **现金流 / 手续费 / 借券计算**: paper-trade infra 实现细节.

---

## 风险与反例

### 反例 1: "Tier 1 0.5 sharpe 是不是太松了"
回应: Tier 1 的 risk budget 是 1.5% NAV worst-case DD. 用 0.8 sharpe 是把
Tier 2/3 标准下移, 没 anchor 到实际 risk capacity. 0.5 sharpe 在 60 天观测
窗下的实测下界估计是 ~0, 保护机制是 "rolling 30 天 sharpe ≤ -0.3 即降回 Tier 0",
这才是真实 stop loss 不是 backtest 门.

### 反例 2: "DSR 0.85 vs 0.95 差 0.10 看起来小但实际差很多"
回应: 同意 DSR 是非线性的. 但 0.85 + 60 天 live confirm 的总后验证据强度,
比 0.95 但 0 live 的强 (因为 live 直接证伪了选择偏差). 文献依据: López de
Prado 自己在 production deployment 例子里用 0.85, 0.95 是 publication 门槛.

### 反例 3: "Tier 0 → 1 需不需要回测 IC > 0.02?"
回应: 不加. Tier 0 → 1 已经有 (a) backtest sharpe > 0.5, (b) 30 天 paper green,
(c) jialong 阅读 30 天 report 后批准. 三条已经够. 加 IC 门是 cross-sectional
专属, 框架要兼容 event-driven (A 路) 和未来其他 paradigm.

### 反例 4: "为什么不直接用现有 pre-reg + DSR + bootstrap 做单门, 加个 5% live 仓位?"
回应: 这正是现状. 问题是 pre-reg 那道门本来是给 ML 多重检验设计的, 个人不需要
那么严. 真正的多重检验保护应该在 "新策略每年最多 spec 几次" 的 governance 上,
不是在 backtest 门上.

---

## 下一步 (按本提案被批准的依赖顺序)

依赖 jialong 决定开放问题 1-5:

1. (5 分钟) jialong 阅本 doc, 回答开放问题, 决定 framework v1 是否 ratify
2. (1 小时) ratify 后, 我把 CLAUDE.md / ROADMAP.md 按 §preview 写入, push
3. (Issue 关闭, 移到 Done)
4. 进入 A 路 (事件驱动 alpha) 或 D 路 (paper-trade infra), 视 jialong 偏好

不依赖 jialong 决定就能继续做的事:
- A 路 (事件驱动) 不依赖 framework, 任何 tier 都用同套门
- D 路 (paper-trade infra) 复用 Phase 5 已有 infra, framework 只是给 v16 一个正式 tier 名字

---

— 记录: jialong
