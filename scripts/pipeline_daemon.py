#!/usr/bin/env python3
"""
scripts/pipeline_daemon.py — 流水线守护进程

持续运行，在 A 股收盘后自动执行日流水线。

功能:
  - 自动检测交易日（跳过周末和节假日）
  - 收盘后等待数据就绪（BaoStock 延迟约 1 小时）
  - 每日执行完整流水线
  - 每周一额外执行因子挖掘
  - 异常自动重试（最多 3 次）
  - 所有输出记录到日志

用法:
  # 前台运行
  python scripts/pipeline_daemon.py

  # 后台运行
  nohup python scripts/pipeline_daemon.py >> logs/daemon.log 2>&1 &

  # 指定执行时间（默认 16:30 — BaoStock 数据约 16:00 就绪）
  python scripts/pipeline_daemon.py --run-time 16:30

  # 立即执行一次然后进入等待
  python scripts/pipeline_daemon.py --run-now
"""

import argparse
import logging
import os
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
os.chdir(PROJECT_ROOT)


def setup_logging():
    log_dir = PROJECT_ROOT / "logs"
    log_dir.mkdir(exist_ok=True)

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
        handlers=[
            logging.FileHandler(log_dir / "daemon.log", encoding="utf-8"),
            logging.StreamHandler(sys.stdout),
        ],
    )
    return logging.getLogger("pipeline_daemon")


def is_weekday(dt: datetime) -> bool:
    """周一到周五"""
    return dt.weekday() < 5


def is_monday(dt: datetime) -> bool:
    return dt.weekday() == 0


def seconds_until(target_hour: int, target_minute: int) -> float:
    """计算从现在到今天目标时间的秒数（如果已过，算到明天）"""
    now = datetime.now()
    target = now.replace(hour=target_hour, minute=target_minute, second=0, microsecond=0)
    if target <= now:
        target += timedelta(days=1)
    return (target - now).total_seconds()


def run_pipeline(date: str, mode: str, logger, max_retries: int = 3) -> bool:
    """
    执行流水线，失败时重试。

    返回:
        True 成功, False 失败
    """
    from pipeline.orchestrator import build_default_pipeline

    for attempt in range(1, max_retries + 1):
        try:
            logger.info("执行流水线 (attempt %d/%d): %s [%s]", attempt, max_retries, date, mode)
            orch = build_default_pipeline()
            ctx = orch.execute(date=date, mode=mode)

            n_failed = sum(1 for r in ctx.stage_results if r.status.value == "failed")
            if n_failed == 0:
                logger.info("流水线完成: %s [%s]", date, mode)
                return True
            else:
                logger.warning("流水线 %d 个阶段失败", n_failed)
                if attempt < max_retries:
                    wait = 60 * attempt
                    logger.info("等待 %ds 后重试...", wait)
                    time.sleep(wait)

        except Exception as e:
            logger.error("流水线异常: %s", e)
            if attempt < max_retries:
                wait = 60 * attempt
                logger.info("等待 %ds 后重试...", wait)
                time.sleep(wait)

    logger.error("流水线最终失败: %s", date)
    return False


def main():
    parser = argparse.ArgumentParser(description="量化流水线守护进程")
    parser.add_argument(
        "--run-time", type=str, default="16:30",
        help="每日执行时间 HH:MM（默认 16:30）",
    )
    parser.add_argument(
        "--run-now", action="store_true",
        help="立即执行一次当日流水线",
    )
    args = parser.parse_args()

    logger = setup_logging()
    run_hour, run_minute = map(int, args.run_time.split(":"))

    logger.info("流水线守护进程启动")
    logger.info("  执行时间: %02d:%02d", run_hour, run_minute)
    logger.info("  项目目录: %s", PROJECT_ROOT)

    # 立即执行
    if args.run_now:
        today = datetime.now().strftime("%Y-%m-%d")
        mode = "weekly" if is_monday(datetime.now()) else "daily"
        logger.info("立即执行: %s [%s]", today, mode)
        run_pipeline(today, mode, logger)

    # 进入守护循环
    last_run_date = None

    while True:
        now = datetime.now()
        today = now.strftime("%Y-%m-%d")

        # 检查是否到了执行时间
        if (
            is_weekday(now)
            and now.hour == run_hour
            and now.minute >= run_minute
            and today != last_run_date
        ):
            mode = "weekly" if is_monday(now) else "daily"
            logger.info("定时触发: %s [%s]", today, mode)

            success = run_pipeline(today, mode, logger)
            last_run_date = today

            if success:
                logger.info("今日流水线完成，等待明天")
            else:
                logger.error("今日流水线失败")

        # 计算下次执行的等待时间
        wait = seconds_until(run_hour, run_minute)

        # 不超过 60 秒的 sleep 周期（方便响应中断）
        sleep_time = min(wait, 60)
        time.sleep(sleep_time)


if __name__ == "__main__":
    main()
