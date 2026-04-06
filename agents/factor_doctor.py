"""
agents/factor_doctor.py — 因子诊断与自动替换 Agent

当因子健康检查发现失效因子时，自动从最近的因子挖掘结果中
推荐替换因子，生成替换建议报告。

工作流:
  1. 读取因子健康报告 → 识别 dead/degraded 因子
  2. 读取最近的因子挖掘结果 → 获取候选替换因子
  3. 排除已在使用的健康因子 → 避免重复
  4. 检查候选因子与存活因子的相关性 → 避免共线
  5. 输出替换建议，可选自动应用
"""

import json
import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

RESEARCH_DIR = Path(__file__).parent.parent / "live" / "factor_research"


class FactorDoctor:
    """因子诊断 Agent：检查因子健康并推荐替换。"""

    # 替换因子的最低门槛
    MIN_ABS_ICIR = 0.2
    MIN_ABS_IC = 0.015

    # 与存活因子的相关性阈值
    CORRELATION_THRESHOLD = 0.7

    def run(self, ctx: Any) -> dict:
        """
        诊断因子健康并生成替换建议。

        返回:
            dict: {
                "sick_factors": [...],
                "replacements": {factor_name: replacement_name},
                "applied": bool,
            }
        """
        from pipeline.factor_monitor import factor_health_report, FACTOR_PRESETS
        from pipeline.active_strategy import get_active_strategy

        active = get_active_strategy()
        preset_key = active if active in FACTOR_PRESETS else "v7"
        current_factors = FACTOR_PRESETS[preset_key]

        # ── 1. 因子健康检查 ──────────────────────────────────
        print("  检查因子健康...")
        health = factor_health_report(factors=current_factors)

        sick_factors = []
        healthy_factors = []
        for name in current_factors:
            info = health.get(name, {})
            status = info.get("status", "no_data")
            if status in ("dead", "degraded"):
                sick_factors.append({"name": name, "status": status, "ic": info.get("rolling_ic")})
                print(f"  {name}: {status} (IC={info.get('rolling_ic', 'N/A')})")
            else:
                healthy_factors.append(name)

        if not sick_factors:
            print("  所有因子健康，无需替换")
            ctx.log_decision("FactorDoctor", "所有因子健康，无需替换")
            return {"sick_factors": [], "replacements": {}, "applied": False}

        print(f"  发现 {len(sick_factors)} 个问题因子: {[f['name'] for f in sick_factors]}")

        # ── 2. 加载最近因子挖掘结果 ──────────────────────────
        mining_data = self._load_latest_mining()
        if not mining_data:
            print("  无因子挖掘数据，无法推荐替换")
            return {"sick_factors": sick_factors, "replacements": {}, "applied": False}

        rankings = mining_data.get("rankings", [])
        corr_matrix = mining_data.get("correlation_matrix", {})

        # ── 3. 为每个失效因子找替换 ──────────────────────────
        used_factors = set(healthy_factors)
        replacements = {}

        for sick in sick_factors:
            sick_name = sick["name"]
            replacement = self._find_replacement(
                sick_name=sick_name,
                rankings=rankings,
                corr_matrix=corr_matrix,
                used_factors=used_factors,
            )
            if replacement:
                replacements[sick_name] = replacement
                used_factors.add(replacement)
                print(f"  推荐替换: {sick_name} → {replacement}")
            else:
                print(f"  {sick_name}: 未找到合适的替换因子")

        # ── 4. 生成建议 ──────────────────────────────────────
        result = {
            "sick_factors": sick_factors,
            "healthy_factors": healthy_factors,
            "replacements": replacements,
            "applied": False,
            "strategy": preset_key,
        }

        if replacements:
            # 构建新因子组合
            new_factors = list(healthy_factors)
            for sick_name, replacement in replacements.items():
                new_factors.append(replacement)

            result["proposed_factors"] = sorted(new_factors)

            ctx.log_decision(
                "FactorDoctor",
                f"推荐替换 {len(replacements)} 个因子: {replacements}",
                f"存活因子: {healthy_factors}, 新组合: {new_factors}",
            )

            # 发送告警
            try:
                from pipeline.alert_notifier import send_alert, AlertLevel
                replacement_str = ", ".join(f"{k}→{v}" for k, v in replacements.items())
                send_alert(
                    level=AlertLevel.WARNING,
                    title=f"因子替换建议: {replacement_str}",
                    body=f"当前策略 {preset_key}, {len(sick_factors)} 个因子失效",
                    source="FactorDoctor",
                    date=ctx.date,
                )
            except Exception:
                pass

        ctx.set("factor_diagnosis", result)
        return result

    def _find_replacement(
        self,
        sick_name: str,
        rankings: list,
        corr_matrix: dict,
        used_factors: set,
    ) -> str | None:
        """
        为失效因子找到最佳替换。

        选择标准:
          1. 不在当前使用列表中
          2. |ICIR| >= MIN_ABS_ICIR, |IC| >= MIN_ABS_IC
          3. 与所有存活因子的相关性 < CORRELATION_THRESHOLD
          4. 按 |ICIR| 降序选第一个
        """
        for r in rankings:
            name = r["name"]

            # 跳过已使用的
            if name in used_factors or name == sick_name:
                continue

            # 基础门槛
            if abs(r.get("ICIR", 0)) < self.MIN_ABS_ICIR:
                continue
            if abs(r.get("IC_mean", 0)) < self.MIN_ABS_IC:
                continue

            # 相关性检查
            too_correlated = False
            if corr_matrix and name in corr_matrix:
                for existing in used_factors:
                    if existing in corr_matrix.get(name, {}):
                        if abs(corr_matrix[name][existing]) > self.CORRELATION_THRESHOLD:
                            too_correlated = True
                            break

            if not too_correlated:
                return name

        return None

    def _load_latest_mining(self) -> dict | None:
        """加载最近的因子挖掘结果"""
        if not RESEARCH_DIR.exists():
            return None

        mining_files = sorted(RESEARCH_DIR.glob("mining_*.json"), reverse=True)
        if not mining_files:
            return None

        try:
            with open(mining_files[0], encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            logger.warning("加载挖掘结果失败: %s", e)
            return None
