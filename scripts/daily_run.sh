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

PYTHON="/opt/homebrew/opt/python@3.11/libexec/bin/python"
STRATEGY="v16"
LOG_DIR="logs"
mkdir -p "$LOG_DIR"

# 确定 T+1 日（今天的交易日，开盘后执行）
if [ -n "${1:-}" ]; then
    TRADE_DATE="$1"
else
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

# ── Step 0: 申万行业分类（30 天 TTL，过期才真正打网络）──
# --quiet：缓存有效时静默退出；过期或首次才刷新并打印
step "Step 0/6: 申万行业分类（TTL 检查）"
"$PYTHON" scripts/refresh_industry.py --quiet || {
    echo "⚠ 申万行业刷新失败，使用旧缓存继续"
}

# ── Step 1: 数据更新（拉最新 A 股日行情到今天）──
step "Step 1/6: 数据更新"
"$PYTHON" -m pipeline.cli data update --source tushare || {
    echo "⚠ 数据更新失败（可能是非交易日或网络问题），继续使用现有数据"
}

# ── Step 2: 生成昨日（T 日）信号 ──
# 用 prev-trading-date 命令计算前一 A 股交易日（正确处理节假日，不只跳周末）
SIGNAL_DATE=$("$PYTHON" -m pipeline.cli prev-trading-date "$TRADE_DATE")
step "Step 2/6: 生成 T 日信号 (signal_date=$SIGNAL_DATE, strategy=$STRATEGY)"
"$PYTHON" -m pipeline.cli signal run --strategy "$STRATEGY" --date "$SIGNAL_DATE"

# ── Step 3: 用 T+1 日开盘价执行调仓 ──
step "Step 3/6: 调仓执行（用 ${TRADE_DATE} 开盘价成交）"
"$PYTHON" -m pipeline.cli rebalance run --strategy "$STRATEGY" --date "$TRADE_DATE"

# ── Step 4: 风险检查 ──
step "Step 4/6: 风险检查"
"$PYTHON" -m pipeline.cli risk check

# ── Step 5: 持仓确认 ──
step "Step 5/6: 持仓确认"
"$PYTHON" -m pipeline.cli positions
echo ""
"$PYTHON" -m pipeline.cli performance

echo ""
echo "═══════════════════════════════════════════════"
echo "  流水线完成 — $(date '+%Y-%m-%d %H:%M:%S')"
echo "  信号日: $SIGNAL_DATE → 成交日: $TRADE_DATE"
echo "  日志: $LOG_FILE"
echo "═══════════════════════════════════════════════"
