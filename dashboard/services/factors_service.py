"""
factors_service.py — 因子健康度与截面快照服务层

封装因子监控相关查询，所有函数捕获异常并返回结构化 dict。
"""

import re
from pathlib import Path
from typing import Any

_ROOT = Path(__file__).parent.parent.parent

# 因子快照目录（与 pipeline/factor_monitor.py 保持一致）
_SNAPSHOT_DIR = _ROOT / "live" / "factor_snapshot"

# 因子研究目录（每个子目录一个 README.md + *.py）
_FACTOR_RESEARCH_DIR = _ROOT / "research" / "factors"

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
        from pipeline.factor_monitor import factor_health_report

        raw = factor_health_report()
        factors: dict[str, Any] = {}
        for factor_name, info in raw.items():
            raw_status = info.get("status", "no_data")
            normalized = _STATUS_MAP.get(raw_status, "warning")
            factors[factor_name] = {
                "rolling_ic": info.get("rolling_ic"),
                "status": normalized,
            }
        return factors
    except Exception:
        return {"error": "Internal server error", "factors": {}}


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
