#!/bin/bash
# 月度 review wrapper, 由 launchd 每月 1 日本地 10:00 触发 (逻辑上首交易日).
# 如果 1 号不是交易日 (周末/假期), paper_trade_monthly_review.py 自己会处理.

set -u
REPO_DIR="/Users/karan/work/quant-dojo"
PYTHON="/opt/homebrew/opt/python@3.11/libexec/bin/python"
LOG="$REPO_DIR/logs/paper_trade_monthly_cron.log"
mkdir -p "$REPO_DIR/logs"

cd "$REPO_DIR"
if [ -f "$REPO_DIR/.env" ]; then
    set -a
    source "$REPO_DIR/.env"
    set +a
fi

{
  echo "========================================"
  echo "[$(date '+%Y-%m-%d %H:%M:%S %z')] monthly review start"
  "$PYTHON" "$REPO_DIR/scripts/paper_trade_monthly_review.py"
  EXIT=$?
  echo "monthly_review exit=$EXIT"
  echo "[$(date '+%Y-%m-%d %H:%M:%S %z')] monthly review done"
  echo ""
} >> "$LOG" 2>&1

exit $EXIT
