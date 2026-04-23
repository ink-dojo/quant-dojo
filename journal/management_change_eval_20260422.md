# 因子评估: research.factors.management_change.factor.compute_factor

> 生成时间: 2026-04-22T22:07:59
> 期间: 2022-01-01 ~ 2025-12-31
> Fwd: 20d, 采样每 5d
> 中性化: size, industry
> Sign: negative (LS mode: Q1_minus_Qn)

## 分段 IC

| 分段 | n | IC mean | ICIR | HAC t | Status |
|---|---:|---:|---:|---:|---|
| FULL | 156 | -0.0057 | -0.127 | -1.04 | dead |
| IS (pre-2025) | 134 | -0.0109 | -0.256 | -2.07 | degraded |
| OOS 2025 | 22 | +0.0305 | +0.590 | +1.45 | healthy |

## 分层回测 (5 分位, 每期均值)

| 分位 | 均值 |
|---|---:|
| Q1 | +0.8570% |
| Q2 | +0.4669% |
| Q3 | +1.0972% |
| Q4 | +0.5090% |
| Q5 | +0.7380% |

LS (Q1_minus_Qn) 每期: +0.1191%, unit Sharpe: +0.067

## 原始 JSON

完整数字见 `logs/<module>_eval_YYYYMMDD.json`.