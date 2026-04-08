"""
pipeline/active_strategy.py — 生产策略状态管理

管理当前激活的策略版本，支持策略切换和历史记录。

策略状态存储在 live/strategy_state.json，格式:
{
  "active_strategy": "v7",
  "updated_at": "2026-04-03T16:30:00",
  "history": [
    {"from": "v7", "to": "v8", "reason": "...", "date": "2026-04-07"}
  ]
}
"""

import json
import logging
from datetime import datetime
from pathlib import Path

logger = logging.getLogger(__name__)

STATE_FILE = Path(__file__).parent.parent / "live" / "strategy_state.json"

# 合法的策略版本
# auto_gen: 由 quant_dojo generate 自动生成的策略，定义存于
# strategies/generated/auto_gen_latest.json
VALID_STRATEGIES = {"ad_hoc", "v7", "v8", "auto_gen"}

# 默认策略
DEFAULT_STRATEGY = "v7"


def _load_state() -> dict:
    """加载策略状态文件"""
    if STATE_FILE.exists():
        try:
            with open(STATE_FILE, encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            logger.warning("读取策略状态文件失败: %s", e)
    return {
        "active_strategy": DEFAULT_STRATEGY,
        "updated_at": datetime.now().isoformat(),
        "history": [],
    }


def _save_state(state: dict):
    """保存策略状态文件"""
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)


def get_active_strategy() -> str:
    """
    获取当前激活的策略名称。

    返回:
        str: 策略名称（如 "v7", "v8"）
    """
    state = _load_state()
    strategy = state.get("active_strategy", DEFAULT_STRATEGY)
    if strategy not in VALID_STRATEGIES:
        logger.warning("策略 %s 不在合法列表中，回退到 %s", strategy, DEFAULT_STRATEGY)
        return DEFAULT_STRATEGY
    return strategy


def set_active_strategy(strategy: str, reason: str = "") -> dict:
    """
    切换激活的策略。

    参数:
        strategy: 新策略名称
        reason: 切换原因

    返回:
        dict: {"previous": str, "current": str, "changed": bool}
    """
    if strategy not in VALID_STRATEGIES:
        raise ValueError(f"策略 {strategy!r} 不合法，必须是 {VALID_STRATEGIES} 之一")

    state = _load_state()
    previous = state.get("active_strategy", DEFAULT_STRATEGY)

    if previous == strategy:
        return {"previous": previous, "current": strategy, "changed": False}

    # 记录历史
    state["history"].append({
        "from": previous,
        "to": strategy,
        "reason": reason,
        "date": datetime.now().isoformat(),
    })

    # 只保留最近 20 条历史
    state["history"] = state["history"][-20:]

    state["active_strategy"] = strategy
    state["updated_at"] = datetime.now().isoformat()
    _save_state(state)

    logger.info("策略切换: %s → %s (原因: %s)", previous, strategy, reason)
    return {"previous": previous, "current": strategy, "changed": True}


def get_strategy_history() -> list:
    """获取策略切换历史"""
    state = _load_state()
    return state.get("history", [])
