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
