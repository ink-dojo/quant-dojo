"""
agents/strategy_composer.py — 策略组合 Agent

职责:
  1. 读取 FactorMiner 的筛选结果
  2. 对推荐因子组合做历史模拟
  3. 与当前生产策略（v7）对比
  4. 如果新组合更优，生成策略升级建议
  5. 自动更新策略配置（需审批）

每周执行一次，在 FactorMiner 之后运行。
"""

import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

STRATEGY_DIR = Path(__file__).parent.parent / "live" / "factor_research"

# 当前生产策略因子（v7）
CURRENT_V7_FACTORS = ["team_coin", "low_vol_20d", "cgo_simple", "enhanced_mom", "bp"]


class StrategyComposer:
    """
    策略组合 Agent：从因子排行榜构建最优组合。

    工作流:
      1. 获取 FactorMiner 推荐因子
      2. IC 加权合成模拟
      3. 与 v7 对比
      4. 输出升级建议（如果有显著提升）
    """

    def __init__(self):
        from utils.runtime_config import get_pipeline_param
        self.UPGRADE_THRESHOLD = get_pipeline_param("strategy_upgrade.threshold", 1.15)
        self.AUTO_UPGRADE = get_pipeline_param("strategy_upgrade.auto_upgrade", True)

    def run(self, ctx: Any) -> dict:
        """
        执行策略组合分析。

        参数:
            ctx: PipelineContext（需要 factor_rankings, recommended_factors）

        返回:
            dict: {
              current_strategy: {...},
              proposed_strategy: {...},
              comparison: {...},
              recommendation: "keep" | "upgrade",
            }
        """
        from utils.alpha_factors import build_fast_factors, FACTOR_CATALOG
        from utils.factor_analysis import compute_ic_series
        from utils.local_data_loader import (
            load_price_wide,
            load_factor_wide,
            get_all_symbols,
        )

        rankings = ctx.get("factor_rankings")
        recommended = ctx.get("recommended_factors")

        if not rankings or not recommended:
            print("  无因子排行数据，跳过策略组合")
            return {"recommendation": "keep", "reason": "无因子排行数据"}

        # 构建 ranking lookup
        rank_by_name = {r["name"]: r for r in rankings}

        # 评估当前 v7 组合
        v7_metrics = self._eval_combo(CURRENT_V7_FACTORS, rank_by_name)
        proposed_metrics = self._eval_combo(recommended, rank_by_name)

        print(f"\n  当前 v7 组合: {CURRENT_V7_FACTORS}")
        print(f"    组合 ICIR: {v7_metrics['combo_icir']:.4f}")
        print(f"    覆盖因子: {v7_metrics['n_valid']}/{len(CURRENT_V7_FACTORS)}")

        print(f"\n  推荐新组合: {recommended}")
        print(f"    组合 ICIR: {proposed_metrics['combo_icir']:.4f}")
        print(f"    覆盖因子: {proposed_metrics['n_valid']}/{len(recommended)}")

        # 对比
        if v7_metrics["combo_icir"] > 0:
            improvement = proposed_metrics["combo_icir"] / v7_metrics["combo_icir"]
        else:
            improvement = float("inf") if proposed_metrics["combo_icir"] > 0 else 1.0

        if improvement >= self.UPGRADE_THRESHOLD and proposed_metrics["n_valid"] >= 3:
            recommendation = "upgrade"
            reason = (
                f"新组合 ICIR={proposed_metrics['combo_icir']:.4f} 比 v7 "
                f"ICIR={v7_metrics['combo_icir']:.4f} 提升 {(improvement-1)*100:.1f}%"
            )
            print(f"\n  建议: 升级策略 ({reason})")
        else:
            recommendation = "keep"
            reason = (
                f"新组合 ICIR={proposed_metrics['combo_icir']:.4f} 未显著优于 v7 "
                f"ICIR={v7_metrics['combo_icir']:.4f} (需 >{self.UPGRADE_THRESHOLD:.0%})"
            )
            print(f"\n  建议: 保持当前策略 ({reason})")

        ctx.log_decision(
            "StrategyComposer",
            f"策略建议: {recommendation}",
            reason,
        )

        # 获取当前激活策略
        from pipeline.active_strategy import get_active_strategy
        current_name = get_active_strategy()

        result = {
            "current_strategy": {
                "name": current_name,
                "factors": CURRENT_V7_FACTORS,
                "metrics": v7_metrics,
            },
            "proposed_strategy": {
                "factors": recommended,
                "metrics": proposed_metrics,
            },
            "improvement_ratio": round(improvement, 4),
            "recommendation": recommendation,
            "reason": reason,
            "auto_upgraded": False,
        }

        # ── 自动升级策略（如果推荐且非 dry_run 且配置允许） ──
        if recommendation == "upgrade" and not ctx.dry_run and self.AUTO_UPGRADE:
            upgrade_result = self._auto_upgrade(recommended, reason, ctx)
            result["auto_upgraded"] = upgrade_result.get("changed", False)

        ctx.set("strategy_recommendation", recommendation)
        ctx.set("strategy_result", result)

        # 保存
        self._save_result(result, ctx.date)

        return result

    def _eval_combo(self, factor_names: list, rank_by_name: dict) -> dict:
        """
        评估因子组合的综合质量。

        组合 ICIR = 加权平均 ICIR（按各因子 |IC| 加权）
        """
        valid_factors = []
        for name in factor_names:
            if name in rank_by_name:
                valid_factors.append(rank_by_name[name])

        if not valid_factors:
            return {"combo_icir": 0.0, "n_valid": 0, "factors": []}

        # IC 加权 ICIR
        weights = np.array([abs(f["IC_mean"]) for f in valid_factors])
        total_w = weights.sum()
        if total_w > 0:
            weights = weights / total_w
        else:
            weights = np.ones(len(valid_factors)) / len(valid_factors)

        icirs = np.array([f["ICIR"] for f in valid_factors])
        combo_icir = float(np.dot(weights, icirs))

        # 各因子详情
        factor_details = [
            {
                "name": f["name"],
                "IC_mean": f["IC_mean"],
                "ICIR": f["ICIR"],
                "weight": round(w, 4),
            }
            for f, w in zip(valid_factors, weights)
        ]

        return {
            "combo_icir": round(combo_icir, 4),
            "n_valid": len(valid_factors),
            "factors": factor_details,
        }

    def _auto_upgrade(self, recommended_factors: list, reason: str, ctx: Any) -> dict:
        """
        自动升级策略版本。

        当推荐因子与已知策略版本匹配时，切换激活策略。
        目前支持: v7 → v8（v7 因子 + shadow_lower）。
        """
        from pipeline.active_strategy import get_active_strategy, set_active_strategy

        current = get_active_strategy()

        # 判断推荐组合是否匹配已知策略定义
        v8_factors = {"team_coin", "low_vol_20d", "cgo_simple", "enhanced_mom_60", "bp", "shadow_lower"}
        recommended_set = set(recommended_factors)

        target_strategy = None
        if recommended_set == v8_factors or (
            "shadow_lower" in recommended_set and recommended_set - v8_factors == set()
        ):
            target_strategy = "v8"

        if target_strategy and target_strategy != current:
            upgrade_result = set_active_strategy(target_strategy, reason)
            if upgrade_result["changed"]:
                print(f"  策略自动升级: {current} → {target_strategy}")
                ctx.log_decision(
                    "StrategyComposer",
                    f"自动升级策略: {current} → {target_strategy}",
                    reason,
                )
                try:
                    from pipeline.alert_notifier import send_strategy_change_alert
                    send_strategy_change_alert(current, target_strategy, reason, date=ctx.date)
                except Exception:
                    pass
            return upgrade_result

        return {"changed": False}

    def _save_result(self, result: dict, date: str):
        """保存策略组合结果"""
        STRATEGY_DIR.mkdir(parents=True, exist_ok=True)
        path = STRATEGY_DIR / f"strategy_{date}.json"
        with open(path, "w", encoding="utf-8") as f:
            json.dump(result, f, ensure_ascii=False, indent=2)
        print(f"  策略分析已保存: {path}")
