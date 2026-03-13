# 研究目录

---

## 结构

```
research/
├── notebooks/          # Jupyter 研究笔记本
│   ├── 01_getting_started.ipynb   # 入门：拉数据、画图、基本分析
│   ├── 02_returns_analysis.ipynb  # 收益率统计特征
│   └── ...
└── factors/            # 因子研究
    ├── momentum.ipynb
    ├── value.ipynb
    └── ...
```

---

## Notebook 命名规范

```
YYYYMMDD_描述_作者首字母.ipynb
示例：20260315_momentum_factor_IC_analysis_jl.ipynb
```

---

## 研究笔记本必须包含

1. **标题和目的** — 这个研究要回答什么问题
2. **数据说明** — 使用了什么数据，时间范围，股票池
3. **方法** — 如何构建信号/因子
4. **结果** — 数据和图表
5. **结论** — 能否用于策略，为什么
6. **局限性** — 这个研究的不足之处

---

## 已有研究

### factors/polar_pv_factor
**极坐标价量融合反转因子** — jialong，2026-02

将价量状态变化映射到极坐标系（马氏距离 + arctan2），构建反转因子。
- 数据：全A股1000只，2019-2023（5年）
- 结果：中性化后多空夏普 **3.41**，年化 **78%**
- 状态：✅ 回测完成，待模拟验证
- 详见：[factors/polar_pv_factor/README.md](factors/polar_pv_factor/README.md)
