# 工作报告 — 2026-03-24

> 本次 session 完整记录：从项目熟悉到策略真相揭示。

---

## 一、今日完成的工作

### 1. Control Plane Convergence（已标 CONVERGED）

对照 `GOAL_control_plane_convergence.md`，执行了三轮独立 review loop，共发现并修复 **14 个 material issues**。

| 轮次 | 发现 | 典型问题 |
|------|------|----------|
| Loop 1 | 8 个 | CLI backtest run 绕过 control_surface；失败回测不持久化；list_runs limit 截断逻辑错误；_compute_metrics 返回 error dict 被当 metrics 存 |
| Loop 2 | 6 个 | metrics=None 导致 TypeError；死代码误导；backtest_service 死 guard；SSE 工具函数重复；XSS 注入 |
| Loop 3 | 2+1 | XSS 补漏（appendPipelineStep + 全局 innerHTML）；sse_utils 缺 __main__ |

**核心改动：**
- CLI `backtest run` 统一走 `control_surface.execute`
- 失败回测持久化到 run_store
- Dashboard 新增运行详情弹窗 + 对比视图
- 全局 HTML 转义防 XSS
- 所有入口共享同一 freshness 实现

**文件：** `pipeline/control_surface.py`, `pipeline/cli.py`, `pipeline/run_store.py`, `pipeline/strategy_registry.py`, `dashboard/static/index.html`, `dashboard/services/backtest_service.py`, `dashboard/services/pipeline_service.py`, `dashboard/services/sse_utils.py`, `tests/test_e2e_control_plane.py`

---

### 2. 死机原因分析

昨晚 autoloop（opus supervisor）4:33 AM 死机。

**根因：** 12 个 Python 进程（autoloop workers）× ~2GB + VM (2.7GB) + Chrome (2.1GB) + Spotify (2.1GB) 超出物理内存 → JetsamEvent OOM → WindowServer crash。

**修复：**
- `loop-runner.sh` MAX_WORKERS 从 4 降到 2
- 新建 `memory-watchdog.sh`（88% 自动杀 worker，95% 紧急 SIGKILL）
- loop-runner 启动时自动开启看门狗，结束时自动关闭
- `WORKER_MODEL` export 到子进程，`run-tasks-parallel.sh` 和 `run-tasks.sh` 优先读环境变量

---

### 3. Free Data Ingestion（Phase 5 子目标）

三轮 autoloop + 手动推进，完成了免费数据接入链路。

**交付物：**
- `providers/base.py` — 数据 provider 抽象契约
- `providers/akshare_provider.py` — AkShare 实现（带重试 + 限流保护）
- `providers/baostock_provider.py` — BaoStock 实现（会话复用，AkShare 不可用时自动降级）
- `pipeline/data_update.py` — 统一更新入口，支持 dry-run
- `pipeline/cli.py` 新增 `data status` / `data update` 命令
- `pipeline/data_checker.py` — 修复列名兼容（中英文都能读）
- `tests/test_data_checker.py` — 10 个测试
- `tests/test_data_update.py` — 6 个测试
- `scripts/batch_update.py` — 全量批更新脚本

**验证：**
- AkShare 当前不可用（东方财富连接拒绝），自动降级到 BaoStock
- BaoStock 会话复用正常，5 只连续查询无 broken pipe
- 3 只股票成功增量更新到 2026-03-24
- `data status` / `data update` / signal 主链路跑通

**遗留：**
- 全量 5477 只更新约需 2-3 小时（BaoStock 串行限制）
- AkShare 需要网络环境变化后重试

---

### 4. Autoloop 调优

| 配置项 | 之前 | 之后 | 原因 |
|--------|------|------|------|
| Supervisor model | sonnet | **opus** | 规划质量更高 |
| Worker model | (跟 supervisor) | **opus** | 执行质量 |
| MAX_WORKERS | 4 | **2** | 防 OOM |
| Task 描述长度 | 3-8 句 | **3-5 句** | 减少 supervisor 输出量 |
| Supervisor 职责 | 只规划 | **先 review 再规划** | 让 opus 发现 worker bug |
| Task 范围 | 无限制 | **每 task ≤3 文件** | 小 commit |
| 文档更新 | 混在代码 task 里 | **必须拆单独 task** | 不污染代码 commit |
| WORKER_MODEL | 没 export | **export 到子进程** | 确保实际生效 |

---

### 5. 策略真相评估（最重要的发现）

用 5289 只 A 股真实日线数据（2013-2025）跑了完整评估。**揭示了之前 notebook 合成数据的假象。**

#### 因子 IC 分析（样本内 2015-2024）

| 因子 | IC 均值 | ICIR | 结论 |
|------|---------|------|------|
| momentum_12_1 | **-0.003** | -0.02 | 无效，A 股中长期动量不存在 |
| reversal_1m | **+0.052** | 0.31 | 有效，A 股短期反转效应 |
| low_vol_20d | **+0.067** | 0.33 | 最强，低波动异象 |
| turnover_rev | **+0.065** | 0.30 | 有效，低换手溢价 |

#### 回测对比

| | v1 等权全因子 | v2 IC加权去momentum | 沪深300 |
|---|---|---|---|
| 年化收益 | -17.70% | **-0.92%** | +0.81% |
| 夏普 | -0.83 | **-0.18** | -0.05 |
| 最大回撤 | -95.17% | **-83.47%** | -46.70% |

#### 样本外 2025

| | v2 策略 | 沪深300 |
|---|---|---|
| 年化收益 | +7.25% | +22.16% |
| 夏普 | 0.39 | 1.34 |
| 最大回撤 | -10.34% | -10.49% |

#### Walk-Forward（17 窗口）

- 夏普均值: -0.75
- 收益胜率: 47%

#### 之前 notebook 显示的 vs 真实

| 指标 | notebook（合成数据） | 真实数据 |
|------|---------------------|----------|
| 年化收益 | +7.12% | **-0.92%** |
| 夏普 | 1.12 | **-0.18** |
| 最大回撤 | -5.42% | **-83.47%** |

#### -83% 回撤诊断

不是代码 bug。2018 年低波动因子选到了一批"之前很安静"的小票（000056, 300152 等），贸易战熊市暴跌 50-65%。策略缺乏市场状态过滤和止损机制，被单年 -69% 打穿。

---

## 二、Phase 5 门槛评审

| 指标 | 门槛 | v2 实际 | 通过 |
|------|------|---------|------|
| 年化收益 > 15% | 15% | -0.92% | ❌ |
| 夏普 > 0.8 | 0.8 | -0.18 | ❌ |
| 最大回撤 < 30% | 30% | 83.47% | ❌ |
| 回测跨度 > 3 年 | 3 年 | 9.6 年 | ✅ |

**结论：三项未达标，不可进入模拟盘。**

---

## 三、当前资产盘点

### 可用的
- 基础设施完整：回测引擎、因子框架、CLI、control plane、dashboard
- 数据管道就绪：5477 只本地 CSV + BaoStock 免费更新
- 三个有效因子已识别（reversal / low_vol / turnover，ICIR > 0.3）
- 完整测试覆盖（62+ 测试通过）

### 不可用的
- 策略本身：收益为负，最大回撤致命
- Momentum 因子：A 股无效，应移除
- 风控机制：不存在（无市场过滤、无止损、无行业中性）
- Paper Trading：NAV 追踪为空

---

## 四、建议后续方向

### 短期（最高优先级）：让策略从亏钱变成赚钱

1. **加市场状态过滤**
   - 用 HS300 的 60 日/120 日均线判断牛熊
   - 熊市降到半仓或空仓
   - 预期效果：避免 2018 年 -69% 的毁灭性打击

2. **加行业中性化**
   - 因子选股后按行业分组，每组选 Top N
   - 避免集中在某个暴跌行业
   - 预期效果：降低最大回撤 20-30 个百分点

3. **加个股止损**
   - 单只持仓跌超 15% 强制卖出
   - 预期效果：截断尾部风险

4. **单因子分层回测**
   - 每个因子单独跑十分位组合
   - 确认 Top 组 vs Bottom 组有显著差异
   - 这步在合成之前做，避免把噪音因子混进去

### 中期：优化因子组合

5. **尝试基本面因子**
   - EP（盈利收益率）、ROE、营收增速
   - 数据已有（`utils/fundamental_loader.py`）

6. **IC 加权优化**
   - 用滚动 IC 动态调权（而不是全样本 IC 静态权重）
   - 6 个月滚动窗口

7. **换仓频率实验**
   - 当前月频，尝试双周 / 周频
   - 反转因子可能在更短周期更有效

### 长期：模拟盘 + 实盘准备

8. 策略达标后再回到 Phase 5 infra
9. 完成 PaperTrader NAV 追踪
10. 连续 3 个月模拟盘验证

---

## 五、文件索引

| 文件 | 说明 |
|------|------|
| `scripts/strategy_eval.py` | 真实数据策略评估脚本（可重复运行） |
| `journal/strategy_eval_20260324.md` | 评估结论简版 |
| `journal/session_report_20260324.md` | 本报告（完整版） |
| `GOAL_control_plane_convergence.md` | 控制面收敛目标（已 CONVERGED） |
| `GOAL_phase5_free_data_ingestion.md` | 数据接入目标（基本完成） |
| `providers/baostock_provider.py` | BaoStock 数据源（当前可用） |
| `scripts/batch_update.py` | 全量数据更新脚本 |

---

## 六、今日 Git 提交记录

```
7dc5c3d research: 真实数据策略评估 — 揭示合成数据假象 + 因子诊断
0dba026 fix: BaoStockProvider 改为实例级会话复用
bb6020d feat: 添加 BaoStockProvider + AkShare 不可用时自动降级
6cd2fa6 test: 补齐 phase 2 缺失的 4 个测试
1ef15fd fix: 修复 autoloop 产出的两个 critical bug + 补充集成测试
0577ee8 docs: 更新 W13 周报
a41b3cf fix: 控制面收敛 — 三轮 review loop 修复 14 个 material issues
```
