# RX 因子健康度周报 — 2026-04-22

> 覆盖 Issue #33/#35/#36 轨道的 6 个差异化因子, 按窗口对比 IC/ICIR 稳定性.
> 门槛: |IC|>0.03 ✅ healthy | |IC|∈[0.02,0.03] 且 |HAC t|≥2 ⚠️ degraded | 其余 ❌ dead

## 因子健康度对比

| 因子 | Display | window 252d IC | window 252d HAC t | window 252d 状态 | window 120d IC | window 120d HAC t | window 120d 状态 |
|---|---|---|---|---|---|---|---|
| RIAD | 散户-机构关注度背离 (size+ind neutral) | -0.0519 | -4.71 | ✅ healthy | -0.0448 | -2.73 | ✅ healthy |
| MFD | 超大单-小单资金流背离 (反转) | -0.0278 | -2.26 | ⚠️ degraded | -0.0023 | -0.30 | ❌ dead |
| BGFD | 券商金股共识度 (follow consensus) | +0.0042 | +0.17 | ❌ dead | +0.0111 | +0.31 | ❌ dead |
| LULR | 连板反转 (高位涨停 → T+5 反转) | +0.0417 | +3.68 | ✅ healthy | +0.0392 | +2.21 | ✅ healthy |
| THCC_inst | 前十大流通股东机构口径环比 (反向) | -0.0093 | -1.41 | ❌ dead | -0.0134 | -1.73 | ❌ dead |
| SB | 机构调研 burst (7d / 91d median) | -0.0015 | -0.15 | ❌ dead | +0.0067 | +0.51 | ❌ dead |

## 各因子详情

### RIAD — 散户-机构关注度背离 (size+ind neutral)

- Sign (研究期望方向): `-1`
- Fwd days: `20`
- Earliest start: `2025-01-13`
- Tags: attention, retail
- Notes: Q2Q3-Q5 LS, 样本 2023-10 起

| 窗口 | n | IC | ICIR | HAC t | Status |
|---|---:|---:|---:|---:|---|
| window 252d | 44 | -0.0519 | -1.036 | -4.71 | ✅ healthy |
| window 120d | 19 | -0.0448 | -0.867 | -2.73 | ✅ healthy |

### MFD — 超大单-小单资金流背离 (反转)

- Sign (研究期望方向): `-1`
- Fwd days: `20`
- Earliest start: `2025-01-13`
- Tags: moneyflow, reversal
- Notes: IC 反向 (派发伪 smart money)

| 窗口 | n | IC | ICIR | HAC t | Status |
|---|---:|---:|---:|---:|---|
| window 252d | 44 | -0.0278 | -0.566 | -2.26 | ⚠️ degraded |
| window 120d | 19 | -0.0023 | -0.086 | -0.30 | ❌ dead |

### BGFD — 券商金股共识度 (follow consensus)

- Sign (研究期望方向): `1`
- Fwd days: `20`
- Earliest start: `2025-01-13`
- Tags: analyst, sentiment
- Notes: 原 fade 假设被证伪, 反向 follow 有效

| 窗口 | n | IC | ICIR | HAC t | Status |
|---|---:|---:|---:|---:|---|
| window 252d | 44 | +0.0042 | +0.036 | +0.17 | ❌ dead |
| window 120d | 19 | +0.0111 | +0.087 | +0.31 | ❌ dead |

### LULR — 连板反转 (高位涨停 → T+5 反转)

- Sign (研究期望方向): `-1`
- Fwd days: `5`
- Earliest start: `2025-01-13`
- Tags: event, limit_up
- Notes: 小 universe (每日~100), 2024+ 有效

| 窗口 | n | IC | ICIR | HAC t | Status |
|---|---:|---:|---:|---:|---|
| window 252d | 116 | +0.0417 | +0.290 | +3.68 | ✅ healthy |
| window 120d | 55 | +0.0392 | +0.274 | +2.21 | ✅ healthy |

### THCC_inst — 前十大流通股东机构口径环比 (反向)

- Sign (研究期望方向): `-1`
- Fwd days: `20`
- Earliest start: `2025-01-13`
- Tags: ownership, institutional
- Notes: 反向: 机构加仓反而 bearish (window-dressing)

| 窗口 | n | IC | ICIR | HAC t | Status |
|---|---:|---:|---:|---:|---|
| window 252d | 44 | -0.0093 | -0.303 | -1.41 | ❌ dead |
| window 120d | 19 | -0.0134 | -0.530 | -1.73 | ❌ dead |

### SB — 机构调研 burst (7d / 91d median)

- Sign (研究期望方向): `1`
- Fwd days: `20`
- Earliest start: `2025-01-13`
- Tags: attention, event
- Notes: null effect, 短期 spike 无 alpha

| 窗口 | n | IC | ICIR | HAC t | Status |
|---|---:|---:|---:|---:|---|
| window 252d | 40 | -0.0015 | -0.031 | -0.15 | ❌ dead |
| window 120d | 13 | +0.0067 | +0.096 | +0.51 | ❌ dead |

## 判读建议

### 状态变化 (window 120d → window 252d)

- **MFD**: `dead` → `degraded`

### 仍 healthy 的因子 (2)

- **RIAD**: IC=-0.0519, HAC t=-4.71
- **LULR**: IC=+0.0417, HAC t=+3.68

*Generated at 2026-04-22T17:52:52*