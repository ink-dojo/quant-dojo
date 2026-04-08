"""
dashboard/services/docs_service.py — markdown 文档浏览服务层

扫描仓库里的 *.md 文档，供 dashboard 的「文档」Tab 浏览。

安全约束（重要）：
  - 根路径锚定到 repo root，read_doc 严格校验路径不越界
  - 只允许扩展名 .md
  - 不读 .git、node_modules、__pycache__ 之类目录
"""
from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any

_ROOT = Path(__file__).parent.parent.parent.resolve()

# 允许扫描的顶层目录 + 根目录本身
_SCAN_DIRS = [
    _ROOT,                    # 根目录的 *.md（ROADMAP / TODO / CLAUDE 等）
    _ROOT / "journal",
    _ROOT / "journal" / "weekly",
    _ROOT / "research" / "factors",
    _ROOT / "notes",
]

# 忽略这些目录名（防扫 .git / node_modules / venv）
_IGNORE_DIRS = {".git", "node_modules", "__pycache__", ".venv", "venv",
                ".pytest_cache", "live", "data"}


def _iter_md_files() -> list[Path]:
    """返回白名单目录下所有 .md 文件。"""
    out: list[Path] = []
    seen: set[Path] = set()
    for base in _SCAN_DIRS:
        if not base.exists():
            continue
        # 根目录只扫一层；子目录递归
        if base == _ROOT:
            for p in base.glob("*.md"):
                if p.is_file() and p not in seen:
                    out.append(p)
                    seen.add(p)
            continue
        for p in base.rglob("*.md"):
            if any(part in _IGNORE_DIRS for part in p.parts):
                continue
            if p.is_file() and p not in seen:
                out.append(p)
                seen.add(p)
    return out


def _relpath(p: Path) -> str:
    try:
        return str(p.resolve().relative_to(_ROOT))
    except ValueError:
        return p.name


def _category(rel: str) -> str:
    """用路径前缀归类。"""
    if rel.startswith("journal/weekly"):
        return "weekly"
    if rel.startswith("journal"):
        return "journal"
    if rel.startswith("research/factors"):
        return "factor"
    if rel.startswith("notes"):
        return "notes"
    return "root"


def _extract_title(path: Path) -> str:
    """抓 markdown 第一个 # 标题，找不到用文件名。"""
    try:
        with open(path, "r", encoding="utf-8") as f:
            for _ in range(40):
                line = f.readline()
                if not line:
                    break
                stripped = line.strip()
                if stripped.startswith("# "):
                    return stripped.lstrip("# ").strip()
    except Exception:
        pass
    return path.stem


def list_docs() -> dict:
    """
    返回整个文档树。

    {
      "docs": [
        {"rel": "ROADMAP.md", "title": "路线图", "category": "root",
         "size": 4532, "updated_at": "2026-04-08T15:00:00"},
        ...
      ],
      "by_category": {"root": 16, "journal": 38, "weekly": 15, "factor": 5}
    }
    """
    files = _iter_md_files()
    docs: list[dict] = []
    for p in files:
        try:
            stat = p.stat()
        except Exception:
            continue
        rel = _relpath(p)
        docs.append({
            "rel": rel,
            "title": _extract_title(p),
            "category": _category(rel),
            "size": stat.st_size,
            "updated_at": datetime.fromtimestamp(stat.st_mtime).isoformat(timespec="seconds"),
        })
    # 按更新时间倒序
    docs.sort(key=lambda d: d["updated_at"], reverse=True)
    counts: dict[str, int] = {}
    for d in docs:
        counts[d["category"]] = counts.get(d["category"], 0) + 1
    return {"docs": docs, "by_category": counts}


def read_doc(rel_path: str) -> dict:
    """
    读取指定相对路径的 markdown 原文。

    安全：
      - 只允许 .md 扩展名
      - resolve 后必须在 repo root 内
      - 不允许包含 .. 直接穿越（额外保险）
    """
    if not rel_path or ".." in rel_path.split("/"):
        return {"rel": rel_path, "content": None, "error": "非法路径"}
    if not rel_path.lower().endswith(".md"):
        return {"rel": rel_path, "content": None, "error": "只支持 .md 文件"}

    target = (_ROOT / rel_path).resolve()
    try:
        target.relative_to(_ROOT)
    except ValueError:
        return {"rel": rel_path, "content": None, "error": "路径越界"}
    if not target.exists() or not target.is_file():
        return {"rel": rel_path, "content": None, "error": "文件不存在"}
    try:
        content = target.read_text(encoding="utf-8")
    except Exception as exc:
        return {"rel": rel_path, "content": None, "error": str(exc)}
    return {
        "rel": rel_path,
        "title": _extract_title(target),
        "content": content,
        "updated_at": datetime.fromtimestamp(target.stat().st_mtime).isoformat(timespec="seconds"),
    }


if __name__ == "__main__":
    import json as _j
    tree = list_docs()
    print(f"共 {len(tree['docs'])} 份文档")
    print(_j.dumps(tree["by_category"], ensure_ascii=False))
    # 读一份 smoke test
    d = read_doc("ROADMAP.md")
    print("ROADMAP 前 200 字:", (d.get("content") or "")[:200])
