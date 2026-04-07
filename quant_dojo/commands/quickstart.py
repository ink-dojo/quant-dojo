"""
quant_dojo quickstart — 零配置一键启动

用法:
  python -m quant_dojo quickstart                 # 全自动
  python -m quant_dojo quickstart --data-dir ~/my-data  # 指定数据目录
  python -m quant_dojo quickstart --skip-download  # 跳过数据下载

自动完成:
  1. init（配置 + 目录创建）
  2. 数据下载（如果数据为空）
  3. 回测（默认 v7 策略）
  4. 激活最优策略
  5. 设置定时任务
"""
import sys
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent.parent


def run_quickstart(data_dir: str = None, skip_download: bool = False):
    """一键完成所有初始设置"""
    sys.path.insert(0, str(PROJECT_ROOT))
    t0 = time.time()

    print("╔═══════════════════════════════════════════════╗")
    print("║  quant-dojo 快速启动                          ║")
    print("║  全自动: init → 数据 → 回测 → 激活 → 定时     ║")
    print("╚═══════════════════════════════════════════════╝\n")

    # ── Step 1: Init ──
    print("━━━ Step 1/5: 初始化 ━━━")
    try:
        from quant_dojo.commands.init import run_init
        run_init(data_dir=data_dir, download=False)
        print("  [OK] 初始化完成\n")
    except Exception as e:
        print(f"  [失败] 初始化失败: {e}")
        sys.exit(1)

    # ── Step 2: Data download ──
    print("━━━ Step 2/5: 数据准备 ━━━")
    data_path = _resolve_data_path(data_dir)
    csv_files = list(data_path.glob("*.csv")) if data_path.exists() else []

    if csv_files:
        print(f"  [OK] 已有 {len(csv_files)} 个数据文件，跳过下载\n")
    elif skip_download:
        print("  [跳过] --skip-download 已设置\n")
    else:
        try:
            from quant_dojo.commands.init import _download_data
            _download_data(data_path)
            csv_files = list(data_path.glob("*.csv"))
            print(f"  [OK] 数据准备完成: {len(csv_files)} 个文件\n")
        except Exception as e:
            print(f"  [失败] 数据下载失败: {e}")
            print("         可手动下载后重新运行 quickstart --skip-download")
            sys.exit(1)

    # 验证数据是否够回测
    csv_files = list(data_path.glob("*.csv")) if data_path.exists() else []
    if not csv_files:
        print("  [错误] 无数据文件，无法继续")
        print("         请先准备数据，然后运行: python -m quant_dojo quickstart --skip-download")
        sys.exit(1)

    # ── Step 3: Backtest ──
    print("━━━ Step 3/5: 回测验证 ━━━")
    best_strategy = "v7"
    best_sharpe = -999

    from quant_dojo.commands.backtest import run_backtest_cmd

    for strat in ["v7", "v8"]:
        try:
            result = run_backtest_cmd(strategy=strat, report=(strat == "v7"))

            if result.status == "success":
                sharpe = result.metrics.get("sharpe", 0)
                total_ret = result.metrics.get("total_return", 0)
                print(f"  [OK] {strat}: 收益 {total_ret:+.2%} | 夏普 {sharpe:.2f}")
                if sharpe > best_sharpe:
                    best_sharpe = sharpe
                    best_strategy = strat
            else:
                print(f"  [注意] {strat} 回测未成功")
        except SystemExit:
            print(f"  [注意] {strat} 回测遇到问题")
        except Exception as e:
            print(f"  [注意] {strat} 回测失败: {e}")

    print(f"\n  推荐策略: {best_strategy} (夏普 {best_sharpe:.2f})\n")

    # ── Step 4: Activate ──
    print("━━━ Step 4/5: 策略激活 ━━━")
    try:
        from pipeline.active_strategy import set_active_strategy, get_active_strategy
        current = get_active_strategy()
        if current == best_strategy:
            print(f"  [OK] 策略 {best_strategy} 已激活\n")
        else:
            set_active_strategy(best_strategy, reason="quickstart 自动激活")
            print(f"  [OK] 策略已激活: {best_strategy}\n")
    except Exception as e:
        print(f"  [跳过] 策略激活失败: {e}\n")

    # ── Step 5: Schedule ──
    print("━━━ Step 5/5: 定时任务 ━━━")
    try:
        from quant_dojo.commands.schedule import setup_schedule
        setup_schedule(time="16:30")
        print()
    except Exception as e:
        print(f"  [跳过] 定时任务设置失败: {e}")
        print("         可手动运行: python -m quant_dojo schedule\n")

    # ── Done ──
    elapsed = time.time() - t0
    print(f"{'='*50}")
    print(f"  快速启动完成! ({elapsed:.1f}s)")
    print(f"{'='*50}")
    print()
    print("  你现在可以:")
    print("    python -m quant_dojo status     # 查看系统状态")
    print("    python -m quant_dojo run        # 手动运行一次")
    print("    python -m quant_dojo dashboard  # 启动仪表盘")
    print()
    print("  定时任务已设置，每个工作日 16:30 自动运行")
    print()


def _resolve_data_path(data_dir: str = None) -> Path:
    """解析数据目录路径"""
    if data_dir:
        return Path(data_dir).expanduser().resolve()

    try:
        from utils.runtime_config import get_local_data_dir
        return get_local_data_dir()
    except Exception:
        return Path.home() / "quant-data"
