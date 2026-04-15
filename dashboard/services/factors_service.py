"""
factors_service.py — 因子健康度与截面快照服务层

封装因子监控相关查询，所有函数捕获异常并返回结构化 dict。
"""

import ast
import re
from pathlib import Path
from typing import Any

_ROOT = Path(__file__).parent.parent.parent

# 因子快照目录（与 pipeline/factor_monitor.py 保持一致）
_SNAPSHOT_DIR = _ROOT / "live" / "factor_snapshot"

# 因子研究目录（每个子目录一个 README.md + *.py）
_FACTOR_RESEARCH_DIR = _ROOT / "research" / "factors"

# 全量因子实现文件（AST 解析，供 /api/factors/library 使用）
_ALPHA_FACTORS_FILE = _ROOT / "utils" / "alpha_factors.py"

# 目录名 → 在 factor_health / signal metadata 里对应的因子 id 列表
# 用于把"因子目录"和"运行时的因子健康状态"对齐
_FACTOR_DIR_TO_IDS: dict[str, list[str]] = {
    "momentum": ["momentum_20", "enhanced_mom_60"],
    "value": ["ep", "bp"],
    "low_vol": ["low_vol", "low_vol_20d"],
    "quality": ["roe", "quality"],
    "polar_pv_factor": ["team_coin", "cgo_simple"],
}

# factor_health_report 状态到三值归一化映射
_STATUS_MAP = {
    "healthy": "healthy",
    "degraded": "warning",
    "dead": "failed",
    "no_data": "warning",
}


def get_factor_health() -> dict:
    """
    获取各因子当前健康状态。

    调用 pipeline.factor_monitor.factor_health_report()，将返回的每个因子状态
    归一化为 "healthy" / "warning" / "failed" 三个值之一。

    返回:
        dict，格式为::

            {
                "momentum_20": {"rolling_ic": 0.035, "status": "healthy"},
                "ep":          {"rolling_ic": 0.012, "status": "warning"},
                ...
            }

        捕获任何异常时返回::

            {"error": "<异常信息>", "factors": {}}
    """
    try:
        from pipeline.factor_monitor import factor_health_report, FACTOR_PRESETS
        from pipeline.active_strategy import get_active_strategy

        # 用当前活跃策略的因子集；fallback 到 v16 → legacy
        try:
            active_id = get_active_strategy().lstrip("multi_factor_")
        except Exception:
            active_id = "v16"
        factor_list = FACTOR_PRESETS.get(active_id) or FACTOR_PRESETS.get("v16") or FACTOR_PRESETS["legacy"]

        raw = factor_health_report(factors=factor_list)
        factors: dict[str, Any] = {}
        for factor_name, info in raw.items():
            if factor_name == "__meta__":
                continue
            raw_status = info.get("status", "no_data")
            normalized = _STATUS_MAP.get(raw_status, "warning")
            factors[factor_name] = {
                "rolling_ic": info.get("rolling_ic"),
                "t_stat": info.get("t_stat"),
                "status": normalized,
            }
        return factors
    except Exception as e:
        return {"error": str(e), "factors": {}}


def get_factor_snapshot() -> dict:
    """
    读取最新日期的因子截面快照，返回各因子的描述统计。

    扫描 live/factor_snapshot/ 目录，取文件名最大（即最新日期）的 .parquet 文件，
    用 pandas 读取后计算每列（因子）的均值、中位数、25% 和 75% 分位数。

    返回:
        dict，格式为::

            {
                "as_of_date": "20260321",
                "stats": {
                    "momentum_20": {"mean": 0.12, "median": 0.10, "q25": 0.05, "q75": 0.18},
                    ...
                }
            }

        文件不存在时返回::

            {"as_of_date": null, "stats": {}}
    """
    try:
        import pandas as pd

        if not _SNAPSHOT_DIR.exists():
            return {"as_of_date": None, "stats": {}}

        parquet_files = sorted(_SNAPSHOT_DIR.glob("*.parquet"))
        if not parquet_files:
            return {"as_of_date": None, "stats": {}}

        latest_file = parquet_files[-1]
        as_of_date = latest_file.stem  # 文件名即日期，如 "20260321"

        df = pd.read_parquet(latest_file)

        stats: dict[str, Any] = {}
        for col in df.columns:
            series = df[col].dropna()
            if series.empty:
                continue
            stats[col] = {
                "mean": round(float(series.mean()), 6),
                "median": round(float(series.median()), 6),
                "q25": round(float(series.quantile(0.25)), 6),
                "q75": round(float(series.quantile(0.75)), 6),
            }

        return {"as_of_date": as_of_date, "stats": stats}
    except Exception:
        return {"as_of_date": None, "stats": {}}


# ══════════════════════════════════════════════════════════════
# 因子目录 / README 浏览
# ══════════════════════════════════════════════════════════════

_VALID_FACTOR_DIR = re.compile(r"^[a-zA-Z0-9_\-]{1,64}$")


def _extract_title(md_text: str, fallback: str) -> str:
    """抓取 markdown 第一个 # 标题，找不到用 fallback。"""
    for line in md_text.splitlines():
        line = line.strip()
        if line.startswith("# "):
            return line.lstrip("# ").strip()
    return fallback


def _extract_status(md_text: str) -> str:
    """解析 README 里形如 '**状态**：已实现 ✅' 的一行，找不到返回 unknown。"""
    m = re.search(r"\*\*状态\*\*[:：]\s*([^\n]+)", md_text)
    if m:
        return m.group(1).strip().split("|")[0].strip()
    return "unknown"


def _extract_summary(md_text: str, n_chars: int = 180) -> str:
    """从 '## 核心思路' / '## 核心' 之后抓第一段非空正文，截断到 n_chars。"""
    lines = md_text.splitlines()
    in_section = False
    buf: list[str] = []
    for line in lines:
        stripped = line.strip()
        if not in_section:
            if stripped.startswith("##") and ("核心" in stripped or "思路" in stripped):
                in_section = True
            continue
        if stripped.startswith("##"):
            break
        if stripped and not stripped.startswith("---"):
            buf.append(stripped)
        if len(" ".join(buf)) >= n_chars:
            break
    summary = " ".join(buf).strip()
    if len(summary) > n_chars:
        summary = summary[:n_chars] + "…"
    return summary or "（尚无描述）"


def list_factor_catalog() -> dict:
    """
    扫描 research/factors/ 下每个子目录，返回因子库目录 + 健康状态 merge。

    返回格式:
        {
          "factors": [
            {
              "dir": "momentum",
              "title": "动量因子研究",
              "status_text": "已实现 ✅",
              "summary": "...",
              "ids": ["momentum_20", "enhanced_mom_60"],
              "health": {
                "momentum_20": {"rolling_ic": 0.03, "status": "healthy"},
                ...
              }
            },
            ...
          ],
          "health_global": {...}  # 原始健康报告
        }
    """
    health = get_factor_health()
    if "factors" in health:  # 错误分支
        health = {}

    factors: list[dict] = []
    if _FACTOR_RESEARCH_DIR.exists():
        for factor_dir in sorted(_FACTOR_RESEARCH_DIR.iterdir()):
            if not factor_dir.is_dir():
                continue
            readme = factor_dir / "README.md"
            if not readme.exists():
                continue
            try:
                md_text = readme.read_text(encoding="utf-8")
            except Exception:
                continue

            ids = _FACTOR_DIR_TO_IDS.get(factor_dir.name, [])
            health_for_dir = {fid: health[fid] for fid in ids if fid in health}

            factors.append({
                "dir": factor_dir.name,
                "title": _extract_title(md_text, factor_dir.name),
                "status_text": _extract_status(md_text),
                "summary": _extract_summary(md_text),
                "ids": ids,
                "health": health_for_dir,
            })

    return {"factors": factors, "health_global": health}


def read_factor_readme(factor_dir: str) -> dict:
    """
    读取某个因子目录下的 README.md 原文。

    严格校验路径防穿越，只允许白名单字符集。

    返回:
        {"dir": "momentum", "content": "# ..."}
        找不到时返回 {"dir": ..., "content": null, "error": "..."}
    """
    if not _VALID_FACTOR_DIR.match(factor_dir):
        return {"dir": factor_dir, "content": None, "error": "非法目录名"}
    target = (_FACTOR_RESEARCH_DIR / factor_dir / "README.md").resolve()
    try:
        target.relative_to(_FACTOR_RESEARCH_DIR.resolve())
    except ValueError:
        return {"dir": factor_dir, "content": None, "error": "路径越界"}
    if not target.exists():
        return {"dir": factor_dir, "content": None, "error": "README 不存在"}
    try:
        return {"dir": factor_dir, "content": target.read_text(encoding="utf-8")}
    except Exception as exc:
        return {"dir": factor_dir, "content": None, "error": str(exc)}


# ══════════════════════════════════════════════════════════════
# 全量因子清单 — AST 解析 utils/alpha_factors.py
# ══════════════════════════════════════════════════════════════

# 因子分类（与 alpha_factors.py 头部 docstring 对齐，手工维护）
# 不在映射里的因子归入"其他"
_FACTOR_CATEGORY: dict[str, str] = {
    # 反转 / 动量
    "reversal_1m": "反转", "reversal_5d": "反转", "reversal_12m_skip3m": "动量",
    "vol_scaled_reversal": "反转", "w_reversal": "反转",
    "enhanced_momentum": "动量", "quality_momentum": "动量",
    "ma_ratio_momentum": "动量", "momentum_6m_skip1m": "动量",
    "momentum_3m_skip1m": "动量", "industry_momentum": "动量",
    "earnings_momentum": "动量", "price_momentum_quality": "动量",
    # 波动 / 风险
    "low_vol_20d": "波动", "idiosyncratic_volatility": "波动",
    "vol_regime": "波动", "vol_asymmetry": "波动",
    "beta_factor": "波动", "return_skewness_20d": "波动",
    "max_ret_1m": "波动", "stock_max_drawdown_60d": "波动",
    "sharpe_20d": "波动",
    # 基本面
    "ep_factor": "基本面", "bp_factor": "基本面", "roe_factor": "基本面",
    "accruals_quality": "基本面", "cfo_accrual_quality": "基本面",
    "dividend_yield": "基本面",
    # 换手 / 流动性
    "turnover_rev": "流动性", "turnover_acceleration": "流动性",
    "turnover_trend": "流动性", "relative_turnover": "流动性",
    "amihud_illiquidity": "流动性", "volume_concentration": "流动性",
    "volume_surge": "流动性", "bid_ask_spread_proxy": "流动性",
    # 微观结构
    "shadow_upper": "微观结构", "shadow_lower": "微观结构",
    "amplitude_hidden": "微观结构", "close_minus_open_volume": "微观结构",
    "avg_intraday_range": "微观结构", "intraday_direction_efficiency": "微观结构",
    "vwap_deviation": "微观结构", "overnight_return": "微观结构",
    # 行为金融
    "cgo": "行为金融", "str_salience": "行为金融",
    "team_coin": "行为金融", "retail_open_trap": "行为金融",
    "insider_buying_proxy": "行为金融",
    # 网络 / 关系
    "network_scc": "网络", "apm_overnight": "网络",
    # 筹码
    "chip_arc": "筹码", "chip_vrc": "筹码",
    # 价量分歧
    "price_volume_divergence": "价量", "price_volume_divergence": "价量",
    "up_down_volume_ratio": "价量", "chaikin_money_flow": "价量",
    # 价格锚
    "price_anchor_dist": "技术", "high_52w_ratio": "技术",
    "price_distance_from_ma": "技术", "bollinger_pct": "技术",
    "rsi_factor": "技术", "return_zscore_20d": "技术",
    "win_rate_trend": "技术", "win_rate_60d": "技术",
    "ret_autocorr_1d": "技术", "earnings_window_proxy": "技术",
}

# 正方向因子（大值好）/ 负方向（小值好，IC 取负）
# 解析不了方向时返回 "?"
_FACTOR_DIRECTION_HINT = {"reversal", "vol", "volatility", "beta", "drawdown",
                          "skewness", "illiquidity"}


def _factor_direction(name: str) -> str:
    """通过名字启发式推测方向：带反转/波动类词根 → 负向；其他 → 正向。"""
    lower = name.lower()
    for hint in _FACTOR_DIRECTION_HINT:
        if hint in lower:
            return "-"
    return "+"


def _clean_doc(raw: str) -> str:
    """取 docstring 首个非空段落，过滤纯符号行，截 120 字符。"""
    if not raw:
        return ""
    for line in raw.splitlines():
        s = line.strip().strip("—-=").strip()
        if s and not s.startswith("==="):
            return s[:120]
    return ""


def list_factor_library() -> dict:
    """
    AST 解析 utils/alpha_factors.py，返回所有公开因子函数列表。

    每个因子含：name / category / direction / summary / args。
    args 是函数签名里除 window/默认参数外的位置参数名，用来暗示所需数据。

    不解析 `_` 开头的私有函数和 `build_fast_factors` 这种聚合器。

    返回:
        {"factors": [ {...}, ... ], "count": N, "categories": {...}}
    """
    if not _ALPHA_FACTORS_FILE.exists():
        return {"factors": [], "count": 0, "categories": {}, "error": "alpha_factors.py 不存在"}

    try:
        tree = ast.parse(_ALPHA_FACTORS_FILE.read_text(encoding="utf-8"))
    except Exception as exc:
        return {"factors": [], "count": 0, "categories": {}, "error": f"解析失败: {exc}"}

    factors: list[dict] = []
    for node in tree.body:
        if not isinstance(node, ast.FunctionDef):
            continue
        name = node.name
        if name.startswith("_") or name == "build_fast_factors":
            continue

        # 提取签名里需要外部传入的数据字段（位置参数，去掉有默认值的）
        posonly = [a.arg for a in node.args.args]
        defaults_n = len(node.args.defaults)
        required = posonly[: len(posonly) - defaults_n] if defaults_n else posonly

        doc = _clean_doc(ast.get_docstring(node) or "")
        category = _FACTOR_CATEGORY.get(name, "其他")
        direction = _factor_direction(name)

        factors.append({
            "name": name,
            "category": category,
            "direction": direction,
            "summary": doc,
            "required_data": required,
            "line": node.lineno,
        })

    # 分类统计
    cat_count: dict[str, int] = {}
    for f in factors:
        cat_count[f["category"]] = cat_count.get(f["category"], 0) + 1

    return {
        "factors": factors,
        "count": len(factors),
        "categories": cat_count,
    }


_VALID_FACTOR_NAME = re.compile(r"^[a-zA-Z_][a-zA-Z0-9_]{0,64}$")


def get_factor_detail(name: str) -> dict:
    """
    获取单个因子的详情：完整 docstring + 源码 + 签名 + 今日截面统计 + 健康状态。

    参数:
        name: 因子函数名（位于 utils/alpha_factors.py 顶层）

    返回:
        {
          "name": ..., "category": ..., "direction": ...,
          "docstring": "完整 docstring",
          "signature": "函数签名字符串",
          "source": "函数完整源码",
          "lineno": 123, "end_lineno": 145,
          "required_data": [...],
          "snapshot": {"mean": ..., "median": ..., "q25": ..., "q75": ...}  # 可能为 None
          "health": {"rolling_ic": 0.03, "status": "healthy"}  # 可能为 None
        }
        找不到时返回 {"error": "..."}
    """
    if not _VALID_FACTOR_NAME.match(name):
        return {"error": "非法因子名"}
    if not _ALPHA_FACTORS_FILE.exists():
        return {"error": "alpha_factors.py 不存在"}

    try:
        source_text = _ALPHA_FACTORS_FILE.read_text(encoding="utf-8")
        tree = ast.parse(source_text)
    except Exception as exc:
        return {"error": f"解析失败: {exc}"}

    target = None
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name == name:
            target = node
            break
    if target is None:
        return {"error": f"未找到因子 {name}"}

    # 完整签名
    try:
        sig = ast.unparse(target.args)
    except Exception:
        sig = ""

    # 源码切片（ast 的 lineno 从 1 开始）
    try:
        lines = source_text.splitlines()
        start = target.lineno - 1
        end = (getattr(target, "end_lineno", None) or target.lineno) - 1
        source_snippet = "\n".join(lines[start : end + 1])
    except Exception:
        source_snippet = ""

    # 今日截面统计 + 健康状态（失败不影响返回）
    snapshot_stats = None
    try:
        snap = get_factor_snapshot()
        stats = (snap or {}).get("stats") or {}
        if name in stats:
            snapshot_stats = stats[name]
    except Exception:
        pass

    health_info = None
    try:
        health = get_factor_health()
        if isinstance(health, dict) and name in health:
            health_info = health[name]
    except Exception:
        pass

    posonly = [a.arg for a in target.args.args]
    defaults_n = len(target.args.defaults)
    required = posonly[: len(posonly) - defaults_n] if defaults_n else posonly

    return {
        "name": name,
        "category": _FACTOR_CATEGORY.get(name, "其他"),
        "direction": _factor_direction(name),
        "docstring": ast.get_docstring(target) or "",
        "signature": f"{name}({sig})",
        "source": source_snippet,
        "lineno": target.lineno,
        "end_lineno": getattr(target, "end_lineno", target.lineno),
        "required_data": required,
        "snapshot": snapshot_stats,
        "health": health_info,
    }


def get_factor_ic_series(factor_id: str) -> dict:
    """
    获取单个因子最近 60 天的日 IC 时序。

    返回:
        {
          "factor": str,
          "ic_series": [{"date": "2026-03-01", "ic": 0.031}, ...],
          "mean_ic": float | None,
          "t_stat": float | None,
        }
    """
    if not _VALID_FACTOR_NAME.match(factor_id):
        return {"factor": factor_id, "ic_series": [], "error": "非法因子名"}
    try:
        from pipeline.factor_monitor import compute_rolling_ic
        ic = compute_rolling_ic(factor_id, lookback_days=60)
        if ic.empty:
            return {"factor": factor_id, "ic_series": [], "mean_ic": None, "t_stat": None}
        import numpy as np
        vals = ic.dropna()
        mean_ic = float(vals.mean()) if len(vals) else None
        std_ic = float(vals.std()) if len(vals) > 1 else None
        n = len(vals)
        t_stat = (mean_ic / (std_ic / (n ** 0.5))) if (std_ic and std_ic > 0 and n > 0) else None
        return {
            "factor": factor_id,
            "ic_series": [
                {"date": d.strftime("%Y-%m-%d"), "ic": round(float(v), 6)}
                for d, v in vals.items()
            ],
            "mean_ic": round(mean_ic, 6) if mean_ic is not None else None,
            "t_stat": round(t_stat, 4) if t_stat is not None else None,
        }
    except Exception as exc:
        return {"factor": factor_id, "ic_series": [], "error": str(exc)}


if __name__ == "__main__":
    print("=== factor health ===")
    health = get_factor_health()
    print(health)

    print("\n=== factor snapshot ===")
    snapshot = get_factor_snapshot()
    print(f"as_of_date: {snapshot['as_of_date']}")
    print(f"因子数: {len(snapshot['stats'])}")
    for fname, s in snapshot["stats"].items():
        print(f"  {fname}: {s}")

    print("\n=== factor catalog ===")
    cat = list_factor_catalog()
    for f in cat["factors"]:
        print(f"  - {f['dir']}: {f['title']} [{f['status_text']}] ids={f['ids']}")

    print("\n✅ factors_service 检查完毕")
