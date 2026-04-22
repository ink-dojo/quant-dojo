#!/bin/bash
# DSR #30 paper-trade EOD wrapper, 由 launchd 每工作日本地 09:30 触发 (上海 21:30 收盘后).
#
# 顺序:
#   1. 尝试 daily_update.sh — 刷价格数据到最新交易日. 失败不 abort (可能 tushare token
#      过期; paper-trade 仍可跑上次已有数据的那天).
#   2. 跑 paper_trade_daily.py — 生成今天的 signal + trade + state.json + 日报.
#
# 日志: logs/paper_trade_cron.log (追加模式, 每次一段带时间戳).
# 失败退出码非 0, launchd 不自动重试; alerts.log 里也会写一行.

set -u  # 不用 -e, 继续在 update 失败后

REPO_DIR="/Users/karan/work/quant-dojo"
PYTHON="/opt/homebrew/opt/python@3.11/libexec/bin/python"
LOG="$REPO_DIR/logs/paper_trade_cron.log"
mkdir -p "$REPO_DIR/logs"

cd "$REPO_DIR"

# 加载 .env (launchd 不会经过 shell rc 文件)
if [ -f "$REPO_DIR/.env" ]; then
    set -a
    source "$REPO_DIR/.env"
    set +a
fi

{
  echo "========================================"
  echo "[$(date '+%Y-%m-%d %H:%M:%S %z')] paper-trade cron start"

  echo "--- step 1: daily_update.sh ---"
  bash "$REPO_DIR/scripts/daily_update.sh" || echo "[warn] data update failed; 继续使用已有数据"

  echo "--- step 2: paper_trade_daily.py ---"
  "$PYTHON" "$REPO_DIR/scripts/paper_trade_daily.py"
  EXIT=$?
  echo "paper_trade_daily exit=$EXIT"

  echo "[$(date '+%Y-%m-%d %H:%M:%S %z')] paper-trade cron done"
  echo ""
} >> "$LOG" 2>&1

exit $EXIT
