"""
quant_dojo init — 首次设置

自动完成：
  1. 检测/创建数据目录
  2. 生成 config.yaml（如果不存在）
  3. 验证数据是否可用
  4. 给出下一步提示
"""
import shutil
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent.parent
CONFIG_DIR = PROJECT_ROOT / "config"
CONFIG_FILE = CONFIG_DIR / "config.yaml"
CONFIG_EXAMPLE = CONFIG_DIR / "config.example.yaml"


def run_init(data_dir: str = None, download: bool = False):
    """运行初始化设置"""
    print("╔═══════════════════════════════════════════════╗")
    print("║  quant-dojo 初始化设置                        ║")
    print("╚═══════════════════════════════════════════════╝\n")

    # ── 1. 数据目录 ──
    if data_dir:
        data_path = Path(data_dir).expanduser().resolve()
    else:
        data_path = _detect_data_dir()

    print(f"  数据目录: {data_path}")

    if not data_path.exists():
        print(f"  [创建] {data_path}")
        data_path.mkdir(parents=True, exist_ok=True)

    # 检查数据文件
    csv_files = list(data_path.glob("*.csv"))
    if csv_files:
        print(f"  [OK] 发现 {len(csv_files)} 个 CSV 数据文件")
    elif download:
        print("  [下载] 正在下载 A 股日线数据...")
        _download_data(data_path)
    else:
        print("  [注意] 数据目录为空")
        print("         运行 python -m quant_dojo init --download 自动下载")
        print("         或手动将 CSV 放入: {data_path}")

    # ── 2. 配置文件 ──
    if CONFIG_FILE.exists():
        print(f"\n  配置文件已存在: {CONFIG_FILE}")
        _update_config_data_dir(data_path)
    else:
        print(f"\n  [创建] 配置文件: {CONFIG_FILE}")
        _create_config(data_path)

    # ── 3. 必要目录 ──
    for d in ["live/signals", "live/portfolio", "live/runs", "journal", "logs"]:
        p = PROJECT_ROOT / d
        if not p.exists():
            p.mkdir(parents=True, exist_ok=True)
            print(f"  [创建] {d}/")

    # ── 4. 验证 ──
    print("\n  运行系统诊断...")
    issues = _quick_check(data_path)
    if issues:
        print("\n  [问题]")
        for issue in issues:
            print(f"    - {issue}")
    else:
        print("  [OK] 系统就绪")

    # ── 5. 下一步 ──
    csv_files = list(data_path.glob("*.csv"))  # re-check after potential download
    print(f"\n{'='*50}")
    print("  初始化完成! 下一步:")
    print(f"{'='*50}")
    if not csv_files:
        print("  1. 下载数据:")
        print("     python -m quant_dojo init --download")
    print("  2. 运行回测验证:")
    print("     python -m quant_dojo backtest")
    print("  3. 启动每日流水线:")
    print("     python -m quant_dojo run")
    print()


def _download_data(data_path: Path):
    """下载 A 股日线数据到指定目录"""
    import sys
    sys.path.insert(0, str(PROJECT_ROOT))

    try:
        from pipeline.data_update import run_update

        # 先尝试获取少量股票做测试
        print("  正在获取股票列表...")
        result = run_update(end_date=None, dry_run=False)

        n_updated = len(result.get("updated", []))
        n_failed = len(result.get("failed", []))
        n_skipped = len(result.get("skipped", []))

        print(f"\n  下载完成:")
        print(f"    成功: {n_updated}")
        print(f"    跳过: {n_skipped}")
        if n_failed:
            print(f"    失败: {n_failed}")

        csv_count = len(list(data_path.glob("*.csv")))
        if csv_count > 0:
            print(f"  [OK] 数据目录现有 {csv_count} 个文件")
        else:
            print("  [注意] 下载完成但数据目录仍为空")
            print("         可能需要检查网络或数据源配置")

    except ImportError as e:
        print(f"  [失败] 缺少依赖: {e}")
        print("         pip install baostock  # 推荐")
        print("         pip install akshare   # 备选")
    except Exception as e:
        print(f"  [失败] 下载失败: {e}")
        print("         请检查网络连接后重试")


def _detect_data_dir() -> Path:
    """自动检测数据目录"""
    candidates = [
        Path.home() / "quant-data",
        Path.home() / "data" / "quant-data",
        PROJECT_ROOT / "data" / "raw",
    ]

    # 检查配置文件
    if CONFIG_FILE.exists():
        try:
            import yaml
            with open(CONFIG_FILE) as f:
                cfg = yaml.safe_load(f) or {}
            configured = cfg.get("phase5", {}).get("local_data_dir", "")
            if configured:
                p = Path(configured).expanduser()
                if p.exists():
                    return p
                candidates.insert(0, p)
        except Exception:
            pass

    # 自动检测
    for p in candidates:
        if p.exists() and list(p.glob("*.csv")):
            return p

    return candidates[0]  # 默认 ~/quant-data


def _create_config(data_path: Path):
    """从模板创建配置文件"""
    if CONFIG_EXAMPLE.exists():
        shutil.copy(CONFIG_EXAMPLE, CONFIG_FILE)
    else:
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        CONFIG_FILE.write_text(
            f"phase5:\n  local_data_dir: \"{data_path}\"\n\n"
            f"pipeline:\n  default_strategy: \"v7\"\n",
            encoding="utf-8",
        )

    _update_config_data_dir(data_path)


def _update_config_data_dir(data_path: Path):
    """更新配置文件中的数据目录"""
    try:
        content = CONFIG_FILE.read_text(encoding="utf-8")
        import re
        new_content = re.sub(
            r'(local_data_dir:\s*)["\']?[^"\'\n]*["\']?',
            f'\\1"{data_path}"',
            content,
        )
        if new_content != content:
            CONFIG_FILE.write_text(new_content, encoding="utf-8")
            print(f"  [更新] config.yaml 数据目录 → {data_path}")
    except Exception:
        pass


def _quick_check(data_path: Path) -> list[str]:
    """快速系统检查"""
    issues = []

    # Python 依赖
    for pkg in ["numpy", "pandas", "scipy"]:
        try:
            __import__(pkg)
        except ImportError:
            issues.append(f"缺少依赖: {pkg}（pip install {pkg}）")

    # 数据目录
    if not data_path.exists():
        issues.append(f"数据目录不存在: {data_path}")
    elif not list(data_path.glob("*.csv")):
        issues.append("数据目录为空，需要下载行情数据")

    return issues
