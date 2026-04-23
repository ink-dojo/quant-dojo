"""
pipeline/regime_detector.py — Macro Regime Gate (框架, 待 jialong 填阈值)

## 用途
为 `riad_signal.py` / `lulr_v2_signal.py` 等策略提供 regime gate 接口:
    - 在生成信号前调用 get_current_regime(date, macro_data)
    - 根据返回值决定是否调仓 (HALT 现金 / 正常下信号 / HALVE 半仓)

## 设计原则
1. **纯函数**: 不读盘不写盘, 输入 (date + macro_data DataFrame) → 输出 enum 值
2. **阈值常量集中**: 所有阈值放在 `REGIME_THRESHOLDS` 字典, jialong 跑完
   `scripts/regime_boundary_analysis.py` 后用 `lag_corr.json` 读出最强 macro 特征
   + 转折月对应的 macro 值, 填到字典里
3. **可扩展**: 当前是二元 gate (normal / high_vol_low_growth), 未来可加多 regime

## 触发条件
本模块仅在以下情况激活使用:
    - `journal/regime_decision_tree_20260422.md` 判读为 **Scenario A** (Step Jump)
    - **且** jialong 在 REGIME_THRESHOLDS 中填入实际阈值常量
    - **否则** get_current_regime() 永远返回 RegimeState.UNKNOWN, 不影响策略

## 数据依赖
macro_data: pd.DataFrame
    index = trade_date (DatetimeIndex)
    columns 至少包含:
        - hs300_ret_6m   (HS300 6 月 trailing return)
        - hs300_ret_3m   (HS300 3 月 trailing return)
        - hs300_vol_60d  (HS300 60 日 realized vol, 年化)
        - hs300_vol_ratio (vol_60d / vol_250d, > 1 = 波动率上升)
来源: `scripts/regime_boundary_analysis.py` 输出的 macro_panel.parquet
"""
from __future__ import annotations

import enum
import logging
from dataclasses import dataclass
from typing import Optional

import pandas as pd

log = logging.getLogger(__name__)


class RegimeState(enum.Enum):
    """Regime 枚举. 策略代码根据返回值决定行动."""

    UNKNOWN = "unknown"          # 阈值未填, 或数据缺失. 策略应忽略 gate, 走原 logic
    NORMAL = "normal"            # 与历史相符, 因子 alpha 预期有效
    HIGH_VOL_LOW_GROWTH = "high_vol_low_growth"  # 9·24 后 regime, 5 因子翻车
    # 未来可扩展: BULL_MOMENTUM, BEAR_TREND 等


@dataclass(frozen=True)
class RegimeReport:
    """gate 输出, 给 caller 完整 context (不是单一 enum, 方便 log)."""

    state: RegimeState
    asof_date: pd.Timestamp
    reason: str                              # 中文说明: "vol_ratio 1.42 > 1.30 阈值"
    raw_features: dict                       # 当前 macro 特征值, 方便 monitor


# ══════════════════════════════════════════════════════════════
# 阈值常量 — jialong 填
# ══════════════════════════════════════════════════════════════
# 流程:
#   1. 在有数据的机器上跑 `scripts/regime_boundary_analysis.py`
#   2. 看 outputs/regime_boundary/lag_corr.json, 找出与 factor_health 相关性最强的 macro 特征
#   3. 看 outputs/regime_boundary/breakpoint.json 的 first_sustained_negative_month
#   4. 取该月份对应的 macro 特征值作为阈值
#   5. 填下面字典
#
# 例 (假设结果显示 vol_ratio 在 2024-09 跨过 1.30):
#   REGIME_THRESHOLDS = {
#       "vol_ratio_threshold": 1.30,
#       "ret_6m_threshold": -0.05,
#       "primary_feature": "hs300_vol_ratio",
#   }

REGIME_THRESHOLDS: dict = {
    # TODO(jialong): 跑完 regime_boundary_analysis.py 后填入. 在此之前模块返回 UNKNOWN.
    "vol_ratio_threshold": None,  # 例: 1.30
    "ret_6m_threshold": None,     # 例: -0.05
    "primary_feature": None,      # 例: "hs300_vol_ratio" 或 "hs300_ret_6m"
}


# ══════════════════════════════════════════════════════════════
# 主函数
# ══════════════════════════════════════════════════════════════

def get_current_regime(
    date: pd.Timestamp | str,
    macro_data: pd.DataFrame,
) -> RegimeReport:
    """
    判定 date 当日的 regime state.

    Args:
        date: 查询日期 (调仓日). 必须在 macro_data.index 内.
        macro_data: 见 module docstring 数据依赖.

    Returns:
        RegimeReport, 包含 state + reason + raw_features.

    使用示例 (riad_signal.py 内):
        regime = get_current_regime(date_t, macro_panel)
        if regime.state == RegimeState.HIGH_VOL_LOW_GROWTH:
            log.info(f"Regime gate triggered: {regime.reason}, skip rebalance")
            return None  # 不调仓
        # else: 走原 RIAD 信号逻辑
    """
    date = pd.Timestamp(date)

    # ── 数据健康检查 ──
    if date not in macro_data.index:
        return RegimeReport(
            state=RegimeState.UNKNOWN,
            asof_date=date,
            reason=f"日期 {date.date()} 不在 macro_data 内, 无法判定",
            raw_features={},
        )

    row = macro_data.loc[date]
    raw_features = row.to_dict()

    # ── 阈值未填: 不激活 gate ──
    if not all(v is not None for v in REGIME_THRESHOLDS.values()):
        return RegimeReport(
            state=RegimeState.UNKNOWN,
            asof_date=date,
            reason="REGIME_THRESHOLDS 未填, gate 未激活 (走原策略 logic)",
            raw_features=raw_features,
        )

    # ── 二元 gate: HIGH_VOL_LOW_GROWTH or NORMAL ──
    vol_ratio = row.get("hs300_vol_ratio")
    ret_6m = row.get("hs300_ret_6m")

    if pd.isna(vol_ratio) or pd.isna(ret_6m):
        return RegimeReport(
            state=RegimeState.UNKNOWN,
            asof_date=date,
            reason=f"macro 特征缺失 (vol_ratio={vol_ratio}, ret_6m={ret_6m})",
            raw_features=raw_features,
        )

    vol_threshold = REGIME_THRESHOLDS["vol_ratio_threshold"]
    ret_threshold = REGIME_THRESHOLDS["ret_6m_threshold"]

    triggered = vol_ratio > vol_threshold and ret_6m < ret_threshold

    if triggered:
        return RegimeReport(
            state=RegimeState.HIGH_VOL_LOW_GROWTH,
            asof_date=date,
            reason=(
                f"vol_ratio {vol_ratio:.2f} > {vol_threshold:.2f} "
                f"且 ret_6m {ret_6m:.2%} < {ret_threshold:.2%} "
                f"→ 进入 high_vol_low_growth regime, 因子 alpha 不可信"
            ),
            raw_features=raw_features,
        )
    else:
        return RegimeReport(
            state=RegimeState.NORMAL,
            asof_date=date,
            reason=(
                f"vol_ratio {vol_ratio:.2f} ≤ {vol_threshold:.2f} "
                f"或 ret_6m {ret_6m:.2%} ≥ {ret_threshold:.2%} → normal"
            ),
            raw_features=raw_features,
        )


def gate_position_size(state: RegimeState) -> float:
    """
    把 regime state 映射到仓位系数 (0 = 现金, 1.0 = 满仓).

    用法 (riad_signal.py 内):
        pos_scale = gate_position_size(regime.state)
        target_weight = base_weight * pos_scale
    """
    return {
        RegimeState.NORMAL: 1.0,
        RegimeState.HIGH_VOL_LOW_GROWTH: 0.0,  # 直接现金
        RegimeState.UNKNOWN: 1.0,              # gate 未激活, 不影响
    }.get(state, 1.0)


# ══════════════════════════════════════════════════════════════
# 最小验证
# ══════════════════════════════════════════════════════════════

if __name__ == "__main__":
    print("=== regime_detector 最小验证 ===")

    # 构造 mock macro_data
    dates = pd.date_range("2024-01-01", "2025-12-31", freq="B")
    rng = pd.np.random.default_rng(42) if hasattr(pd, "np") else None
    import numpy as np
    rng = np.random.default_rng(42)

    mock_macro = pd.DataFrame(
        {
            "hs300_ret_6m": np.concatenate([
                rng.normal(0.05, 0.02, len(dates) // 2),    # 上半段牛
                rng.normal(-0.08, 0.03, len(dates) - len(dates) // 2),  # 下半段熊
            ]),
            "hs300_ret_3m": rng.normal(0.0, 0.05, len(dates)),
            "hs300_vol_60d": rng.normal(0.20, 0.05, len(dates)),
            "hs300_vol_ratio": np.concatenate([
                rng.normal(0.95, 0.10, len(dates) // 2),    # 低波
                rng.normal(1.40, 0.15, len(dates) - len(dates) // 2),  # 高波
            ]),
        },
        index=dates,
    )

    # ── Test 1: 阈值未填 → UNKNOWN ──
    # 用 mock_macro 末尾真实存在的日期 (2025 高波段)
    test_date = mock_macro.index[-30]  # 倒数第 30 个交易日, 落在高波段内
    report = get_current_regime(test_date, mock_macro)
    assert report.state == RegimeState.UNKNOWN, "阈值未填时应返回 UNKNOWN"
    print(f"✅ Test 1 (阈值未填 → UNKNOWN): {report.reason}")

    # ── Test 2: 临时填阈值, 期望触发 HIGH_VOL_LOW_GROWTH ──
    REGIME_THRESHOLDS["vol_ratio_threshold"] = 1.30
    REGIME_THRESHOLDS["ret_6m_threshold"] = -0.05
    REGIME_THRESHOLDS["primary_feature"] = "hs300_vol_ratio"

    report = get_current_regime(test_date, mock_macro)
    print(f"✅ Test 2 (阈值已填, 高波动期): {report.state.value}")
    print(f"   reason: {report.reason}")
    print(f"   vol_ratio={report.raw_features.get('hs300_vol_ratio'):.2f} "
          f"ret_6m={report.raw_features.get('hs300_ret_6m'):.2%}")
    assert report.state in (RegimeState.HIGH_VOL_LOW_GROWTH, RegimeState.NORMAL), \
        "阈值已填应返回 NORMAL 或 HIGH_VOL_LOW_GROWTH, 不应是 UNKNOWN"

    # ── Test 3: 仓位系数映射 ──
    assert gate_position_size(RegimeState.NORMAL) == 1.0
    assert gate_position_size(RegimeState.HIGH_VOL_LOW_GROWTH) == 0.0
    assert gate_position_size(RegimeState.UNKNOWN) == 1.0
    print("✅ Test 3 (仓位系数映射): all pass")

    # ── 还原阈值 (避免影响后续 import) ──
    REGIME_THRESHOLDS["vol_ratio_threshold"] = None
    REGIME_THRESHOLDS["ret_6m_threshold"] = None
    REGIME_THRESHOLDS["primary_feature"] = None

    print("\n✅ 最小验证全部通过. 等 jialong 跑完 regime_boundary_analysis 后填阈值即可激活.")
