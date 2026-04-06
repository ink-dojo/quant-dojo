"""
quant_dojo schedule — 设置定时自动运行

生成 crontab 条目，每个交易日自动执行全流程。
"""
import os
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent.parent


def setup_schedule(time: str = "16:30", remove: bool = False):
    """设置或移除定时任务"""
    sys.path.insert(0, str(PROJECT_ROOT))

    python_path = sys.executable
    project_dir = str(PROJECT_ROOT)
    marker = "# quant-dojo-auto"

    if remove:
        _remove_cron(marker)
        print("  [OK] 已移除 quant-dojo 定时任务")
        return

    hour, minute = time.split(":")

    # 生成 crontab 行
    cron_line = (
        f"{minute} {hour} * * 1-5 "
        f"cd {project_dir} && {python_path} -m quant_dojo run "
        f">> {project_dir}/logs/cron.log 2>&1 {marker}"
    )

    print("╔═══════════════════════════════════════════════╗")
    print("║  quant-dojo 定时任务设置                       ║")
    print("╚═══════════════════════════════════════════════╝\n")
    print(f"  执行时间: 每个工作日 {time}")
    print(f"  项目目录: {project_dir}")
    print(f"  Python: {python_path}")
    print()
    print(f"  crontab 条目:")
    print(f"  {cron_line}")
    print()

    # 检查当前 crontab
    existing = _get_current_crontab()
    if marker in existing:
        print("  [注意] 已存在 quant-dojo 定时任务，将替换")
        _remove_cron(marker)

    _add_cron(cron_line)
    print("  [OK] 定时任务已添加")
    print()
    print("  查看: crontab -l")
    print("  移除: python -m quant_dojo schedule --remove")


def _get_current_crontab() -> str:
    """获取当前 crontab"""
    try:
        import subprocess
        result = subprocess.run(["crontab", "-l"], capture_output=True, text=True)
        return result.stdout if result.returncode == 0 else ""
    except Exception:
        return ""


def _add_cron(line: str):
    """添加 crontab 条目"""
    import subprocess

    current = _get_current_crontab()
    new_crontab = current.rstrip("\n") + "\n" + line + "\n"

    proc = subprocess.run(
        ["crontab", "-"],
        input=new_crontab,
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        raise RuntimeError(f"crontab 设置失败: {proc.stderr}")


def _remove_cron(marker: str):
    """移除包含 marker 的 crontab 条目"""
    import subprocess

    current = _get_current_crontab()
    lines = [l for l in current.split("\n") if marker not in l]
    new_crontab = "\n".join(lines).strip() + "\n"

    subprocess.run(
        ["crontab", "-"],
        input=new_crontab,
        capture_output=True,
        text=True,
    )
