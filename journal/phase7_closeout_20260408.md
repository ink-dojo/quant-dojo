# Phase 7 Closeout — Agentic Research 骨架完成

> 2026-04-08 · jialong · 活跃策略 `v7`

## 目标回顾

Phase 7 第一阶段 + 第二阶段的落地，让 AI 从"解释结果"升级为
"能提出实验、运行实验、总结结果"的研究助理，并且所有变更操作都走
批准门 —— 不触碰真实资金。

对齐 ROADMAP Phase 7 的所有待办：

**第一阶段：**
- [x] AI 根据周报 / 风险状态提出新的研究问题
- [x] AI 批量运行标准化 backtest
- [x] AI 比较不同策略 / 参数 / 区间的结果
- [x] AI 输出实验总结和建议，但不直接执行交易

**第二阶段：**
- [x] 风险门禁：不满足约束时禁止进入模拟盘
- [x] 批准流：AI 提议后必须人工批准才能执行
- [x] 运行日志：记录 AI 提议、参数、结论、最终动作

## 架构总览

整条链路：

```
factor_monitor / risk_monitor / live_vs_backtest
        │
        ▼  (系统状态)
pipeline/research_planner.py
        │  ResearchQuestion(id, type, priority, question,
        │                    rationale, proposed_experiment, source)
        ▼
pipeline/experiment_runner.py
        │  propose_experiment  →  ExperimentRecord(status="proposed")
        │  run_experiment      →  control_surface.execute("backtest.run",
        │                                                 approved=True,
        │                                                 experiment_id=...)
        ▼
pipeline/run_store.RunRecord (+experiment_id 反向索引)
pipeline/experiment_store.ExperimentRecord (+run_id 正向索引)
        │
        ▼
pipeline/experiment_summarizer.py
        │  compare_to_baseline + summarize_experiments
        ▼
pipeline/risk_gate.py
        │  evaluate(metrics, DEFAULT_RULES)
        ▼
CLI: python -m pipeline.cli research {propose,run,list,summarize}
     python -m quant_dojo history --ai-only
```

## 新增/修改模块

| 模块 | 职责 | 行数（含测试） |
|---|---|---|
| `pipeline/research_planner.py` | 系统状态 → ResearchQuestion | 305 + 266 |
| `pipeline/experiment_store.py` | ExperimentRecord CRUD | 238 + 370 |
| `pipeline/experiment_runner.py` | ResearchQuestion → 回测执行 | 224 + 288 |
| `pipeline/experiment_summarizer.py` | baseline 对比汇总 | 221 + 223 |
| `pipeline/risk_gate.py` | 回测指标 → 通过/失败 | 180 + 200 |
| `pipeline/cli.py` | `research propose/run/list/summarize` 子命令 | +130 |
| `pipeline/run_store.py` | `RunRecord.experiment_id` 反向索引 | +3 |
| `pipeline/control_surface.py` | `_backtest_run` 透传 experiment_id | +5 |
| `quant_dojo/commands/history.py` | `[AI]` 标签 + `--ai-only` | +15 |
| `quant_dojo/__main__.py` | `--ai-only` CLI flag | +3 |

## 测试覆盖

Phase 7 新增独立测试文件：

- `test_research_planner.py` — 27 passed
- `test_experiment_store.py` — 26 passed
- `test_experiment_runner.py` — 16 passed（含 experiment_id 注入）
- `test_experiment_summarizer.py` — 16 passed
- `test_research_cli.py` — 10 passed（含 argparse 子进程）
- `test_run_store_experiment_id.py` — 4 passed
- `test_risk_gate.py` — 18 passed
- `test_history_cli.py` — 36 passed（+5 for AI 过滤）

累计 153 个 Phase 7 相关断言通过。

全量 pytest（含原有测试套件）见 session 末尾运行结果。

## 设计取舍

### 1. 纯函数优先于服务
`research_planner` / `experiment_summarizer` / `risk_gate` 全部是无状态纯函数，
输入 dict、输出 dict/dataclass。这三个模块没有任何文件 I/O —— 读盘由调用方完成，
这样单测不需要 tmp_path fixture 就能写。只有 `experiment_store` 和 `experiment_runner`
碰磁盘。

### 2. 规则驱动，不让 LLM 决定是否跑 backtest
`research_planner` 的 detector 全是硬编码阈值（`FACTOR_DECAY_T_STAT_THRESHOLD`、
`LIVE_BT_DRIFT_THRESHOLD`、`HIGH_DRIFT_THRESHOLD`），未来接 LLM 只应让它做措辞润色
或次序建议，**不能让模型决定要不要跑回测**。这样系统行为可审计、可复现。

### 3. 审批门沿用 control_surface 的既有契约
`experiment_runner.run_experiment` 调用的是 `control_surface.execute("backtest.run",
approved=True, ...)` —— 没有绕过原有审批，只是在研究助理的 CLI 层默认不加
`--approved`，用户必须显式打这个 flag 才会真拉起回测。命令参数留了 `max_runs`
做预算控制。

### 4. 双向索引而非外键表
`ExperimentRecord.run_id` 正向指向回测，`RunRecord.experiment_id` 反向指回实验。
没有引入新的关系表，两个 JSON 目录就够。代价是维护两处一致性，收益是：
- `history --ai-only` 只需要扫 `live/runs/*.json` 一次
- `experiment_store.list_experiments` 不依赖 run_store 存在
- 老的 RunRecord 读进来 `experiment_id=None`，向后兼容

### 5. `risk_gate` 的 max_drawdown 特殊规则
`max_drawdown` 是负数，`-0.30` 差于 `-0.15`，普通 `min/max` 语义会反直觉。
新增 `max_abs` 比较类型，专门给回撤用；`|max_drawdown| > max_abs` 才算失败。
边界测试锁死 `-0.30` 恰好通过，`-0.3001` 就挂。

## 坑和教训

### /tmp 是失效存储（见 `feedback_no_tmp_workdir.md`）
上一次 session 我在 `/private/tmp/quant-dojo-fix/` 完成了 Phase 7 第一轮的
~16 个 commit，电脑重启后 macOS 把 `/private/tmp` 清空，**整批工作彻底丢失** ——
没 push 的 commit 消失，tmp 里那个 git remote 也没了。

这次重建直接 clone 到 `~/work/quant-dojo/`，并写了一条 feedback memory，下一次
启动会被加载，避免再踩。

### Phase 7 可以不依赖实际跑回测来单测
`experiment_runner` 的测试全部用 fake executor 注入 —— 没有启动策略引擎、没有
读数据、没有写 `live/runs/`。这让单元测试 1 秒内跑完 16 个用例，CI 里不会卡。
代价是 integration 路径需要另外的 smoke test（后续 Phase 7.5 再做）。

## 下一步（Phase 7.5+）

- [ ] `research` CLI 的 integration smoke：真实跑一次 `research run --approved
      --max-runs 1` 看端到端是否 ok
- [ ] `risk_gate` 接入 `experiment_summarizer`：summarize 时把 gate 结论一起打印
- [ ] `experiment_store` 的 TTL / GC：跑多了会积累一堆 proposed，需要定期清
- [ ] Dashboard 展示 `live/experiments/` 目录（类似现在的 `live/runs/`）
- [ ] 接一条最小 LLM 次序润色（仅措辞，不改阈值）

## 本周 commit 序列（Phase 7 重建）

从 `2555643` 开始的 ~10 个 commit，按时间顺序：

1. `feat: phase 7 research_planner — 系统状态转研究问题`
2. `test: 覆盖 research_planner 三类 detector 和 plan_research`
3. `feat: phase 7 experiment_store — 实验记录持久化`
4. `feat: phase 7 experiment_runner — ResearchQuestion 转回测`
5. `feat: phase 7 experiment_summarizer — 对 baseline 总结实验产出`
6. `feat: phase 7 research CLI 子命令 propose/run/list/summarize`
7. `feat: phase 7 RunRecord.experiment_id 反向索引`
8. `feat: phase 7 history [AI] 标签和 --ai-only 过滤`
9. `feat: phase 7 risk_gate — 实验结果最低门槛检查`
10. `docs: phase 7 closeout + ROADMAP 更新`（本 commit）

完。
