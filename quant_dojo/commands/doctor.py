"""
quant_dojo doctor — 系统诊断

检查所有依赖、配置、数据是否就绪，帮助定位问题。
"""
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent.parent


def run_doctor():
    """运行系统诊断"""
    sys.path.insert(0, str(PROJECT_ROOT))

    print("╔═══════════════════════════════════════════════╗")
    print("║  quant-dojo 系统诊断                          ║")
    print("╚═══════════════════════════════════════════════╝\n")

    issues = []
    warnings = []

    # ── 1. Python 依赖 ──
    print("━━━ 依赖检查 ━━━")
    required = {
        "numpy": "数值计算",
        "pandas": "数据处理",
        "scipy": "统计检验",
        "yaml": "配置文件 (pyyaml)",
    }
    optional = {
        "akshare": "A股数据源",
        "streamlit": "Dashboard",
        "matplotlib": "绘图",
    }

    for pkg, desc in required.items():
        try:
            __import__(pkg)
            print(f"  [OK] {pkg} — {desc}")
        except ImportError:
            print(f"  [缺失] {pkg} — {desc}")
            issues.append(f"缺少必要依赖: {pkg}")

    for pkg, desc in optional.items():
        try:
            __import__(pkg)
            print(f"  [OK] {pkg} — {desc}")
        except ImportError:
            print(f"  [可选] {pkg} — {desc} (未安装)")

    # ── 2. 配置文件 ──
    print("\n━━━ 配置检查 ━━━")
    config_file = PROJECT_ROOT / "config" / "config.yaml"
    if config_file.exists():
        print(f"  [OK] config.yaml 存在")
        try:
            from utils.runtime_config import get_config, get_local_data_dir
            cfg = get_config()
            data_dir = get_local_data_dir()
            print(f"  数据目录: {data_dir}")
            strategy = cfg.get("pipeline", {}).get("default_strategy", "v7")
            print(f"  默认策略: {strategy}")
        except Exception as e:
            print(f"  [问题] 配置解析失败: {e}")
            issues.append("config.yaml 解析失败")
    else:
        print(f"  [缺失] config.yaml 不存在")
        print("         运行 `python -m quant_dojo init` 创建")
        warnings.append("config.yaml 不存在，使用默认配置")

    # ── 3. 数据 ──
    print("\n━━━ 数据检查 ━━━")
    try:
        from utils.runtime_config import get_local_data_dir
        data_dir = get_local_data_dir()
        if data_dir.exists():
            csv_files = list(data_dir.glob("*.csv"))
            print(f"  [OK] 数据目录存在: {data_dir}")
            print(f"  CSV 文件: {len(csv_files)}")
            if len(csv_files) == 0:
                issues.append("数据目录为空")
        else:
            print(f"  [缺失] 数据目录不存在: {data_dir}")
            issues.append(f"数据目录不存在: {data_dir}")
    except Exception as e:
        print(f"  [问题] 数据检查失败: {e}")

    # 新鲜度
    try:
        from pipeline.data_checker import check_data_freshness
        info = check_data_freshness()
        stale = info.get("days_stale", -1)
        latest = info.get("latest_date", "?")
        if stale > 5:
            print(f"  [过期] 最新数据: {latest} (延迟 {stale} 天)")
            warnings.append(f"数据过期 {stale} 天")
        else:
            print(f"  [OK] 最新数据: {latest} (延迟 {stale} 天)")
    except Exception:
        pass

    # ── 4. 目录结构 ──
    print("\n━━━ 目录结构 ━━━")
    for d in ["live/signals", "live/portfolio", "live/runs", "journal", "logs"]:
        p = PROJECT_ROOT / d
        if p.exists():
            print(f"  [OK] {d}/")
        else:
            print(f"  [缺失] {d}/")
            warnings.append(f"目录 {d} 不存在（运行 init 创建）")

    # ── 5. 核心模块 ──
    print("\n━━━ 模块检查 ━━━")
    modules = [
        ("utils.local_data_loader", "本地数据加载"),
        ("utils.alpha_factors", "因子计算"),
        ("pipeline.daily_signal", "信号生成"),
        ("backtest.standardized", "标准化回测"),
        ("strategies.multi_factor", "多因子策略"),
        ("live.paper_trader", "模拟交易"),
    ]
    for mod, desc in modules:
        try:
            __import__(mod)
            print(f"  [OK] {mod} — {desc}")
        except Exception as e:
            err = str(e).split("\n")[0][:50]
            print(f"  [问题] {mod} — {err}")
            issues.append(f"模块导入失败: {mod}")

    # ── 总结 ──
    print(f"\n{'='*50}")
    if not issues and not warnings:
        print("  [OK] 系统就绪，可以开始使用")
        print(f"{'='*50}")
        print("\n  下一步:")
        print("    python -m quant_dojo backtest     # 回测验证")
        print("    python -m quant_dojo run           # 每日流水线")
    elif not issues:
        print(f"  系统基本就绪 ({len(warnings)} 个提示)")
        for w in warnings:
            print(f"    - {w}")
    else:
        print(f"  发现 {len(issues)} 个问题:")
        for i in issues:
            print(f"    [!] {i}")
        if warnings:
            print(f"  另有 {len(warnings)} 个提示:")
            for w in warnings:
                print(f"    - {w}")
    print(f"{'='*50}")
