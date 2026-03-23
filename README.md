# quant-dojo 量化道场

> 总工作计划入口：[`WORKPLAN.md`](./WORKPLAN.md)

## 量化工作台（Dashboard）

```bash
# 启动量化工作台
cd quant-dojo
source venv/bin/activate
python -m dashboard.app
# 自动打开 http://localhost:8888
```

- 默认地址：`http://localhost:8888`
- 首次启动会自动打开浏览器
- 若 AI 不可用，需要启动 Ollama 或配置 `claude -p`

---

> 目标：**真正盈利**。

jialong x xingyu x lexi。

---

## 愿景

| 阶段 | 目标 | 标志 |
|------|------|------|
| 入门 | 理解量化逻辑，跑通第一个策略 | 第一次完整回测 |
| 进阶 | 多因子选股 + 系统化回测框架 | 夏普比率 > 1 的稳定策略 |
| 实战 | 模拟盘验证，控制风险 | 模拟盘连续3个月正收益 |
| 盈利 | 真实资金，严格风控 | 实盘稳定运行 |

---

## 仓库结构

```
quant-dojo/
├── ROADMAP.md           # 学习路线 + 开发计划
├── WORKFLOW.md          # 工作流规范
├── config/              # 配置文件模板（不提交真实密钥）
├── data/                # 数据目录（本地存储，不入库）
│   ├── raw/             # 原始数据
│   └── processed/       # 清洗后数据
├── research/            # 研究笔记本
│   ├── notebooks/       # Jupyter notebooks
│   └── factors/         # 因子研究
├── strategies/          # 策略实现
│   ├── base.py          # 基类
│   └── examples/        # 示例策略
├── backtest/            # 回测引擎
├── utils/               # 工具函数
│   ├── data_loader.py   # 数据加载
│   ├── metrics.py       # 绩效指标
│   └── plotting.py      # 可视化
├── live/                # 实盘接口（后期）
└── journal/             # 研究日志 + 复盘
```

---

## 快速开始

```bash
# 1. 克隆仓库
git clone https://github.com/Waaangjl/quant-dojo.git
cd quant-dojo

# 2. 创建虚拟环境
python -m venv venv
source venv/bin/activate   # Windows: venv\Scripts\activate

# 3. 安装依赖
pip install -r requirements.txt

# 4. 配置
cp config/config.example.yaml config/config.yaml
# 编辑 config.yaml，填入你的数据源 API Key

# 5. 跑第一个示例
jupyter notebook research/notebooks/01_getting_started.ipynb
```

---

## 分工

| 人 | 强项 | 主要负责 |
|----|------|---------|
| jialong | 金融逻辑 | 策略思路、因子设计、风控规则 |
| xingyu | 代码实现 | 框架搭建、数据管道、回测引擎 |

两人共同：研究复盘、策略评审、实盘决策

---

## 核心原则

1. **先存活，再盈利** — 风险管理优先于收益追求
2. **逻辑先行** — 每个策略必须有经济逻辑，不做纯数据挖掘
3. **样本外验证** — 所有策略必须通过 walk-forward 测试
4. **记录一切** — journal 里记录每个决策和复盘
5. **简单优先** — 简单策略 + 严格执行 > 复杂策略 + 随意执行
