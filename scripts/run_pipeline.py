#!/usr/bin/env python3
"""
scripts/run_pipeline.py — AI Agent 量化流水线入口

用法:
  # 日模式（默认）— 数据检查 + 信号 + 调仓 + 风控 + 日报
  python scripts/run_pipeline.py

  # 指定日期
  python scripts/run_pipeline.py --date 2026-04-03

  # 周模式 — 额外执行因子挖掘 + 策略组合
  python scripts/run_pipeline.py --mode weekly

  # 全模式 — 无条件执行所有阶段
  python scripts/run_pipeline.py --mode full

  # 干跑（不执行实际操作）
  python scripts/run_pipeline.py --dry-run

  # 只执行特定阶段
  python scripts/run_pipeline.py --only factor_mine,strategy_compose

Cron 示例:
  # 每个交易日 16:00 执行日模式
  0 16 * * 1-5 cd /path/to/quant-dojo && python scripts/run_pipeline.py >> logs/pipeline.log 2>&1

  # 每周一 16:30 执行周模式
  30 16 * * 1 cd /path/to/quant-dojo && python scripts/run_pipeline.py --mode weekly >> logs/pipeline.log 2>&1
"""

import argparse
import logging
import sys
import os
from datetime import datetime
from pathlib import Path

# 确保项目根目录在 sys.path 中
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
os.chdir(PROJECT_ROOT)


def setup_logging(date: str):
    """配置日志输出到文件 + 控制台"""
    log_dir = PROJECT_ROOT / "logs"
    log_dir.mkdir(exist_ok=True)
    log_file = log_dir / f"pipeline_{date}.log"

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
        handlers=[
            logging.FileHandler(log_file, encoding="utf-8"),
            logging.StreamHandler(sys.stdout),
        ],
    )
    return log_file


def main():
    parser = argparse.ArgumentParser(description="AI Agent 量化流水线")
    parser.add_argument(
        "--date", type=str, default=None,
        help="交易日期 YYYY-MM-DD（默认: 今天）",
    )
    parser.add_argument(
        "--mode", type=str, default="daily",
        choices=["daily", "weekly", "full"],
        help="运行模式: daily(默认)/weekly/full",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="干跑模式（不执行实际操作）",
    )
    parser.add_argument(
        "--only", type=str, default=None,
        help="只执行指定阶段（逗号分隔）",
    )

    args = parser.parse_args()

    date = args.date or datetime.now().strftime("%Y-%m-%d")
    log_file = setup_logging(date)

    print(f"日志文件: {log_file}")

    # 构建流水线
    from pipeline.orchestrator import build_default_pipeline

    orch = build_default_pipeline()

    # 如果指定了 --only，过滤阶段
    if args.only:
        only_stages = set(args.only.split(","))
        orch.stages = [s for s in orch.stages if s.name in only_stages]
        if not orch.stages:
            print(f"错误: 未找到阶段 {args.only}")
            print(f"可用阶段: {', '.join(s.name for s in orch.stages)}")
            sys.exit(1)

    # 执行
    ctx = orch.execute(
        date=date,
        mode=args.mode,
        dry_run=args.dry_run,
    )

    # 退出码
    n_failed = sum(1 for r in ctx.stage_results if r.status.value == "failed")
    sys.exit(1 if n_failed > 0 else 0)


if __name__ == "__main__":
    main()
