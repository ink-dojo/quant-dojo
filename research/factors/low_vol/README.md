# 低波动因子研究

**作者**：jialong
**日期**：2026-03
**状态**：已实现 ✅ | 待跑完整回测

---

## 核心思路

低波动异象（Low Volatility Anomaly）：低波动率/低Beta的股票往往获得超出CAPM预测的超额收益，与传统"高风险高回报"认知相反。

- **波动率因子**：`vol = -rolling_std(ret, 20) * sqrt(252)`（取负：低波动=大因子值）
- **Beta 因子**：`beta = -rolling_beta(ret, market_ret, 60)`（取负：低Beta=大因子值）
- **合成因子**：截面 z-score 后按 0.5:0.5 加权

---

## 研究假设

**假设**：A 股市场存在"低波动溢价"，低波动率/低Beta股票长期跑赢高波动股票。

**经济学解释**：
- **行为金融**：散户偏好彩票型股票（高波动），导致高波动股票被高估
- **委托代理**：机构投资者有跑赢基准的考核压力，偏好高Beta股票，导致低Beta被低估
- **波动率约束**：杠杆受限的投资者偏好高Beta股票，造成定价偏差（Black 1972）

---

## 检验结果

（运行 `08_low_vol_factor.ipynb` 填充）

| 指标 | 波动率因子 | Beta 因子 | 合成因子 |
|------|-----------|----------|---------|
| IC 均值 | - | - | - |
| ICIR | - | - | - |
| 多空年化 | - | - | - |
| 多空夏普 | - | - | - |

---

## 文件说明

| 文件 | 说明 |
|------|------|
| `low_vol_factor.py` | 因子计算模块（波动率/Beta/合成） |
| `08_low_vol_factor.ipynb` | 完整研究 Notebook（IC分析/分层回测） |
| `README.md` | 本文件 |

---

## 使用方法

```python
from research.factors.low_vol.low_vol_factor import (
    compute_realized_vol,
    compute_beta,
    compute_composite_low_vol,
)

# 计算波动率因子
vol_factor = compute_realized_vol(ret_wide, window=20)

# 计算 Beta 因子（需要沪深300收益率）
beta_factor = compute_beta(ret_wide, hs300_ret, window=60)

# 合成低波动因子
composite = compute_composite_low_vol(vol_factor, beta_factor, weights=(0.5, 0.5))
```

---

## 参考文献

- Baker, Bradley, Wurgler (2011). "Benchmarks as Limits to Arbitrage"
- Frazzini, Pedersen (2014). "Betting Against Beta"
- 国内研究：华泰证券《低波动因子在A股的适用性研究》
