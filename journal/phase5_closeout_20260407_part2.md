# Phase 5 收尾后续 — 2026-04-07（part 2）

> 同一天的第二段自主工作 session 延续 `phase5_closeout_20260407.md`，
> 把 Phase 5 从 95% → 100% 并推进 Phase 6 Control Plane 最后一项。

## 收尾背景

第一段 session 留下两类未完成小事：

1. **live/runs/ 垃圾回收**：前一天调试留下 23 个 `status=failed` 且
   metrics 全空的 run JSON，污染 `history` / `status` 的列表。
2. **Phase 6 dashboard 操作页**：后端没有 rebalance / weekly report
   的 HTTP 触发入口，用户只能回到 CLI。

## 本次 session 产出

### 1. `quant_dojo history --purge-failed`

新增 `_purge_failed_backtest_runs()` helper。删除条件：`status==failed`
且 `metrics.total_return` 为空/零。保留任何带实际 metrics 的失败记录
（比如风控提前终止但已经跑出了部分数据）。

- 实测扫走本地 23 个空壳 failed run，live/runs/ 从 24 个 JSON 降到 1 个
- `--dry-run` 预演模式
- `run_history(purge_failed=True)` 走同一条路径，给 status 命令重用留口子

### 2. CLI 控制面链路集成测试

新文件 `tests/test_cli_chain_integration.py`。锁住：
```
history --json → compare --runs → diff <run_id>
```
三个命令可以无缝串联。任何一侧的 JSON 契约 / run 选择逻辑被改坏，
这个测试第一时间报错。这就是 Phase 6 "一个终端做完所有事" 的骨架。

### 3. `quant_dojo diff --trend` 逐日偏差迷你图

`_render_trend(dates, live_cum, bt_cum, width)` 把逐日累计偏差画成一段
定宽 ASCII 条形图：负偏差在零线左侧，正偏差在右侧，按 max-abs 归一化。
实际样本：
```
  日期           gap
  2026-03-20    +0.00%              |
  2026-03-24    +1.08%              |████████████
```

回答 "gap 正在收敛 / 发散 / 稳定" 这类问题不用再去 Excel 画图。

### 4. Dashboard 触发路由 (`/api/trigger/*`)

新 router `dashboard/routers/trigger.py`：

- `POST /api/trigger/rebalance` → `control_surface.execute("rebalance.run", approved=True, date=...)`
- `POST /api/trigger/weekly-report` → `control_surface.execute("report.weekly", approved=True, week=...)`

所有入口走审批门；control_surface 的 error → HTTP 400，
requires_approval → HTTP 403。前端按钮接入只需要一次 POST。

这是 Phase 6 dashboard 最后一项 "操作页" 的后端补齐。

### 5. `quant_dojo history --since` 日期过滤

- 绝对：`--since 2026-04-01`
- 相对：`--since 7d` / `--since 2w` / `--since 24h` / `--since 30m`

相对时间通过 `_normalize_since()` 归一化成绝对 ISO 时间戳再走字符串比
较过滤路径，0 性能开销。常见查询 "最近 7 天跑了什么" 一行搞定。

## 测试总览

```
116 passed → 138 passed
```

新增覆盖：
- `test_history_cli.py` +15 条（purge + since + relative since）
- `test_diff_cli.py` +5 条（trend 渲染逻辑）
- `test_cli_chain_integration.py` 新文件 6 条
- `test_dashboard_trigger_router.py` 新文件 7 条

## 状态推进

| Phase | 之前 | 之后 |
|-------|-----|------|
| Phase 5 | 95% | **100%** |
| Phase 6 CLI | 4/5 done（命令树重构留白） | 4/5 done（同） |
| Phase 6 Dashboard | 4/5 done（操作页缺） | **5/5 done** |

## 下一步

Phase 5 收官。Phase 6 除了 "统一命令树" 重构（roadmap 里已注明暂留）
已全部完成。正式可以开始 Phase 7 Agentic Research — 让 AI 根据周报
/ 因子健康提出实验、批量运行回测、总结结果。
