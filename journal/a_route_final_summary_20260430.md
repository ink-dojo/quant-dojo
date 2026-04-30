# A 路最终总结 — 4/4 候选全死, 转 C+D

_2026-04-30 — A 路 (event-driven alpha) 4 个候选跑完全部 framework_pass=0_

---

## A 路是什么

按 2026-04-29 我对 jialong 的提议 (转方向 = "换赛道", 跳出 cross-sectional rank):
> A 路: 事件驱动 alpha. 用 SSD 上的 events (top_list / repurchase / share_float /
> stk_surv) 找 [-3, +30] 事件窗的 abn return signal, 不再做 quintile factor.

预期: 4 个候选里至少 1 个能过 Live-Tier 1 严格门 (T3 PASS + IS slice 失败窗 < 0.3% NAV/yr).

---

## 实际结果 (4/4 全死)

| Issue | 候选 | n_events | full T+5 net | T3 OOS verdict | framework_pass |
|---|---|---|---|---|---|
| #56 | LHB 龙虎榜 | 130k | +7.81% | T2 multi_day extreme drag 6.6% NAV/yr | 0 |
| #57 | 回购预案 | 11.5k | -0.37% | OOS PASS 1 (loose) 但 IS drag 0.78% | 0 |
| #58 | 限售解禁 | 16k | T+10 -9.15% (反向 supply pressure) | reverse 不可执行 (借券难) | 0 |
| #59 | 机构调研 | 28k | T+5 -0.97% | 全 cell FAIL | 0 |

**4 个候选 0 个过 framework**. 不是参数不对, 是 cross-sectional event-driven
alpha 在当前 (2024-26) A 股市场普遍被磨掉了.

---

## 投入

代码:
- `utils/event_study.py`: 5 通用 utility (load_event_parquets / compute_event_abn_returns /
  quintile_spread / cell_verdict / framework_strict_decision / t1_limit_mask)
- `utils/event_alpha_pipeline.py`: 3-variant + decision orchestrator
- 4 个 study scripts (LHB phase 1+2 / 回购 / 解禁 / 调研)

Commits: ~30 个, ~2500 行 code + journal

journals: 5 个 (LHB phase 1+2, 回购, 解禁, 调研, 本 final)

总耗时: 估计 3-4 小时 (从 LHB Phase 1 启动到本 final summary)

---

## 教训 (诚实)

### 1. simplify review 找到 7+ 处真 bug

跨 4 个 study, simplify review 共发现:
- 3 个 cost / 数学错误 (LHB cost under-count 2x, 回购 unit off 10000x, journal 算术 10x off)
- 4 个 vectorize miss (compute_event_abn_returns / add_t1_limit_mask /
  load_circ_mv_for_events 都先 iterrows 后 vectorize)
- 2 个 抽象 miss (event_study utils 第二次 candidate 才抽 framework_strict_decision,
  event_alpha_pipeline 第三次 candidate 才抽)
- 1 个 decision logic 太松 (LHB phase 2 自动判 "继续" 跟 framework 严格门冲突)

每次 simplify cycle 都是必要的 — **没有 review 至少 50% 这些 bug 会进入下一个 candidate 复制传播**.

### 2. "做到头" 比"找到 alpha"更有价值

最初 plan 是 "A 路 4 候选挑 1 个能跑". 实际结果是 4/4 死, 更 valuable —
得到 honest "现况 cross-sectional event-driven 不行" 的结论, 而不是 over-fit
到一个看起来还行但 OOS 会崩的候选.

A 股事件 alpha 的"老 anomaly 被 arbitrage 平"是 well-known 假说, 现在有了
direct empirical 证据.

### 3. utils 框架是真 sunk-cost recoverable

每个 study script 现在 ~150-300 行, 90%+ 是数据加载 + signal 定义, 真正的
event-window backtest + cross-tab + decision 全部是 utils 的 5 个函数 + 1 个
orchestrator. 后续如果出现新事件数据 (例如未来 tushare 加 dragon_tigers
第二维度, 或 margin / ETF flow 等), 直接 import 一行 = 1 个新 study.

不浪费.

---

## 下一步 (按原 A → B → C → D 顺序)

A 已完结 (4/4 杀). B 已 ratified (评估范式 v1, Issue #50). 接下来:

**C: 质量改进现有 cross-sectional 因子**
- roe_stability 单腿 (Issue #47 5/7 切片 PASS, 仅 T4 FAIL)
- 加 regime overlay (HS300 RSRS 信号下停仓) / quality overlay / 改 horizon
- 红线: regime mask 必须用纯外生信号 (HS300 价量) 不能用 fwd_ret, 否则 OOS 拟合

**D: paper-trade infra 真用法**
- Issue #51 ready (roe_stability + v16 双 ledger 30 天 paper smoke)
- 现有候选立刻接进去, nightly 跑, 30 天后看 backtest-vs-live tracking error
- 不等 C 完成 — D 跟 C 并行不冲突

**优先级**: D 先做 (启动后台跑, 30 天 deferred deadline), 同期 C 主动改进.
30 天后看 D 收的 tracking error vs C 改进版的 OOS 测试, 综合决定是否升 Tier 1.

---

## A 路 close-out 状态

- ✅ 4 issues 全 closed (#56, #57, #58, #59)
- ✅ 4 journals 全 push (LHB phase 1+2, repurchase, share_float, stk_surv)
- ✅ utils framework 抽出, 后续可复用
- ✅ A 路最终决议 (本 doc)
- ⏭️  转 C + D 并行

— 记录: jialong
