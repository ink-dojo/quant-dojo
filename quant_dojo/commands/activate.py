"""
quant_dojo activate — 将回测策略部署为 live 策略

用法:
  python -m quant_dojo activate v8                    # 切换到 v8
  python -m quant_dojo activate v7 --reason "Q2验证通过"  # 带原因
  python -m quant_dojo activate --show                # 查看当前策略和历史
"""
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent.parent


def run_activate(strategy: str = None, reason: str = "", show: bool = False):
    """激活策略"""
    sys.path.insert(0, str(PROJECT_ROOT))
    from pipeline.active_strategy import (
        get_active_strategy,
        set_active_strategy,
        get_strategy_history,
        VALID_STRATEGIES,
    )

    if show or strategy is None:
        _show_current(get_active_strategy, get_strategy_history, VALID_STRATEGIES)
        return

    print("╔═══════════════════════════════════════════════╗")
    print("║  quant-dojo 策略激活                           ║")
    print("╚═══════════════════════════════════════════════╝\n")

    current = get_active_strategy()
    print(f"  当前策略: {current}")
    print(f"  目标策略: {strategy}")

    if strategy == current:
        print(f"\n  [OK] 策略已经是 {strategy}，无需切换")
        return

    if strategy not in VALID_STRATEGIES:
        print(f"\n  [错误] 未知策略: {strategy}")
        print(f"  可选: {', '.join(sorted(VALID_STRATEGIES))}")
        sys.exit(1)

    result = set_active_strategy(strategy, reason=reason or f"手动切换到 {strategy}")
    print(f"\n  [OK] 策略已切换: {result['previous']} → {result['current']}")
    print()
    print("  下一步:")
    print("    python -m quant_dojo run   # 用新策略运行")


def _show_current(get_active_strategy, get_strategy_history, valid_strategies):
    """显示当前策略状态"""
    print("╔═══════════════════════════════════════════════╗")
    print("║  quant-dojo 策略状态                           ║")
    print("╚═══════════════════════════════════════════════╝\n")

    current = get_active_strategy()
    print(f"  当前策略: {current}")
    print(f"  可选策略: {', '.join(sorted(valid_strategies))}")

    history = get_strategy_history()
    if history:
        print(f"\n  切换历史 (最近 {min(len(history), 5)} 条):")
        for h in history[-5:]:
            date = h.get("date", "?")[:10]
            print(f"    {date}: {h.get('from', '?')} → {h.get('to', '?')} ({h.get('reason', '')})")
    else:
        print("\n  无切换历史")
