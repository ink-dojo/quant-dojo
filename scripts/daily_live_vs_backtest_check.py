#!/usr/bin/env python3
"""
scripts/daily_live_vs_backtest_check.py — Tier 1.4 daily cron 入口 (Issue #41)

每日收盘后跑一次 (建议 16:00, A 股 15:00 收盘 + 1h buffer):
    1. 算 live nav vs backtest equity 的最新一日 z-score 偏差
    2. 偏差 z ≥ 2σ → WARN alert (logs/alerts.log)
    3. 偏差 z ≥ 3σ → CRITICAL alert + 写 live/tracking_divergence_state.json
       (下次 active_strategy.py 调仓时读 state 触发 kill switch HALVE)

退出码 (cron 可读):
    0 = ok / insufficient_data
    1 = warn (留意, 不动作)
    2 = critical (kill 联动, 必须人工跟进)

## launchd 配置示例 (macOS, ~/Library/LaunchAgents/com.quantdojo.divergence.plist)

    <?xml version="1.0" encoding="UTF-8"?>
    <plist version="1.0">
    <dict>
        <key>Label</key><string>com.quantdojo.divergence</string>
        <key>ProgramArguments</key>
        <array>
            <string>/opt/homebrew/bin/python3.11</string>
            <string>/Users/karan/Documents/GitHub/quant-dojo/scripts/daily_live_vs_backtest_check.py</string>
            <string>--live-nav</string>
            <string>/Users/karan/Documents/GitHub/quant-dojo/live/portfolio/nav.csv</string>
            <string>--backtest-run</string>
            <string>/Users/karan/Documents/GitHub/quant-dojo/runs/spec_v4_baseline/run.json</string>
        </array>
        <key>StartCalendarInterval</key>
        <dict>
            <key>Hour</key><integer>16</integer>
            <key>Minute</key><integer>0</integer>
        </dict>
        <key>StandardOutPath</key>
        <string>/Users/karan/Documents/GitHub/quant-dojo/logs/divergence_cron.log</string>
        <key>StandardErrorPath</key>
        <string>/Users/karan/Documents/GitHub/quant-dojo/logs/divergence_cron.err</string>
    </dict>
    </plist>

## crontab 配置示例 (Linux)

    0 16 * * 1-5 cd /path/to/quant-dojo && \
        /usr/bin/python3 scripts/daily_live_vs_backtest_check.py \
            --live-nav live/portfolio/nav.csv \
            --backtest-run runs/spec_v4_baseline/run.json \
            >> logs/divergence_cron.log 2>&1
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

# 允许从仓库根目录直接运行: python scripts/daily_live_vs_backtest_check.py
ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from pipeline.live_vs_backtest import (  # noqa: E402
    DEFAULT_DIVERGENCE_STATE_FILE,
    check_and_alert,
)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="每日 live vs backtest divergence 检查 + alert + state 持久化"
    )
    parser.add_argument(
        "--live-nav",
        required=True,
        type=Path,
        help="live nav.csv 路径 (e.g. live/portfolio/nav.csv)",
    )
    parser.add_argument(
        "--backtest-run",
        required=True,
        type=Path,
        help="对应回测 run JSON 路径 (含 artifacts.equity_csv)",
    )
    parser.add_argument(
        "--state-file",
        type=Path,
        default=DEFAULT_DIVERGENCE_STATE_FILE,
        help=f"alert state JSON 输出路径 (默认 {DEFAULT_DIVERGENCE_STATE_FILE.name})",
    )
    parser.add_argument(
        "--lookback-days",
        type=int,
        default=30,
        help="历史 σ 估计窗口 (默认 30 个交易日)",
    )
    parser.add_argument(
        "--warn-zscore",
        type=float,
        default=2.0,
        help="WARN 阈值 (默认 2.0σ)",
    )
    parser.add_argument(
        "--critical-zscore",
        type=float,
        default=3.0,
        help="CRITICAL 阈值 (默认 3.0σ, 触发 kill switch HALVE)",
    )
    parser.add_argument(
        "--no-alert",
        action="store_true",
        help="不发 alert (只算 + 写 state). 用于回测验证 / debug",
    )
    parser.add_argument(
        "--no-state",
        action="store_true",
        help="不写 state file. 用于 dry-run.",
    )
    args = parser.parse_args()

    state_file = None if args.no_state else args.state_file

    alert = check_and_alert(
        live_nav_path=args.live_nav,
        backtest_run_path=args.backtest_run,
        state_file=state_file,
        notify=not args.no_alert,
        lookback_days=args.lookback_days,
        warn_zscore=args.warn_zscore,
        critical_zscore=args.critical_zscore,
    )

    # 输出可读摘要
    print(f"asof_date    : {alert.asof_date or '(N/A)'}")
    print(f"alert_level  : {alert.alert_level}")
    print(f"zscore       : {alert.zscore:.3f}")
    print(f"daily_delta  : {alert.daily_delta:+.4%}")
    print(f"hist_std     : {alert.historical_std:.4%}")
    print(f"n_obs        : {alert.n_observations}")
    if alert.fallback_reason:
        print(f"fallback     : {alert.fallback_reason}")
    if alert.is_critical():
        print("⚠️  CRITICAL — kill switch HALVE 将在下一次调仓触发")
        return 2
    if alert.is_warn():
        print("⚠️  WARN — 留意, 暂不动作")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
