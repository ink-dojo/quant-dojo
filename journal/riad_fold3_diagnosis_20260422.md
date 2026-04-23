# RIAD Fold 3 (2025 H2) 负 Sharpe 诊断报告

> 日期: 2026-04-22
> Issue: #36
> 结论: Fold 3 负 Sharpe **不是 alpha decay**, 是 **三重原因叠加**
>   1. Long leg 结构性跑输 benchmark (从始至终, 不是新问题)
>   2. 散户 overpower 机构: 2025 H2 AI/题材炒作板块里因子假设反转
>   3. stk_surv 数据稀疏: 2025 H2 调研披露 -38%, inst leg 信号弱化

## 核心发现

### Finding 1 — Long leg 从始至终就跑输 benchmark

月度 attribution (vs 等权 tradable benchmark):

| 分段 | LS Sharpe | **Long excess SR** | Short excess SR |
|---|---:|---:|---:|
| 2024 H1 | +3.29 | **-0.89** | +2.50 |
| 2024 H2 | +1.57 | **-2.46** | +3.07 |
| 2025 H1 | +1.53 | **-1.11** | +2.07 |
| 2025 H2 | -0.12 | **-1.82** | +1.05 (bias-adjusted -0.5) |

**所有分段 Long Q2Q3 excess SR 都是负的**. Q2Q3 (机构关注高 + 散户关注中等) 的股票从来没有跑赢
等权 tradable universe.

### Finding 2 — Short excess SR 被 tradable filter bias 高估

`daily_returns.py` baseline 的 gross_short 没做 tradable filter, Q5 股包含 ST/停牌,
NaN return 被当作 0 拉低 Q5 均值, **假造 short alpha**.

直接验证 "Long benchmark - Short Q5 (带 tradable filter)":

| 分段 | Baseline LS SR | Bench-Q5 unrestr SR | **Bench-Q5 margin filter SR** |
|---|---:|---:|---:|
| 2024 H1 | +3.29 | +3.21 | +2.34 |
| 2024 H2 | +1.57 | +2.76 | +1.87 |
| 2025 H1 | +1.53 | +2.69 | +1.47 |
| **2025 H2** | **-0.12** | **-0.53** | **-0.77** |

实盘可执行 (margin filter) 的 2025 H2 Sharpe 是 **-0.77**, 比原 baseline -0.12 更差.
**修正认知**: RIAD short leg 的真实 alpha 在 2025 H2 **已经消失**, 不是 "仅降到 +1".

### Finding 3 — 行业 attribution 揭示真正失败原因

2025 H2 各 SW1 行业内 LS (Q2Q3-Q5) Sharpe:

**严重失效 (SR < -1)** — 全是 2025 散户炒作题材重灾区:
- 41 **交通运输** SR -2.03 (低空经济 / 无人机)
- 11 **农林牧渔** SR -1.98
- 74 **机械设备** SR -1.19 (人形机器人 / 具身智能)
- 62 **计算机** SR -1.03 (AI / DeepSeek / 算力)

**仍有强 alpha (SR > 1)** — 非题材板块:
- 28 **家电** SR +2.26
- 63 **传媒** SR +2.38
- 46 **综合** SR +2.24
- 72 **非银金融** SR +1.94
- 35 **轻工** SR +1.82
- 43 **商业贸易** SR +1.72
- 22 **化工** SR +1.49
- 24 **有色** SR +1.08

**诊断**: 在 AI/机器人/低空经济等题材里, **散户追捧的股票 (Q5) 反而跑赢机构调研股 (Q2Q3)**,
Barber-Odean attention bias 假设被 "散户 overpower 机构" 逆转.

### Finding 4 — stk_surv 数据在 2025 H2 显著稀疏

数据覆盖月度汇总:

| 分段 | retail 日均 | retail 独立股 | surv 月均调研 | surv 独立股 | surv 总机构 |
|---|---:|---:|---:|---:|---:|
| 2024 H1 | 144.9 | 1430 | 725 | 538 | 6477 |
| 2024 H2 | 204.0 | 2141 | 658 | 502 | 7582 |
| 2025 H1 | 189.0 | 2054 | 722 | 556 | 6736 |
| **2025 H2** | 193.3 | 1938 | **449 (-38%)** | **365 (-34%)** | 5428 (-19%) |

**关键**: retail 覆盖稳定, 但 **stk_surv 调研数据 -38%**. 可能原因:
- 数据滞后披露 (tushare 最新 2026-03-24, 2025 Q4 调研尚在补录)
- 新披露规则 (证监会 2025 年某次新规?)
- 单纯机构调研频率下降 (牛市里机构躺赢, 调研动力低)

**影响**: inst_attn leg 信号弱化, RIAD = retail_z - inst_z 更依赖 retail, 在散户极端情绪下失效加剧.

## 综合诊断

**RIAD 2025 H2 负 Sharpe 的三重原因**:

1. **结构性** (Finding 1): Long Q2Q3 从始至终跑输等权 benchmark, 不是新问题, 但 2025 H2 benchmark 大涨 +19% 让 long 拖后腿
2. **行为金融** (Finding 3): 在散户炒作板块里 attention bias 反转 (Barber-Odean 失灵)
3. **数据质量** (Finding 4): stk_surv 2025 H2 披露 -38%, 机构 leg 信号弱化; 可能是滞后披露, 3-6 个月后 revisit

## 策略改进方向 (待讨论, 不着急做)

### 即期可做
1. **替换 long leg**: Long = 等权 tradable universe (passive beta), Short = Q5 (filtered). 
   - Bench-Q5 2024+2025H1 Sharpe 远高于 baseline LS, 但 2025 H2 仍负.
   - 不解决"散户 overpower 机构"问题
2. **行业中性 LS**: 每个行业内 Q2Q3-Q5, 行业等权加总. 
   - 部分消解 Finding 3, 但依然 handle 不了"板块内散户反杀"
3. **行业排除**: 过去 N 月 turnover > threshold (高换手 = 高散户参与) 的行业剔除 LS 
   - 最直接对应 Finding 3 的 diagnosis
   - 风险: 事后 filter, pre-reg discipline 困难

### 战略考量
1. **等 stk_surv 数据补全再重算 Fold 3**: 若 2025 Q4 调研披露 3-6 月后补齐, Sharpe 可能回升
2. **Factor decay 监测**: 加入 monitoring infra (Issue #X - Plan B), 每月看 IC 是否 < 0.03
3. **换底层假设**: RIAD 基于 "机构 informed + 散户 noise" 假设, 在部分散户化市场下失灵.
   可能需要 "retail attention + retail performance" 两维信号 (加入价格动量) 识别 crowded trap

## Pre-reg 纪律恪守

以下 **不能** 基于本诊断做:
- 调 RIAD window (20d / 60d)
- 调 quantile 阈值 ([0.2, 0.6], [0.8, 1.0])
- 事后选"失效行业"剔除 (这是 data-snooping)
- 调 size / industry 中性化参数

允许的**pre-reg 扩展**:
- 开新研究轨道 "RIAD v2: with concept-turnover overlay" (独立 spec + 独立 n_trials)
- 等更多样本 (2026 H1 数据到齐后再判)

## 数据与代码

```
research/factors/retail_inst_divergence/
  fold3_monthly_attribution.py    月度 IC + long/short leg SR
  bench_short_only.py             Long Bench - Short Q5 验证
  industry_attribution.py         28 个 SW1 行业 LS attribution
  data_coverage_check.py          ths/dc/stk_surv 月度覆盖度

logs/
  riad_fold3_attribution_20260422.json
  riad_fold3_daily_attribution.parquet
  riad_fold3_monthly_attribution.parquet
  riad_bench_short_20260422.json
  riad_bench_short_daily.parquet
  riad_industry_attribution_20260422.json
  riad_data_coverage_20260422.json
```

— 记录: jialong
— 更新: 2026-04-22
