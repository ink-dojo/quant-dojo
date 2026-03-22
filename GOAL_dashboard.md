# GOAL — quant-dojo 量化工作台 Web Dashboard

> 给 /autoloop 的目标文件。当前日期：2026-03-22

---

## 背景

现有基础设施已完整（pipeline/ + live/ + agents/），但使用分散。
目标：做一个本地 Web 仪表盘，把所有内容统一到一个页面，内置 AI 对话。

**数据路径：** `/Users/karan/Desktop/20260320/`
**启动方式：** `python -m dashboard.app` → 打开 `http://localhost:8888`

---

## 理想终态

### 目录结构

```
quant-dojo/
└── dashboard/
    ├── __init__.py
    ├── app.py          # FastAPI 主程序
    ├── routers/
    │   ├── portfolio.py   # 持仓相关 API
    │   ├── signals.py     # 信号相关 API
    │   ├── factors.py     # 因子相关 API
    │   ├── risk.py        # 风险相关 API
    │   └── ai.py          # AI Agent API
    └── static/
        └── index.html     # 单文件前端（不需要 npm/node）
```

---

### 1. FastAPI 后端 `dashboard/app.py`

```python
"""
量化工作台后端
运行：python -m dashboard.app
访问：http://localhost:8888
"""
```

启动时自动打开浏览器（`webbrowser.open`）。

**API 路由：**

```
GET  /api/portfolio          → 当前持仓明细
GET  /api/portfolio/nav      → NAV 历史曲线数据（用于图表）
GET  /api/signals/latest     → 最新一期选股名单（30只）
GET  /api/signals/history    → 最近10期信号记录
GET  /api/factors/health     → 各因子健康状态
GET  /api/factors/snapshot   → 最新因子值截面
GET  /api/risk/alerts        → 当前风险预警列表
GET  /api/data/status        → 数据新鲜度（最新日期、是否过时）
POST /api/ai/debate          → 运行 BullBearDebate
     body: {"symbol": "600000", "context": "..."}
     返回: {bull_args, bear_args, conclusion, confidence}
POST /api/ai/analyze         → 运行 StockAnalyst（单只股票综合分析）
     body: {"symbol": "600000"}
     返回: {price_summary, factor_exposure, fundamental, debate}
POST /api/pipeline/run       → 手动触发每日信号生成
     body: {"date": "2026-03-20"}
     返回: SSE 流式进度（用 StreamingResponse）
```

所有 API 返回 JSON，错误时返回 `{"error": "...", "detail": "..."}` 不崩溃。

---

### 2. 前端 `dashboard/static/index.html`

**单文件，不需要 npm/webpack/node。** 用 CDN 引入：
- **Chart.js** — NAV 曲线、因子热力图
- **Tailwind CSS CDN** — 样式
- **原生 fetch** — API 调用

**页面布局（4个面板 + AI对话）：**

```
┌─────────────────────────────────────────────────────────┐
│  🎯 quant-dojo 量化工作台          数据: 2026-03-20 ✅   │
├──────────────┬──────────────┬──────────────┬────────────┤
│  📊 持仓概览  │  🎯 今日选股  │  🔬 因子健康  │ ⚠️ 风险预警 │
│              │              │              │            │
│  NAV: 103.2万│  前5名：      │ 动量: 健康✅  │ 无预警 ✅   │
│  收益: +3.2% │  600519 茅台  │ EP:  健康✅  │            │
│  夏普: 1.24  │  000858 五粮液│ 低波: 衰减⚠️ │            │
│  回撤: -4.1% │  ...         │ 换手: 健康✅  │            │
├──────────────┴──────────────┴──────────────┴────────────┤
│  📈 NAV 曲线 vs 沪深300（Chart.js 折线图，可切换时间范围） │
│  [1个月] [3个月] [6个月] [全部]                          │
├─────────────────────────────────────────────────────────┤
│  🤖 AI 分析                                              │
│  股票代码: [600519    ] [分析] [辩论]                     │
│  ┌───────────────────────────────────────────────────┐  │
│  │ 🐂 多方：贵州茅台高端白酒护城河深厚...              │  │
│  │ 🐻 空方：估值偏高，PE 30x 高于历史均值...           │  │
│  │ ⚖️ 结论：中性偏多，置信度 0.62                      │  │
│  └───────────────────────────────────────────────────┘  │
│  [手动触发今日选股]                                       │
└─────────────────────────────────────────────────────────┘
```

**交互细节：**
- 页面加载时自动刷新所有数据
- 右上角显示数据日期 + 新鲜度状态（绿色✅/红色❌）
- NAV 曲线：对比线为沪深300，鼠标悬停显示具体数值
- 因子健康：颜色编码（绿=健康，黄=衰减，红=失效）
- AI 分析框：输入股票代码 → 点击"辩论" → 流式显示结果（SSE）
- "手动触发今日选股"按钮 → POST /api/pipeline/run → 进度条显示

**自动刷新：** 每5分钟自动重新拉取数据（不刷新页面）

---

### 3. AI 对话流式输出 `dashboard/routers/ai.py`

BullBearDebate 调用 LLMClient（`claude -p` 或 Ollama），可能需要30-60秒。
用 SSE（Server-Sent Events）流式返回进度：

```
data: {"stage": "bull", "content": "正在分析多方论据..."}
data: {"stage": "bear", "content": "正在分析空方论据..."}
data: {"stage": "moderator", "content": "正在综合结论..."}
data: {"stage": "done", "result": {...}}
```

前端用 `EventSource` 接收，实时显示进度。

---

### 4. 启动脚本 `dashboard/app.py` 末尾

```python
if __name__ == "__main__":
    import webbrowser, uvicorn, threading
    threading.Timer(1.0, lambda: webbrowser.open("http://localhost:8888")).start()
    uvicorn.run(app, host="0.0.0.0", port=8888)
```

---

### 5. 依赖更新 `requirements.txt`

新增：
```
fastapi>=0.110.0
uvicorn>=0.27.0
```

（其余已有：numpy, pandas, matplotlib, akshare, pyarrow）

---

### 6. 更新 README.md

在顶部加快速启动：

```bash
# 启动量化工作台
cd quant-dojo
source venv/bin/activate
python -m dashboard.app
# 自动打开 http://localhost:8888
```

---

## 硬性约束

1. **前端单文件**，不引入 npm/node/webpack，CDN 即可
2. **数据路径固定**：`/Users/karan/Desktop/20260320/`
3. **没有数据时不报错**：各 API 在数据缺失时返回空列表/默认值，页面显示"暂无数据"
4. **LLM 不可用时**：AI 路由返回 `{"error": "LLM 后端不可用，请启动 Ollama 或配置 claude -p"}` 而不是崩溃
5. **禁止动的文件**：`backtest/engine.py` 签名、`polar_pv_factor/` 目录
6. **commit message 禁止 AI 署名**

---

## 完成验证标准

```bash
# 1. 依赖可安装
pip install fastapi uvicorn

# 2. 后端启动
python -m dashboard.app &
sleep 3

# 3. 所有 API 返回 200
curl -s http://localhost:8888/api/portfolio | python3 -m json.tool
curl -s http://localhost:8888/api/signals/latest | python3 -m json.tool
curl -s http://localhost:8888/api/factors/health | python3 -m json.tool
curl -s http://localhost:8888/api/risk/alerts | python3 -m json.tool
curl -s http://localhost:8888/api/data/status | python3 -m json.tool

# 4. 前端可访问
curl -s http://localhost:8888/ | grep -q "quant-dojo" && echo "✅ 前端 OK"

# 5. AI 路由响应（LLM 不可用时也不崩溃）
curl -s -X POST http://localhost:8888/api/ai/debate \
  -H "Content-Type: application/json" \
  -d '{"symbol":"600519","context":"测试"}' | python3 -m json.tool
```
