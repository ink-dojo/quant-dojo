"""
quant_dojo signals — 查看信号历史

用法:
  python -m quant_dojo signals           # 最近 5 天的信号
  python -m quant_dojo signals -n 10     # 最近 10 天
  python -m quant_dojo signals --date 2026-04-03  # 指定日期
"""
import json
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent.parent


def show_signals(n: int = 5, date: str = None):
    """显示信号历史"""
    signal_dir = PROJECT_ROOT / "live" / "signals"

    if not signal_dir.exists():
        print("  尚无信号记录")
        print("  运行: python -m quant_dojo run")
        return

    if date:
        # 查看指定日期
        signal_file = signal_dir / f"{date}.json"
        if not signal_file.exists():
            print(f"  未找到 {date} 的信号记录")
            return
        _print_signal(signal_file)
        return

    # 最近 n 天的信号
    signal_files = sorted(signal_dir.glob("*.json"), reverse=True)[:n]

    if not signal_files:
        print("  尚无信号记录")
        print("  运行: python -m quant_dojo run")
        return

    print(f"{'='*60}")
    print(f"  最近 {len(signal_files)} 天信号")
    print(f"{'='*60}\n")

    for f in signal_files:
        _print_signal(f)
        print()

    print(f"{'='*60}")


def _print_signal(signal_file: Path):
    """打印单天信号"""
    try:
        data = json.loads(signal_file.read_text(encoding="utf-8"))
    except Exception:
        return

    date = data.get("date", signal_file.stem)
    picks = data.get("picks", [])
    strategy = data.get("strategy", "?")
    scores = data.get("scores", {})

    print(f"  {date} | {strategy} | {len(picks)} 只")
    if picks:
        # 显示 top 10
        for i, symbol in enumerate(picks[:10], 1):
            score = scores.get(symbol, "")
            score_str = f" ({score:.4f})" if isinstance(score, (int, float)) else ""
            print(f"    {i:>2}. {symbol}{score_str}")
        if len(picks) > 10:
            print(f"    ... 等 {len(picks)} 只")
