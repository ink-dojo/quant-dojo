"""
quant_dojo dashboard — 启动可视化仪表盘

一键启动 Streamlit 仪表盘，展示持仓、绩效、因子、信号、告警、回测结果。
"""
import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent.parent


def launch_dashboard(port: int = 8501):
    """启动 Streamlit dashboard"""
    app_path = PROJECT_ROOT / "streamlit_dashboard" / "app.py"

    if not app_path.exists():
        print(f"  [错误] Dashboard 文件不存在: {app_path}")
        sys.exit(1)

    # 检查 streamlit 是否安装
    try:
        import streamlit
    except ImportError:
        print("  [错误] streamlit 未安装")
        print("  安装: pip install streamlit")
        sys.exit(1)

    # 检查数据文件
    data_path = PROJECT_ROOT / "live" / "dashboard" / "dashboard_data.json"
    if not data_path.exists():
        print("  [提示] Dashboard 数据文件不存在")
        print("         先运行: python -m quant_dojo run")
        print("         或手动导出: python -m pipeline.dashboard_export")
        print()

    print("╔═══════════════════════════════════════════════╗")
    print("║  quant-dojo Dashboard                         ║")
    print("╚═══════════════════════════════════════════════╝")
    print(f"  地址: http://localhost:{port}")
    print(f"  按 Ctrl+C 停止")
    print()

    subprocess.run(
        [sys.executable, "-m", "streamlit", "run", str(app_path),
         "--server.port", str(port),
         "--server.headless", "true"],
        cwd=str(PROJECT_ROOT),
    )
