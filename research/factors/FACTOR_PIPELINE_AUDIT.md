# 因子构建流程审计报告

**日期**：2026-04-14  
**范围**：`research/factors/` 下四个因子模块 + `utils/factor_analysis.py` + `utils/multi_factor.py`

---

## 总结

去极值和行业中性化的**工具函数已存在**，问题不是缺功能，而是**流程没有强制衔接**：
因子模块内部做了 z-score，但跳过了 winsorize；notebook 里拿到因子后直接做 IC 分析，没有经过 `neutralize_factor()`。

---

## 已有的能力（不是"missing"）

| 工具 | 位置 | 说明 |
|------|------|------|
| `winsorize()` | `utils/factor_analysis.py:17` | ±3σ 截尾，单截面 Series 输入 |
| `neutralize_factor()` | `utils/factor_analysis.py:223` | 去极值 + 行业哑变量 + 对数市值 OLS，完整流程 |
| `neutralize_factor_by_industry()` | `utils/factor_analysis.py:293` | 仅行业组内去均值，轻量版 |
| 行业中性化验证 | `research/notebooks/10_industry_neutral.ipynb` | 已验证中性化前后 ICIR 对比框架 |

---

## 真实问题：流程衔接断裂

### 问题一：因子模块内部 z-score 未先做 winsorize

四个因子模块（`value_factor.py`, `momentum_factor.py`, `quality_factor.py`, `low_vol_factor.py`）
在合成因子时都调用了自己内部的 `cross_zscore()`，但没有在此之前调用 `winsorize()`。

**具体位置**：

- `value_factor.py:78` — `cross_zscore(ep)` 直接作用于原始 EP 值
- `quality_factor.py:138` — `_cross_section_zscore()` 同样没有 winsorize

**影响**：一个极端估值的股票（如 PE=0.1 或 PE=500）会把整个截面的 z-score 拉偏，使大量股票都落在负侧。

**正确流程**：
```python
# 当前（有问题）
ep_z = cross_zscore(ep)

# 应该是
ep_winsorized = ep.apply(lambda row: winsorize(row.dropna()), axis=1)  # 截面逐日
ep_z = cross_zscore(ep_winsorized)
```

---

### 问题二：notebook 拿到合成因子后直接做 IC，未经 neutralize_factor()

`06_value_factor.ipynb` 的流程：

```
compute_composite_value() → IC 分析 → 分层回测
```

notebook 结论里自己也写了：
> "行业偏差：价值因子易暴露于金融、地产等高杠杆行业，需行业中性化后使用"

但实际上并没有调用 `neutralize_factor()`，中性化步骤停留在文字说明层面。

`10_industry_neutral.ipynb` 演示了中性化流程，但使用的是**合成行业分组**（按股票代码范围分桶），不是真实申万行业分类。

---

### 问题三：`winsorize()` 的方法不够鲁棒

`utils/factor_analysis.py:17` 的实现：

```python
mean = series.mean()
std = series.std()
series.clip(lower=mean - n_sigma * std, upper=mean + n_sigma * std)
```

用均值和标准差做截尾，但均值和标准差本身就受极端值影响——这是一个循环依赖。
更鲁棒的方法是 MAD（中位数绝对偏差）：

```python
median = series.median()
mad = (series - median).abs().median()
series.clip(lower=median - n * mad, upper=median + n * mad)
```

---

### 问题四：quality_factor 的前视偏差处理是近似的

`quality_factor.py:49` 对季报数据做了 `shift(1)`（往前移一个报告期），但：
- A股 Q1 报告（3月31日）的实际公告截止日是 4月30日
- `shift(1)` 在报告期频率上移动的是上一季度，而非实际公告延迟

代码注释里已经说明这是已知近似。严格处理需要用公告日（`announcement_date`）替换报告期末作为 index。

---

### 次要问题：compute_beta 的性能

`low_vol_factor.py:62` 使用双层 Python 循环计算滚动 Beta，
对全市场 5000 只股票会非常慢。目前规模（沪深300）可以接受，扩展时需要向量化。

---

## 优先级建议

| 优先级 | 问题 | 影响 |
|--------|------|------|
| P0 | 因子模块内的 cross_zscore 前加 winsorize | 直接影响因子截面分布质量 |
| P1 | 各因子 notebook 加上 neutralize_factor() 调用 | 真实 IC 被行业效应污染 |
| P1 | 接入真实申万行业分类替换合成分组 | 10_industry_neutral 结论目前不可信 |
| P2 | winsorize() 改为 MAD 方法 | 更鲁棒，现有方法在极端市场仍有问题 |
| P3 | quality_factor 的公告日处理 | 已知近似，影响较小 |
| P3 | compute_beta 向量化 | 仅影响速度，不影响结果正确性 |

---

## 建议的标准因子流程

```python
# Step 1：计算原始因子（各 factor 模块负责）
raw_factor = compute_xxx_factor(...)

# Step 2：去极值 + 行业/市值中性化（统一在此处理）
from utils.factor_analysis import neutralize_factor
neutral_factor = neutralize_factor(raw_factor, df_info, n_sigma=3.0)

# Step 3：IC 分析 / 分层回测（用中性化后的因子）
ic = compute_ic_series(neutral_factor, fwd_ret)
```

各因子模块内部的 z-score 合成逻辑可以保留（合成多个子因子时有用），
但应在**输出到外部之前**先做 winsorize，以保证截面分布的鲁棒性。
