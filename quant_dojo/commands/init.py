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


def run_init(data_dir: str = None):
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
    else:
        print("  [注意] 数据目录为空，需要先下载行情数据")
        print(f"         将 A 股日线 CSV 放入: {data_path}")
        print("         文件格式: sh.600000.csv / sz.000001.csv")

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
    print(f"\n{'='*50}")
    print("  初始化完成! 下一步:")
    print(f"{'='*50}")
    if not csv_files:
        print("  1. 下载 A 股日线数据到数据目录")
        print("     或运行: python -m pipeline.cli data update")
    print("  2. 运行回测验证:")
    print("     python -m quant_dojo backtest")
    print("  3. 启动每日流水线:")
    print("     python -m quant_dojo run")
    print()


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
