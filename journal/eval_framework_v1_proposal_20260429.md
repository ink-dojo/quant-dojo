# 评估范式 v1 提案: Live-Tier 0/1/2/3 分级实盘门

_2026-04-29 — Issue #50, **RATIFIED 2026-04-29 by jialong** (回答见 §"7 个开放问题"已决)_

> **Rev 2 修订** (2026-04-29 同日, simplify review 后):
> - 命名改 `Live-Tier 0/1/2/3` 与 ROADMAP.md 已有的研究 "Tier 1a/1b/2/3" 区分.
> - §preview 加 WORKFLOW.md 和 `pipeline/risk_gate.py` (原版漏了, simplify 警告 "如果 ratify 后只改 CLAUDE.md 不改 risk_gate.py, 代码会继续用老门把所有 tier 候选都挡住").
> - Tier 1 sharpe 0.5 derivation 重写 (原版 CI 公式错: `1/√(60/250)` 不是 0.65 是 2.04; 实际 60-day sharpe SE 用 Lo 2002 ≈ 2.2, CI 巨大不能 pin 任何门. 改成"约定值 + risk-budget 经济解释 + live exit rule").
> - Tier 2 DSR 0.85 derivation 重写 (原版假引 LdP "production deployment", 无依据; 改成"约定值 + 60 天 live 后验等价 framing").
> - Cost 算术修正 (0.40% → 0.30%, buffer 算到 0.5% 不变).
> - roe_stability T4 失败窗 net_ann 引用换源 (原引 -1.31% 不在 journal; 改用 stacked T4 -0.7% / 单腿待补).
> - 删除 × 0.5 horizon factor (无依据).
> - Tier 3 evidence 窗 6 月 → 12 月 (原版与 Tier 2 重合).
> - 删除 "information-theoretic" 修辞 (sampling-CI 不是 Shannon).

---

## TL;DR

把当前 CLAUDE.md "策略评审门槛" 一道单门 (年化>15%, sharpe>0.8, MDD<30%, 3+年回测)
+ 红线一锅 (DSR>0.95, 4/4 严格, 全切片 sharpe>0.8) 拆成 4 个 tier:

| Live-Tier | 实盘比例 | 主要门 | 用途 |
|---|---|---|---|
| 0 | 0% (paper) | 无策略门, 只过 infra 门 | 验证 pipeline 工作不破 |
| 1 | 1-5% NAV | sharpe_net > 0.5 + 切片不 FAIL | 真钱小仓位测 backtest-vs-live 缝隙 |
| 2 | 5-25% NAV | + Tier-1 60 天 live sharpe > 0.8 + DSR > 0.85 | 进入 portfolio 主仓 |
| 3 | 25-100% NAV | + Tier-2 12 月 live + 原 4/4 全门 (DSR > 0.95) | 机构级 / 外部资金可接 |

每一级门由 risk budget → max DD → sharpe 反推, 不拍脑门. 每一级升级必须有 live
证据 (60 天 Tier-1 / 12 月 Tier-2), 不允许 backtest 直接跳 Tier 2+.

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
7. **当前阶段定位是 Tier 0 验证, 不是 Tier 1+ 部署**. jialong 2026-04-29 明确
   "还没准备好真钱". 因此:
   - Tier 1 的具体启动 **必须再开一个独立决策点** (新 issue, jialong 显式 ratify),
     不靠这个 framework 自动触发.
   - Tier 0 跑满 30 天后产出 review report (不是 framework 自动决定升 Tier 1,
     是给 jialong 一个 "准备好了吗" 的输入).
   - 短期目标 = **Tier 0 infra 跑通 + 至少一个候选有 30 天 paper 数据**, 不是
     "找到一个 Tier 1 候选".

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

### 门 (一阶推导 + 约定)
- **HARD**: no lookahead
- **Backtest**: sharpe_net > 0.5 over 3+ year, with 双边 0.5% cost
  - **0.5% cost 算: ** A 股零售实成本 = 双边佣金 0.025%×2 = 0.05% + 卖方印花 0.05% + 双边滑点 0.1%×2 = 0.20%, 合计 **0.30% min**. 0.5% 是 0.30% 真值 + 0.20% buffer (regime stress 下滑点扩大空间).
  - **0.5 sharpe 不是 CI 推出的**, 是约定值. 严格 sampling-CI 推算 (Lo 2002): 60 天观测期年化 sharpe SE ≈ √((1+S²/2)/T_years) = √((1.125)/0.238) ≈ 2.17, 即真 sharpe 0.5 的 60 天观测可能落在 [-3.8, +4.8]. **CI 这么大根本 pin 不了任何门**.
  - 0.5 的 risk-budget 经济解释: 5% NAV 仓位 × sharpe 0.5 (vol 15% 假设) ≈ 7.5% 年化 × 5% = **0.375% NAV/year 期望收益**. 与 5% × 0.5% × 12 (cost drag) = 0.30% NAV/year 几乎抵消. 这是 "刚刚值得为收 friction data 而 deploy" 的边缘. 低于 0.5 backtest sharpe 的策略, 期望真钱回报负, 除非 friction-measurement 价值本身 > 期望回报 — 可以辩论但不该是默认.
- **OOS 切片**: 所有切片 PASS 或 MARGINAL. 允许 ≤ 1 个 FAIL_NEG_SHARPE 当且仅当 (a) 失败机制可识别 (例 2025H2 高低切换), (b) **失败窗 net_ann × Tier-1 仓位 < 0.3% NAV** (例: roe_stability 在 stacked T4 测得 net_ann -0.7%; 5% × 0.7% = 0.035% NAV 单事件损失, 远小于 0.3% 阈). **不允许任何 FAIL_IC_FLIP** (IC 翻号是结构问题不是 regime 问题).
  - 0.3% NAV 阈值的来源: Tier-1 worst-case DD 是 5% × 30% = 1.5% NAV (最差年). 单 6-月失败窗造成 0.3% NAV 损失 = 1.5% 的 1/5 = 一年里允许 5 次同等失败窗. 一年 ~ 2 个 6-月窗, 5 倍冗余, 安全余度足够.
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
- **Backtest**: DSR > 0.85 (约定值)
  - **DSR 含义**: Bailey & López de Prado (2014) 的 deflated sharpe ratio, 多重检验
    校正后的真 sharpe > 0 的概率下界. 0.95 是文献 publication-quality 门槛.
  - **为什么 0.85 而不是 0.95**: 这是 working choice, 不是直接从 LdP 论文里
    copy 来的"production threshold". 推理是: Tier 2 升级要先有 Tier 1 60 天 live
    confirm. Live 数据是独立证据 (没受多重检验偏差影响), 把 backtest DSR 0.85
    + live 60 天 sharpe > 0.8 联合起来的总后验, 在合理先验下大致等价于
    backtest DSR 0.95 单独 (live 把 ~10pp posterior 转到 "真 sharpe > 0" 那侧).
    具体后验数字依赖 prior 和 noise model, **不是严格 Bayesian 推导**, 是
    "用 live 换 backtest 严格度" 的政策性选择, 数字可议. jialong 可调 0.80
    或 0.90.
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
- **必须从 Tier 2 升级**: **12+ 月** live sharpe > 1.0 (注意: 比 Tier 2 的 6 月长一倍 — Tier 3 把仓位再扩 4x, evidence 窗也应该 scale up)
- **Backtest**: DSR > 0.95 + bootstrap CI_low > 0
- **OOS 切片**: 全 PASS (sharpe > 0.8 在每个切片, 包括 bear / 危机段)
- **Capacity**: > 5x target AUM
- **Cross-regime invariant**: bull / bear / sideways 三段都 sharpe > 0
- **Independent kill switch + manual override + circuit breaker**
- **必须经历至少一次 regime transition** (bull→bear 或反向) in Tier-2 12 月窗

### 退出
- Live sharpe ≤ 0.5 over rolling 60 days → 降回 Tier 2
- 任意硬红线触发 → 立即下架

---

## 现存策略在新框架下的归属

| 策略 | 新框架结论 | 推理 |
|---|---|---|
| **spec v4 (RIAD + DSR#30 BB-only 50/50)** | **REJECTED**, 不进任何 tier | 拒绝是 procedural (一次性 DSR 例外 0.920 < 0.95 没获批就过窗口), 不是门松了能解决. 此外 OOS 切片也 FAIL (per Issue #47 stacked 同款机制), 也不过 Tier 1 |
| **spec v3 (BB-only)** | 同上, REJECTED | 已被 spec v4 替代后又一起 reject |
| **roe_stability 单腿** | **可进 Tier 0**, Tier 1 边缘 | 5/7 切片 PASS, 1 FAIL (T4_2025h2 sharpe -0.26), 1 MARGINAL (T5 n=3 噪音). T4 失败机制可识别 (高低切换). 失败窗 net_ann 单腿数据 journal 没直接列, 用 stacked T4 net_ann -0.7% 作上界估 (单腿应小于此, 因 stacked = 50/50 平均, 单腿 roe 仅占一半). 5% 仓位 × 0.7% 损失 = **0.035% NAV 单事件**, 远小于 0.3% 阈. **建议 jialong 批准 Tier 0 → Tier 1 路径**, 升级前要补单腿真实 net_ann 数字 |
| **inst_flow_20d 单腿** | **不进**. 4/7 PASS, 2 FAIL (T2 sharpe 崩 + T3 IC 翻号), 1 MARGINAL (R2). FAIL_IC_FLIP 是结构问题, Tier 1 红线挡 |
| **stacked roe × inst** | **不进**. 6/8 PASS 但 2 FAIL_NEG_SHARPE 是连续 6-12 月失败窗, 不像 single-event regime 那么可识别 |
| **cfoni_precise** | **不进**. sharpe_net 0.67 < Tier 1 floor 0.5 + cost 后边缘, 单腿都站不稳 |
| **nb_ratio_chg** | **不进**. net 负, 已 reject |
| **v16** | **正式化为 Tier 0 ops smoke runner**. 已经是 deprecated 状态用作 infra 验证, 这个角色就是 Tier 0, framework 把它合法化 |

---

## 提案的文件修改 (preview, 不直接编辑, 等 jialong 批准)

**4 个文件必须一起改, 否则 drift**. 原版 (rev 1) 漏了 WORKFLOW.md 和 risk_gate.py,
simplify reviewer 警告 "如果 ratify 后只改 doc 不改 risk_gate.py, 代码会继续用
老门 (sharpe>0.8 / ann>0.15 / mdd<0.30) 把所有 Tier 0/1 候选都挡住".

### (1) CLAUDE.md "策略评审门槛" 段 (line **246-252**, header 是 `## 策略评审门槛（来自 WORKFLOW.md）`) 改写为:

```markdown
## 策略 Live-Tier 与实盘门 (v1, 2026-04-29 框架)

策略不是 "能不能上线" 的二元判断, 是 4 级 Live-Tier 渐进:

- **Live-Tier 0** (paper-only): no lookahead + 回测 sharpe_net > 0 + 30 天 paper smoke
- **Live-Tier 1** (1-5% NAV): + backtest sharpe_net > 0.5 (with 双边 0.5% cost) + 全 OOS 切片不 FAIL_IC_FLIP + 30 天 paper green
- **Live-Tier 2** (5-25% NAV): + 60 天 Live-Tier-1 live sharpe > 0.8 + DSR > 0.85 + 全切片 0 FAIL + capacity ¥50万
- **Live-Tier 3** (25-100% / 外部资金): + 12 月 Live-Tier-2 live sharpe > 1.0 + DSR > 0.95 + 全切片 sharpe > 0.8 + cross-regime invariant + 经历至少一次 regime transition

详见 `journal/eval_framework_v1_proposal_20260429.md` (含 first-principles 推导 + 已知约定值标注).

升级 always 需要 live 证据. 降级不需要新证据. spec v4 历史拒绝结论不变.
```

### (2) WORKFLOW.md "策略评审 Checklist" 段 (line **85-103**) 的 `**绩效标准（最低门槛）**` 子段改写为:

```markdown
**绩效标准 (按 Live-Tier 入门门槛, 详见 `journal/eval_framework_v1_proposal_20260429.md`)**

进 paper-trade (Live-Tier 0) 前自检:
- [ ] no lookahead / no fwd-leak (HARD red line, 全 tier 适用)
- [ ] cost-aware sharpe_net > 0 over 3+ year, 双边 0.5% cost

进 1-5% 实盘 (Live-Tier 1) 前自检:
- [ ] backtest sharpe_net > 0.5 / IC HAC t > 2
- [ ] OOS 切片无 FAIL_IC_FLIP, 至多 1 个 FAIL_NEG_SHARPE 且失败窗 net_ann × 仓位 < 0.3% NAV
- [ ] Live-Tier 0 paper-trade 30 天 green light

(Live-Tier 2/3 进入条件参见 framework doc, 不能跳过 Tier 1)
```

### (3) ROADMAP.md 加新一节 "Live-Tier 实盘状态" (位置: 在 `## Phase 8: Real-Money Readiness（远期，当前暂缓）` 段之后, 与 ROADMAP 现有的研究 "Tier 1a/1b/2/3" 区分开) :

```markdown
## Live-Tier 实盘状态 (v1, 2026-04-29 框架启用)

(注: 这是 LIVE-MONEY tier, 跟本 ROADMAP 上文 Space-C 的研究 "Tier 1a/1b/2/3" 不是
同一概念. 详见 `journal/eval_framework_v1_proposal_20260429.md`)

- Live-Tier 3: 无
- Live-Tier 2: 无
- Live-Tier 1: 无
- Live-Tier 0: roe_stability 单腿 (待 jialong 批准启动 paper smoke 30 天)
- 历史 deprecated ops smoke runner: v16 (Live-Tier 0 内, 不算 strategy)
```

### (4) `pipeline/risk_gate.py` `DEFAULT_RULES` (line **32-50**) **必须改**, 否则代码层继续按老门拒掉 Tier 0/1 候选:

```python
# 当前硬编码的 sharpe>0.8 / ann_return>0.15 / mdd<0.30 适用 Live-Tier 2/3.
# Live-Tier 0/1 的入门门有 strategy-tier 维度, DEFAULT_RULES 不能 one-size-fit-all.

# 建议改造方向 (二选一, 由 jialong 拍板):
#  A) DEFAULT_RULES 改成 dict[str, dict] 按 tier 分: TIER_RULES = {0: {...}, 1: {...}, 2: ..., 3: ...}.
#     gate 调用方传 tier= 参数, 默认 tier=2 (保持当前严格度向后兼容).
#  B) DEFAULT_RULES 仅作为 Tier 2 用; 加 LIVE_TIER_0_RULES / LIVE_TIER_1_RULES 字典.
#     调用方显式选门, 不设默认.

# 注释里 "默认门槛来自 CLAUDE.md「策略评审门槛」" 那一行也要更新成
# "默认门槛 = Live-Tier 2 (其他 tier 见 ...)".
```

### 不改的文件 (确认过 grep)
- `journal/paper_trade_spec_v4_*` — 历史决定文档, 不改.
- 其他 journal entries — 历史快照, 引用旧门是历史事实.

---

## 7 个开放问题 (RATIFIED 2026-04-29 by jialong)

| # | 问题 | 决定 | 理由 |
|---|---|---|---|
| 1 | roe_stability 进 Tier 0 paper smoke? | **批准** | 5/7 切片 PASS 最干净候选; Tier 0 零真钱 |
| 2 | v16 vs roe_stability vs 双跑? | **双跑** | v16 = infra ops smoke (深度集成 pipeline), roe_stability = strategy smoke. 目的不同, 双 ledger 30 天看清差异 |
| 3 | 5% NAV 上限合适? | **保留 5% 占位**, Tier 1 启动需独立决策 | 现在不跑真钱, 5% 是占位符. 等 Tier 0 30 天后再问 jialong NAV anchor |
| 4 | 允许 Tier 1 ≤1 FAIL_NEG_SHARPE? | **允许** (按 §Tier 1 推导的 0.3% NAV 阈) | Tier 1 目的本就是 friction measurement, 严格不允许 = 这个 tier 永远空着 = 退化成二元单门 |
| 5 | Tier 2 升级窗 60 vs 90 天? | **60 天** | 见 §反例 3, 不是统计显著门是 governance 门, 拖 90 天信息增量小 |
| 6 | Tier 2 DSR 0.80/0.85/0.90? | **0.85** | 中间值, 真到 Tier 2 那一步还能再调, 现在不会触发 |
| 7 | risk_gate.py 改造 A vs B? | **A** (DEFAULT_RULES dict by tier, 默认 tier=2 兼容) | 向后兼容, 老 caller 不破; 新 caller 加 tier= 参数; 工程量小 |

短期阻塞解除 (按本批准, 立即可做):
- ratify 本提案 → 改 4 个文件 (CLAUDE.md / WORKFLOW.md / ROADMAP.md / pipeline/risk_gate.py)
- 开新 Issue: "Tier 0 启动: roe_stability + v16 双 ledger 30 天 paper smoke"
- 关本 Issue #50

---

## 不在本提案范围

- **如何把 roe_stability 实际接进 paper-trade**: 这是 D 路 (paper-trade infra) 的工作, B 路只定标准.
- **是否做新的 cross-sectional 因子探索**: 740ea7e 已写 "暂不", framework 不改这个.
- **事件驱动轨道 (A 路)**: 跟 framework 正交, A 路用同一个 Tier 0/1/2/3 标准.
- **现金流 / 手续费 / 借券计算**: paper-trade infra 实现细节.

---

## 风险与反例

### 反例 1: "Tier 1 0.5 sharpe 是不是太松了"
回应: 0.5 是约定值不是 CI 推出的 (60 天观测窗 sharpe SE ≈ 2.2, 大到 pin 不了
任何门 — 见 §Tier 1 门 "0.5 sharpe 不是 CI 推出的"). 经济解释: backtest sharpe < 0.5
策略在 5% 仓位 + 0.5% cost 假设下期望真钱回报负, 不值得为收 friction data
而 deploy. 真实 stop loss 是 "rolling 30 天 sharpe ≤ -0.3 → 降回 Tier 0",
不是 backtest 门. 用 0.8 是把 Tier 2 标准下移, 没 anchor 到 Tier 1 risk capacity.

### 反例 2: "DSR 0.85 vs 0.95 差 0.10 看起来小但实际差很多"
回应: 同意 DSR 是非线性的. 0.85 是 working choice 不是 LdP 论文里直接 copy
的 production threshold (rev 1 误称, 已撤). 推理: backtest DSR 0.85 + 60 天
live sharpe > 0.8 联合后验, 在合理先验下大致等价于单看 backtest DSR 0.95.
具体后验依赖 prior 和 noise model, 不是严格 Bayesian 推导. jialong 可调 0.80
或 0.90, 这是政策性数字.

### 反例 3: "Tier 1 升 Tier 2 60 天 live, 60 天能验出什么"
回应: 60 天 ≈ 12 周 ≈ 60 trading days 的 sharpe estimate SE ≈ 2.2 (Lo 2002).
60 天 live sharpe > 0.8 不是统计显著性证明 (CI 远超 ±0.8), 是 "策略没在 Tier 1
真实仓位下崩盘" 的 governance 证据 + tracking error < 200bp/月 这个独立指标 (这个
有信号意义因为它是 backtest-vs-live 偏差, 不依赖 sharpe 估计精度). 真正
统计显著的 sharpe 估计需要 N 年级别样本; Tier 3 的 12 月 + DSR 0.95 是这个目的.

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
