#!/bin/bash
# A 股日行情增量更新脚本
# 每个工作日 A 股收盘后（北京时间 16:30 后，美东约 04:30 AM）自动拉取全市场数据。
#
# 注意：本脚本仅负责数据更新，不生成信号也不调仓。
# 完整模拟盘流水线请使用 scripts/daily_run.sh：
#   bash scripts/daily_run.sh           # 自动推断日期（每日早晨美国时间运行一次即可）
#
# 时序说明（T+1 开盘成交模式）：
#   T 日数据更新 + 信号生成 → T+1 日 rebalance 用开盘价成交
#
# 日志: logs/daily_update.log

set -e

REPO_DIR="/Users/karan/work/quant-dojo"
PYTHON="/opt/homebrew/opt/python@3.11/libexec/bin/python"
LOG="$REPO_DIR/logs/daily_update.log"

echo "========================================" >> "$LOG"
echo "[$(date '+%Y-%m-%d %H:%M:%S')] 开始数据更新" >> "$LOG"

cd "$REPO_DIR"

# 加载 .env（cron 环境没有 shell 初始化，手动 export）
if [ -f "$REPO_DIR/.env" ]; then
    export $(grep -v '^#' "$REPO_DIR/.env" | xargs)
fi

# 数据更新
"$PYTHON" -m pipeline.cli data update --source tushare >> "$LOG" 2>&1
STATUS=$?

if [ $STATUS -eq 0 ]; then
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] ✅ 数据更新成功" >> "$LOG"
else
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] ❌ 数据更新失败 (exit=$STATUS)" >> "$LOG"
fi

echo "" >> "$LOG"
