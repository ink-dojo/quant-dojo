# v33 = reversal_skip1m tradeable L/S — 预注册单次实验 — 20260417

> 预注册: Q5-Q1 日频等权, borrow 8%, txn/side 0.150%
> eval 2022-01-04~2025-12-31 n=969
> DSR n_trials=10, sharpe_std=0.481

## 1. gross vs net 对比

| 策略               |   n |   ann_return |   sharpe |     mdd |    vol |   psr_0 |   psr_0.5 |   win_rate |
|:-------------------|----:|-------------:|---------:|--------:|-------:|--------:|----------:|-----------:|
| gross LS (学术)    | 969 |       0.2094 |   1.0333 | -0.1474 | 0.1804 |  0.9874 |    0.8963 |     0.5150 |
| net LS (tradeable) | 969 |       0.0260 |   0.1214 | -0.2000 | 0.1804 |  0.6756 |    0.2998 |     0.4809 |

- 总摩擦年化: 18.34% (融券 8.00% + txn 估 10.34%)
- 长腿日均换手 11.97%, 短腿 10.39%

## 2. Admission 判定

- gross LS: {'ann_pass': True, 'sharpe_pass': True, 'mdd_pass': True, 'psr0_pass': True, 'all_pass': True}
- **net LS (tradeable)**: {'ann_pass': False, 'sharpe_pass': False, 'mdd_pass': True, 'psr0_pass': False, 'all_pass': False}

## 3. net LS 统计推断

- Bootstrap 95% CI: [-0.754, 0.888]
- CI 下界 > 0.80: FAIL
- DSR (n_trials=10, std=0.481): **0.1519**
- DSR > 0.95: FAIL
- MinTRL vs sr=0.5: inf 日 (inf 年)
- MinTRL vs sr=0.8: inf 日 (inf 年)

## 4. 分年诊断

|      year |        n |   gross_sr |   net_sr |   net_ann |   net_mdd |
|----------:|---------:|-----------:|---------:|----------:|----------:|
| 2022.0000 | 242.0000 |     1.3198 |   0.3519 |    0.0676 |   -0.1601 |
| 2023.0000 | 242.0000 |     0.5420 |  -0.6047 |   -0.0733 |   -0.1626 |
| 2024.0000 | 242.0000 |     1.4790 |   0.7938 |    0.1983 |   -0.1558 |
| 2025.0000 | 243.0000 |     0.5891 |  -0.4794 |   -0.0650 |   -0.1470 |

## 5. 诚实结论

- gross sharpe: 1.033, net sharpe: 0.121
- 摩擦扣除幅度: 0.912 sharpe 点
- admission 四门 (net): FAIL
- DSR (net, n_trials=10): FAIL
- CI 下界 > 0.80 (net): FAIL

**net admission 未过**: 融券成本 + txn 把表面强 sharpe 击穿。
含义: 之前报告的 'LS sharpe=1.497' 是学术 gross 值, 实操需要附注。
合规: 停止反转因子方向, 不重试调参数。

## 6. 严禁 (红线)

- 不换因子 (reversal_1m, reversal_5d, etc.)
- 不换 quintile (10/20 分位)
- 不调 borrow / txn / long-short 口径
- 不加 regime/overlay
- 失败就写结论, 不 ad-hoc
