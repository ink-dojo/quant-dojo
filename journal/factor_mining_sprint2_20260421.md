# 散户低频因子挖掘 Sprint 2 — 2026-04-21

> 作者：jialong + Claude | 时长：~2h | 主题：专注"散户可做 + HFT 无法抢跑"的低频 alpha

## 动机

承接 Sprint 1 (F1-F8)，这一轮聚焦**散户友好**的低频事件/动量因子：
- 目标节奏：20-60 日漂移，月频换仓
- 目标成本：ETF/个股都能做，不需要 HFT 基础设施
- 目标独立性：与现有 v17 六因子组合正交

## 跑完的因子（4 个）

| # | 因子 | 数据源 | 最强 ICIR | HAC t | 结论 |
|---|---|---|---:|---:|---|
| F9 | **PEAD 业绩预告漂移** | 业绩预告 2010-2026 (171k) | IS 0.34 / OOS -0.03 | +4.40 / -0.23 | ❌ **2023 后完全失效** |
| F10 | **解禁压力 (lockup)** | 解禁 2018-2025 (18k) | raw 0.53 / ind+size 中性 0.09 | +7.05 / +1.07 | ❌ **95% 是 size 敞口**, 仅 Q5 avoid filter 可用 |
| F11 | **股东增减持 (insider)** | 公告 2018-2025 (94k) | raw 0.19 / 中性 -0.13 | +2.32 / -1.59 | ❌ **中性化后反转**, 不是独立 alpha |
| F13 | **行业 3 月反转 (ind_reversal)** | 价格 + 申万一级 | -0.35 (OOS -0.35) | -4.77 (OOS -3.16) | ✅ **OOS 不衰减**, 推入 v18 |

注：F13 ID 跳过 F12 因为 F12 已被 insider 占用，F13 = industry momentum/reversal family。

## F9 (PEAD) 的意外发现

业绩预告 surprise (预告类型 + 业绩变动幅度 combo) 在 IS 2014-2022 是**教科书级 alpha**：
- ICIR **+0.341**, HAC t **+4.40**
- 20 日前瞻 IC 单调, 40d 也稳

但在 OOS 2023-2025 **完全失效**：
- ICIR -0.03, HAC t -0.23 (几乎为 0)

**推测原因** (均非空穴来风):
1. 2023 年注册制全面铺开，预告披露质量提升, 市场效率上移
2. 散户占比下降 (北向+机构 dominate), 反应速度变快
3. 业绩"明面利好"已被预告前 20d 定价完毕 (信息领先泄露)
4. 2023-2024 市场主题是小微盘 regime, 业绩逻辑被压制

**行动建议**: 不推 v18，但值得持续监控 2026+ 是否回归有效。

## F10 (解禁压力) 的陷阱

- 原始版本 ICIR **+0.53** (20d) / **+0.61** (40d), HAC t +6.35 / +7.05 — **乍看是强 alpha**
- Q5 (规模最大解禁) 20d 前瞻年化 **-10.35%** vs Q1 +9.8%
- 行业中性化后 ICIR 跌到 +0.06, HAC t +0.77 — 失效
- size 中性化 (用 log price 代理) 后 ICIR +0.07
- 行业+size 双中性化后 ICIR +0.09

**结论**: 解禁压力 = size/行业敞口代理, 不是 stock-specific alpha。
**但 avoid filter 依然实用**: portfolio construction 时排除未来 20d 解禁 pct > 20% 的股票 (Q5), 这是纯机械过滤, 不涉及 alpha 合成。

## F13 (行业 3 月反转) — 唯一赢家

### 信号层

行业级月频动量长短:
- **mom_12_1** (过去 12 月-最近 1 月): top-5 ann +23.03%, LS ann **+16.68%**, Sharpe 0.52
  - IS 2015-2021: ann +23.55%, Sharpe **0.70** — 符合 Moskowitz 经典
  - OOS 2022-2025: ann +6.15%, Sharpe 0.21 — 衰减
- **mom_3** (过去 3 月): LS ann **-23.61%**, Sharpe -0.42 — **反向**!

### 个股层 (行业信号广播到股票)

过去 3 月行业累计收益 → 作为 -signal (即 "行业前 3m 跌多 → 未来 20d 预期反弹"):

| 区间 | IC | ICIR | HAC t | n |
|---|---:|---:|---:|---:|
| ALL 2015-2025 | -0.041 | **-0.318** | **-4.77** | 2590 |
| IS 2015-2021 | -0.033 | -0.306 | -3.66 | 1641 |
| **OOS 2022-2025** | **-0.055** | **-0.347** | **-3.16** | 949 |

**OOS 比 IS 更强** — 极 robust 的反转信号。

### v18 OOS 验证

训练 2022-2024 / 测试 2025, v18 = v17 (6f SN crowding) + ind_reversal_3m:

#### 【修正】真 pb 结果 (外置盘恢复后重跑)

| 策略 | 阶段 | 年化 | 夏普 | MDD | 超额 |
|---|---|---:|---:|---:|---:|
| v9_5f | OOS | +33.06% | 1.394 | -17.53% | +12.42% |
| v17_6f | OOS | +35.04% | 1.455 | -17.20% | +14.10% |
| **v18_7f** | **OOS** | **+34.17%** | **1.509** | **-15.14%** | **+13.09%** |

**v18 vs v17 OOS 差异 (真 pb)**:
- Δ 年化 **-0.87%** (由正转负)
- Δ 夏普 **+0.054** (原 +0.195, 缩 4×)
- Δ MDD **改善 +2.06pp**
- Δ 超额 **-1.02%** (由正转负)

ind_reversal_3m 权重 **8.8%**, ICIR +0.307 (被 bp 的 +1.023 / neg_crowding 的 +1.111 双重压制)。

**结论修正**:
- v18 **不是显著胜出**, 只是 **"小幅降 MDD + 持平收益"** 的风险优化变种
- 上次 +0.195 Sharpe 的幻觉来自 bp=1 占位导致 v17 失去最强因子 (ICIR +1.023, 权重 19.6%)
- ind_reversal_3m 与 bp 存在信息重叠 (反转+低估值共振), 不是独立 alpha
- 不升格主因子, 保留在备选池继续观察

#### 【已废止】pb=1 fallback 结果 (保留用作对比参考)

| 策略 | 阶段 | 年化 | 夏普 | MDD | 超额 |
|---|---|---:|---:|---:|---:|
| v9_5f | OOS | +41.97% | 1.411 | -21.99% | +20.60% |
| v17_6f | OOS | +34.55% | 1.289 | -20.24% | +14.13% |
| v18_7f | OOS | +38.20% | 1.483 | -16.85% | +16.97% |

> 首次 v18 OOS 运行时外置盘访问被系统撤回, bp 因子以常数 1.0 占位 (ICIR ≈ 0)。
> v17 baseline 因而失真 (丢失 19.6% 权重的 bp), 让 v18 看起来 +0.195 Sharpe。
> 外置盘恢复后用真 pb 重跑, Δ Sharpe 缩为 +0.054, 结论重大修正。

## 方法论收获

### 1. A 股事件驱动因子几乎都是 size 代理

PEAD / lockup / insider 三个因子的原始 IC 都还行 (ICIR 0.19-0.61), 但一旦做**行业+size 双中性化**, ICIR 几乎归零或反转。

**原因**: A 股 2018-2025 时段 size premium 剧烈波动 (小微盘 2021-2022 跑输 → 2023-2024 暴涨 → 2024-10 崩盘 → 2025 反弹), 任何"小盘股为主"的信号集合都有 size loading 假象。

**教训**: 新因子合格标准应当**强制**做行业+size 双中性化后再看 ICIR。这是 sprint 3 的 filter。

### 2. OOS 反而更强 = 真信号的稀有特征

F13 ind_reversal_3m 的 OOS ICIR **-0.347 比 IS -0.306 更强**, 这在因子研究中极少见。
通常解释: 2023-2025 A 股 regime 转为"板块轮动加剧", 反转效应放大。

相比之下 F9 PEAD 的 IS-OOS 断裂是典型的"时代终结" (regime shift 导致某 anomaly 失效)。

### 3. 散户 alpha 的现实约束

承接 jialong 的直觉 ("拼不赢高频"):
- 事件驱动 20-60d 漂移: HFT 无法抢跑 (窗口太长) → 散户理论上有空间
- 但 **信息已被公募/北向提前定价**: 很多 "公开事件" 在公告日 T+0 前 5d 已经反应完
- 真正的散户低频 alpha 在于 **cross-sectional 行为偏差** (反转/低 vol/高质量), 不在 **事件驱动**

### 4. Portfolio construction alpha 也是 alpha

F10 解禁压力 "非 alpha" 但其 Q5 avoid filter 实用 — 排除掉将大规模解禁的股票, 相当于节省 -10% 年化。
这不进因子池但进**选股前置过滤**, 对最终组合贡献可观。

## 产出文件

- `research/factors/earnings_pead/` (factor_research.py + 4 个 parquet + report.md)
- `research/factors/lockup_pressure/` (factor_research.py + 2 个 parquet + report.md)
- `research/factors/insider_trading/` (factor_research.py + 3 个 parquet + report.md)
- `research/factors/industry_momentum/` (factor_research.py + 3 个 parquet + report.md)
- `scripts/v18_ind_reversal_oos_eval.py`
- `journal/v18_ind_reversal_oos_20260421.md`
- `journal/factor_mining_sprint2_20260421.md` (本文)

## 下一步推荐

### 短期 (本周)

1. ~~**正式化 v18**~~: **已否决** — 真 pb 下 Δ Sharpe 仅 +0.054, 与 bp 信息重叠, 不升格主力
2. **补做 avoid filter**: 封装 `utils/filters/lockup_pressure_filter.py`, 在 portfolio 层面统一用
3. ~~**重跑 v18 带真 bp**~~: **已完成 2026-04-21** — 结论重大修正, 见上表
4. **跨年 OOS**: 扩大到 v17 vs v18 的 2022-2025 walk-forward (不止 2025 一年) 再下定论

### 中期 (下周)

1. **继续挖行业动量家族**:
   - 行业轮动信号 (top-3 行业动量 + bot-3 行业反转 合成)
   - 行业 beta 时变 (高 beta 行业 in bull, 低 beta in bear)
2. **挖 cross-sectional 低 vol**: low-vol 20/60/120d 在 A 股散户账户表现 (免融资)
3. **把 ETF layer 上线**: 用现有申万一级映射表跑纯 ETF 月频 momentum 组合, 给 jialong 一个真正能 copy-paste 的散户策略

### 长期 (月度)

1. **2026 Q2 后重测 PEAD**: 看是否回归 (政策/市场 regime 变化)
2. **业绩预告质量研究**: 预告差异幅度 (预告值 vs 实际披露) 比预告类型更细, 或可 recover alpha

---

— 记录：jialong (代 claude 整理)
— 2026-04-21
