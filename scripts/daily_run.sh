#!/bin/bash
# daily_run.sh — 每日模拟盘流水线（T+1 开盘成交版）
#
# 正确的时序逻辑：
#   T 日收盘后（或 T+1 日早晨）：
#     data update       → 拉入 T 日行情
#     signal run --date T   → 用 T 日数据生成信号，保存 live/signals/T.json
#   T+1 日开盘后（09:35 CST / 美东 21:35 前一天）：
#     rebalance run --date T+1 → 读 T 日信号，用 T+1 日开盘价成交
#
# 实际操作方式（每日早晨美国时间一次性跑完）：
#   1. 拉 T 日数据（前一个自然交易日）
#   2. 生成 T 日信号
#   3. 用 T+1 日开盘价（= 今天开盘价）执行调仓
#
# 用法:
#   bash scripts/daily_run.sh              # 自动推断日期
#   bash scripts/daily_run.sh 2026-04-10   # 指定 T+1 日（今天的交易日）
#
# 脚本接收的日期参数为 T+1 日；T 日（信号日）由 rebalance 命令内部自动推算。
#
# 日志写入 logs/daily_run_YYYY-MM-DD.log

set -euo pipefail
cd "$(dirname "$0")/.."

STRATEGY="v7"
LOG_DIR="logs"
mkdir -p "$LOG_DIR"

# 确定 T+1 日（今天的交易日，开盘后执行）
if [ -n "${1:-}" ]; then
    TRADE_DATE="$1"
else
    # 默认取今天日期（假设脚本在开盘后运行）
    TRADE_DATE=$(date '+%Y-%m-%d')
fi

LOG_FILE="$LOG_DIR/daily_run_${TRADE_DATE}.log"

echo "╔═══════════════════════════════════════════════╗"
echo "║  每日模拟盘流水线（T+1 开盘成交）             ║"
echo "╚═══════════════════════════════════════════════╝"
echo "  策略: $STRATEGY"
echo "  成交日（T+1）: $TRADE_DATE"
echo "  日志: $LOG_FILE"
echo "  时间: $(date '+%Y-%m-%d %H:%M:%S')"
echo ""

# 用 tee 同时输出到终端和日志
exec > >(tee -a "$LOG_FILE") 2>&1

step() {
    echo ""
    echo "━━━ $1 ━━━ $(date '+%H:%M:%S')"
}

# ── Step 1: 数据更新（拉最新 A 股日行情到今天）──
step "Step 1/5: 数据更新"
python -m pipeline.cli data update || {
    echo "⚠ 数据更新失败（可能是非交易日或网络问题），继续使用现有数据"
}

# ── Step 2: 生成昨日（T 日）信号 ──
# 计算前一交易日日期（信号日 = T 日）
SIGNAL_DATE=$(python -c "
import datetime, sys
d = datetime.date.fromisoformat('${TRADE_DATE}')
d -= datetime.timedelta(days=1)
while d.weekday() >= 5:
    d -= datetime.timedelta(days=1)
print(d.isoformat())
")
step "Step 2/5: 生成 T 日信号 (signal_date=$SIGNAL_DATE, strategy=$STRATEGY)"
python -m pipeline.cli signal run --strategy "$STRATEGY" --date "$SIGNAL_DATE"

# ── Step 3: 用 T+1 日开盘价执行调仓 ──
# rebalance 命令内部会自动读取 live/signals/$SIGNAL_DATE.json
step "Step 3/5: 调仓执行（用 ${TRADE_DATE} 开盘价成交）"
python -m pipeline.cli rebalance run --strategy "$STRATEGY" --date "$TRADE_DATE"

# ── Step 4: 风险检查 ──
step "Step 4/5: 风险检查"
python -m pipeline.cli risk check

# ── Step 5: 持仓确认 ──
step "Step 5/5: 持仓确认"
python -m pipeline.cli positions
echo ""
python -m pipeline.cli performance

echo ""
echo "═══════════════════════════════════════════════"
echo "  流水线完成 — $(date '+%Y-%m-%d %H:%M:%S')"
echo "  信号日: $SIGNAL_DATE → 成交日: $TRADE_DATE"
echo "  日志: $LOG_FILE"
echo "═══════════════════════════════════════════════"
