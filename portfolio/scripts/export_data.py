"""
Portfolio 数据导出管道 — 最小可用版（Phase A.2）

把 quant-dojo 仓库里分散的研究产物汇聚成一组前端可直接 `fetch()` 的
JSON，写到 `portfolio/public/data/` 下。Next.js 构建时以 SSG 读取，
所以所有数据必须在 `npm run build` 之前跑一次本脚本。

输出结构（相对于 portfolio/public/data/）：
  meta.json                    生成时间 + 源 commit
  factors/index.json           66 因子汇总列表（轻量）
  factors/hero.json            8 个英雄因子（含 IC 统计 + 选定理由）
  strategy/versions.json       v7/v9/v10/v16 四个策略版本的元数据 + 指标
  strategy/equity_v9.json      v9 权益曲线（walk-forward 研究门面）
  strategy/equity_v16.json     v16 权益曲线（生产门面）
  journey/phases.json          ROADMAP.md 里的阶段与完成状态

运行:
  python portfolio/scripts/export_data.py
"""
from __future__ import annotations

import csv
import json
import re
import subprocess
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
PORTFOLIO = ROOT / "portfolio"
OUT = PORTFOLIO / "public" / "data"

COVERAGE_JSON = ROOT / "journal" / "portfolio_factor_coverage.json"
ROADMAP_MD = ROOT / "ROADMAP.md"
RUNS_DIR = ROOT / "live" / "runs"
STATE_JSON = ROOT / "live" / "strategy_state.json"
SIGNALS_DIR = ROOT / "live" / "signals"
SNAPSHOT_DIR = ROOT / "live" / "factor_snapshot"
JOURNAL_DIR = ROOT / "journal"

# 双门面策略决策见 journal/portfolio_face_strategy.md
FACE_RESEARCH_VERSION = "v9"
FACE_PRODUCTION_VERSION = "v16"

# 8 个英雄因子（见 journal/portfolio_hero_factors.md）
HERO_FACTORS: list[dict] = [
    {
        "name": "enhanced_momentum",
        "tier": "core",
        "title_en": "Enhanced Momentum",
        "title_zh": "风险调整动量",
        "pitch": "风险调整动量，reversal_1m 的进化版 — 把收益除以波动率再取横截面排名。",
    },
    {
        "name": "bp_factor",
        "tier": "core",
        "title_en": "Book-to-Price",
        "title_zh": "账面市值比（价值因子）",
        "pitch": "经典 Fama-French 价值因子 — 1/PB 做截面 winsorize，FM t 接近显著。",
    },
    {
        "name": "low_vol_20d",
        "tier": "core",
        "title_en": "Low Volatility 20d",
        "title_zh": "20日低波动",
        "pitch": "覆盖度全库第一：研究文件夹 + notebook + IC 统计 + v7 + v16 + snapshot 六项齐全。",
    },
    {
        "name": "roe_factor",
        "tier": "core",
        "title_en": "ROE (Honest Failure)",
        "title_zh": "ROE — 诚实证伪",
        "pitch": "假设质量溢价 → IC≈0、FM 不显著。展示在这里不是成功案例，是研究流程本身。",
    },
    {
        "name": "team_coin",
        "tier": "experimental",
        "title_en": "Team Coin",
        "title_zh": "球队硬币（行为金融）",
        "pitch": "全库 ICIR 第一 (0.45) + FM t 第一 (5.08)。低波动时看动量，高波动时看反转。",
    },
    {
        "name": "cgo",
        "tier": "experimental",
        "title_en": "Capital Gain Overhang",
        "title_zh": "处置效应 CGO",
        "pitch": "行为金融独有视角 — 未实现盈亏压力；v7 权重 0.20，FM t=3.38。",
    },
    {
        "name": "amihud_illiquidity",
        "tier": "experimental",
        "title_en": "Amihud Illiquidity",
        "title_zh": "Amihud 非流动性",
        "pitch": "v16 引入的流动性维度 — 核心因子稳定后再加新信号的典型扩展路径。",
    },
    {
        "name": "momentum_6m_skip1m",
        "tier": "experimental",
        "title_en": "Momentum 6m Skip-1m",
        "title_zh": "6 月动量 · 跳过最近 1 月",
        "pitch": "中期动量变体，与 enhanced_momentum (60 日) 形成短/中期互补。",
    },
]

STRATEGY_VERSIONS: list[dict] = [
    {
        "id": "v7",
        "name_en": "5-Factor Baseline",
        "name_zh": "5 因子等权基线",
        "tagline": "通过 admission 的第一版 — 手工权重、等权合成",
        "status": "legacy",
        "era_start": "2026-Q1",
        "factors": ["team_coin", "low_vol_20d", "cgo", "enhanced_momentum", "bp_factor"],
    },
    {
        "id": FACE_RESEARCH_VERSION,
        "name_en": "ICIR-Weighted Research Face",
        "name_zh": "ICIR 学习权重 · 研究门面",
        "tagline": "从手工权重到数据驱动 — walk-forward 评估 OOS +18%",
        "status": "research-face",
        "era_start": "2026-Q2",
        "factors": ["team_coin", "low_vol_20d", "cgo", "enhanced_momentum", "bp_factor"],
        "highlights": [
            "OOS Sharpe 1.60 (vs v7 1.35)",
            "Walk-forward 中位 Sharpe 0.5256",
            "权重演化反映 A 股风格切换",
        ],
    },
    {
        "id": "v10",
        "name_en": "v9 + Portfolio Stop-Loss (Rejected)",
        "name_zh": "ICIR 权重 + 组合止损（已否决）",
        "tagline": "止损层破坏 OOS 泛化 — 诚实证伪案例",
        "status": "rejected",
        "era_start": "2026-Q2",
        "factors": ["team_coin", "low_vol_20d", "cgo", "enhanced_momentum", "bp_factor"],
        "highlights": [
            "IS 回撤 -42% → -24%（看起来在救命）",
            "OOS Sharpe 1.60 → 0.27（止损把超额砍光）",
            "WF 中位数 0.53 → 0.46（样本外平均更差）",
            "结论：单独叠加止损无 regime 信号不够，已回滚",
        ],
        "eval_report": "journal/v10_icir_stoploss_eval_20260416.md",
    },
    {
        "id": FACE_PRODUCTION_VERSION,
        "name_en": "9-Factor Production Face",
        "name_zh": "9 因子生产门面",
        "tagline": "因子挖掘落地 — 年化 22.37%，当前 live active",
        "status": "production",
        "era_start": "2026-Q4",
        "factors": [
            "low_vol_20d",
            "team_coin",
            "shadow_lower",
            "amihud_illiquidity",
            "price_volume_divergence",
            "high_52w_ratio",
            "turnover_acceleration",
            "momentum_6m_skip1m",
            "win_rate_60d",
        ],
    },
]


def git_head() -> dict:
    try:
        sha = subprocess.check_output(
            ["git", "-C", str(ROOT), "rev-parse", "HEAD"], text=True
        ).strip()
        short = sha[:8]
        msg = subprocess.check_output(
            ["git", "-C", str(ROOT), "log", "-1", "--pretty=%s"], text=True
        ).strip()
        return {"sha": sha, "short": short, "subject": msg}
    except Exception:
        return {"sha": None, "short": None, "subject": None}


def load_coverage() -> dict:
    if not COVERAGE_JSON.exists():
        raise SystemExit(
            f"Missing {COVERAGE_JSON.relative_to(ROOT)} — "
            "run scripts/audit_factor_data_coverage.py first."
        )
    return json.loads(COVERAGE_JSON.read_text(encoding="utf-8"))


def load_hero_stats() -> dict | None:
    """取 journal/hero_factor_stats_*.json 里最新的那份（文件名含日期）。"""
    candidates = sorted(JOURNAL_DIR.glob("hero_factor_stats_*.json"))
    if not candidates:
        return None
    try:
        return json.loads(candidates[-1].read_text(encoding="utf-8"))
    except Exception as e:
        print(f"  [warn] hero_factor_stats load failed: {e}")
        return None


def latest_run(strategy_id: str) -> Path | None:
    """取 live/runs/ 里指定策略最新的成功 run JSON。"""
    candidates = sorted(
        RUNS_DIR.glob(f"multi_factor_{strategy_id}_*.json"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    for p in candidates:
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            continue
        if data.get("status") == "success":
            return p
    return None


def write_factors(coverage: dict) -> None:
    factors_dir = OUT / "factors"
    factors_dir.mkdir(parents=True, exist_ok=True)

    rows = []
    for f in coverage["factors"]:
        ic = f.get("ic_stats") or {}
        rows.append(
            {
                "name": f["name"],
                "category": f["category"],
                "docstring": f["docstring_first"],
                "coverage_score": f["coverage_score"],
                "has_research_folder": f["has_research_folder"],
                "research_slug": f.get("research_folder_slug"),
                "in_v7": f["in_v7_strategy"],
                "in_v16": f["in_v16_strategy"],
                "in_snapshot": f["in_latest_snapshot"],
                "ic_mean": ic.get("ic_mean"),
                "icir": ic.get("icir"),
                "fm_t_stat": ic.get("fm_t_stat"),
                "verdict": ic.get("verdict"),
            }
        )

    index = {
        "generated_at": coverage["generated_at"],
        "total": coverage["total_factors"],
        "with_ic_stats": coverage["with_ic_stats"],
        "with_research_folder": coverage["with_research_folder"],
        "in_v7_strategy": coverage["in_v7_strategy"],
        "in_v16_strategy": coverage["in_v16_strategy"],
        "by_category_counts": {k: len(v) for k, v in coverage["by_category"].items()},
        "factors": rows,
    }
    (factors_dir / "index.json").write_text(
        json.dumps(index, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    # 英雄因子：把覆盖度/IC 等数据贴回来，加上 hero 元数据
    by_name = {f["name"]: f for f in coverage["factors"]}
    hero_rows = []
    for hero in HERO_FACTORS:
        src = by_name.get(hero["name"])
        if src is None:
            print(f"  [warn] hero factor not found in coverage: {hero['name']}")
            continue
        ic = src.get("ic_stats") or {}
        hero_rows.append(
            {
                **hero,
                "category": src["category"],
                "docstring": src["docstring_first"],
                "coverage_score": src["coverage_score"],
                "research_slug": src.get("research_folder_slug"),
                "lineno": src["lineno"],
                "in_v7": src["in_v7_strategy"],
                "in_v16": src["in_v16_strategy"],
                "ic_mean": ic.get("ic_mean"),
                "icir": ic.get("icir"),
                "ic_positive_pct": ic.get("ic_positive_pct"),
                "fm_t_stat": ic.get("fm_t_stat"),
                "verdict": ic.get("verdict"),
                "has_ic_stats": src["has_ic_stats"],
            }
        )
    (factors_dir / "hero.json").write_text(
        json.dumps(
            {"generated_at": coverage["generated_at"], "factors": hero_rows},
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    print(f"  wrote factors/index.json  ({len(rows)} factors)")
    print(f"  wrote factors/hero.json   ({len(hero_rows)} hero factors)")

    # hero_detail.json — 深度数据（IC 月度序列 / 衰减 / 分层）
    hero_stats = load_hero_stats()
    if hero_stats is None:
        print("  [skip] factors/hero_detail.json — "
              "run scripts/deep_analysis_hero_factors.py to populate")
        return
    detail_payload = {
        "generated_at": hero_stats.get("generated_at"),
        "window": hero_stats.get("window"),
        "fwd_days": hero_stats.get("fwd_days"),
        "universe_size": hero_stats.get("universe_size"),
        "trading_days": hero_stats.get("trading_days"),
        "factors": hero_stats.get("factors", {}),
    }
    (factors_dir / "hero_detail.json").write_text(
        json.dumps(detail_payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    n_with_data = sum(
        1 for f in detail_payload["factors"].values() if "error" not in f
    )
    print(f"  wrote factors/hero_detail.json ({n_with_data} factors with deep data)")


def write_strategy(coverage_generated_at: str) -> None:
    strategy_dir = OUT / "strategy"
    strategy_dir.mkdir(parents=True, exist_ok=True)

    # 读 live/strategy_state.json 拿当前 active
    state = {}
    if STATE_JSON.exists():
        try:
            state = json.loads(STATE_JSON.read_text(encoding="utf-8"))
        except Exception:
            state = {}
    active = state.get("active_strategy")

    versions_out = []
    for v in STRATEGY_VERSIONS:
        run_path = latest_run(v["id"])
        metrics = None
        run_id = None
        equity_ref = None
        if run_path:
            data = json.loads(run_path.read_text(encoding="utf-8"))
            m = data.get("metrics") or {}
            metrics = {
                "total_return": m.get("total_return"),
                "annualized_return": m.get("annualized_return"),
                "sharpe": m.get("sharpe"),
                "max_drawdown": m.get("max_drawdown"),
                "volatility": m.get("volatility"),
                "win_rate": m.get("win_rate"),
                "n_trading_days": m.get("n_trading_days"),
                "period_start": m.get("start_date"),
                "period_end": m.get("end_date"),
            }
            run_id = data.get("run_id")
            equity_csv = run_path.with_name(run_path.stem + "_equity.csv")
            if equity_csv.exists():
                equity_ref = write_equity_curve(equity_csv, v["id"])
        versions_out.append(
            {
                **v,
                "is_active": (v["id"] == active),
                "run_id": run_id,
                "metrics": metrics,
                "equity_file": equity_ref,
            }
        )

    payload = {
        "generated_at": coverage_generated_at,
        "active_strategy": active,
        "active_note": state.get("note"),
        "research_face": FACE_RESEARCH_VERSION,
        "production_face": FACE_PRODUCTION_VERSION,
        "versions": versions_out,
    }
    (strategy_dir / "versions.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"  wrote strategy/versions.json ({len(versions_out)} versions)")


def write_equity_curve(csv_path: Path, strategy_id: str) -> str:
    """把 equity CSV 转成精简 JSON（date + cum_return）。"""
    strategy_dir = OUT / "strategy"
    out_name = f"equity_{strategy_id}.json"
    out_path = strategy_dir / out_name

    points = []
    with csv_path.open(encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            points.append(
                {
                    "date": row.get("date"),
                    "cum_return": float(row.get("cumulative_return") or 0.0),
                }
            )
    out_path.write_text(
        json.dumps(
            {"strategy": strategy_id, "points": points},
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    print(f"  wrote strategy/{out_name}  ({len(points)} points)")
    return out_name


PHASE_HEADER_RE = re.compile(r"^## Phase ([\w\d\-\. ]+?)[:：](.+?)$")


def parse_roadmap() -> list[dict]:
    """解析 ROADMAP.md 的 ## Phase N:... 标题，连带统计完成勾选比。"""
    if not ROADMAP_MD.exists():
        return []
    text = ROADMAP_MD.read_text(encoding="utf-8")
    lines = text.splitlines()

    phases: list[dict] = []
    current: dict | None = None

    def close(p: dict | None):
        if p is None:
            return
        checks = p.pop("_checks", [])
        done = sum(1 for c in checks if c)
        total = len(checks)
        p["checks_total"] = total
        p["checks_done"] = done
        p["progress"] = (done / total) if total else None
        phases.append(p)

    for raw in lines:
        line = raw.rstrip()
        # 任何 `## ` 顶级标题都终止当前 Phase 的 checkbox 归属，
        # 避免 ROADMAP 尾部 "## Portfolio 站点" 的勾选泄漏进 phase 8。
        if line.startswith("## ") and not PHASE_HEADER_RE.match(line):
            close(current)
            current = None
            continue
        m = PHASE_HEADER_RE.match(line)
        if m and line.startswith("## "):
            close(current)
            label, desc = m.groups()
            # desc 可能含 ✅/完成/运行中 等状态尾词
            status = "planned"
            if "✅" in desc or "完成" in desc:
                status = "done"
            elif "运行中" in desc or "进行中" in desc:
                status = "running"
            current = {
                "id": f"phase-{label.strip().lower().replace(' ', '-')}",
                "label": f"Phase {label.strip()}",
                "title": desc.replace("✅", "").strip(),
                "status": status,
                "_checks": [],
            }
            continue
        if current is None:
            continue
        # 统计任务勾选
        t = line.strip()
        if t.startswith("- [x]"):
            current["_checks"].append(True)
        elif t.startswith("- [ ]"):
            current["_checks"].append(False)

    close(current)
    return phases


def write_journey() -> None:
    journey_dir = OUT / "journey"
    journey_dir.mkdir(parents=True, exist_ok=True)
    phases = parse_roadmap()
    (journey_dir / "phases.json").write_text(
        json.dumps(
            {
                "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
                "source": "ROADMAP.md",
                "phases": phases,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    print(f"  wrote journey/phases.json ({len(phases)} phases)")


def write_live() -> None:
    """导出 live/dashboard.json：最近信号、最近 runs、strategy state 摘要。"""
    live_dir = OUT / "live"
    live_dir.mkdir(parents=True, exist_ok=True)

    state: dict = {}
    if STATE_JSON.exists():
        try:
            state = json.loads(STATE_JSON.read_text(encoding="utf-8"))
        except Exception:
            state = {}

    signal_dates: list[str] = []
    if SIGNALS_DIR.exists():
        signal_dates = sorted(
            [p.stem for p in SIGNALS_DIR.glob("*.json")],
            reverse=True,
        )[:10]

    snapshot_dates: list[str] = []
    if SNAPSHOT_DIR.exists():
        snapshot_dates = sorted(
            [p.stem for p in SNAPSHOT_DIR.glob("*.json")],
            reverse=True,
        )[:10]

    recent_runs: list[dict] = []
    seen_run_ids: set[str] = set()
    if RUNS_DIR.exists():
        candidates = sorted(
            RUNS_DIR.glob("multi_factor_*.json"),
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )
        for p in candidates[:40]:
            try:
                data = json.loads(p.read_text(encoding="utf-8"))
            except Exception:
                continue
            rid = data.get("run_id")
            if not rid or rid in seen_run_ids:
                continue
            seen_run_ids.add(rid)
            m = data.get("metrics") or {}
            recent_runs.append(
                {
                    "run_id": rid,
                    "strategy_id": data.get("strategy_id"),
                    "strategy_name": data.get("strategy_name"),
                    "status": data.get("status"),
                    "created_at": data.get("created_at"),
                    "annualized_return": m.get("annualized_return"),
                    "sharpe": m.get("sharpe"),
                    "max_drawdown": m.get("max_drawdown"),
                }
            )
            if len(recent_runs) >= 15:
                break

    payload = {
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
        "active_strategy": state.get("active_strategy"),
        "active_note": state.get("note"),
        "state_updated_at": state.get("updated_at"),
        "signal_dates": signal_dates,
        "snapshot_dates": snapshot_dates,
        "recent_runs": recent_runs,
    }
    (live_dir / "dashboard.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(
        f"  wrote live/dashboard.json "
        f"(signals={len(signal_dates)}, runs={len(recent_runs)})"
    )


def write_meta(coverage: dict) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "meta.json").write_text(
        json.dumps(
            {
                "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                "coverage_generated_at": coverage["generated_at"],
                "git": git_head(),
                "face": {
                    "research": FACE_RESEARCH_VERSION,
                    "production": FACE_PRODUCTION_VERSION,
                },
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    print("  wrote meta.json")


def main() -> None:
    print(f"Exporting to {OUT.relative_to(ROOT)}")
    coverage = load_coverage()
    write_meta(coverage)
    write_factors(coverage)
    write_strategy(coverage["generated_at"])
    write_live()
    write_journey()
    print("done.")


if __name__ == "__main__":
    main()
