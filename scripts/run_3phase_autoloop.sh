#!/bin/bash
# 三阶段 autoloop 串行执行器
#
# 用法: bash scripts/run_3phase_autoloop.sh
#
# 每个阶段：清理 loop-state → 写入阶段 context → 启动 autoloop → 等待完成
# 阶段之间自动衔接，日志分别写到 /tmp/autoloop-phase{1,2,3}.log

set -euo pipefail
cd "$(dirname "$0")/.."
GOAL="GOAL_v6_admission_push.md"
LOOP_RUNNER="$HOME/.claude/scripts/loop-runner.sh"
STATE=".claude/loop-state"

echo "╔═══════════════════════════════════════════════╗"
echo "║  三阶段 Autoloop — V6 Admission Push          ║"
echo "╚═══════════════════════════════════════════════╝"
echo "  Goal: $GOAL"
echo "  Time: $(date)"
echo ""

run_phase() {
  local phase=$1
  local context_file=$2
  local log="/tmp/autoloop-phase${phase}.log"

  echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
  echo "  Phase ${phase} 启动 — $(date '+%H:%M:%S')"
  echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

  # 清理上一轮状态
  rm -f "$STATE"

  # 运行 autoloop（阻塞等待完成）
  bash "$LOOP_RUNNER" "$GOAL" \
    --max-iter 5 \
    --context "$context_file" \
    > "$log" 2>&1

  local exit_code=$?
  echo "  Phase ${phase} 完成 — $(date '+%H:%M:%S') (exit: $exit_code)"
  echo "  日志: $log"

  # 检查是否收敛
  if grep -q "CONVERGED=true" "$STATE" 2>/dev/null; then
    echo "  ✓ CONVERGED"
  else
    echo "  ⚠ 未收敛（可能达到 max-iter）"
  fi
  echo ""
}

# ── Phase 1 Context ──────────────────────────────────────
cat > /tmp/phase1_context.md << 'PHASE1'
## Phase-Specific Instructions (Phase 1 of 3)

本轮只做第一阶段：固化保守基线和 admission 口径。

必须完成：
1. 把 v6(lag1) 固化成唯一 admission baseline
2. 统一 scripts/strategy_eval.py 和 journal 文档的口径
3. 明确默认设定（lag1、因子、择时、持股数、换仓频率、成本、股票池）
4. 区分 optimistic 和 honest_baseline
5. 主脚本默认改为保守口径

禁止：
- 不要做 stop-loss、双周换仓、行业上限
- 不要改因子集合或择时逻辑
- 不要只改文档不改脚本

完成标准：v6(lag1) baseline 定义清晰，主脚本默认保守，文档不再混用乐观/保守结论。
PHASE1

# ── Phase 2 Context ──────────────────────────────────────
cat > /tmp/phase2_context.md << 'PHASE2'
## Phase-Specific Instructions (Phase 2 of 3)

第一阶段已完成。本轮只做第二阶段：选一个最小改动方向并重评估。

必须完成：
1. 从候选里只选一个：个股止损 / 双周换仓 / 行业上限微调
2. 默认先评估个股止损
3. 不改因子集合、择时、持股数、成本
4. 重跑完整 admission pack（样本内/外/WF/年度/回撤诊断）
5. 生成 baseline vs new 对照

禁止：
- 不能同时上多个优化
- 结果不理想不能临时加补丁
- 不能扩大战线

完成标准：有清晰的单变量对照，能回答"这一个改动是否足以推过门槛"。
PHASE2

# ── Phase 3 Context ──────────────────────────────────────
cat > /tmp/phase3_context.md << 'PHASE3'
## Phase-Specific Instructions (Phase 3 of 3)

前两阶段已完成。本轮只做第三阶段：写正式 admission decision。

必须完成：
1. 输出正式 admission decision（allow 或 deny）
2. 如果 allow：写清允许版本 + 保护措施 + 工程项
3. 如果 deny：写清差什么 + 下一轮唯一改动
4. 更新 WORKPLAN 和 decision 文档口径一致

禁止：
- 不用"接近通过""基本可以""建议先试运行"替代正式结论
- 不新增实验
- 不弱化保守口径来凑 allow
- 不跳过保护措施

完成标准：生成 journal/strategy_admission_decision_*.md，WORKPLAN 同步，明确 handoff 与否。
PHASE3

# ── 执行 ──────────────────────────────────────────────────
START_TIME=$(date +%s)

run_phase 1 /tmp/phase1_context.md
run_phase 2 /tmp/phase2_context.md
run_phase 3 /tmp/phase3_context.md

ELAPSED=$(( ($(date +%s) - START_TIME) / 60 ))
echo "═══════════════════════════════════════════════"
echo "  三阶段全部完成 — 总耗时 ${ELAPSED} 分钟"
echo "  日志: /tmp/autoloop-phase{1,2,3}.log"
echo "═══════════════════════════════════════════════"
