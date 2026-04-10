#!/bin/bash
# A 股日行情增量更新脚本
# 每个工作日收盘后（美国时间晚上）自动拉取 Tushare 全市场数据
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
