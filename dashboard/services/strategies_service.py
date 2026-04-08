"""
dashboard/services/strategies_service.py — 策略展示服务层

给前端「当前策略是什么」的可读快照：
  - 当前激活的策略 id + 切换历史
  - 策略的因子组成（factor_id / 方向 / 权重 / 中文说明）
  - 每个因子的健康状态（接 factor_monitor）

目标用户是对量化陌生的新人 —— 所有信息都要能被一眼看懂，
不需要他翻代码。
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Optional

# ══════════════════════════════════════════════════════════════
# 策略元数据（与 pipeline/daily_signal.py 中的定义保持同步）
#
# 如果以后 daily_signal 的因子组成改了，这里需要同步维护，
# 因为前端要展示的是"这个策略在当前代码里用了哪些因子"，
# 而 daily_signal 里的组成是硬编码的。
# ══════════════════════════════════════════════════════════════

_STRATEGY_META: dict[str, dict] = {
    "ad_hoc": {
        "id": "ad_hoc",
        "display_name": "ad-hoc 等权组合",
        "tagline": "动量 + EP + 低波动 + 换手反转，四因子等权",
        "description": (
            "最早期的 baseline 策略，四个经典因子等权合成。"
            "适合做基准对比，但没有行业中性化，长期会被行业轮动噪音干扰。"
        ),
        "factors": [
            {
                "id": "momentum_20",
                "label": "20 日动量",
                "weight": 0.25,
                "direction": 1,
                "explain": "过去 20 日涨幅，看近期表现强的继续强。",
            },
            {
                "id": "ep",
                "label": "EP（盈利价格比）",
                "weight": 0.25,
                "direction": 1,
                "explain": "每块钱股价对应多少盈利，越高越便宜。",
            },
            {
                "id": "low_vol",
                "label": "低波动",
                "weight": 0.25,
                "direction": -1,
                "explain": "波动大的股票未来回报反而更差，取负值。",
            },
            {
                "id": "turnover_rev",
                "label": "换手反转",
                "weight": 0.25,
                "direction": -1,
                "explain": "换手率高的股票常见反转，取负值。",
            },
        ],
    },
    "v7": {
        "id": "v7",
        "display_name": "v7 IC 加权五因子",
        "tagline": "行业中性化 + IC 动态加权，当前生产策略",
        "description": (
            "v7 是 Phase 5 验证通过的生产策略：先做行业中性化去掉板块轮动，"
            "再用最近 60 日 IC 均值的绝对值给每个因子动态加权，抗过拟合能力更强。"
        ),
        "factors": [
            {
                "id": "team_coin",
                "label": "团队币（量价共振）",
                "weight": None,
                "direction": 1,
                "explain": "量价共振的复合因子，捕捉主力资金协同的建仓信号。",
            },
            {
                "id": "low_vol_20d",
                "label": "20 日低波动",
                "weight": None,
                "direction": 1,
                "explain": "20 日收益波动率，取负后高分意味着低波动，A 股长期有低波动溢价。",
            },
            {
                "id": "cgo_simple",
                "label": "CGO（相对成本线）",
                "weight": None,
                "direction": 1,
                "explain": "当前价相对 60 日均价的偏离度，均值回归视角下偏低的更有机会。",
            },
            {
                "id": "enhanced_mom_60",
                "label": "增强动量 60",
                "weight": None,
                "direction": 1,
                "explain": "60 日动量 + 跳过近端噪音，捕捉中期趋势。",
            },
            {
                "id": "bp",
                "label": "BP（账面市值比）",
                "weight": None,
                "direction": 1,
                "explain": "账面价值 / 市值，经典价值因子，高 BP 代表便宜。",
            },
        ],
    },
    "v8": {
        "id": "v8",
        "display_name": "v8 = v7 + 影线支撑",
        "tagline": "在 v7 基础上加入 shadow_lower 微观结构因子",
        "description": (
            "v8 保留 v7 的五个因子 + 新增 shadow_lower（下影线支撑）。"
            "shadow_lower 衡量 K 线下影线相对实体的长度，长下影是盘中接筹的技术信号。"
        ),
        "factors": [
            {"id": "team_coin", "label": "团队币", "weight": None, "direction": 1,
             "explain": "量价共振因子。"},
            {"id": "low_vol_20d", "label": "20 日低波动", "weight": None, "direction": 1,
             "explain": "低波动溢价。"},
            {"id": "cgo_simple", "label": "CGO", "weight": None, "direction": 1,
             "explain": "相对成本线偏离。"},
            {"id": "enhanced_mom_60", "label": "增强动量 60", "weight": None, "direction": 1,
             "explain": "60 日增强动量。"},
            {"id": "bp", "label": "BP", "weight": None, "direction": 1,
             "explain": "账面市值比。"},
            {"id": "shadow_lower", "label": "下影线支撑", "weight": None, "direction": 1,
             "explain": "长下影线暗示盘中承接力，ICIR 约 0.51。",
            },
        ],
    },
    "auto_gen": {
        "id": "auto_gen",
        "display_name": "auto-gen（AI 自动合成）",
        "tagline": "由 quant_dojo generate 生成的实验性组合",
        "description": (
            "quant_dojo generate 根据最近因子表现自动合成的组合，"
            "定义存在 strategies/generated/auto_gen_latest.json。"
            "属于实验性策略，上线前应手动 review。"
        ),
        "factors": [],  # 动态读取 auto_gen_latest.json
    },
}


# ══════════════════════════════════════════════════════════════
# 路径
# ══════════════════════════════════════════════════════════════

_ROOT = Path(__file__).parent.parent.parent
_STATE_FILE = _ROOT / "live" / "strategy_state.json"
_AUTO_GEN_FILE = _ROOT / "strategies" / "generated" / "auto_gen_latest.json"


# ══════════════════════════════════════════════════════════════
# 读取
# ══════════════════════════════════════════════════════════════

def _load_state() -> dict:
    if not _STATE_FILE.exists():
        return {"active_strategy": "v7", "history": []}
    try:
        return json.loads(_STATE_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {"active_strategy": "v7", "history": []}


def _auto_gen_factors() -> list[dict]:
    """读 auto_gen_latest.json 拿到因子列表；读不到返回空。"""
    if not _AUTO_GEN_FILE.exists():
        return []
    try:
        data = json.loads(_AUTO_GEN_FILE.read_text(encoding="utf-8"))
        factors_raw = data.get("factors") or data.get("factor_weights") or []
        if isinstance(factors_raw, dict):
            return [
                {"id": k, "label": k, "weight": float(v), "direction": 1,
                 "explain": "由 generate 命令合成，具体语义见 utils/alpha_factors.py"}
                for k, v in factors_raw.items()
            ]
        if isinstance(factors_raw, list):
            return [
                {"id": f.get("id") or f.get("name", "?"),
                 "label": f.get("label") or f.get("name", "?"),
                 "weight": f.get("weight"),
                 "direction": f.get("direction", 1),
                 "explain": f.get("explain", "由 generate 命令合成")}
                for f in factors_raw
            ]
    except Exception:
        pass
    return []


def _factor_health_map() -> dict:
    """拉一次因子健康报告，失败返回空 dict。"""
    try:
        from pipeline.factor_monitor import factor_health_report
        return factor_health_report() or {}
    except Exception:
        return {}


# ══════════════════════════════════════════════════════════════
# 对外
# ══════════════════════════════════════════════════════════════

def get_active_strategy_view() -> dict:
    """
    返回当前激活策略的完整可读快照。

    {
      "active": "v7",
      "display_name": "...",
      "tagline": "...",
      "description": "...",
      "factors": [{id, label, weight, direction, explain, health_status}],
      "history": [{from, to, reason, date}],
      "all_strategies": ["ad_hoc", "v7", "v8", "auto_gen"],
    }
    """
    state = _load_state()
    active = state.get("active_strategy", "v7")
    meta = _STRATEGY_META.get(active) or _STRATEGY_META["v7"]

    factors = list(meta["factors"])
    if active == "auto_gen":
        factors = _auto_gen_factors()

    # 合并因子健康
    health = _factor_health_map()
    for f in factors:
        h = health.get(f["id"], {})
        f["health_status"] = h.get("status", "unknown")
        f["rolling_ic"] = h.get("rolling_ic")
        f["t_stat"] = h.get("t_stat")

    return {
        "active": active,
        "display_name": meta["display_name"],
        "tagline": meta["tagline"],
        "description": meta["description"],
        "factors": factors,
        "history": state.get("history", [])[-10:],
        "all_strategies": list(_STRATEGY_META.keys()),
    }


def list_all_strategies() -> list[dict]:
    """列出所有已知策略的简介（用于"所有策略"表格）。"""
    return [
        {
            "id": meta["id"],
            "display_name": meta["display_name"],
            "tagline": meta["tagline"],
            "n_factors": len(meta["factors"]) if meta["id"] != "auto_gen" else len(_auto_gen_factors()),
        }
        for meta in _STRATEGY_META.values()
    ]


if __name__ == "__main__":
    import json as _j
    print("=== active strategy ===")
    print(_j.dumps(get_active_strategy_view(), ensure_ascii=False, indent=2))
    print("\n=== all strategies ===")
    print(_j.dumps(list_all_strategies(), ensure_ascii=False, indent=2))
