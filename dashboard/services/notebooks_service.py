"""
dashboard/services/notebooks_service.py — Jupyter notebook 浏览服务层

列出 research/notebooks/ 下所有 .ipynb 文件，提取第一个 markdown cell 作为标题。

这个服务只做列表 + 元数据抽取，不执行 / 不渲染 notebook —— 想跑 notebook
用户会自己开 jupyter。
"""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

_ROOT = Path(__file__).parent.parent.parent.resolve()
_NOTEBOOKS_DIR = _ROOT / "research" / "notebooks"


def _extract_notebook_title_and_desc(nb_path: Path) -> tuple[str, str]:
    """
    读 notebook 的第一个 markdown cell，抓标题 + 首段描述。

    返回 (title, description)。失败时返回 (文件名, "").
    """
    try:
        with open(nb_path, "r", encoding="utf-8") as f:
            nb = json.load(f)
    except Exception:
        return nb_path.stem, ""

    cells = nb.get("cells", [])
    for cell in cells:
        if cell.get("cell_type") != "markdown":
            continue
        source = cell.get("source", [])
        if isinstance(source, list):
            text = "".join(source)
        else:
            text = str(source)
        lines = [l.strip() for l in text.splitlines() if l.strip()]
        if not lines:
            continue
        title = lines[0].lstrip("# ").strip() or nb_path.stem
        # 描述 = 标题后的第一行非空
        desc = ""
        for l in lines[1:]:
            if not l.startswith("#"):
                desc = l
                break
        return title, desc
    return nb_path.stem, ""


def _count_cells(nb_path: Path) -> dict:
    """统计 code / markdown cell 数量。"""
    try:
        with open(nb_path, "r", encoding="utf-8") as f:
            nb = json.load(f)
    except Exception:
        return {"code": 0, "markdown": 0}
    code, md = 0, 0
    for cell in nb.get("cells", []):
        t = cell.get("cell_type")
        if t == "code":
            code += 1
        elif t == "markdown":
            md += 1
    return {"code": code, "markdown": md}


def list_notebooks() -> dict:
    """
    扫描 research/notebooks/ 下所有 .ipynb。

    返回:
      {
        "notebooks": [
          {"filename": "01_getting_started.ipynb",
           "title": "...",
           "description": "...",
           "cells": {"code": 12, "markdown": 8},
           "size": 45213,
           "updated_at": "..."},
          ...
        ],
        "n_total": 13
      }
    """
    if not _NOTEBOOKS_DIR.exists():
        return {"notebooks": [], "n_total": 0}

    out: list[dict] = []
    for nb_path in sorted(_NOTEBOOKS_DIR.glob("*.ipynb")):
        try:
            stat = nb_path.stat()
        except Exception:
            continue
        title, desc = _extract_notebook_title_and_desc(nb_path)
        out.append({
            "filename": nb_path.name,
            "title": title,
            "description": desc,
            "cells": _count_cells(nb_path),
            "size": stat.st_size,
            "updated_at": datetime.fromtimestamp(stat.st_mtime).isoformat(timespec="seconds"),
        })
    return {"notebooks": out, "n_total": len(out)}


if __name__ == "__main__":
    import json as _j
    print(_j.dumps(list_notebooks(), ensure_ascii=False, indent=2)[:1500])
