# Factor Mining Sprint 3 — 20260422 overnight session

## 目的

jialong 休息前委派：继续挖新因子，只挖我认为能 work 的。

自我约束：
- 不瞎打随机 factor，每个必须有已发表文献且在 A 股 analog market 有证据
- Pre-reg 参数 + 门槛，不事后调参
- 过了 gate 再继续下一个，否则诚实 KILL 并停

## 挑选依据

查阅 `utils/alpha_factors.py` 现有 70 个因子，排除已覆盖。筛出两个**有学术证据 + A 股验证 + 库里没有**的：

| 候选 | 文献 | A 股证据 | 机制 |
|------|------|---------|-----|
| Frog-in-the-Pan (FiP) | Da, Gurun, Warachka 2014 RFS | 孙谦 2019 | Information Discreteness × Momentum |
| Asset Growth (AG yoy) | Cooper, Gulen, Schill 2008 JF | 田利辉 2014 | 管理层过度扩张 → 反转 |

锁定参数（pre-reg）：
- FiP: `lookback=250`, `skip=21`, 原论文参数
- AG: 年频 total_assets YoY, T+1 信号
- Universe: 全 A 主板（剔除 688/300/301），剔除停牌>50% 的 symbol
- Window: 2018/2019 – 2025（AG warmup 需要历史财报）
- IC method: Spearman rank, min 300 stocks/day
- Kill rule: `|IC| < 0.02 OR |t-stat| < 3.0` at primary horizon

## 结果

### Sprint 3.1 — Frog-in-the-Pan

```
 fwd   ic_mean      icir    t_stat     t_hac  pct_pos  n_days
   1 -0.000959 -0.012860 -0.529901 -0.466842 0.487044    1698
   5 -0.002830 -0.037408 -1.539632 -0.760788 0.469894    1694
  10 -0.003107 -0.039844 -1.637475 -0.636016 0.494967    1689
  20 -0.004475 -0.057278 -2.346996 -0.647097 0.475283    1679
```

**Verdict (fwd=1): KILL** — IC -0.001, t -0.53, HAC-t -0.47。完全是噪声。

所有 horizon 都指向反转（IC 负），但幅度可忽略。HAC-t 全部 < 1，说明所谓"显著性"几乎全是自相关伪影。

**失败解释**：孙谦 2019 用的窗口是 2005-2015，那段 A 股 momentum 效应显著。2019-2025 的 A 股 momentum 本身已经弱化/反转（见 `journal/factor_mining_sprint_20260421.md`），所以依赖 momentum 的 FiP 增强机制跟着失效。

### Sprint 3.2 — Asset Growth YoY

```
 fwd   ic_mean      icir    t_stat     t_hac  pct_pos  n_days
   1 -0.001426 -0.017588 -0.763620 -0.696680 0.496552    1885
   5 -0.004052 -0.047868 -2.076068 -1.006698 0.489633    1881
  10 -0.007716 -0.087742 -3.800341 -1.436214 0.461087    1876
  20 -0.013339 -0.142878 -6.171952 -1.644464 0.414255    1866
```

**Verdict (fwd=20d): KILL** — |IC| 0.013 < 0.02 gate；raw t -6.17 看似显著但 HAC-t -1.64 < 2。

**但有意思的地方**：
- 方向**正确**（IC 负，符合 Cooper-Gulen-Schill 预测）
- IC 随 horizon **单调放大**（1d → 20d，|IC| 从 0.001 → 0.013）
- raw t 膨胀 + HAC 大幅缩水 → 揭示信号是年频、返回是短频带自相关，统计量被稀释
- fwd=20 时 IC<0 占比 58.6%，pct_pos 0.414

这是典型的"信号真但不够强"的 A 股慢信息因子。在月频/季频 long-short 组合里或许还能凑出年化 3-5%，但作为 alpha 单独使用不够格。

## 元观察 — Sprint 3 连续失败的意义

- **Sprint 1 (2026-04-21)**：6 因子挖掘，1 过 gate
- **Sprint 2 (2026-04-21)**：4 因子挖掘，1 过 gate
- **Sprint 3 (2026-04-22)**：2 published-backed 因子，0 过 gate

累计 **12 因子，2 过 gate（17%）**。而且 Sprint 3 的特殊性：两个都是**教科书级 + A 股文献验证**的因子，连它们都过不了，说明不是"没挑好因子"，而是：

1. **A 股 cross-sectional factor premium 在 2019-2025 这个窗口上普遍薄**（这和私募千亿 alpha 不矛盾 — 他们做的是事件驱动/中频/HFT，不是 cross-sectional factor，见 memory `feedback_ashare_alpha_nuance`）
2. **Post-2021 regime 切换** — ETF 规模膨胀 + 量化资金入场套利，把小盘反转/动量/AG 这类经典因子的边际压平
3. 我自己的规则 `research-space-saturation (2026-04-21)` 已经警告过：连续 sprint hit rate < 30% 应停止继续挖 cross-sectional 同范式

## 下次开工建议 — 不要继续挖横截面因子

有 conviction 的路径（按优先级）：

### A. Paper trade DSR #30 先跑完一个月，用真实 slippage 校准回测

已经在跑（2026-04-17 起步）。现在没有这份数据，所有回测的成本估计都是虚的。**这是唯一能把回测号称的 Sharpe 2.47 压缩到真实数的办法**。

建议每周五晚汇总：backtest vs live 的单日 pnl diff 分布，>2σ 异常写进 journal。

### B. Tier 1b MD&A drift 全 A 股 IC 评估（Issue #28 正在跑）

文本语义 alpha 属于"空间 C"，和横截面因子范式完全不同。Tier 1 cheap baseline 跑完才看 Tier 2 LLM 增量。**这是非同范式路径**，一旦 IC > 0.02 就显著增加候选池。

### C. Regime gate 产品化

`journal/phase5_regime_robust_plan_20260420.md` 已写 spec。把现有策略 × regime 分层跑 IC，找出哪些因子在哪个 regime 里仍 alive。这是**同数据换坐标系**，不是挖新因子，预期 hit rate 高。

### D. 小盘 capacity-aware 深挖

memory `feedback_ashare_alpha_nuance`：私募在小盘事件驱动做 alpha。`research/factors/limit_up_sleeve/` 有基础，可扩：
- 涨停开板后 intraday 反弹分布
- 封板量占比 × 次日跳空
- 被限仓后的小微盘反弹

但这些接近 DSR #30/#33 的逻辑，风险是和现有 event-driven 候选共线。需先算相关性。

### 不建议继续

- 不要再挖同类 cross-sectional factor on tushare daily
- 不要 variant tweaking（DSR #30 换一种 parameterization 等），这些都是 overfit 路径

## 产物

- `research/factors/frog_in_pan/factor.py` + `evaluate.py` + `ic_results.csv`
- `research/factors/asset_growth/factor.py` + `evaluate.py` + `ic_results.csv`

两份代码都经过 smoke test + pre-reg runner，KILL 结果也留着，未来若要再验证或扩展（换 universe / 换窗口）可直接复用框架。
