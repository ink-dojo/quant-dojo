# 价值因子（EP / BP / SP 合成）

**作者**：jialong / xingyu
**日期**：2026-03
**状态**：框架完成 ✅ | 待真实数据回测

---

## 核心思路

基于经典价值投资理论：被市场低估的股票（相对于其基本面）长期具有超额收益。

本模块构建三个互补的价值维度，截面 z-score 标准化后等权合成：

| 子因子 | 公式 | 经济含义 |
|--------|------|---------|
| **EP** | 1 / PE_TTM | 盈利收益率，捕捉盈利相对股价的低估 |
| **BP** | 1 / PB | 净资产收益率，捕捉账面价值相对股价的低估 |
| **SP** | 1 / PS | 销售收益率，捕捉收入相对股价的低估（受利润率影响小） |

**数据处理**：
- PE ≤ 0（亏损股）置 NaN，避免负 PE 产生虚假高 EP
- PB ≤ 0（资不抵债）置 NaN
- 各维度独立截面 z-score，消除量纲差异后等权合成

---

## 预期 IC / ICIR 数据区间

基于学术文献和 A 股历史经验：

| 指标 | 预期区间 | 说明 |
|------|---------|------|
| IC 均值 | 0.02 ~ 0.06 | A 股价值溢价显著，但近年有所减弱 |
| ICIR | 0.3 ~ 0.8 | 价值因子在不同市场环境下较稳定 |
| 多空年化 | 10% ~ 30% | 牛市期间可能跑输，熊市中表现更好 |
| 多空夏普 | 0.5 ~ 1.5 | 行业中性化后夏普会明显提升 |

---

## 回测结论

[待填入实际回测结果]

---

## 与动量因子正交性

理论上价值（低估值）与动量（近期强势）存在负相关，是经典的"价值-动量"悖论。

预期截面 Spearman 相关系数：-0.1 ~ 0.1（基本正交，可互补合成多因子模型）

[待填入实际回测结果]

---

## 局限性

1. **PS 数据**：`fundamental_loader.get_pe_pb` 当前返回 `pcf`（市现率）而非 `ps`（市销率），使用时需注意字段映射或额外接入市销率数据
2. **财务数据滞后**：PE/PB 估值指标背后的财务数据为季度披露，存在最多 90 天的信息滞后，实盘使用需考虑公告日期
3. **行业暴露**：价值因子天然偏向金融、地产等高杠杆行业，建议结合行业中性化使用
4. **市场周期**：A 股价值溢价具有明显的周期性，成长风格偏强时因子效果减弱
5. **股票质量**：纯低估值策略可能买入"价值陷阱"（基本面持续恶化的低估股），需叠加质量筛选

---

## 文件说明

```
value/
├── README.md               # 本文件
├── value_factor.py         # 因子计算函数（compute_ep / compute_bp / compute_sp / compute_composite_value）
└── 06_value_factor.ipynb   # 完整研究 Notebook（含 mock 数据演示 + 真实数据接入指引）
```

---

## 可复用代码

因子计算直接调用本模块：

```python
from research.factors.value.value_factor import (
    compute_ep, compute_bp, compute_sp, compute_composite_value
)

ep = compute_ep(pe_wide)        # PE 宽表 → EP 因子
bp = compute_bp(pb_wide)        # PB 宽表 → BP 因子
sp = compute_sp(ps_wide)        # PS 宽表 → SP 因子
value = compute_composite_value(ep, bp, sp)  # 合成价值因子
```

IC 分析和分层回测复用 `utils/factor_analysis.py`：

```python
from utils.factor_analysis import compute_ic_series, quintile_backtest
ic_series = compute_ic_series(value, fwd_ret, method='spearman')
layer_ret = quintile_backtest(value, daily_ret, n_groups=10)
```

---

## 下一步

- [ ] 接入真实 PE/PB/PS 数据，完成 2019~2024 完整回测
- [ ] 行业市值中性化后重新评估 IC
- [ ] 与极坐标价量因子、动量因子组合，构建多因子模型
- [ ] 探索 EP/BP/SP 的最优权重（IC 加权 vs 等权）
