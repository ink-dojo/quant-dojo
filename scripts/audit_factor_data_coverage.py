"""
审计 portfolio 站点需要的因子数据覆盖度

扫描 utils/alpha_factors.py 中的全部因子函数，为每个因子打标签：
  - has_compute_func       : 函数是否在 alpha_factors 里
  - has_research_folder    : research/factors/{slug}/ 是否存在（含 README）
  - has_dedicated_notebook : research/notebooks/ 下是否有专属 notebook
  - has_ic_stats           : 在 journal/full_factor_analysis_20260325.md 的 IC 表里
  - in_v7_strategy         : 是否属于 v7/v9/v10 的 5 因子核心
  - in_v16_strategy        : 是否属于 v16 的 9 因子组合
  - in_factor_snapshot     : 是否在 live/factor_snapshot/ 最新 parquet 的列里
  - docstring              : 函数 docstring（截取前 120 字）

输出:
  - journal/portfolio_factor_coverage.json  (供下游脚本/前端消费)

运行:
  cd /path/to/quant-dojo && python scripts/audit_factor_data_coverage.py
"""
from __future__ import annotations

import ast
import json
import re
import sys
from pathlib import Path

import pandas as pd


ROOT = Path(__file__).resolve().parent.parent
ALPHA_FILE = ROOT / "utils" / "alpha_factors.py"
RESEARCH_FACTORS_DIR = ROOT / "research" / "factors"
NOTEBOOKS_DIR = ROOT / "research" / "notebooks"
FACTOR_SNAPSHOT_DIR = ROOT / "live" / "factor_snapshot"
FULL_ANALYSIS_MD = ROOT / "journal" / "full_factor_analysis_20260325.md"
OUT_JSON = ROOT / "journal" / "portfolio_factor_coverage.json"

# v7/v9/v10 共用核心 5 因子（见 scripts/v9_icir_weighted_eval.py 等）
V7_CORE_FACTORS = {
    "team_coin",
    "low_vol_20d",
    "cgo",           # 在 alpha_factors 里叫 cgo；策略里别名 cgo_simple
    "enhanced_momentum",
    "bp_factor",
}
# v16 — 因子挖掘会话精选（见 live/strategy_state.json）
V16_FACTORS = {
    "low_vol_20d",
    "team_coin",
    "shadow_lower",
    "amihud_illiquidity",     # 策略里别名 amihud_illiq
    "price_volume_divergence",# 策略里别名 price_vol_divergence
    "high_52w_ratio",         # 策略里别名 high_52w
    "turnover_acceleration",  # 策略里别名 turnover_accel
    "momentum_6m_skip1m",     # 策略里别名 mom_6m_skip1m
    "win_rate_60d",
}

# 策略别名 → alpha_factors 真名
STRATEGY_ALIASES = {
    "cgo_simple": "cgo",
    "enhanced_mom_60": "enhanced_momentum",
    "bp": "bp_factor",
    "ep": "ep_factor",
    "amihud_illiq": "amihud_illiquidity",
    "price_vol_divergence": "price_volume_divergence",
    "high_52w": "high_52w_ratio",
    "turnover_accel": "turnover_acceleration",
    "mom_6m_skip1m": "momentum_6m_skip1m",
}

# 类别分类（基于 PORTFOLIO_PLAN.md 第三节）
CATEGORY_MAP = {
    # 技术
    "reversal_1m": "technical",
    "low_vol_20d": "technical",
    "turnover_rev": "technical",
    "enhanced_momentum": "technical",
    "quality_momentum": "technical",
    "ma_ratio_momentum": "technical",
    "high_52w_ratio": "technical",
    "momentum_6m_skip1m": "technical",
    "momentum_3m_skip1m": "technical",
    "reversal_5d": "technical",
    "reversal_12m_skip3m": "technical",
    # 基本面
    "ep_factor": "fundamental",
    "bp_factor": "fundamental",
    "roe_factor": "fundamental",
    "accruals_quality": "fundamental",
    "earnings_momentum": "fundamental",
    "dividend_yield": "fundamental",
    "cfo_accrual_quality": "fundamental",
    # 微观结构
    "shadow_upper": "microstructure",
    "shadow_lower": "microstructure",
    "amplitude_hidden": "microstructure",
    "w_reversal": "microstructure",
    "price_volume_divergence": "microstructure",
    "insider_buying_proxy": "microstructure",
    # 行为金融
    "cgo": "behavioral",
    "str_salience": "behavioral",
    "team_coin": "behavioral",
    "relative_turnover": "behavioral",
    # 筹码
    "chip_arc": "chip",
    "chip_vrc": "chip",
    # 流动性
    "amihud_illiquidity": "liquidity",
    "bid_ask_spread_proxy": "liquidity",
    # 扩展研究（其余默认归这里）
}


def extract_factor_functions(py_file: Path) -> list[dict]:
    """
    用 AST 解析 alpha_factors.py，提取所有顶层函数。
    过滤条件：
      - 名字不以下划线开头（排除私有工具）
      - 名字不是 build_fast_factors 这类工厂函数
    """
    src = py_file.read_text(encoding="utf-8")
    tree = ast.parse(src)

    excluded = {"build_fast_factors"}  # 工厂函数，不是单独的因子

    factors = []
    for node in tree.body:
        if not isinstance(node, ast.FunctionDef):
            continue
        if node.name.startswith("_"):
            continue
        if node.name in excluded:
            continue
        doc = ast.get_docstring(node) or ""
        # 取 docstring 第一段
        first_para = doc.split("\n\n")[0].strip().replace("\n", " ")
        first_para = re.sub(r"\s+", " ", first_para)
        factors.append({
            "name": node.name,
            "lineno": node.lineno,
            "signature_params": [a.arg for a in node.args.args],
            "docstring_first": first_para[:180],
        })
    return factors


def parse_ic_stats_table(md_file: Path) -> dict[str, dict]:
    """
    从 full_factor_analysis_20260325.md 解析 IC/ICIR 排名表。
    返回 {factor_key: {ic_mean, icir, ic_positive_pct, fm_t, verdict}}
    """
    if not md_file.exists():
        return {}

    content = md_file.read_text(encoding="utf-8")
    # 找到表格行：| 排名 | 因子 | 类别 | IC均值 | ICIR | IC>0% | FM t值 | IC+FM |
    result = {}
    for line in content.splitlines():
        # 形如: | 1 | **team_coin** | 行为金融 | 0.039 | **0.453** | 71.5% | **5.08** ✅ | 双杀 |
        m = re.match(
            r"\|\s*(\d+)\s*\|\s*\*{0,2}([\w_]+)\*{0,2}\s*\|\s*([^|]+?)\s*\|\s*"
            r"([-\d.]+)\s*\|\s*\*{0,2}([-\d.]+)\*{0,2}\s*\|\s*([\d.]+)%\s*\|\s*"
            r"\*{0,2}([-\d.]+)\*{0,2}\s*[^|]*\|\s*(\S+)\s*\|",
            line,
        )
        if m:
            _, name, category, ic, icir, ic_pos, fm_t, verdict = m.groups()
            # 策略别名归一到 alpha_factors 真名
            canonical = STRATEGY_ALIASES.get(name, name)
            result[canonical] = {
                "source_name": name,
                "category_zh": category.strip(),
                "ic_mean": float(ic),
                "icir": float(icir),
                "ic_positive_pct": float(ic_pos) / 100,
                "fm_t_stat": float(fm_t),
                "verdict": verdict,
            }
    return result


def get_factor_snapshot_columns() -> set[str]:
    """读取最新 factor_snapshot parquet 的列（归一到 alpha_factors 真名）"""
    parquets = sorted(FACTOR_SNAPSHOT_DIR.glob("*.parquet"))
    if not parquets:
        return set()
    latest = parquets[-1]
    df = pd.read_parquet(latest)
    cols = set(df.columns)
    return {STRATEGY_ALIASES.get(c, c) for c in cols}


def has_research_folder(factor_name: str) -> tuple[bool, str | None]:
    """
    检查 research/factors/{slug}/ 是否存在。
    因子目录命名可能是短名（momentum/value 等），尝试多种匹配。
    """
    if not RESEARCH_FACTORS_DIR.exists():
        return False, None
    # 直接匹配
    for slug in [factor_name, factor_name.replace("_factor", ""),
                 factor_name.replace("_", ""), factor_name.split("_")[0]]:
        folder = RESEARCH_FACTORS_DIR / slug
        if folder.exists() and (folder / "README.md").exists():
            return True, slug
    # 特殊映射
    special = {
        "enhanced_momentum": "momentum",
        "ma_ratio_momentum": "momentum",
        "quality_momentum": "momentum",
        "bp_factor": "value",
        "ep_factor": "value",
        "roe_factor": "quality",
        "low_vol_20d": "low_vol",
    }
    if factor_name in special:
        folder = RESEARCH_FACTORS_DIR / special[factor_name]
        if folder.exists() and (folder / "README.md").exists():
            return True, special[factor_name]
    return False, None


def has_notebook_mention(factor_name: str) -> bool:
    """简单检查 notebook 文件名或内容中是否提到该因子（粗粒度）"""
    if not NOTEBOOKS_DIR.exists():
        return False
    # 先看文件名
    short_patterns = [factor_name, factor_name.replace("_factor", "")]
    for nb in NOTEBOOKS_DIR.glob("*.ipynb"):
        for p in short_patterns:
            if p in nb.stem:
                return True
    return False


def audit() -> dict:
    factors = extract_factor_functions(ALPHA_FILE)
    ic_stats = parse_ic_stats_table(FULL_ANALYSIS_MD)
    snapshot_cols = get_factor_snapshot_columns()

    records = []
    for f in factors:
        name = f["name"]
        folder_found, folder_slug = has_research_folder(name)
        record = {
            "name": name,
            "category": CATEGORY_MAP.get(name, "extended"),
            "lineno": f["lineno"],
            "docstring_first": f["docstring_first"],
            "has_compute_func": True,
            "has_research_folder": folder_found,
            "research_folder_slug": folder_slug,
            "has_dedicated_notebook": has_notebook_mention(name),
            "has_ic_stats": name in ic_stats,
            "ic_stats": ic_stats.get(name),
            "in_v7_strategy": name in V7_CORE_FACTORS,
            "in_v16_strategy": name in V16_FACTORS,
            "in_latest_snapshot": name in snapshot_cols,
        }
        # 可用数据的原始打分：每一项加 1
        signals = [
            record["has_research_folder"],
            record["has_dedicated_notebook"],
            record["has_ic_stats"],
            record["in_v7_strategy"],
            record["in_v16_strategy"],
            record["in_latest_snapshot"],
        ]
        record["coverage_score"] = sum(1 for s in signals if s)
        records.append(record)

    # 汇总
    by_category = {}
    for r in records:
        by_category.setdefault(r["category"], []).append(r["name"])

    return {
        "generated_at": "2026-04-16",
        "source_file": str(ALPHA_FILE.relative_to(ROOT)),
        "total_factors": len(records),
        "with_ic_stats": sum(1 for r in records if r["has_ic_stats"]),
        "with_research_folder": sum(1 for r in records if r["has_research_folder"]),
        "in_v7_strategy": sum(1 for r in records if r["in_v7_strategy"]),
        "in_v16_strategy": sum(1 for r in records if r["in_v16_strategy"]),
        "by_category": {k: sorted(v) for k, v in sorted(by_category.items())},
        "factors": sorted(records, key=lambda x: (-x["coverage_score"], x["name"])),
    }


def print_summary(result: dict):
    print("=" * 60)
    print(f"Factor Coverage Audit — {result['generated_at']}")
    print("=" * 60)
    print(f"全部因子函数: {result['total_factors']}")
    print(f"  有 IC 统计（journal）:    {result['with_ic_stats']}")
    print(f"  有 research/factors 文件夹: {result['with_research_folder']}")
    print(f"  在 v7/v9/v10 核心 5 因子: {result['in_v7_strategy']}")
    print(f"  在 v16 生产 9 因子:       {result['in_v16_strategy']}")

    print("\n按类别分布:")
    for cat, names in result["by_category"].items():
        print(f"  {cat:15s} {len(names):3d}: {', '.join(names[:5])}{' …' if len(names) > 5 else ''}")

    print("\n覆盖度最高的 12 个因子（候选英雄池）:")
    print(f"  {'name':28s} {'cat':15s} score  flags")
    for r in result["factors"][:12]:
        flags = []
        if r["has_research_folder"]: flags.append("research")
        if r["has_dedicated_notebook"]: flags.append("nb")
        if r["has_ic_stats"]: flags.append(f"IC={r['ic_stats']['icir']:+.2f}")
        if r["in_v7_strategy"]: flags.append("v7")
        if r["in_v16_strategy"]: flags.append("v16")
        if r["in_latest_snapshot"]: flags.append("snap")
        print(f"  {r['name']:28s} {r['category']:15s} {r['coverage_score']:5d}  {', '.join(flags)}")


def main():
    result = audit()
    OUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    with open(OUT_JSON, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    print_summary(result)
    print(f"\n写入 {OUT_JSON.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
