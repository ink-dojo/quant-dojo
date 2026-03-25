"""
pipeline/live_data_service.py — 实时数据服务

两个核心功能：
  1. 盘中实时行情轮询（Sina API）
  2. 收盘后自动 EOD 更新（BaoStock）

安全措施：
  - 所有网络请求有超时和重试
  - 数据写入前先校验格式
  - 异常不会中断服务主循环
  - 日志记录所有操作

用法：
  # 启动实时轮询（盘中用）
  python -m pipeline.live_data_service poll --interval 5

  # 执行 EOD 更新（收盘后用）
  python -m pipeline.live_data_service eod

  # 两者都做（自动判断时间）
  python -m pipeline.live_data_service auto
"""
import argparse
import datetime
import json
import logging
import sys
import time
from pathlib import Path

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)

# 项目根目录
ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

# A 股交易时间
MARKET_OPEN_AM = datetime.time(9, 30)
MARKET_CLOSE_AM = datetime.time(11, 30)
MARKET_OPEN_PM = datetime.time(13, 0)
MARKET_CLOSE_PM = datetime.time(15, 0)
EOD_TRIGGER_TIME = datetime.time(15, 30)


def is_market_hours() -> bool:
    """判断当前是否在 A 股交易时间"""
    now = datetime.datetime.now().time()
    weekday = datetime.datetime.now().weekday()
    if weekday >= 5:  # 周末
        return False
    return ((MARKET_OPEN_AM <= now <= MARKET_CLOSE_AM) or
            (MARKET_OPEN_PM <= now <= MARKET_CLOSE_PM))


def is_after_close() -> bool:
    """判断是否在收盘后（15:00-23:59）"""
    now = datetime.datetime.now().time()
    weekday = datetime.datetime.now().weekday()
    if weekday >= 5:
        return False
    return now >= MARKET_CLOSE_PM


# ══════════════════════════════════════════════════════════════
# 1. 实时行情轮询
# ══════════════════════════════════════════════════════════════

def poll_realtime(interval: int = 5, symbols: list = None):
    """
    盘中实时行情轮询。

    参数:
        interval: 轮询间隔（秒），默认 5
        symbols: 监控的股票列表，None 时用模拟仓持仓
    """
    from providers.sina_provider import fetch_realtime_quotes

    if symbols is None:
        # 从模拟仓读取持仓
        try:
            from live.paper_trader import PaperTrader
            trader = PaperTrader()
            pos = trader.get_current_positions()
            if isinstance(pos, dict):
                symbols = list(pos.keys())
            elif hasattr(pos, "index"):
                symbols = list(pos.index)
        except Exception:
            pass

    if not symbols:
        # 默认监控一些核心股票
        symbols = ["600000", "000001", "600519", "000858", "601318"]

    logger.info("实时轮询启动: %d 只股票, 间隔 %ds", len(symbols), interval)

    # 实时数据存储路径
    live_dir = ROOT / "live" / "realtime"
    live_dir.mkdir(parents=True, exist_ok=True)

    try:
        while True:
            if not is_market_hours():
                logger.info("非交易时间，等待开盘...")
                time.sleep(60)
                continue

            try:
                quotes = fetch_realtime_quotes(symbols)
                ts = datetime.datetime.now().strftime("%H:%M:%S")

                # 打印摘要
                up, down, flat = 0, 0, 0
                for sym, q in quotes.items():
                    pnl = (q["price"] / q["prev_close"] - 1) if q["prev_close"] > 0 else 0
                    if pnl > 0.001:
                        up += 1
                    elif pnl < -0.001:
                        down += 1
                    else:
                        flat += 1

                logger.info("[%s] %d 只行情: ↑%d ↓%d →%d", ts, len(quotes), up, down, flat)

                # 保存最新快照（覆盖写）
                snapshot = {
                    "timestamp": datetime.datetime.now().isoformat(),
                    "quotes": {s: q for s, q in quotes.items()},
                }
                snapshot_path = live_dir / "latest.json"
                with open(snapshot_path, "w", encoding="utf-8") as f:
                    json.dump(snapshot, f, ensure_ascii=False, indent=2)

            except Exception as e:
                logger.error("轮询异常: %s", e)

            time.sleep(interval)

    except KeyboardInterrupt:
        logger.info("轮询已停止")


# ══════════════════════════════════════════════════════════════
# 2. EOD 自动更新
# ══════════════════════════════════════════════════════════════

def run_eod_update():
    """
    收盘后自动执行：
      1. 更新本地日线数据
      2. 生成当日信号
      3. 更新 freshness 状态
    """
    today = datetime.date.today().strftime("%Y-%m-%d")
    logger.info("EOD 更新开始: %s", today)

    # 1. 更新数据
    try:
        from pipeline.data_update import run_update
        result = run_update(end_date=today)
        updated = len(result.get("updated", []))
        failed = len(result.get("failed", []))
        logger.info("数据更新完成: %d 更新, %d 失败", updated, failed)
    except Exception as e:
        logger.error("数据更新失败: %s", e)
        return

    # 2. 生成信号
    try:
        from pipeline.daily_signal import run_daily_pipeline
        signal = run_daily_pipeline(today)
        picks = signal.get("picks", [])
        logger.info("信号生成完成: %d 只", len(picks))
    except Exception as e:
        logger.warning("信号生成失败（可能非交易日）: %s", e)

    # 3. 检查 freshness
    try:
        from pipeline.data_checker import check_data_freshness
        status = check_data_freshness()
        logger.info("数据状态: %s, 最新: %s", status["status"], status["latest_date"])
    except Exception as e:
        logger.warning("freshness 检查失败: %s", e)

    logger.info("EOD 更新完成")


# ══════════════════════════════════════════════════════════════
# 3. 自动模式
# ══════════════════════════════════════════════════════════════

def auto_mode(interval: int = 5):
    """
    自动模式：
      - 盘中：实时轮询
      - 收盘后：执行 EOD 更新，然后停止
    """
    logger.info("自动模式启动")
    eod_done_today = False

    while True:
        now = datetime.datetime.now()

        if is_market_hours():
            # 盘中轮询
            poll_realtime(interval=interval)
            eod_done_today = False

        elif is_after_close() and not eod_done_today:
            # 收盘后执行 EOD
            logger.info("检测到收盘，执行 EOD 更新...")
            run_eod_update()
            eod_done_today = True
            logger.info("EOD 完成，等待明天...")

        else:
            # 非交易时间
            time.sleep(60)


# ══════════════════════════════════════════════════════════════
# CLI
# ══════════════════════════════════════════════════════════════

def main():
    parser = argparse.ArgumentParser(description="quant-dojo 实时数据服务")
    sub = parser.add_subparsers(dest="cmd")

    p_poll = sub.add_parser("poll", help="盘中实时行情轮询")
    p_poll.add_argument("--interval", type=int, default=5, help="轮询间隔（秒）")

    sub.add_parser("eod", help="收盘后 EOD 更新")

    p_auto = sub.add_parser("auto", help="自动模式（盘中轮询 + 收盘更新）")
    p_auto.add_argument("--interval", type=int, default=5, help="轮询间隔（秒）")

    args = parser.parse_args()

    if args.cmd == "poll":
        poll_realtime(interval=args.interval)
    elif args.cmd == "eod":
        run_eod_update()
    elif args.cmd == "auto":
        auto_mode(interval=args.interval)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
