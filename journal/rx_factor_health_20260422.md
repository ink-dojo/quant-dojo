# RX 因子健康度周报 — 2026-04-22

> 覆盖 Issue #33/#35/#36 轨道的 6 个差异化因子, 按窗口对比 IC/ICIR 稳定性.
> 门槛: |IC|>0.03 ✅ healthy | |IC|∈[0.02,0.03] 且 |HAC t|≥2 ⚠️ degraded | 其余 ❌ dead

## 因子健康度对比

| 因子 | Display | window 504d IC | window 504d HAC t | window 504d 状态 | window 252d IC | window 252d HAC t | window 252d 状态 |
|---|---|---|---|---|---|---|---|
| RIAD | 散户-机构关注度背离 (size+ind neutral) | -0.0586 | -4.84 | ✅ healthy | -0.0519 | -4.71 | ✅ healthy |
| MFD | 超大单-小单资金流背离 (反转) | -0.0211 | -2.52 | ⚠️ degraded | -0.0278 | -2.26 | ⚠️ degraded |
| BGFD | 券商金股共识度 (follow consensus) | -0.0068 | -0.32 | ❌ dead | +0.0042 | +0.17 | ❌ dead |
| LULR | 连板反转 (高位涨停 → T+5 反转) | +0.0425 | +4.87 | ✅ healthy | +0.0417 | +3.68 | ✅ healthy |
| THCC_inst | 前十大流通股东机构口径环比 (反向) | -0.0110 | -1.66 | ❌ dead | -0.0093 | -1.41 | ❌ dead |
| SB | 机构调研 burst (7d / 91d median) | -0.0078 | -1.25 | ❌ dead | -0.0015 | -0.15 | ❌ dead |
| SRR | 停复牌反转 (log1p duration, hold 5d) | +0.0238 | +0.24 | ⚠️ degraded | +0.0185 | +0.18 | ❌ dead |
| MCHG | 高管变动事件 (董事长/总经理/CFO/财务总监) | -0.0020 | -0.18 | ❌ dead | +0.0195 | +0.91 | ❌ dead |

## 各因子详情

### RIAD — 散户-机构关注度背离 (size+ind neutral)

- Sign (研究期望方向): `-1`
- Fwd days: `20`
- Earliest start: `2024-01-26`
- Tags: attention, retail
- Notes: Q2Q3-Q5 LS, 样本 2023-10 起

| 窗口 | n | IC | ICIR | HAC t | Status |
|---|---:|---:|---:|---:|---|
| window 504d | 89 | -0.0586 | -0.810 | -4.84 | ✅ healthy |
| window 252d | 44 | -0.0519 | -1.036 | -4.71 | ✅ healthy |

### MFD — 超大单-小单资金流背离 (反转)

- Sign (研究期望方向): `-1`
- Fwd days: `20`
- Earliest start: `2024-01-26`
- Tags: moneyflow, reversal
- Notes: IC 反向 (派发伪 smart money)

| 窗口 | n | IC | ICIR | HAC t | Status |
|---|---:|---:|---:|---:|---|
| window 504d | 90 | -0.0211 | -0.328 | -2.52 | ⚠️ degraded |
| window 252d | 44 | -0.0278 | -0.566 | -2.26 | ⚠️ degraded |

### BGFD — 券商金股共识度 (follow consensus)

- Sign (研究期望方向): `1`
- Fwd days: `20`
- Earliest start: `2024-01-26`
- Tags: analyst, sentiment
- Notes: 原 fade 假设被证伪, 反向 follow 有效

| 窗口 | n | IC | ICIR | HAC t | Status |
|---|---:|---:|---:|---:|---|
| window 504d | 90 | -0.0068 | -0.055 | -0.32 | ❌ dead |
| window 252d | 44 | +0.0042 | +0.036 | +0.17 | ❌ dead |

### LULR — 连板反转 (高位涨停 → T+5 反转)

- Sign (研究期望方向): `-1`
- Fwd days: `5`
- Earliest start: `2024-01-26`
- Tags: event, limit_up
- Notes: 小 universe (每日~100), 2024+ 有效

| 窗口 | n | IC | ICIR | HAC t | Status |
|---|---:|---:|---:|---:|---|
| window 504d | 230 | +0.0425 | +0.304 | +4.87 | ✅ healthy |
| window 252d | 116 | +0.0417 | +0.290 | +3.68 | ✅ healthy |

### THCC_inst — 前十大流通股东机构口径环比 (反向)

- Sign (研究期望方向): `-1`
- Fwd days: `20`
- Earliest start: `2024-01-26`
- Tags: ownership, institutional
- Notes: 反向: 机构加仓反而 bearish (window-dressing)

| 窗口 | n | IC | ICIR | HAC t | Status |
|---|---:|---:|---:|---:|---|
| window 504d | 90 | -0.0110 | -0.281 | -1.66 | ❌ dead |
| window 252d | 44 | -0.0093 | -0.303 | -1.41 | ❌ dead |

### SB — 机构调研 burst (7d / 91d median)

- Sign (研究期望方向): `1`
- Fwd days: `20`
- Earliest start: `2024-01-26`
- Tags: attention, event
- Notes: null effect, 短期 spike 无 alpha

| 窗口 | n | IC | ICIR | HAC t | Status |
|---|---:|---:|---:|---:|---|
| window 504d | 86 | -0.0078 | -0.174 | -1.25 | ❌ dead |
| window 252d | 40 | -0.0015 | -0.031 | -0.15 | ❌ dead |

### SRR — 停复牌反转 (log1p duration, hold 5d)

- Sign (研究期望方向): `-1`
- Fwd days: `5`
- Earliest start: `2024-01-26`
- Tags: event, suspend
- Notes: IS 2022-24 +IC, OOS 2025 -IC 符号翻转, 单独 dead

| 窗口 | n | IC | ICIR | HAC t | Status |
|---|---:|---:|---:|---:|---|
| window 504d | 45 | +0.0238 | +0.043 | +0.24 | ⚠️ degraded |
| window 252d | 44 | +0.0185 | +0.033 | +0.18 | ❌ dead |

### MCHG — 高管变动事件 (董事长/总经理/CFO/财务总监)

- Sign (研究期望方向): `-1`
- Fwd days: `20`
- Earliest start: `2024-01-26`
- Tags: event, governance
- Notes: IS 负 OOS 正 regime 翻转, 和 SRR 共同证实 2024/25 structural shift

| 窗口 | n | IC | ICIR | HAC t | Status |
|---|---:|---:|---:|---:|---|
| window 504d | 62 | -0.0020 | -0.039 | -0.18 | ❌ dead |
| window 252d | 25 | +0.0195 | +0.284 | +0.91 | ❌ dead |

## 判读建议

### 状态变化 (window 252d → window 504d)

- **SRR**: `dead` → `degraded`

### 仍 healthy 的因子 (2)

- **RIAD**: IC=-0.0586, HAC t=-4.84
- **LULR**: IC=+0.0425, HAC t=+4.87

*Generated at 2026-04-22T22:12:59*