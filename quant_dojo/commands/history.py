"""
quant_dojo history — 运行历史索引

统一视角看所有运行记录：
  - live/runs/*.json           回测 run（标准化 backtest）
  - logs/quant_dojo_run_*.json 每日 pipeline run

用法:
  python -m quant_dojo history                          # 最近 20 条全部
  python -m quant_dojo history --type backtest          # 只看回测
  python -m quant_dojo history --type daily             # 只看每日 pipeline
  python -m quant_dojo history --strategy v7            # 筛选策略
  python -m quant_dojo history --status success         # 筛选状态
  python -m quant_dojo history --limit 50               # 条数
  python -m quant_dojo history --json                   # 机器可读

一行一条、固定宽度，方便 grep / 人眼扫描。
"""
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Optional

PROJECT_ROOT = Path(__file__).parent.parent.parent
LIVE_RUNS_DIR = PROJECT_ROOT / "live" / "runs"
LOGS_DIR = PROJECT_ROOT / "logs"


def _load_backtest_runs() -> list[dict]:
    """读 live/runs/*.json 并归一化字段"""
    if not LIVE_RUNS_DIR.exists():
        return []
    out = []
    for path in LIVE_RUNS_DIR.glob("*.json"):
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except (OSError, json.JSONDecodeError):
            continue
        # 只看有 run_id 的真正回测记录（排除 equity csv 或其他辅助 json）
        if "run_id" not in data or "strategy_id" not in data:
            continue
        metrics = data.get("metrics", {}) or {}
        out.append({
            "kind": "backtest",
            "run_id": data.get("run_id", ""),
            "strategy": data.get("strategy_id", ""),
            "status": data.get("status", "?"),
            "created_at": data.get("created_at", ""),
            "start": data.get("start_date", ""),
            "end": data.get("end_date", ""),
            "total_return": metrics.get("total_return"),
            "sharpe": metrics.get("sharpe"),
            "max_drawdown": metrics.get("max_drawdown"),
            "error": data.get("error") or "",
            "path": str(path),
        })
    return out


def _load_daily_runs() -> list[dict]:
    """读 logs/quant_dojo_run_*.json 并归一化字段"""
    if not LOGS_DIR.exists():
        return []
    out = []
    for path in LOGS_DIR.glob("quant_dojo_run_*.json"):
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except (OSError, json.JSONDecodeError):
            continue
        steps = data.get("steps", {}) or {}
        n_ok = sum(1 for s in steps.values() if s.get("status") == "ok")
        n_fail = sum(1 for s in steps.values() if s.get("status") == "failed")
        status = "success" if n_fail == 0 and n_ok > 0 else "failed" if n_fail > 0 else "unknown"
        out.append({
            "kind": "daily",
            "run_id": f"daily_{data.get('date', path.stem)}",
            "strategy": "",
            "status": status,
            "created_at": data.get("timestamp", ""),
            "start": data.get("date", ""),
            "end": data.get("date", ""),
            "total_return": None,
            "sharpe": None,
            "max_drawdown": None,
            "error": "",
            "path": str(path),
            "n_ok": n_ok,
            "n_fail": n_fail,
            "elapsed_sec": data.get("elapsed_sec", 0),
        })
    return out


def _sort_key(row: dict) -> str:
    """按 created_at 排序（倒序），没有时间戳的退回 run_id"""
    return row.get("created_at") or row.get("run_id", "")


def _purge_failed_backtest_runs(dry_run: bool = False) -> list[str]:
    """
    删除 live/runs/ 下状态为 failed 且无有用 metrics 的回测 run JSON。

    这些多来自"忘了传 --start/--end"之类的调试失败，保留它们只会污染
    `quant_dojo status` 的回测记录列表。

    返回被删除（或 dry_run 模式下将会被删除）的路径列表。
    """
    if not LIVE_RUNS_DIR.exists():
        return []
    deleted: list[str] = []
    for path in LIVE_RUNS_DIR.glob("*.json"):
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except (OSError, json.JSONDecodeError):
            continue
        if data.get("status") != "failed":
            continue
        metrics = data.get("metrics") or {}
        # 只删真正空壳的 failed run，保留包含有用 metrics 的失败记录
        if metrics.get("total_return"):
            continue
        deleted.append(str(path))
        if not dry_run:
            try:
                path.unlink()
            except OSError:
                pass
    return deleted


def run_history(
    kind: Optional[str] = None,
    strategy: Optional[str] = None,
    status: Optional[str] = None,
    limit: int = 20,
    as_json: bool = False,
    purge_failed: bool = False,
    dry_run: bool = False,
):
    """
    列出运行历史。

    参数:
        kind         : "backtest" / "daily" / None (所有)
        strategy     : 筛选策略前缀
        status       : 筛选状态 ("success" / "failed" / ...)
        limit        : 最多显示条数
        as_json      : JSON 输出
        purge_failed : 先删除 live/runs/ 下空壳 failed 记录再列表
        dry_run      : purge 模式下只打印不删除
    """
    if purge_failed:
        removed = _purge_failed_backtest_runs(dry_run=dry_run)
        label = "(dry-run) 将删除" if dry_run else "已删除"
        print(f"  {label} {len(removed)} 个空壳 failed run")
        for p in removed:
            print(f"    - {Path(p).name}")
        if removed:
            print()

    rows: list[dict] = []
    if kind in (None, "backtest"):
        rows.extend(_load_backtest_runs())
    if kind in (None, "daily"):
        rows.extend(_load_daily_runs())

    if strategy:
        rows = [r for r in rows if r.get("strategy", "").startswith(strategy)]
    if status:
        rows = [r for r in rows if r.get("status") == status]

    rows.sort(key=_sort_key, reverse=True)
    rows = rows[:limit]

    if as_json:
        print(json.dumps(rows, indent=2, ensure_ascii=False))
        return

    print("╔═══════════════════════════════════════════════╗")
    print("║  quant-dojo 运行历史                           ║")
    print("╚═══════════════════════════════════════════════╝")
    print(f"  筛选: kind={kind or '全部'} strategy={strategy or '*'} "
          f"status={status or '*'} limit={limit}")
    print(f"  共找到 {len(rows)} 条\n")

    if not rows:
        print("  无记录")
        return

    print(f"  {'时间':<20}  {'类型':<9}  {'策略':<8}  {'状态':<8}  {'run_id / 关键信息'}")
    print("  " + "─" * 90)
    for r in rows:
        ts = (r.get("created_at") or "")[:19].replace("T", " ").ljust(19)
        kind_s = r.get("kind", "?").ljust(9)
        strat = (r.get("strategy") or "-").ljust(8)
        st = r.get("status", "?").ljust(8)
        if r["kind"] == "backtest":
            ret = r.get("total_return")
            sharpe = r.get("sharpe")
            if ret is not None and sharpe is not None:
                tail = f"{r['run_id'][:28]:<28}  收益 {ret:+.2%}  夏普 {sharpe:+.2f}"
            elif r.get("error"):
                tail = f"{r['run_id'][:28]:<28}  error: {r['error'][:40]}"
            else:
                tail = r["run_id"]
        else:
            n_ok = r.get("n_ok", 0)
            n_fail = r.get("n_fail", 0)
            elapsed = r.get("elapsed_sec", 0)
            tail = f"{r['run_id'][:28]:<28}  {n_ok}ok/{n_fail}fail  {elapsed:.0f}s"
        print(f"  {ts}  {kind_s}  {strat}  {st}  {tail}")
