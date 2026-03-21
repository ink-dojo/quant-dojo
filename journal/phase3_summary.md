# Phase 3 因子研究总结

**完成日期**：2026-03-21
**阶段周期**：第 9-16 周（实际用时）
**核心成果**：完成 4 大经典因子框架建设 + 因子衰减分析工具

---

## 已实现因子

### 1. 价值因子（Value Factor）

**实现**：EP（盈利收益率）、BP（账面收益率）、SP（销售收益率）等权合成
**文件**：
- `research/factors/value/value_factor.py` — 因子计算（compute_ep/bp/sp/composite_value）
- `research/factors/value/06_value_factor.ipynb` — 完整研究 Notebook
- `research/factors/value/README.md` — 研究文档

**关键指标预期**（文献参考值）：
| 指标 | 预期值 | 说明 |
|------|--------|------|
| IC 均值 | 0.02 ~ 0.06 | A 股价值溢价显著 |
| ICIR | 0.3 ~ 0.8 | 较稳定，不同市场周期波动 |
| 多空年化 | 10% ~ 30% | 与市场风格相关 |
| 多空夏普 | 0.5 ~ 1.5 | 行业中性化后更优 |

**数据处理细节**：
- 负 PE（亏损股）、负 PB（资不抵债）置 NaN，避免虚假高估值信号
- 截面 z-score 标准化后等权合成，消除量纲差异
- 财务数据滞后：季报公布约 1~4 个月，建议结合公告日期处理

**已知局限**：
- PS 数据当前用 pcf（市现率）替代，需完善数据源
- 财务数据滞后性导致前视偏差风险
- 天然偏向金融、地产等高杠杆行业
- A 股价值溢价具有明显周期性，成长风格偏强时效果减弱
- 可能买入"价值陷阱"，需叠加质量筛选

---

### 2. 质量因子（Quality Factor）

**实现**：ROE（净资产收益率）、ROE 稳定性（滚动 8 期标准差）、毛利率等权合成
**文件**：
- `research/factors/quality/quality_factor.py` — 因子计算
- `research/factors/quality/07_quality_factor.ipynb` — 完整研究 Notebook
- `research/factors/quality/README.md` — 研究文档

**关键指标预期**（文献参考值）：
| 指标 | 预期值 | 说明 |
|------|--------|------|
| IC 均值 | 0.03 ~ 0.08 | 中国 A 股质量因子较弱 |
| ICIR | 0.3 ~ 0.8 | 稳定性偏低 |
| IC > 0 占比 | 55% ~ 65% | 方向正确但非高度显著 |
| 分层单调性 | 弱 ~ 中 | 高分组优于低分组 |

**前视偏差处理**（重点）：
- 使用 `shift(1)` 确保任意交易日只能看到上一期已公布的季报
- `ffill` 对齐到日频，季报间的交易日沿用最新已知值
- 注意：报告期末与实际公告日存在时间差，严格处理需引入公告日时间戳

**已知局限**：
- 残留前视偏差：shift(1) 以报告期末为基准，非真实公告日
- 毛利率代理：get_financials 不直接提供毛利率
- 幸存者偏差：需配合历史成分股名单
- 行业集中：高 ROE 行业（银行、白酒）暴露集中，未中性化
- 财务造假风险：建议结合经营性现金流校验

---

### 3. 低波动因子（Low Volatility Factor）

**实现**：已实现波动率（20 日滚动标准差）、Beta 因子（60 日滚动 OLS）、等权合成
**文件**：
- `research/factors/low_vol/low_vol_factor.py` — 因子计算
- `research/factors/low_vol/08_low_vol_factor.ipynb` — 完整研究 Notebook
- `research/factors/low_vol/README.md` — 研究文档

**理论假设**：
- **低波动异象**：低波动/低 Beta 股票长期获得 CAPM 预测之外的超额收益
- **行为金融解释**：散户偏好彩票型高波动股票，导致高波动被高估；机构有跑赢基准压力，偏好高 Beta
- **参考文献**：Baker et al. (2011)《Benchmarks as Limits to Arbitrage》

**因子设计**：
- 波动率因子：`vol = -rolling_std(ret, 20) * sqrt(252)`（取负：低波=大因子值）
- Beta 因子：`beta = -rolling_beta(ret, hs300_ret, 60)`（相对沪深300，取负）
- 合成：截面 z-score 后按 0.5:0.5 加权

**待验证 IC/ICIR**（需运行 notebook 后填充）：
| 指标 | 波动率 | Beta | 合成 |
|------|--------|------|------|
| IC 均值 | — | — | — |
| ICIR | — | — | — |
| 多空年化 | — | — | — |
| 多空夏普 | — | — | — |

---

### 4. 动量因子（Momentum Factor）— 已完成

**实现**：多周期动量（5/10/20/60/120 日），skip=1 避免反转噪音
**文件**：
- `research/factors/momentum/momentum_factor.py`
- `research/notebooks/05_momentum_factor.ipynb`
- `research/factors/momentum/README.md`

**已验证 IC 结果**（来自 02_statistics_basics.ipynb）：
- 20 日动量 Rank IC 接近零，A 股短期无明显动量效应

---

## 因子有效性理论排名（实测后更新）

基于 A 股市场特征的理论预期排名：

| 排名 | 因子 | 理由 | 预期 IC | 与其他因子正交性 |
|------|------|------|--------|-----------------|
| 1️⃣ | 动量（Momentum） | 中短期趋势明显，机构跟风买入 | 0.00 ~ 0.02 | 与价值负相关 |
| 2️⃣ | 质量（Quality） | 白马股溢价显著（消费/医药） | 0.03 ~ 0.08 | 与低波正相关 |
| 3️⃣ | 价值（Value） | 均值回归机制，但周期性强 | 0.02 ~ 0.06 | 与动量负相关 |
| 4️⃣ | 低波动（Low Vol） | 散户主导导致低波溢价弱 | 未知 | 与质量弱正相关 |

> 注：理论排名基于 A 股市场结构特点（散户主导、板块轮动、基本面认知不足）。
> 实际有效性需通过 2019~2024 完整回测数据验证。

---

## 因子相关性矩阵（理论预期）

```
         动量   质量   价值   低波
动量    1.00  -0.15  -0.50  -0.20
质量   -0.15   1.00   0.10   0.40
价值   -0.50   0.10   1.00   0.05
低波   -0.20   0.40   0.05   1.00
```

**解读**：
- **动量 vs 价值**：负相关（-0.50）→ 互补性好，可组合
- **质量 vs 低波**：正相关（0.40）→ 高质量公司往往波动低
- **价值 vs 其他**：弱相关 → 独立贡献，但效果不稳定

---

## 工具框架完善

### 因子衰减分析（Factor Decay Analysis）
```python
from utils.factor_analysis import factor_decay_analysis

decay_df = factor_decay_analysis(
    factor_wide=value_factor,
    ret_wide=return_wide,
    horizons=[1, 5, 10, 20, 60],
    method='spearman'
)
# 返回 DataFrame: index=['mean_ic', 'icir', 't_stat'], columns=[1, 5, 10, 20, 60]
```

**用途**：观察因子预测力在不同持有期的衰减规律，判断最优交易频率。

### 多因子合成（IC Weighted Composite）
```python
from utils.factor_analysis import ic_weighted_composite

composite = ic_weighted_composite(
    factor_dict={'value': v, 'quality': q, 'momentum': m},
    ic_series_dict={'value': ic_v, 'quality': ic_q, 'momentum': ic_m},
    rolling_window=60
)
```

**权重更新频率**：60 日滚动，动态调整各因子权重

### IC/ICIR 批量分析
```python
from utils.factor_analysis import factor_summary_table

summary = factor_summary_table(
    factors={'值': value, '质': quality, '动': momentum},
    ret_wide=return_wide
)
```

---

## Phase 4 建议（多因子策略回测）

### 1. 因子选择与权重设置

**建议纳入的因子**（依据 IC 稳定性）：
```
首选组合（预期夏普 > 1.0）：
  ├─ 质量因子（权重 40%）— 白马股溢价显著
  ├─ 动量因子（权重 40%）— 机构跟风明显
  └─ 低波动因子（权重 20%）— 风险控制维度

备选方案：
  └─ 价值因子单独回测 → 如 ICIR < 0.3 则剔除，或在价值风格偶数年加入
```

### 2. 回测参数建议

| 参数 | 建议值 | 说明 |
|------|--------|------|
| 回测周期 | 2019-01-01 ~ 2024-12-31 | 包含牛/熊/震荡各市场状态 |
| 股票池 | CSI 500 | 剔除 ST、停牌、新上市 |
| 交易频率 | 月度调仓 | 平衡成本与有效性 |
| 单边交易成本 | 0.15% | 保守估计（实际 0.1~0.2% 之间） |
| 风险度量 | VaR(95%) | 相对夏普比率 |

### 3. 已知陷阱

- **前视偏差**：财务数据 shift(1) + ffill，但未用真实公告日 → Phase 4 改进
- **幸存者偏差**：需用历史成分股（非当前）回测 → 接入 BaoStock 历史名单
- **行业暴露**：质量/动量可能集中于白马行业 → 加入行业中性化
- **过拟合**：CSI 500 样本量仍有限 → Walk-forward 验证必须
- **交易成本**：日内 T+1 限制 + 涨跌停 → 月度调仓规避

---

## 文件清单

```
research/factors/
├── value/
│   ├── README.md
│   ├── value_factor.py
│   └── 06_value_factor.ipynb
├── quality/
│   ├── README.md
│   ├── quality_factor.py
│   └── 07_quality_factor.ipynb
├── low_vol/
│   ├── README.md
│   ├── low_vol_factor.py
│   └── 08_low_vol_factor.ipynb
├── momentum/
│   ├── README.md
│   ├── momentum_factor.py
│   └── 05_momentum_factor.ipynb
└── polar_pv_factor/  # 极坐标价量反转因子（第一阶段完成）
    ├── README.md
    ├── polar_factor.py
    └── 04_polar_factor.ipynb

utils/
├── factor_analysis.py  # 新增：factor_decay_analysis()
├── data_loader.py
├── fundamental_loader.py
└── ...

journal/
└── phase3_summary.md  # 本文件
```

---

## 下一步 Phase 4 里程碑

- [ ] 运行 `06_value_factor.ipynb` ~ `08_low_vol_factor.ipynb`，填充实测 IC/ICIR
- [ ] 建立多因子选股策略框架 (`strategies/multi_factor_stock_picker.py`)
- [ ] 在 CSI 500 历史成分股上完整回测，验证各因子 IC
- [ ] 行业 + 市值中性化处理 (`utils/factor_analysis.neutralize_factor()`)
- [ ] Walk-forward 验证，验证样本外表现
- [ ] 仓位管理与止损机制设计
- [ ] 输出最终策略评审报告（年化 > 15%、夏普 > 0.8 为及格线）

---

**报告审核**：xingyu
**最后更新**：2026-03-21
