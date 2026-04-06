"""
quant_dojo update — 增量更新本地行情数据

用法:
  python -m quant_dojo update             # 增量更新全部股票
  python -m quant_dojo update --dry-run   # 查看待更新范围
  python -m quant_dojo update --full      # 全量重新下载
"""
import sys
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent.parent


def run_update(dry_run: bool = False, full: bool = False):
    """运行数据更新"""
    sys.path.insert(0, str(PROJECT_ROOT))
    t0 = time.time()

    print("╔═══════════════════════════════════════════════╗")
    print("║  quant-dojo 数据更新                          ║")
    print("╚═══════════════════════════════════════════════╝\n")

    if dry_run:
        print("  模式: 空跑（仅查看待更新范围）\n")

    # 检查数据目录
    try:
        from utils.runtime_config import get_local_data_dir
        data_dir = get_local_data_dir()
        if not data_dir.exists():
            print(f"  [错误] 数据目录不存在: {data_dir}")
            print("         运行: python -m quant_dojo init --download")
            sys.exit(1)

        csv_count = len(list(data_dir.glob("*.csv")))
        print(f"  数据目录: {data_dir}")
        print(f"  现有文件: {csv_count}")
    except Exception as e:
        print(f"  [错误] 数据目录检测失败: {e}")
        print("         运行: python -m quant_dojo init")
        sys.exit(1)

    # 数据新鲜度
    try:
        from pipeline.data_checker import check_data_freshness
        info = check_data_freshness()
        days_stale = info.get("days_stale", -1)
        latest = info.get("latest_date", "?")
        print(f"  最新数据: {latest} (延迟 {days_stale} 天)")
    except Exception:
        pass

    print()

    # 执行更新
    try:
        from pipeline.data_update import run_update as _run_update

        symbols = None
        if full:
            # 全量模式：从 provider 获取完整股票列表
            print("  [全量模式] 将重新下载所有股票数据")
            try:
                from providers.baostock_provider import BaoStockProvider
                provider = BaoStockProvider()
                symbols = provider.get_stock_list()
                print(f"  股票列表: {len(symbols)} 只")
            except Exception as e:
                print(f"  [错误] 获取股票列表失败: {e}")
                sys.exit(1)

        result = _run_update(symbols=symbols, dry_run=dry_run)

        elapsed = time.time() - t0
        n_updated = len(result.get("updated", []))
        n_skipped = len(result.get("skipped", []))
        n_failed = len(result.get("failed", []))

        print(f"\n{'='*50}")
        print(f"  更新完成 — {elapsed:.1f}s")
        print(f"  更新: {n_updated} | 跳过: {n_skipped} | 失败: {n_failed}")

        if n_failed > 0:
            print(f"\n  部分股票更新失败，可稍后重试:")
            print(f"    python -m quant_dojo update")
        elif n_updated == 0 and n_skipped > 0:
            print(f"\n  数据已是最新，无需更新")
        else:
            print(f"\n  下一步:")
            print(f"    python -m quant_dojo run       # 运行今日流水线")
        print(f"{'='*50}")

    except ImportError as e:
        print(f"  [错误] 缺少数据源依赖: {e}")
        print("         pip install baostock  # 推荐")
        sys.exit(1)
    except Exception as e:
        print(f"  [错误] 数据更新失败: {e}")
        print("         运行 python -m quant_dojo doctor 排查")
        sys.exit(1)
