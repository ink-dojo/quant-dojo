# Regime Boundary 分析报告
_2026-04-23 · Issue #37 · `scripts/regime_boundary_analysis.py`_

---

## 运行参数

```
--start 2023-10-01 --end 2025-12-31
factors: RIAD, MFD, LULR, SRR, MCHG
```

产出文件:
- `logs/regime_boundary/factor_panel.parquet` (27 月 × 15 列)
- `logs/regime_boundary/macro_panel.parquet` (27 月 × 4 列)
- `logs/regime_boundary/lag_corr.json`
- `logs/regime_boundary/breakpoint.json`
- `logs/regime_boundary/regime_boundary.png`

---

## 核心数字速查

| 维度 | 数值 | 解读 |
|---|---|---|
| `first_negative_month` | 2023-10 | 跨因子聚合健康指数首次转负 |
| `first_sustained_negative_month` | 2023-12 | 算法检测的"持续负"起始月 |
| `peak_value` | +0.066 (2024-01) | 聚合 IC 最高峰 |
| `trough_value` | -0.081 (2023-10) | 聚合 IC 最低谷 |
| `peak_to_trough_delta` | 0.147 | 从峰到谷的绝对变化 |
| 最强 macro 滞后相关 | hs300_ret_6m, lag=3, r=-0.34 | 弱联动 |

---

## 因子月度 Effective IC 摘要

> effective_ic = raw_ic × factor_sign，使 + = 因子方向正确工作

| Factor | 2024 年均 IC | 2025 年均 IC | 趋势 |
|---|---|---|---|
| **RIAD** | +0.064 | +0.044 | 仍正，轻微下行 |
| **MFD** | +0.021 | +0.023 | 持平 |
| **LULR** | -0.042 | -0.051 | 持续负，结构性弱 |
| **SRR** | NaN (稀疏) | -0.075 (仅 4 月) | 新加因子，样本少 |
| **MCHG** | +0.016 (稀疏) | -0.022 (稀疏) | 样本不足 |

LULR 是唯一明确持续负的因子 (2024 年每月均负)。RIAD、MFD 在 2024-2025 维持正 IC。

---

## 聚合健康指数时序 (agg_ic)

```
2023-10: -0.081 ← 最低谷
2023-11: +0.006
2023-12: +0.018
2024-01: +0.066 ← 峰值
2024-02: -0.025
2024-03: +0.047
2024-04: +0.012
2024-05: +0.020
2024-06: +0.016
2024-07: +0.015
2024-08: +0.028
2024-09: -0.012  (9/24 政策反转发生)
2024-10: -0.016
2024-11: -0.018
2024-12: +0.035
2025-01: +0.046
2025-02: +0.007
2025-03: -0.065 ← 第二谷 (SRR 2025-03 = -0.302 拉低)
2025-04: +0.020
2025-05: -0.017
2025-06: +0.038
2025-07: -0.016
2025-08: +0.005
2025-09: +0.009
2025-10: -0.005
2025-11: +0.003
2025-12: -0.015
```

**主要观察**:
1. 9/24 政策反转 (2024-09) 后，聚合 IC 有 3 个月轻微负值 (-0.012 ~ -0.018)，但幅度小
2. 2025-03 出现次谷 (-0.065)，由 SRR = -0.302 主导，但 SRR 数据极稀疏 (n=3)
3. 整体维持在 ±0.05 的振荡区间，无明显单向下行趋势

---

## 宏观特征与因子健康的关系

### 滞后互相关

| 特征 | 最强 lag | Pearson r | 解读 |
|---|---|---|---|
| hs300_ret_6m | lag=3 | -0.34 | 6M 回报高 → 3 月后因子 IC 偏低 |
| hs300_ret_3m | lag=-3 | +0.30 | 弱反向领先 |
| hs300_vol_60d | lag=2 | +0.18 | 无显著关联 |
| hs300_vol_ratio | lag=2 | +0.27 | 无显著关联 |

所有相关系数 < 0.4，属于**弱联动**。无法通过单一宏观指标可靠预测因子 IC 变化。

### 9/24 事件期间的宏观特征

| 月份 | hs300_ret_6m | hs300_vol_ratio | agg_ic |
|---|---|---|---|
| 2024-09 | +0.136 | 1.485 | -0.012 |
| 2024-10 | +0.080 | 1.667 | -0.016 |
| 2024-11 | +0.094 | 1.689 | -0.018 |
| 2024-12 | +0.137 | 1.172 | +0.035 |

**注**: vol_ratio 在 9/24 后飙升至历史高位 (1.69)，但因子 IC 仅轻微负值，非崩溃型。

---

## Scenario 判读 (对应 regime_decision_tree_20260422.md)

按优先级逐项检查：

### Step 1: RIAD 单因子 6 月 IC 检查 (Scenario C 触发条件)

RIAD 2025 下半年月度 effective IC：
- Jul: +0.052, Aug: +0.050, Sep: +0.045, Oct: -0.027, Nov: +0.058, Dec: +0.082
- 6 个月中仅 1 月 < -0.02 → **NOT Scenario C**

### Step 2: 聚合健康指数特征

- 不连续负值，反复振荡 → 非"持续负"
- `first_sustained_negative_month` = 2023-12，但实际 IC 在 2023-12 即为正值
- 不满足 "2024-08 ~ 2024-11 突变" → **NOT Scenario A**

### Step 3: Macro 联动强度

- 最强相关 r = 0.34 (弱联动，< 0.5 的 Scenario A 门槛) → **NOT Scenario A**

### Step 4: 各因子时间分布

- LULR: 2024 全年每月均负（结构性差）
- RIAD: 2024-2025 基本正向
- MFD: 持平
- SRR/MCHG: 数据稀疏，各自时间不同步

各因子负向时间不同步，跨度远 > 6 月 → **Scenario D (因子分散时间表型)**

---

## 判读结论：Scenario D

**"不是 regime shift，是 LULR 一只因子的结构性弱化，RIAD 仍然有效。"**

- LULR 连续负 IC 已超 18 个月（2024-01 起），建议触发 `degraded warn` 状态
- RIAD + MFD 仍正常工作，spec v4 的主要 alpha 来源未受威胁
- 不需要加全局 regime gate（Scenario A 路径），不需要参数重估（B 路径）
- 建议按 Scenario D 行动：给 `rx_factor_monitor` 加 per-factor sunset 逻辑

---

## REGIME_THRESHOLDS 填写结果

```python
REGIME_THRESHOLDS = {
    "vol_ratio_threshold": 1.40,   # 9/24 事件 vol_ratio 最高 1.69，取 1.40 作 tail-risk 门槛
    "ret_6m_threshold": -0.10,     # 2023-10 型深度熊市 (-11.3%)
    "primary_feature": "hs300_vol_ratio",
    # 注: AND 条件在 27 个月观察期内从未同时触发
    # gate 设为纯 tail-risk 防护，Scenario D 下不参与日常调仓决策
}
```

**重要**: 在 27 个月观察期内，`vol_ratio > 1.40 AND ret_6m < -0.10` 从未同时满足：
- 2024-10/11 期间: vol_ratio 1.67，但 ret_6m = +0.08（正值，不触发）
- 2023-10 期间: ret_6m = -0.113（很负），但 vol_ratio = 0.88（不触发）

这意味着该 gate 设计针对"经典危机"场景（高波动 + 深度熊市并行），
而非 A 股常见的"大涨导致因子失效"场景。

如果未来实盘发现"post-rally 因子失效"是常态问题，可考虑：
- 把 AND 改为 OR
- 或加独立的 `high_rally_regime` gate（vol_ratio > 1.40 OR ret_6m > 0.25）

---

## 建议下一步行动

1. **不开新 regime gate issue**（Scenario D 不需要）
2. **Issue: rx_factor_monitor 加 auto-sunset 逻辑** (Scenario D 明确要求)
   - LULR: 已满足 6 月 IC < -0.02 的 `degraded warn` 条件
   - 设置 12 月持续负 → 强制从 registry 移除的 sunset 逻辑
3. **Issue #39 (Tier 1.2 Capacity)**: 与 regime 分析结论独立，今日继续实现
