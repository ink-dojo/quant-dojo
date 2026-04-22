#!/bin/bash
# DSR #30 paper-trade EOD wrapper, 由 launchd 每工作日本地 09:30 触发 (上海 21:30 收盘后).
#
# 顺序:
#   1. 刷价格数据 (tushare 120 积分 / daily + adj_factor). 失败不 abort.
#   2. 刷回购事件 parquet (akshare stock_repurchase_em, 免 token). 失败不 abort.
#   3. paper_trade_daily.py — 生成今天的 signal + trade + state.json + 日报.
#   4. state.json 有变化则 git commit + push main, 触发 Vercel 重部署
#      https://quantdojo.vercel.app/live/paper-trade 页面. 失败不影响 cron 成功.
#
# 日志: logs/paper_trade_cron.log
# 失败退出码非 0, launchd 不自动重试.

set -u

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

# Paper-trade 专用 token 覆盖主 token (scope 仅此脚本)
if [ -n "${PAPER_TRADE_TUSHARE_TOKEN:-}" ]; then
    export TUSHARE_TOKEN="$PAPER_TRADE_TUSHARE_TOKEN"
fi

{
  echo "========================================"
  echo "[$(date '+%Y-%m-%d %H:%M:%S %z')] paper-trade cron start"
  echo "  TUSHARE_TOKEN prefix: ${TUSHARE_TOKEN:0:8}... (paper-trade 专用)"

  echo "--- step 1: 刷价格数据 (tushare 120 积分 / daily + adj_factor) ---"
  "$PYTHON" -m pipeline.cli data update --source tushare || \
      echo "[warn] price update failed; 继续使用已有价格"

  echo "--- step 2: 刷回购事件 (akshare stock_repurchase_em, 免 token) ---"
  "$PYTHON" "$REPO_DIR/scripts/refresh_buyback_events.py" || \
      echo "[warn] buyback refresh failed; 继续使用已有 parquet"

  echo "--- step 3: paper_trade_daily.py ---"
  "$PYTHON" "$REPO_DIR/scripts/paper_trade_daily.py"
  EXIT=$?
  echo "paper_trade_daily exit=$EXIT"

  echo "--- step 4: auto-commit state.json → Vercel redeploy ---"
  STATE_JSON="$REPO_DIR/portfolio/public/data/paper_trade/state.json"
  if [ -f "$STATE_JSON" ] && git -C "$REPO_DIR" diff --quiet -- "$STATE_JSON"; then
      echo "  state.json 未变化, 跳过 push"
  elif [ -f "$STATE_JSON" ]; then
      TODAY=$(date '+%Y-%m-%d')
      git -C "$REPO_DIR" add "$STATE_JSON"
      git -C "$REPO_DIR" commit -m "chore(paper-trade): EOD state snapshot $TODAY" \
          --no-verify 2>&1 | tail -3
      if git -C "$REPO_DIR" push origin main 2>&1 | tail -3; then
          echo "  pushed, Vercel 几分钟后会重新部署"
      else
          echo "  [warn] push 失败 (SSH key 未加载? 或网络?); state.json 仍在本地"
      fi
  fi

  echo "[$(date '+%Y-%m-%d %H:%M:%S %z')] paper-trade cron done"
  echo ""
} >> "$LOG" 2>&1

exit $EXIT
