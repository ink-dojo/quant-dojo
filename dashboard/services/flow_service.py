"""
dashboard/services/flow_service.py — 工作流状态服务层

把"项目现在处于哪一步、下一步应该做什么"抽象成一组状态卡片
（data / signal / rebalance / risk / weekly_report）。

面向零经验用户 —— 每个状态带中文说明和 CTA（call-to-action），
让新人不用翻文档就能知道接下来点什么按钮。
"""
from __future__ import annotations

import json
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Optional

# ══════════════════════════════════════════════════════════════
# 路径锚定
# ══════════════════════════════════════════════════════════════

_ROOT = Path(__file__).parent.parent.parent
_LIVE = _ROOT / "live"
_SIGNALS_DIR = _LIVE / "signals"
_RUNS_DIR = _LIVE / "runs"
_PORTFOLIO_DIR = _LIVE / "portfolio"
_FACTOR_SNAPSHOT = _LIVE / "factor_snapshot"
_WEEKLY_DIR = _ROOT / "journal" / "weekly"
_EXPERIMENTS_DIR = _LIVE / "experiments"
_STRATEGY_STATE = _LIVE / "strategy_state.json"


# ══════════════════════════════════════════════════════════════
# 工具函数
# ══════════════════════════════════════════════════════════════

def _latest_file(directory: Path, pattern: str = "*.json") -> Optional[Path]:
    """返回目录里名字排序最大的文件。不存在返回 None。"""
    if not directory.exists():
        return None
    files = sorted(directory.glob(pattern))
    return files[-1] if files else None


def _file_mtime_iso(path: Path) -> str:
    """文件 mtime → ISO 字符串。"""
    return datetime.fromtimestamp(path.stat().st_mtime).isoformat(timespec="seconds")


def _days_since(iso_str: str) -> Optional[int]:
    """从 ISO 时间字符串到今天的完整天数。"""
    try:
        dt = datetime.fromisoformat(iso_str.replace("Z", ""))
        return (datetime.now() - dt).days
    except Exception:
        return None


# ══════════════════════════════════════════════════════════════
# 状态卡片构造器
# ══════════════════════════════════════════════════════════════

def _data_card() -> dict:
    """数据是否准备好？—— 检查 factor_snapshot 的最新日期。"""
    latest = _latest_file(_FACTOR_SNAPSHOT, "*.parquet")
    if latest is None:
        return {
            "key": "data",
            "title": "① 数据",
            "status": "missing",
            "headline": "未找到因子截面",
            "explain": "系统还没算过因子。先跑一次 pipeline，会自动从本地 CSV 加载价格、计算因子、写入截面。",
            "cta": {"label": "立刻运行 pipeline", "endpoint": "POST /api/trigger/rebalance"},
            "detail": {"factor_snapshot_dir": str(_FACTOR_SNAPSHOT)},
        }
    as_of = latest.stem  # "20260407"
    mtime = _file_mtime_iso(latest)
    age = _days_since(mtime) or 0
    fresh = age <= 3
    return {
        "key": "data",
        "title": "① 数据",
        "status": "ok" if fresh else "stale",
        "headline": f"截面日期 {as_of}（{age} 天前）",
        "explain": "每天 A 股收盘后的 OHLCV + 因子值。新鲜的数据是所有下游的基础 —— 超过 3 天就算旧了。" if fresh
        else "数据有点旧了。重新跑一次 pipeline 就会刷新因子截面。",
        "cta": None if fresh else {"label": "刷新数据", "endpoint": "POST /api/trigger/rebalance"},
        "detail": {"as_of_date": as_of, "updated_at": mtime, "age_days": age},
    }


def _signal_card() -> dict:
    """最近一次选股信号。"""
    latest = _latest_file(_SIGNALS_DIR, "*.json")
    if latest is None:
        return {
            "key": "signal",
            "title": "② 每日选股",
            "status": "missing",
            "headline": "还没有任何信号",
            "explain": "信号是「今天应该持有哪 30 只股票」的清单，由因子合成打分后选出。点「运行 pipeline」会在 live/signals/ 生成一条。",
            "cta": {"label": "生成今日信号", "endpoint": "POST /api/trigger/rebalance"},
            "detail": None,
        }
    try:
        data = json.loads(latest.read_text(encoding="utf-8"))
    except Exception:
        data = {}
    sig_date = data.get("date", latest.stem)
    picks = data.get("picks", []) or []
    factors_used = (data.get("metadata") or {}).get("factors_used", [])
    strategy = (data.get("metadata") or {}).get("strategy", "ad_hoc")
    age = _days_since(_file_mtime_iso(latest)) or 0
    return {
        "key": "signal",
        "title": "② 每日选股",
        "status": "ok" if age <= 3 else "stale",
        "headline": f"{sig_date} 选出 {len(picks)} 只（策略 {strategy}）",
        "explain": "多因子打分把 5000+ 只股票压缩成 30 只候选，这就是你下一步应该关注的持仓。",
        "cta": None,
        "detail": {
            "date": sig_date,
            "n_picks": len(picks),
            "factors_used": factors_used,
            "strategy": strategy,
            "top_picks": picks[:10],
        },
    }


def _portfolio_card() -> dict:
    """模拟盘组合最新净值。"""
    nav_file = _PORTFOLIO_DIR / "nav.csv"
    if not nav_file.exists():
        return {
            "key": "portfolio",
            "title": "③ 模拟盘",
            "status": "missing",
            "headline": "未启动",
            "explain": "模拟盘按信号虚拟建仓、每日计算净值。跑一次 rebalance 就会初始化。",
            "cta": {"label": "初始化组合", "endpoint": "POST /api/trigger/rebalance"},
            "detail": None,
        }
    try:
        lines = nav_file.read_text(encoding="utf-8").strip().splitlines()
        if len(lines) < 2:
            raise ValueError("nav.csv 为空")
        header = lines[0].split(",")
        last = lines[-1].split(",")
        row = dict(zip(header, last))
        nav = float(row.get("nav", row.get("total_value", 1.0)))
        last_date = row.get("date", "?")
        initial = 1.0
        if "initial_capital" in header:
            initial = float(row.get("initial_capital", 1.0)) or 1.0
        pnl = (nav / initial - 1) * 100 if initial else 0.0
        return {
            "key": "portfolio",
            "title": "③ 模拟盘",
            "status": "ok",
            "headline": f"净值 {nav:.4f}（{pnl:+.2f}%）",
            "explain": "模拟盘按你的策略每日虚拟调仓，不碰真钱，累计净值告诉你策略在实盘条件下表现如何。",
            "cta": None,
            "detail": {"nav": nav, "last_date": last_date, "pnl_pct": round(pnl, 4)},
        }
    except Exception as exc:
        return {
            "key": "portfolio",
            "title": "③ 模拟盘",
            "status": "warning",
            "headline": "读取异常",
            "explain": f"nav.csv 存在但解析失败：{exc}",
            "cta": None,
            "detail": None,
        }


def _risk_card() -> dict:
    """风险快照 —— 统计 live/runs 失败率 + factor health。"""
    runs = sorted(_RUNS_DIR.glob("*.json")) if _RUNS_DIR.exists() else []
    n_runs = len(runs)
    n_failed = 0
    for p in runs[-20:]:  # 看最近 20 条
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
            if data.get("status") == "failed":
                n_failed += 1
        except Exception:
            continue

    # 因子健康
    try:
        from pipeline.factor_monitor import factor_health_report
        health = factor_health_report()
        degraded = [k for k, v in health.items() if v.get("status") in ("degraded", "dead")]
    except Exception:
        degraded = []

    status = "ok"
    headline_parts = []
    if n_failed > 0:
        status = "warning"
        headline_parts.append(f"最近 {n_failed}/{min(n_runs,20)} 次回测失败")
    if degraded:
        status = "warning" if status == "ok" else status
        headline_parts.append(f"{len(degraded)} 个因子退化")
    if not headline_parts:
        headline_parts.append("无告警")

    return {
        "key": "risk",
        "title": "④ 风险监控",
        "status": status,
        "headline": " · ".join(headline_parts),
        "explain": "系统会盯着回测失败率、最大回撤、因子衰减。出现黄色就停下来检查 —— 这是策略翻车前的早期信号。",
        "cta": None,
        "detail": {"n_runs_total": n_runs, "n_failed_last_20": n_failed, "degraded_factors": degraded},
    }


def _weekly_report_card() -> dict:
    """最新周报。"""
    if not _WEEKLY_DIR.exists():
        return {
            "key": "weekly",
            "title": "⑤ 周报",
            "status": "missing",
            "headline": "未找到 journal/weekly/",
            "explain": "每周五跑 weekly_report 会写一份策略复盘到 journal/weekly/，记录净值、持仓、因子 IC。",
            "cta": {"label": "生成周报", "endpoint": "POST /api/trigger/weekly-report"},
            "detail": None,
        }
    files = sorted(_WEEKLY_DIR.glob("*.md"))
    if not files:
        return {
            "key": "weekly",
            "title": "⑤ 周报",
            "status": "missing",
            "headline": "周报目录为空",
            "explain": "每周五跑一次 weekly_report，系统会把这一周的净值、持仓、因子 IC 总结成一份 markdown。",
            "cta": {"label": "生成周报", "endpoint": "POST /api/trigger/weekly-report"},
            "detail": None,
        }
    latest = files[-1]
    mtime = _file_mtime_iso(latest)
    age = _days_since(mtime) or 0
    return {
        "key": "weekly",
        "title": "⑤ 周报",
        "status": "ok" if age <= 10 else "stale",
        "headline": f"{latest.stem}（{age} 天前）",
        "explain": "本周净值 / 持仓 / 因子 IC / 风险告警 的汇总。每周五运行一次，是最重要的阶段性审计产物。",
        "cta": None if age <= 10 else {"label": "生成新一期", "endpoint": "POST /api/trigger/weekly-report"},
        "detail": {"file": latest.name, "updated_at": mtime},
    }


def _research_card() -> dict:
    """Phase 7 研究助理 —— 有没有提议中的实验。"""
    if not _EXPERIMENTS_DIR.exists():
        return {
            "key": "research",
            "title": "⑥ 研究助理",
            "status": "idle",
            "headline": "没有实验记录",
            "explain": "Phase 7 研究助理会根据因子健康和风险状态提议回测实验，但必须人工批准才会真正执行。",
            "cta": None,
            "detail": {"n_experiments": 0},
        }
    files = list(_EXPERIMENTS_DIR.glob("*.json"))
    n_total = len(files)
    status_counts: dict[str, int] = {}
    for p in files:
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
            s = data.get("status", "proposed")
            status_counts[s] = status_counts.get(s, 0) + 1
        except Exception:
            continue
    proposed = status_counts.get("proposed", 0)
    return {
        "key": "research",
        "title": "⑥ 研究助理",
        "status": "attention" if proposed else "idle",
        "headline": f"共 {n_total} 个实验，{proposed} 个待批准" if proposed else f"共 {n_total} 个实验",
        "explain": "AI 把系统异常转成「要不要跑一次 backtest 验证」的提议。你可以在「研究」页看到每条提议、批准后才会真跑。",
        "cta": None,
        "detail": {"n_total": n_total, "by_status": status_counts},
    }


# ══════════════════════════════════════════════════════════════
# 对外
# ══════════════════════════════════════════════════════════════

def _active_strategy() -> str:
    """从 strategy_state.json 读当前策略，读不到用默认 v7。"""
    try:
        if _STRATEGY_STATE.exists():
            data = json.loads(_STRATEGY_STATE.read_text(encoding="utf-8"))
            return data.get("active_strategy", "v7")
    except Exception:
        pass
    return "v7"


def _suggested_next_action(cards: list[dict]) -> dict:
    """
    从所有卡片里选一条最该做的事返回。顺序：
      1. 任何 missing 状态的第一个 → 补齐
      2. 任何 stale 状态的第一个 → 刷新
      3. attention（研究提议） → 批准
      4. 否则默认"看看总览"
    """
    for c in cards:
        if c["status"] == "missing":
            return {
                "card_key": c["key"],
                "title": f"先补上：{c['title']}",
                "explain": c["explain"],
                "cta": c["cta"],
            }
    for c in cards:
        if c["status"] == "stale":
            return {
                "card_key": c["key"],
                "title": f"刷新：{c['title']}",
                "explain": c["explain"],
                "cta": c["cta"],
            }
    for c in cards:
        if c["status"] == "attention":
            return {
                "card_key": c["key"],
                "title": f"需要你决定：{c['title']}",
                "explain": c["explain"],
                "cta": {"label": "打开研究页", "route": "#research"},
            }
    return {
        "card_key": None,
        "title": "一切正常",
        "explain": "系统健康。你可以去「因子库」看看每个因子表现，或者在「文档」页读 ROADMAP 对齐下一阶段计划。",
        "cta": {"label": "浏览因子库", "route": "#factors"},
    }


def get_flow_status() -> dict:
    """
    聚合整条工作流的状态卡片 + 下一步建议。

    返回:
        {
          "generated_at": "2026-04-08T21:05:00",
          "active_strategy": "v7",
          "cards": [data, signal, portfolio, risk, weekly, research],
          "next_action": {...}
        }
    """
    cards = [
        _data_card(),
        _signal_card(),
        _portfolio_card(),
        _risk_card(),
        _weekly_report_card(),
        _research_card(),
    ]
    return {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "active_strategy": _active_strategy(),
        "cards": cards,
        "next_action": _suggested_next_action(cards),
    }


if __name__ == "__main__":
    import json as _json
    print(_json.dumps(get_flow_status(), ensure_ascii=False, indent=2))
