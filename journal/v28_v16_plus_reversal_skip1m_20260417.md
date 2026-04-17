# v28 = v16 + reversal_skip1m — 预注册单次实验 — 20260417

> 数据: v16 底层 + reversal_skip1m 新因子, eval 2022-01-04~2025-12-31 n=969
> 预注册: IC 加权, 30 只, 行业中性, reversal_skip1m 方向=+1
> DSR n_trials=7

## 1. Metrics 对比

| 策略                      |   n |   ann_return |   sharpe |     mdd |    vol |   psr_0 |   psr_0.5 |   win_rate |
|:--------------------------|----:|-------------:|---------:|--------:|-------:|--------:|----------:|-----------:|
| v16 baseline              | 969 |       0.1855 |   0.6763 | -0.4145 | 0.2804 |  0.9266 |    0.6846 |     0.5614 |
| v28 (v16+reversal_skip1m) | 969 |       0.1868 |   0.6682 | -0.4327 | 0.2891 |  0.9243 |    0.6779 |     0.5521 |

## 2. Admission 判定

- v16 baseline: {'ann_pass': True, 'sharpe_pass': False, 'mdd_pass': False, 'psr0_pass': False, 'all_pass': False}
- **v28**: {'ann_pass': True, 'sharpe_pass': False, 'mdd_pass': False, 'psr0_pass': False, 'all_pass': False}

## 3. v28 统计推断

- Bootstrap 95% CI: [-0.387, 1.772]
- CI 下界 > 0.80: ❌
- DSR (n_trials=7, std=0.156): **0.8449**
- DSR > 0.95: ❌
- MinTRL vs sr=0.5: 12275 日 (48.7 年)
- MinTRL vs sr=0.8: inf 日 (inf 年)

## 4. 分年 v28 vs v16

|      year |        n |   v16_sr |   v28_sr |   v28_ann |   v28_mdd |
|----------:|---------:|---------:|---------:|----------:|----------:|
| 2022.0000 | 242.0000 |  -0.6381 |  -0.2912 |   -0.0836 |   -0.3175 |
| 2023.0000 | 242.0000 |   0.7142 |   0.6227 |    0.1344 |   -0.1841 |
| 2024.0000 | 242.0000 |   0.7867 |   0.6689 |    0.2327 |   -0.3919 |
| 2025.0000 | 243.0000 |   1.9182 |   1.7595 |    0.5464 |   -0.1888 |

## 5. 诚实结论

- admission 四门: ❌
- DSR: ❌
- 95% CI 下界 > 0.80: ❌

**admission 未过**: reversal_skip1m 没能救活 v16。
可能原因: (a) long-only 顶 30 采样不如 long-short 分组, (b) 因子加 IC 权重后被稀释。
合规下一步: 不重试加减因子, 转多策略集成 (v16 + 完全独立策略族)。

## 6. 严禁 (红线)

- 不换 direction 重试; 不换 reversal 窗口 (5/20/40)
- 不删 v16 原有因子做 '优化' (事后剪枝)
- 不用 equal weight / LASSO / IR optimal 等其他权重方案重试
- 若失败, 回到更根本的层面: 多策略集成, asset class 扩展
