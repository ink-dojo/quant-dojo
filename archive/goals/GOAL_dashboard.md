# GOAL — quant-dojo 量化工作台 Web Dashboard

> 给 `/autoloop` 的目标文件。当前日期：2026-03-22

---

## 任务定义

为现有量化研究/交易基础设施补一个**本地单机 Web 仪表盘**，把分散的持仓、信号、因子、风险和 AI 分析统一到一个页面中，支持日常查看与手动触发任务。

这是一个**本地工具台**，不是正式对外产品。优先级顺序如下：

1. 先把现有数据和能力稳定展示出来
2. 再补手动触发与流式进度
3. 最后补 UI 细节和体验优化

---

## 背景与边界

- 现有基础设施已存在：`pipeline/`、`live/`、`agents/`
- 数据路径固定：`/Users/karan/Desktop/20260320/`
- 启动方式固定：`python -m dashboard.app`
- 访问地址固定：`http://localhost:8888`
- 使用场景是**本机单用户**，不做登录、权限、数据库、云部署

---

## 成功标准

完成后，用户应当能够在一个页面中完成以下事情，而不需要手动翻文件夹或运行多段脚本：

1. 看见当前持仓、NAV 曲线、最新选股、因子健康和风险状态
2. 明确知道当前数据日期，以及数据是否过时
3. 输入股票代码，触发 AI 分析或多空辩论，并看到流式进度
4. 手动触发一次信号生成，并看到执行进度和结果状态
5. 在数据缺失、LLM 不可用或部分模块失败时，页面仍可正常打开，接口不会崩溃

---

## 非目标

以下内容不属于本次任务范围，避免边做边扩：

- 不做账号体系、多用户、权限控制
- 不做数据库迁移或持久化改造
- 不做前后端分离工程，不引入 npm / node / webpack
- 不做复杂任务调度系统，只提供手动触发入口
- 不重构既有核心回测/因子引擎

---

## 现有模块与文件（直接复用，不要重新实现）

### 可直接调用的 Python 模块

```python
# 持仓管理
from live.paper_trader import PaperTrader
pt = PaperTrader()
positions = pt.get_current_positions()   # 返回 DataFrame
perf = pt.get_performance()              # 返回 dict

# 风险监控
from live.risk_monitor import check_risk_alerts, format_risk_report
alerts = check_risk_alerts(pt, price_data={})

# 每日信号生成
from pipeline.daily_signal import run_daily_pipeline
result = run_daily_pipeline(date="2026-03-20")

# 因子健康度
from pipeline.factor_monitor import factor_health_report
health = factor_health_report()

# 数据新鲜度
from pipeline.data_checker import check_data_freshness
status = check_data_freshness()

# AI 辩论
from agents.debate import BullBearDebate
from agents.base import LLMClient
llm = LLMClient()
debate = BullBearDebate(llm)
result = debate.analyze(topic="600519", context="...")
# 返回: {bull_args, bear_args, conclusion, confidence}

# 单只股票分析
from agents.stock_analyst import StockAnalyst
analyst = StockAnalyst(llm)
result = analyst.analyze(symbol="600519", start="2023-01-01", end="2026-03-20")

# 本地数据加载
from utils.local_data_loader import load_price_wide, load_factor_wide, get_all_symbols
```

### 现有文件路径（services 层直接读这些）

```
live/portfolio/nav.csv          # NAV 历史，列: date, nav（nav=0 说明从未调仓）
live/portfolio/positions.json   # 当前持仓（可能不存在，需容错）
live/portfolio/trades.json      # 历史交易记录
live/signals/{date}.json        # 每日信号，格式见下
live/factor_snapshot/{date}.parquet  # 因子截面快照
```

### 信号文件格式（`live/signals/2026-03-20.json`）

```json
{
  "date": "2026-03-20",
  "picks": ["600015", "601997", "601169", ...],
  "scores": {"600015": 0.85, ...},
  "factor_values": {
    "momentum_20": {"600015": 0.12, ...},
    "ep": {"600015": 0.08, ...},
    "low_vol": {"600015": -0.3, ...},
    "turnover": {"600015": 0.5, ...}
  },
  "excluded": {"st": 0, "new_listing": 8, "low_price": 15}
}
```

---

## 交付物

### 目录结构

```text
quant-dojo/
└── dashboard/
    ├── __init__.py
    ├── app.py
    ├── services/
    │   ├── data_loader.py       # 读 live/ 文件，统一容错
    │   ├── portfolio_service.py
    │   ├── signals_service.py
    │   ├── factors_service.py
    │   ├── risk_service.py
    │   ├── ai_service.py
    │   └── pipeline_service.py
    ├── routers/
    │   ├── portfolio.py
    │   ├── signals.py
    │   ├── factors.py
    │   ├── risk.py
    │   ├── data_status.py
    │   ├── ai.py
    │   └── pipeline.py
    └── static/
        └── index.html
```

说明：

- `routers/` 只负责 HTTP 层，不直接写数据拼装逻辑
- `services/` 负责读取本地文件、容错、统一输出格式
- 前端保持**单文件**

---

## 实现原则

### 1. 本地优先

- 默认所有功能都围绕本机目录和本机服务
- 不依赖外部数据库
- 不增加额外运维复杂度

### 2. 容错优先

- 任何单个数据源缺失，都不应导致整个页面报错
- 任何 AI/LLM 调用失败，都必须返回可读错误
- 所有接口都返回结构化 JSON

### 3. 先稳定再漂亮

- 先实现稳定的数据读取和接口契约
- 再实现单页布局和交互
- 最后再补自动刷新、进度显示和视觉优化

### 4. 代码规范（项目要求）

- 注释用**中文**，变量名/函数名用**英文 snake_case**
- 每个函数必须有中文 docstring（说明参数和返回值）
- 每个新文件末尾加 `if __name__ == "__main__":` 做最小验证
- **禁止** commit message 里加任何 AI 署名（Co-Authored-By 等）

---

## 后端目标

### 主程序 `dashboard/app.py`

要求：

- 使用 FastAPI
- 提供静态页面入口 `/`
- 注册所有 API 路由
- 启动后自动打开浏览器
- 端口固定为 `8888`

推荐启动代码：

```python
if __name__ == "__main__":
    import threading
    import webbrowser
    import uvicorn

    threading.Timer(1.0, lambda: webbrowser.open("http://localhost:8888")).start()
    uvicorn.run(app, host="0.0.0.0", port=8888)
```

---

## API 契约

所有接口默认返回 JSON。

统一错误格式：

```json
{
  "error": "human readable message",
  "detail": "optional detail"
}
```

统一约定：

- 数据缺失时返回空列表、空对象或带默认值的对象
- 不因文件不存在直接抛 500 栈追踪到前端
- 尽量在返回中附带 `as_of_date`，方便前端展示

### Portfolio

```text
GET /api/portfolio
GET /api/portfolio/nav
```

- `/api/portfolio` 返回当前持仓、总市值、收益、夏普、回撤等摘要
  - 调用 `PaperTrader().get_current_positions()` 和 `get_performance()`
- `/api/portfolio/nav` 返回 NAV 历史，读 `live/portfolio/nav.csv`，并附沪深300对比数据

建议返回结构：

```json
{
  "as_of_date": "2026-03-20",
  "summary": {
    "nav": 1032000,
    "return_pct": 0.032,
    "sharpe": 1.24,
    "max_drawdown": -0.041
  },
  "positions": []
}
```

### Signals

```text
GET /api/signals/latest
GET /api/signals/history
```

- `/api/signals/latest` 读 `live/signals/` 最新日期的 JSON，返回 picks + scores + excluded 统计
- `/api/signals/history` 返回最近 10 期信号日期列表及每期持仓数

### Factors

```text
GET /api/factors/health
GET /api/factors/snapshot
```

- `/api/factors/health` 调用 `factor_health_report()`，状态值统一为 `healthy` / `warning` / `failed`
- `/api/factors/snapshot` 读最新 `live/factor_snapshot/{date}.parquet`，返回各因子截面均值/分位数

### Risk

```text
GET /api/risk/alerts
```

- 调用 `check_risk_alerts()`，无预警时返回空列表，不要返回报错文本

### Data Status

```text
GET /api/data/status
```

- 调用 `check_data_freshness()`，返回最新数据日期和是否过时

建议返回结构：

```json
{
  "as_of_date": "2026-03-20",
  "is_stale": false,
  "checks": {
    "portfolio": "ok",
    "signals": "ok",
    "factors": "ok",
    "risk": "ok"
  }
}
```

### AI

```text
POST /api/ai/debate
POST /api/ai/analyze
```

- `/api/ai/debate` 调用 `BullBearDebate(LLMClient()).analyze()`，用 StreamingResponse 流式返回
- `/api/ai/analyze` 调用 `StockAnalyst(LLMClient()).analyze()`

LLM 不可用时返回：

```json
{
  "error": "LLM 后端不可用，请启动 Ollama 或配置 claude -p"
}
```

### Pipeline

```text
POST /api/pipeline/run
```

- 调用 `run_daily_pipeline(date=...)`，用 StreamingResponse 流式返回进度

---

## 流式输出约束

统一实现原则：

- 后端用 `StreamingResponse` 返回 `text/event-stream`
- 前端**不要使用 `EventSource`**（只支持 GET）
- 前端统一使用 `fetch` + `ReadableStream` 手动解析 SSE chunk

适用接口：

- `POST /api/ai/debate`
- `POST /api/ai/analyze`
- `POST /api/pipeline/run`

建议流式事件格式：

```text
data: {"stage":"start","content":"任务开始"}
data: {"stage":"bull","content":"正在分析多方论据"}
data: {"stage":"bear","content":"正在分析空方论据"}
data: {"stage":"moderator","content":"正在综合结论"}
data: {"stage":"done","result":{...}}
```

要求：

- 每个阶段都要能在前端落地显示
- 失败时发送 `stage=error`
- 最后一条必须是 `stage=done` 或 `stage=error`

---

## 前端目标

### 文件

`dashboard/static/index.html`

### 技术约束

- 单文件
- 不使用 npm / webpack / node
- 用 CDN 引入 Tailwind CSS 和 Chart.js
- 数据请求使用原生 `fetch`

### 页面布局

```
┌─────────────────────────────────────────────────────────┐
│  🎯 quant-dojo 量化工作台          数据: 2026-03-20 ✅   │
├──────────────┬──────────────┬──────────────┬────────────┤
│  📊 持仓概览  │  🎯 今日选股  │  🔬 因子健康  │ ⚠️ 风险预警 │
│  NAV: 103.2万│  前5名：      │ 动量: 健康✅  │ 无预警 ✅   │
│  收益: +3.2% │  600519 茅台  │ EP:  健康✅  │            │
│  夏普: 1.24  │  000858 五粮液│ 低波: 衰减⚠️ │            │
│  回撤: -4.1% │  ...         │ 换手: 健康✅  │            │
├──────────────┴──────────────┴──────────────┴────────────┤
│  📈 NAV 曲线 vs 沪深300（Chart.js，支持 1M/3M/6M/全部）  │
├─────────────────────────────────────────────────────────┤
│  🤖 AI 分析                                              │
│  股票代码: [600519    ] [分析] [辩论]                     │
│  🐂 多方：...   🐻 空方：...   ⚖️ 结论：置信度 0.62       │
├─────────────────────────────────────────────────────────┤
│  ⚙️  手动触发今日选股  [运行]  进度: ████░░ 60%           │
└─────────────────────────────────────────────────────────┘
```

### 页面行为

- 页面加载后自动拉取全部数据
- 每 5 分钟自动刷新一次，不强制整页刷新
- 右上角显示数据日期与新鲜度状态（绿色✅ / 红色❌）
- 数据为空时显示"暂无数据"
- 某个模块失败时，只在该模块区域显示错误，不影响其他模块

### 图表区

NAV 图支持：

- 展示 NAV vs 沪深300（沪深300取 `000300`，用 akshare 或本地数据）
- 悬停查看数值
- 时间范围切换：`1个月`、`3个月`、`6个月`、`全部`

---

## 实施顺序

### Phase 1. 搭骨架

- 创建 `dashboard/` 目录和 FastAPI 入口
- 接好静态首页路由
- 搭建 `routers/` 和 `services/` 基础结构

完成标志：`python -m dashboard.app` 启动，浏览器能打开空壳页面

### Phase 2. 打通数据接口

- 完成 portfolio / signals / factors / risk / data status 只读接口
- `services/data_loader.py` 读 `live/` 目录下的 CSV 和 JSON

完成标志：所有只读接口返回 200，无数据时返回合理默认值

### Phase 3. 完成前端展示

- 4 个面板 + NAV 图表渲染
- 首次加载 + 5 分钟自动刷新
- loading / empty / error 三态

完成标志：首页可用于日常查看

### Phase 4. 接 AI 与手动触发

- `/api/ai/debate` + `/api/ai/analyze` 流式接口
- `/api/pipeline/run` 流式进度
- 前端 fetch stream parser

完成标志：AI 对话有可见进度，LLM 不可用时不崩溃

### Phase 5. 收尾

- 更新 `requirements.txt`（新增 `fastapi>=0.110.0`, `uvicorn>=0.27.0`）
- 更新 `README.md` 顶部加快速启动
- 清理硬编码和重复逻辑

---

## 硬性约束

1. 前端必须保持单文件，不引入 npm / node / webpack
2. 数据路径固定为 `/Users/karan/Desktop/20260320/`
3. 没有数据时不报错，各接口必须返回可消费默认值
4. LLM 不可用时必须优雅失败，不得让服务崩溃
5. 不要修改 `backtest/engine.py` 的既有签名
6. 不要修改 `polar_pv_factor/` 目录
7. commit message **禁止** AI 署名（`Co-Authored-By: Claude` 等）
8. 注释用中文，变量名用英文 snake_case，每个函数有中文 docstring

---

## 风险点与预案

### 风险 1. 数据格式不统一

预案：把文件读取与字段映射集中放进 `services/data_loader.py`，不要把路径解析和列名判断散落在各 router 中

### 风险 2. LLM 响应慢或不可用

预案：AI 接口始终返回明确错误信息；前端展示 loading 和 error，不做无限等待

### 风险 3. 流式实现不一致

预案：明确采用 `POST + StreamingResponse + fetch stream parser`，不写成 `EventSource`

### 风险 4. 页面被单个模块拖垮

预案：各模块独立请求、独立渲染、独立报错，不做"一个接口失败导致整页白屏"的耦合实现

### 风险 5. NAV 数据为空（从未调仓）

预案：`live/portfolio/nav.csv` 可能只有表头没有数据行，`/api/portfolio/nav` 返回空数组，图表显示"暂无历史数据"

---

## 验收标准

```bash
# 1. 安装依赖
pip install fastapi uvicorn

# 2. 启动服务
python -m dashboard.app &
sleep 3

# 3. 首页可访问
curl -s http://localhost:8888/ | grep -q "quant-dojo" && echo "✅ 前端 OK"

# 4. 只读接口返回 200 且是合法 JSON
curl -s http://localhost:8888/api/portfolio | python3 -m json.tool
curl -s http://localhost:8888/api/portfolio/nav | python3 -m json.tool
curl -s http://localhost:8888/api/signals/latest | python3 -m json.tool
curl -s http://localhost:8888/api/signals/history | python3 -m json.tool
curl -s http://localhost:8888/api/factors/health | python3 -m json.tool
curl -s http://localhost:8888/api/factors/snapshot | python3 -m json.tool
curl -s http://localhost:8888/api/risk/alerts | python3 -m json.tool
curl -s http://localhost:8888/api/data/status | python3 -m json.tool

# 5. AI 接口在正常或失败场景下都不崩溃
curl -s -X POST http://localhost:8888/api/ai/debate \
  -H "Content-Type: application/json" \
  -d '{"symbol":"600519","context":"测试"}' | python3 -m json.tool

curl -s -X POST http://localhost:8888/api/ai/analyze \
  -H "Content-Type: application/json" \
  -d '{"symbol":"600519"}' | python3 -m json.tool

# 6. 模块可导入
python -c "from dashboard.app import app; print('✅ dashboard OK')"
```

补充验收要求：

1. 首页打开后 5 秒内展示基础框架和数据状态
2. 数据缺失时页面显示"暂无数据"，而不是 traceback
3. 某个模块失败时，其余模块仍可正常使用
4. 手动触发 pipeline 时前端有可见进度反馈
5. AI 路由在 LLM 缺失时返回可读错误信息

---

## README 更新要求

在 `README.md` 顶部补充：

```bash
# 启动量化工作台
cd quant-dojo
source venv/bin/activate
python -m dashboard.app
# 自动打开 http://localhost:8888
```

说明：
- 默认地址：`http://localhost:8888`
- 首次启动会自动打开浏览器
- 若 AI 不可用，需要启动 Ollama 或配置 `claude -p`
