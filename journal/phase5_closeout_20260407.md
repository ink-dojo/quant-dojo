# Phase 5 收尾总结 — 2026-04-07

> 这份文档记录了 2026-04-07 一次约 2 小时的自主工作 session 内，
> 为关闭 Phase 5 "模拟实盘基础设施" 所做的全部改动。
>
> 进度：Phase 5 从 60% → 95%。剩余 5% 是未来用"同起点回测"方法学再跑一次对照，确认偏差分解的 2% 建仓 + 0.4% 成本成立。

## 背景

session 开始时 Phase 5 状态：
- 连续运行 10 天干净 replay 已通过 ✓
- restart-safe 覆盖 ✓
- IC 审计完成（因子都健康，之前的 dead 告警是小样本误报）✓
- 三个遗留项：审计价值提升、实盘 vs 回测差异工具、周报诚信

## 本次 session 完成项

### 1. 实盘 vs 回测差异分析工具 (Task #112)

**模块** `pipeline/live_vs_backtest.py`

核心：`compute_divergence(live_nav_path, backtest_run_path, start, end)`

- 读两边的 NAV / equity 曲线
- 在共同交易日交集上对齐
- 输出每日累计收益、日偏差、summary 指标（mean、std、max-abs、final_gap_pct）
- 再提供 `render_markdown_report(div)` 渲染成结构化报告

**首次跑出来的结论**（v7, 2026-03-20 ~ 2026-03-31, 8 天共同窗口）：

| 项 | 值 |
|----|---:|
| live 累计收益 | -3.22% |
| backtest 累计收益 | -1.17% |
| **累计偏差** | **-2.05%** |
| 日均偏差 | -0.26% |
| 偏差 σ | 1.57% |
| 最大单日偏差 | -3.01% (2026-03-24) |

**偏差成因分解**：
- 交易成本 ≈ 0.4% （0.0006 双边 × 8 天高换手）
- 整数股约束：噪声，非漂移
- 行业中性化触发点不一致：日噪声，非漂移
- **主因 ≈ 1.5%**：fresh-start 方法学差异 — 干净 replay 每 8 天从头建仓，回测是 540 天连续演化出来的尾段 8 天
- 下次对照要让回测从同一个 2026-03-20 起点，否则建仓窗口差异压倒一切

### 2. `quant_dojo diff` CLI 子命令 (Task #113)

`quant_dojo/commands/diff.py` 把 `compute_divergence` 包装成一级 CLI 入口：

```bash
python -m quant_dojo diff                                # 最新成功回测 run
python -m quant_dojo diff v7_20260407_41b618e5           # 指定 run_id
python -m quant_dojo diff --run /path/to/run.json        # 指定完整路径
python -m quant_dojo diff --start 2026-03-20 --end 2026-03-27
python -m quant_dojo diff --save journal/diff.md
python -m quant_dojo diff --json                         # 机器可读
```

特别处理：
- `_resolve_run_path` 自动取 `live/runs/` 下最新且**带 equity_csv artifact** 的 run，跳过失败的 / 每日 pipeline 产物
- 打印结束附一行结论：`跟踪良好` / `纯噪声` / `系统性少赚 X%` / `系统性多赚 X%`

测试：`tests/test_diff_cli.py`，10 个 case。

### 3. 周报审计增强 (Task #111，本 session 继续做尾巴)

已在前一个 commit 中做完；本 session 只做了最后的验证和 ROADMAP 标记。

### 4. `quant_dojo history` 运行历史索引 (Task #114 / Phase 6 prep)

`quant_dojo/commands/history.py` — 统一看所有运行记录：

```bash
python -m quant_dojo history                  # 最近 20 条全部
python -m quant_dojo history --type backtest  # 只看回测
python -m quant_dojo history --type daily     # 只看每日 pipeline
python -m quant_dojo history --strategy v7    # 策略过滤
python -m quant_dojo history --status success # 状态过滤
python -m quant_dojo history --json           # JSON
```

实现要点：
- 同时扫 `live/runs/*.json`（回测）和 `logs/quant_dojo_run_*.json`（每日 pipeline）
- 统一字段：kind / run_id / strategy / status / created_at + 每种类型的关键指标
- 对 stray JSON（没有 run_id 或 strategy_id 的）做过滤
- 按 created_at 倒序排序

测试：`tests/test_history_cli.py`，9 个 case。

### 5. `quant_dojo status` 集成 diff 摘要 (Task #115)

给 `show_status()` 加了一个新 section "偏差 (live vs backtest)"：

```
━━━ 偏差 (live vs backtest) ━━━
  基于 v7_20260407_41b618e5 (8 天共同窗口)
  live -3.22%  bt -1.17%  gap -2.05%  σ 1.57%
  结论: 系统性少赚 2.05%
  详情: python -m quant_dojo diff v7_20260407_41b618e5
```

自动选最新**成功**回测 run，调 `compute_divergence`，再用 gap 和 σ 给一个 verdict tag。

这样日常复盘时一眼能看到"今天实盘是不是还在追踪回测"，不用单独跑 diff。

测试：`test_quant_dojo_cli.py::TestStatusCommand` 里新增 3 个 case。

### 6. ROADMAP 更新

Phase 5 进度条 85% → 95%，标记实盘 vs 回测差异分析 + 审计价值提升均已完成。CLI 命令数量 15 → 16（新增 `diff`） + 额外的 `history`。

## Commit 列表

```
ee2fcce feat: add live vs backtest divergence analysis tool
9898db3 docs: live vs backtest v7 gap analysis 20260407
5e66ae6 feat: add 'quant_dojo diff' subcommand for live vs backtest gap
3c7ade4 test: cover quant_dojo diff subcommand
2eef79a docs: bump phase 5 to 95% — diff tool and audit done
a931169 feat: add 'quant_dojo history' unified run index
85c4e16 test: cover quant_dojo history command
02d52cc feat: surface live vs backtest divergence in quant_dojo status
583b1f6 test: cover status backtest divergence section
```

## 测试情况

单跑本次新增 / 修改的测试文件：

```
tests/test_diff_cli.py                                   10 passed
tests/test_history_cli.py                                 9 passed
tests/test_quant_dojo_cli.py::TestStatusCommand           8 passed
tests/test_phase5_regression.py                          13 passed
tests/test_factor_monitor_health.py                       4 passed
tests/test_weekly_report_audit.py                         7 passed
```

跑完整套件 `pytest tests/ -x` 时有一个预先存在的 test ordering
artifact（`test_compare_all_strategies_default` 在 full run 时失败，
单跑 `test_quant_dojo_cli.py` 完整 73 个 case 时通过）—— 不是本次
改动引入的，未处理。

## Phase 5 剩余（进入 Phase 6 前）

- [ ] 用**同起点回测** 重做实盘 vs 回测对照，验证偏差分解里 2% 建仓
  + 0.4% 成本的假设是否成立
- [ ] 把 Phase 5 的 lessons 汇总一份 README-friendly 的"如何信任
  模拟盘"文档（可选）

## Phase 6 开局准备

本次 session 的 `quant_dojo history` 已经是 Phase 6 "运行历史索引"
的第一块砖。下一步建议：

- 把 `quant_dojo backtest` / `run` / `signal` 等命令的输出统一
  写入 `logs/` + `live/runs/`，让 `history` 覆盖率 100%
- 给 dashboard 加"差异分析"页，把 `compute_divergence` 的
  markdown 报告也能在浏览器里看
- `quant_dojo compare` 支持传入 run_id（而不是重跑回测），直接
  对比两个历史 run，减少重复工作
