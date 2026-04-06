#!/bin/bash
# daily_run.sh — Phase 5 每日模拟盘流水线
#
# 用法:
#   bash scripts/daily_run.sh              # 自动使用最新可用交易日
#   bash scripts/daily_run.sh 2026-03-20   # 指定日期
#
# 流程: data update → signal run → rebalance run → risk check → positions
# 策略: v7 industry-neutral（当前唯一 active strategy）
#
# 日志写入 logs/daily_run_YYYY-MM-DD.log

set -euo pipefail
cd "$(dirname "$0")/.."

STRATEGY="v7"
LOG_DIR="logs"
mkdir -p "$LOG_DIR"

# 确定运行日期
if [ -n "${1:-}" ]; then
    DATE="$1"
else
    # 自动获取最新数据日期
    DATE=$(python -c "
from utils.local_data_loader import load_price_wide, get_all_symbols
import pandas as pd
symbols = get_all_symbols()[:10]
pw = load_price_wide(symbols, '2020-01-01', '2099-12-31', field='close')
print(pw.index[-1].strftime('%Y-%m-%d'))
" 2>/dev/null || echo "")
    if [ -z "$DATE" ]; then
        echo "错误：无法确定最新数据日期" >&2
        exit 1
    fi
fi

LOG_FILE="$LOG_DIR/daily_run_${DATE}.log"

echo "╔═══════════════════════════════════════════════╗"
echo "║  Phase 5 每日模拟盘流水线                     ║"
echo "╚═══════════════════════════════════════════════╝"
echo "  策略: $STRATEGY"
echo "  日期: $DATE"
echo "  日志: $LOG_FILE"
echo "  时间: $(date '+%Y-%m-%d %H:%M:%S')"
echo ""

# 用 tee 同时输出到终端和日志
exec > >(tee -a "$LOG_FILE") 2>&1

step() {
    echo ""
    echo "━━━ $1 ━━━ $(date '+%H:%M:%S')"
}

# ── Step 1: 数据更新 ──
step "Step 1/5: 数据更新"
python -m pipeline.cli data update || {
    echo "⚠ 数据更新失败（可能是非交易日或网络问题），继续使用现有数据"
}

# ── Step 2: 信号生成 ──
step "Step 2/5: 信号生成 (strategy=$STRATEGY)"
python -m pipeline.cli signal run --strategy "$STRATEGY" --date "$DATE"

# ── Step 3: 调仓执行 ──
step "Step 3/5: 调仓执行"
python -m pipeline.cli rebalance run --strategy "$STRATEGY" --date "$DATE"

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
echo "  日志: $LOG_FILE"
echo "═══════════════════════════════════════════════"
