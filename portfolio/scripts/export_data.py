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
import hashlib
import json
import re
import shutil
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
SOURCE_DIR = OUT / "source"

# 策略门面（诚实版）
# v9  — 实际生产门面：ICIR 学习权重、WF 中位 sharpe 0.53、OOS +18%，真实 track record
# v16 — 因子挖掘会话候选：2026-04-14 从 v11-v21 中挑出，仅 1 次 IS 回测、未做 WF，
#       最大回撤 -43% 超过 30% 红线、sharpe 0.73 未达 0.8 门槛 → 标为 candidate 不上 live
FACE_PRODUCTION_VERSION = "v9"
FACE_RESEARCH_VERSION = "v9"
CANDIDATE_VERSION = "v25"

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
        "era_start": "Week 5 · 2026-04-13",
        "factors": ["team_coin", "low_vol_20d", "cgo", "enhanced_momentum", "bp_factor"],
    },
    {
        "id": "v9",
        "name_en": "ICIR-Weighted Research Face",
        "name_zh": "ICIR 学习权重 · research face",
        "tagline": "手工权重 → 数据驱动. WF 中位 sharpe 0.53 · OOS 较 v7 +18% · 多因子线里唯一通过完整 WF 验证的版本",
        "status": "production",
        "era_start": "Week 5 · 2026-04-13 ~ 04-17",
        "factors": ["team_coin", "low_vol_20d", "cgo", "enhanced_momentum", "bp_factor"],
        "highlights": [
            "OOS Sharpe 1.60 (vs v7 1.35)",
            "Walk-forward 17 窗口中位 Sharpe 0.53",
            "权重演化反映 A 股风格切换",
            "与 v7 同因子集 → 方法论升级，非扩因子",
        ],
    },
    {
        "id": "v10",
        "name_en": "v9 + Portfolio Stop-Loss (Rejected)",
        "name_zh": "ICIR 权重 + 组合止损（已否决）",
        "tagline": "止损层破坏 OOS 泛化 — 诚实证伪案例",
        "status": "rejected",
        "era_start": "Week 5 · 2026-04-13 ~ 04-17",
        "factors": ["team_coin", "low_vol_20d", "cgo", "enhanced_momentum", "bp_factor"],
        "highlights": [
            "IS 回撤 -42% → -24%（看起来在救命）",
            "OOS Sharpe 1.60 → 0.27（止损把超额砍光）",
            "WF 中位数 0.53 → 0.46（样本外平均更差）",
            "结论：无 regime 信号的裸止损不够，已回滚",
        ],
        "eval_report": "journal/v10_icir_stoploss_eval_20260416.md",
    },
    {
        "id": "v16",
        "name_en": "9-Factor Mining Candidate",
        "name_zh": "9 因子挖掘候选（pending WF）",
        "tagline": "2026-04-14 因子挖掘会话从 v11-v21 共 12 个候选中挑出；IS sharpe 0.80、回撤 -43% 红线未过",
        "status": "candidate",
        "era_start": "Week 5 · 2026-04-13 ~ 04-17",
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
        "highlights": [
            "IS 年化 22.9% / Sharpe 0.80（sharpe 公式 2026-04-17 修复后重算）",
            "PSR 95.3% — 夏普显著大于零",
            "但最大回撤 -43% 超过 30% 红线（CLAUDE.md）",
            "WF 验证尚未运行 — 样本外表现未知",
            "与 v10 当初的幻觉同构：从 12 候选里挑 best-in-sample",
        ],
        "gate_check": {
            "annual_return": {"value": 0.2287, "threshold": 0.15, "pass": True},
            "sharpe": {"value": 0.80, "threshold": 0.8, "pass": True},
            "max_drawdown": {"value": -0.4306, "threshold": -0.30, "pass": False},
            "wf_validated": {"value": False, "threshold": True, "pass": False},
        },
    },
    {
        "id": "v25",
        "name_en": "v16 + HS300 Regime-Gated Stop",
        "name_zh": "v16 + HS300 熊市门控止损",
        "tagline": "2026-04-17 回撤治理：HS300<MA120 时启用半仓止损，MDD 从 -43% 收到 -26%；sharpe 仅退 0.03",
        "status": "candidate",
        "era_start": "Week 5 · 2026-04-13 ~ 04-17",
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
        "highlights": [
            "IS 2022-2025 年化 18.7% / Sharpe 0.77 / MDD -26%",
            "PSR 95.1% — 夏普显著大于零；DSR 91.1%",
            "MDD 过 admission -30% 门（v16 -43% 不过）",
            "Sharpe 0.77 仍低于 0.80 admission 门槛，差 0.03",
            "外生 regime（HS300 120 日均线）门控 → 震荡市不触发，避免 v10/v11 反例",
            "WF 验证待办：验证 regime 门控在 OOS 仍有效",
        ],
        "gate_check": {
            "annual_return": {"value": 0.1872, "threshold": 0.15, "pass": True},
            "sharpe": {"value": 0.77, "threshold": 0.8, "pass": False},
            "max_drawdown": {"value": -0.2605, "threshold": -0.30, "pass": True},
            "wf_validated": {"value": False, "threshold": True, "pass": False},
        },
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

    # 诚实门面 vs strategy_state.json 声明的 active：
    #   production_face = 我们判断的生产门面（v9，经过 WF 验证）
    #   declared_active = live/strategy_state.json 当前写入（2026-04-14 声明为 v16，
    #                     但 v16 未通过 admission gate 且未生成过 live 信号）
    # 两者不一致本身是故事的一部分，页面上会展示这个 gap。
    payload = {
        "generated_at": coverage_generated_at,
        "production_face": FACE_PRODUCTION_VERSION,
        "research_face": FACE_RESEARCH_VERSION,
        "candidate": CANDIDATE_VERSION,
        "declared_active": None,
        "declared_note": None,
        "face_note": (
            "v9 是走过 walk-forward 17 窗口的 research face (中位 Sharpe 0.53 · OOS 较 v7 +18%). "
            "v16 是 Week 5 挖掘 session 里 sharpe 最高的候选, 但回撤 -43% 超红线、WF 未跑, 未 promote. "
            "实际 paper-trade 跑的是独立的 event-driven BB-only (见 /live/paper-trade), "
            "不是 multi-factor 这条线."
        ),
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


CANDIDATES_CHANGE: dict[str, str] = {
    "v11": "v10 + 2 个正交新因子（shadow_lower + amihud_illiquidity）",
    "v12": "v11 + close_minus_open_volume（主力净买入代理）",
    "v13": "v11 + momentum_6m_skip1m（中期反转）",
    "v14": "v13 + rsi_factor（RSI-14 超买超卖）",
    "v15": "v13 用 price_dist_ma60 替换 high_52w",
    "v16": "v13 + win_rate_60d（60 日胜率反转）",
    "v17": "v16 + vol_asymmetry（上涨/下跌波动率比）",
    "v18": "v16 + network_scc（股票相关性网络关联度）",
    "v19": "v16 + volume_concentration（量能集中度）",
    "v20": "v16 + w_reversal（W 型价格反转）",
    "v21": "v16 用 w_reversal 替换 high_52w",
    "v22": "v16 正交剪枝：5 独立因子（low_vol_20d / team_coin / shadow_lower / pv_div / turnover_accel）",
    "v23": "v16 + adaptive_half_position_stop（IS 调参，2022-2025 MDD -26% 但 sharpe 退 0.08）",
    "v24": "v16 九因子，n_stocks 30→60（宽持仓稀释尾部风险）",
    "v25": "v16 + regime_gated_half_position_stop（HS300<MA120 熊市门控）— 本次会话选中",
}


def write_candidates() -> None:
    """
    导出历次会话产出的 v11-v25 候选。用于 /strategy/candidates 页，
    让访客看到选中版本是从 15 个候选里挑的，不是「独立得到的最优解」。

    指标来源：candidate_review.json（从 equity CSV 基于当前 metrics 公式重新计算，
    避免 2026-04-14 sharpe 公式修复前留下的过时 JSON 指标混入）。
    """
    strategy_dir = OUT / "strategy"
    strategy_dir.mkdir(parents=True, exist_ok=True)

    review_path = strategy_dir / "candidate_review.json"
    review_rows: dict[str, dict] = {}
    if review_path.exists():
        try:
            review_rows = {
                r["version"]: r
                for r in json.loads(review_path.read_text(encoding="utf-8"))["candidates"]
            }
        except Exception:
            review_rows = {}

    ids = list(CANDIDATES_CHANGE.keys())
    rows: list[dict] = []
    for sid in ids:
        p = latest_run(sid)
        if p is None:
            continue
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            continue
        # 优先用 candidate_review.json（权威口径）；缺失时回退 run.json 原始指标
        rev = review_rows.get(sid)
        if rev is not None:
            ann = rev.get("ann_return")
            sr = rev.get("sharpe")
            mdd = rev.get("max_drawdown")
            wr = rev.get("win_rate")
            psr = rev.get("psr_vs_zero")
        else:
            m = data.get("metrics") or {}
            ann = m.get("annualized_return")
            sr = m.get("sharpe")
            mdd = m.get("max_drawdown")
            wr = m.get("win_rate")
            psr = None

        rows.append({
            "id": sid,
            "change_zh": CANDIDATES_CHANGE[sid],
            "run_id": data.get("run_id"),
            "strategy_name": data.get("strategy_name"),
            "created_at": data.get("created_at"),
            "status": data.get("status"),
            "annualized_return": ann,
            "sharpe": sr,
            "max_drawdown": mdd,
            "win_rate": wr,
            "psr": psr,
            "selected": (sid == CANDIDATE_VERSION),
        })

    # 按 sharpe 降序
    rows.sort(key=lambda r: (r.get("sharpe") is None, -(r.get("sharpe") or 0)))

    payload = {
        "session_date": "2026-04-17",
        "session_note": (
            "2026-04-17 回撤治理专场：先修 sharpe 公式 / WF 泄漏 / factor 前视 "
            "/ stop_loss σ 偷看 等 7 处统计代码 bug；再走 Route B—"
            "v25 = v16 + regime_gated_half_position_stop（HS300<MA120 熊市门控）。"
            "IS 2022-2025 MDD 从 -43% 收到 -26%（过 admission -30% 门），"
            "sharpe 仅退 0.03 至 0.768，DSR 91.1%。另 v24（n=60 宽持仓）、"
            "v22（正交剪枝）未能改善回撤或 sharpe，淘汰。"
            "v25 sharpe 0.768 仍 < 0.80 admission gate，下一步需 walk-forward 确认 OOS。"
        ),
        "selected": CANDIDATE_VERSION,
        "candidates": rows,
    }
    (strategy_dir / "candidates.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"  wrote strategy/candidates.json ({len(rows)} candidates)")


# ROADMAP.md 里 Phase N 标题带的是 "（第 X-Y 周）" 这种计划周数 (按 ROADMAP 假设的
# 9 个月日历算的), 不是实际日历周. 项目实际从 2026-03-13 起跑, 所以 Journey 页面
# 展示的是 Week N · 实际日期区间. 下面的 overlay 把两者解耦:
# - title 里的 "（第 X-Y 周）" 去掉 (ROADMAP.md 不动)
# - 加 week_range / date_range 字段, 按实际 git 历史
PHASE_OVERLAY: dict[str, dict[str, str]] = {
    "phase-0": {"week_range": "Week 1", "date_range": "2026-03-13 → 03-17"},
    "phase-1": {"week_range": "Week 1-2", "date_range": "2026-03-18 → 03-26"},
    "phase-2": {"week_range": "Week 2-3", "date_range": "2026-03-27 → 04-02"},
    "phase-3": {"week_range": "Week 3-4", "date_range": "2026-04-03 → 04-09"},
    "phase-4": {"week_range": "Week 4-5", "date_range": "2026-04-10 → 04-16"},
    "phase-5": {"week_range": "Week 5-6", "date_range": "2026-04-14 → 04-21"},
    "phase-6": {"week_range": "Week 6", "date_range": "2026-04-16 → ongoing"},
    "phase-7": {"week_range": "Week 6", "date_range": "2026-04-21 → ongoing"},
    "phase-8": {"week_range": "未开始", "date_range": "planned"},
}

_PHASE_WEEK_SUFFIX_RE = re.compile(r"（第[^）]*周）")


def _strip_week_suffix(title: str) -> str:
    """去掉 ROADMAP 标题里 '（第 X-Y 周）' 计划周数后缀 (保留其他括注)."""
    return _PHASE_WEEK_SUFFIX_RE.sub("", title).strip()


def write_journey() -> None:
    journey_dir = OUT / "journey"
    journey_dir.mkdir(parents=True, exist_ok=True)
    phases = parse_roadmap()
    for p in phases:
        p["title"] = _strip_week_suffix(p["title"])
        overlay = PHASE_OVERLAY.get(p["id"])
        if overlay:
            p["week_range"] = overlay["week_range"]
            p["date_range"] = overlay["date_range"]
    (journey_dir / "phases.json").write_text(
        json.dumps(
            {
                "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
                "project_started_at": "2026-03-13",
                "current_week": 6,
                "current_date": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
                "source": "ROADMAP.md + git history (week overlay)",
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

    # Paper-trade 从 2026-04-17 (Week 6 Day 1) 起真正 live.
    # 之前的 signal 文件是研究期 (multi-factor session) 产物, 不是实盘信号.
    # Live 页面只展示 ≥ go-live 日期的 signal 文件.
    PAPER_TRADE_GO_LIVE = "2026-04-17"
    signal_dates: list[str] = []
    if SIGNALS_DIR.exists():
        signal_dates = sorted(
            [p.stem for p in SIGNALS_DIR.glob("*.json") if p.stem >= PAPER_TRADE_GO_LIVE],
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
        # Multi-factor 线的 research face, 不是实际 live strategy (live 是独立
        # 的 event-driven BB-only spec v3, 见 /live/paper-trade).
        "production_face": FACE_PRODUCTION_VERSION,
        "candidate": CANDIDATE_VERSION,
        "note": (
            "v9 是 walk-forward 验证过的 research face. v25 是 Week 5 mining round + "
            "regime gating 的候选, 未过 admission gate. 实际 paper-trade 跑的是独立的 "
            "event-driven BB-only (spec v3), 见 /live/paper-trade."
        ),
        "signal_dates": signal_dates,
        "signal_dates_note": (
            "Paper-trade 从 2026-04-17 (Week 6 Day 1) 启动; signal 每交易日 EOD 生成. "
            "早于该日期的 signal 文件是研究期 multi-factor session 产物, 不是实盘信号."
        ),
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


SOURCE_GLOBS = [
    "*.md",
    "*.toml",
    "Makefile",
    "utils/**/*.py",
    "backtest/**/*.py",
    "pipeline/**/*.py",
    "live/**/*.py",
    "scripts/**/*.py",
    "tests/**/*.py",
    "research/**/*.py",
    "research/**/*.md",
    "research/**/*.ipynb",
    "journal/**/*.md",
    "quant_dojo/**/*.py",
    "dashboard/**/*.py",
    "strategies/**/*.py",
    "providers/**/*.py",
    "agents/**/*.py",
    "portfolio/src/**/*.ts",
    "portfolio/src/**/*.tsx",
    "portfolio/scripts/**/*.py",
]

SOURCE_EXCLUDE_PARTS = {
    ".git",
    ".next",
    ".vercel",
    "__pycache__",
    "node_modules",
    "out",
    "public",
}

LANG_BY_SUFFIX = {
    ".py": "python",
    ".ts": "typescript",
    ".tsx": "tsx",
    ".md": "markdown",
    ".toml": "toml",
    ".yml": "yaml",
    ".yaml": "yaml",
    ".json": "json",
    ".ipynb": "notebook",
}

MAX_SOURCE_BYTES = 220_000


def _source_kind(rel: str) -> str:
    if rel.startswith("backtest/") or rel.startswith("strategies/"):
        return "backtest"
    if rel.startswith("utils/walk_forward.py") or rel.startswith("utils/purged_cv.py"):
        return "validation"
    if rel.startswith("tests/"):
        return "tests"
    if rel.startswith("live/"):
        return "live"
    if rel.startswith("pipeline/risk") or "risk" in rel or "capacity" in rel or "vol_targeting" in rel:
        return "risk"
    if rel.startswith("pipeline/") or rel.startswith("quant_dojo/") or rel.startswith("dashboard/"):
        return "pipeline"
    if rel.startswith("research/factors/"):
        return "factor"
    if rel.startswith("research/"):
        return "research"
    if rel.startswith("journal/"):
        return "journal"
    if rel.startswith("portfolio/"):
        return "site"
    return "other"


def _source_slug(rel: str) -> str:
    slug = re.sub(r"[^A-Za-z0-9._-]+", "__", rel.strip("/"))
    return slug.strip("_")


def _read_notebook(path: Path) -> str:
    data = json.loads(path.read_text(encoding="utf-8"))
    chunks: list[str] = []
    for i, cell in enumerate(data.get("cells", []), start=1):
        cell_type = cell.get("cell_type", "cell")
        source = cell.get("source", [])
        text = "".join(source) if isinstance(source, list) else str(source)
        if not text.strip():
            continue
        fence = "python" if cell_type == "code" else "markdown"
        chunks.append(f"# %% [{i}] {cell_type}\n```{fence}\n{text.rstrip()}\n```")
    return "\n\n".join(chunks) + "\n"


def _read_source_file(path: Path) -> tuple[str, bool]:
    truncated = False
    if path.suffix == ".ipynb":
        text = _read_notebook(path)
    else:
        raw = path.read_bytes()
        if len(raw) > MAX_SOURCE_BYTES:
            raw = raw[:MAX_SOURCE_BYTES]
            truncated = True
        text = raw.decode("utf-8", errors="replace")
    if len(text.encode("utf-8")) > MAX_SOURCE_BYTES:
        text = text.encode("utf-8")[:MAX_SOURCE_BYTES].decode("utf-8", errors="replace")
        truncated = True
    return text, truncated


def write_source_index() -> None:
    if SOURCE_DIR.exists():
        shutil.rmtree(SOURCE_DIR)
    files_dir = SOURCE_DIR / "files"
    files_dir.mkdir(parents=True, exist_ok=True)

    candidates: dict[str, Path] = {}
    for pattern in SOURCE_GLOBS:
        for path in ROOT.glob(pattern):
            if not path.is_file():
                continue
            rel = path.relative_to(ROOT).as_posix()
            parts = set(rel.split("/"))
            if parts & SOURCE_EXCLUDE_PARTS:
                continue
            if path.suffix in {".pyc", ".png", ".parquet", ".csv", ".log", ".db"}:
                continue
            candidates[rel] = path

    manifest_files: list[dict] = []
    for rel, path in sorted(candidates.items()):
        try:
            content, truncated = _read_source_file(path)
        except Exception as e:
            print(f"  [warn] source skipped {rel}: {e}")
            continue
        digest = hashlib.sha1(rel.encode("utf-8")).hexdigest()[:16]
        data_file = f"files/{digest}.json"
        payload = {
            "path": rel,
            "language": LANG_BY_SUFFIX.get(path.suffix, "text"),
            "kind": _source_kind(rel),
            "lines": len(content.splitlines()),
            "bytes": len(content.encode("utf-8")),
            "truncated": truncated,
            "content": content,
        }
        (files_dir / f"{digest}.json").write_text(
            json.dumps(payload, ensure_ascii=False),
            encoding="utf-8",
        )
        manifest_files.append(
            {
                "path": rel,
                "slug": _source_slug(rel),
                "data_file": data_file,
                "language": payload["language"],
                "kind": payload["kind"],
                "lines": payload["lines"],
                "bytes": payload["bytes"],
                "truncated": truncated,
            }
        )

    (SOURCE_DIR / "manifest.json").write_text(
        json.dumps(
            {
                "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                "total": len(manifest_files),
                "files": manifest_files,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    print(f"  wrote source/manifest.json ({len(manifest_files)} files)")


def main() -> None:
    print(f"Exporting to {OUT.relative_to(ROOT)}")
    coverage = load_coverage()
    write_meta(coverage)
    write_factors(coverage)
    write_strategy(coverage["generated_at"])
    write_candidates()
    write_live()
    write_journey()
    write_source_index()
    print("done.")


if __name__ == "__main__":
    main()
