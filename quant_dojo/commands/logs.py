"""
quant_dojo logs — 查看运行历史

用法:
  python -m quant_dojo logs           # 最近 10 次运行
  python -m quant_dojo logs -n 20     # 最近 20 次
  python -m quant_dojo logs --detail  # 显示步骤详情
"""
import json
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent.parent


def show_logs(n: int = 10, detail: bool = False):
    """显示最近的运行日志"""
    log_dir = PROJECT_ROOT / "logs"

    if not log_dir.exists():
        print("  尚无运行记录")
        print("  运行: python -m quant_dojo run")
        return

    # 按文件名倒序（日期越新越前）
    log_files = sorted(log_dir.glob("quant_dojo_run_*.json"), reverse=True)

    if not log_files:
        print("  尚无运行记录")
        print("  运行: python -m quant_dojo run")
        return

    log_files = log_files[:n]

    print(f"{'='*60}")
    print(f"  最近 {len(log_files)} 次运行")
    print(f"{'='*60}\n")

    for log_file in log_files:
        try:
            data = json.loads(log_file.read_text(encoding="utf-8"))
        except Exception:
            continue

        date = data.get("date", "?")
        ts = data.get("timestamp", "")[:19]
        elapsed = data.get("elapsed_sec", 0)
        steps = data.get("steps", {})

        n_ok = sum(1 for s in steps.values() if s.get("status") != "failed")
        n_fail = sum(1 for s in steps.values() if s.get("status") == "failed")

        status_mark = "OK" if n_fail == 0 else "FAIL"
        print(f"  [{status_mark}] {date}  {ts}  {elapsed:.1f}s  ({n_ok} ok / {n_fail} fail)")

        if detail:
            for step_name, step_data in steps.items():
                s = step_data.get("status", "?")
                mark = "ok" if s != "failed" else "FAIL"
                line = f"        {step_name}: [{mark}]"
                if step_data.get("error"):
                    line += f" — {step_data['error'][:60]}"
                print(line)
            print()

    if not detail and any(
        any(s.get("status") == "failed" for s in json.loads(f.read_text(encoding="utf-8")).get("steps", {}).values())
        for f in log_files[:3]
        if f.exists()
    ):
        print(f"\n  有失败记录，使用 --detail 查看详情")

    print(f"\n{'='*60}")
