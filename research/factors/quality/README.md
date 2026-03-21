# 质量因子研究

## 因子逻辑

综合质量因子由三个维度等权合成：

| 子因子 | 含义 | 数据来源 |
|--------|------|----------|
| ROE | 净资产收益率（季报） | `fundamental_loader.get_financials` |
| ROE 稳定性 | 滚动8期 ROE 负标准差（越稳定越大） | 由 ROE 宽表计算 |
| 毛利率 | 毛利率 / net_margin 退后 | `fundamental_loader.get_financials` |

合成方式：各维度截面 z-score → 等权求均值 → 再截面 z-score。

### 前视偏差处理（重点）

财报公布存在约 1~4 个月的滞后（年报最长，通常次年 4 月底才完整公布）。
若直接以报告期末作为数据可用时间，将导致严重前视偏差。

本模块的处理方式：

```python
# 1. shift(1)：只用上一期已公布的季报数据
s = df["roe"].shift(1)

# 2. ffill：对齐到日频，季报之间的交易日沿用最新已知值
wide = wide.reindex(date_range).ffill()
```

| 方法 | 风险等级 | 说明 |
|------|----------|------|
| 直接使用报告期末 | 🔴 高 | 引入 1~4 个月前视偏差 |
| shift(1) + ffill（本方案） | 🟡 中 | 仍以报告期末为基准，非真实公告日 |
| 实际公告日时间戳（推荐）| 🟢 低 | 需额外获取 akshare 公告日数据 |

## API

```python
from research.factors.quality.quality_factor import (
    compute_roe_factor,       # {symbol: df} → date × symbol ROE 宽表
    compute_roe_stability,    # roe_wide, window=8 → 稳定性宽表
    compute_gross_margin,     # {symbol: df} → date × symbol 毛利率宽表
    compute_composite_quality # roe, stability, gm → 综合质量因子
)
```

## 预期表现（待真实数据验证）

| 指标 | 参考范围 | 备注 |
|------|----------|------|
| IC 均值 | 0.03 ~ 0.08 | 质量因子在 A 股较弱 |
| ICIR | 0.3 ~ 0.8 | 稳定性偏低 |
| IC > 0 占比 | 55% ~ 65% | 方向正确但不显著 |
| 分层单调性 | 弱 ~ 中 | 高分组优于低分组 |

> 注：以上为文献参考范围，实际结果以 `07_quality_factor.ipynb` 中真实数据回测为准。

## 局限性

1. **残留前视偏差**：shift(1) 以报告期末为基准，与真实公告日存在误差
2. **毛利率代理**：`get_financials` 不直接提供毛利率，用 `net_margin` 替代
3. **幸存者偏差**：需配合历史成分股名单使用
4. **行业集中**：未中性化可能导致因子暴露集中在某些高 ROE 行业（如银行、白酒）
5. **财务造假风险**：A 股存在盈余管理，建议结合经营性现金流校验

## 文件说明

| 文件 | 说明 |
|------|------|
| `quality_factor.py` | 核心实现，所有函数含中文 docstring |
| `07_quality_factor.ipynb` | 研究 notebook（mock 数据演示 + IC/分层回测） |
| `README.md` | 本文档 |
