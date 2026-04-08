"""
quant_dojo diff — 实盘 vs 回测差异分析

把 `pipeline/live_vs_backtest.compute_divergence` 包成一级 CLI 命令。

用法:
  python -m quant_dojo diff                                 # 用最新 v7 回测 run
  python -m quant_dojo diff v7_20260407_41b618e5            # 指定 run id
  python -m quant_dojo diff --run /path/to/run.json         # 指定完整 run 路径
  python -m quant_dojo diff --start 2026-03-20              # 限定起始日
  python -m quant_dojo diff --save journal/diff.md          # 保存 markdown 报告
  python -m quant_dojo diff --json                          # 打印摘要的 JSON 形式
"""
import json
import sys
from pathlib import Path
from typing import Optional

PROJECT_ROOT = Path(__file__).parent.parent.parent
LIVE_RUNS_DIR = PROJECT_ROOT / "live" / "runs"
LIVE_NAV_DEFAULT = PROJECT_ROOT / "live" / "portfolio" / "nav.csv"


def _resolve_run_path(run: Optional[str], strategy_hint: Optional[str]) -> Optional[Path]:
    """
    根据用户提供的 run id / 路径 / 空值，解析出一个回测 run JSON 路径。

    规则：
      - 如果 run 是存在的路径，直接用
      - 如果 run 看起来像 run_id（不是路径），在 live/runs 下找 `<run_id>.json`
      - 如果 run 为空：用 LIVE_RUNS_DIR 下按修改时间最新的 run（可选 strategy 前缀过滤）
    """
    if run:
        p = Path(run)
        if p.exists():
            return p
        # try as run_id inside live/runs
        candidate = LIVE_RUNS_DIR / f"{run}.json"
        if candidate.exists():
            return candidate
        return None

    # pick the newest run json that actually has an equity_csv artifact
    if not LIVE_RUNS_DIR.exists():
        return None
    candidates = sorted(LIVE_RUNS_DIR.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
    if strategy_hint:
        candidates = [c for c in candidates if c.name.startswith(f"{strategy_hint}_")]
    for c in candidates:
        try:
            with open(c, "r", encoding="utf-8") as f:
                data = json.load(f)
            if data.get("artifacts", {}).get("equity_csv"):
                return c
        except (OSError, json.JSONDecodeError):
            continue
    return None


def run_diff(
    run: Optional[str] = None,
    live_nav: Optional[str] = None,
    strategy: Optional[str] = None,
    start: Optional[str] = None,
    end: Optional[str] = None,
    save: Optional[str] = None,
    as_json: bool = False,
):
    """入口：CLI 层负责参数解析，调用 pipeline.live_vs_backtest 做计算"""
    sys.path.insert(0, str(PROJECT_ROOT))

    from pipeline.live_vs_backtest import compute_divergence, render_markdown_report

    run_path = _resolve_run_path(run, strategy)
    if run_path is None:
        print("  [错误] 找不到可用的回测 run")
        print(f"         尝试了: {run or '(最新 run)'}")
        print(f"         live/runs 目录: {LIVE_RUNS_DIR}")
        sys.exit(1)

    nav_path = Path(live_nav) if live_nav else LIVE_NAV_DEFAULT
    if not nav_path.exists():
        print(f"  [错误] live nav 文件不存在: {nav_path}")
        sys.exit(1)

    div = compute_divergence(
        live_nav_path=nav_path,
        backtest_run_path=run_path,
        start=start,
        end=end,
    )

    if div.get("status") != "ok":
        print("  [错误] 无法计算差异")
        print(f"         状态: {div.get('status')}")
        print(f"         原因: {div.get('reason', '-')}")
        if "live_dates" in div:
            print(f"         live 可用日期: {div['live_dates']}")
        sys.exit(2)

    s = div["summary"]
    meta = div["meta"]

    if as_json:
        print(json.dumps({"summary": s, "meta": meta, "n_overlap": div["n_overlap"]},
                         indent=2, ensure_ascii=False))
    else:
        print("╔═══════════════════════════════════════════════╗")
        print("║  quant-dojo 实盘 vs 回测差异                   ║")
        print("╚═══════════════════════════════════════════════╝")
        print(f"  策略: {meta['strategy_id']}")
        print(f"  run : {meta['backtest_run']}")
        print(f"  live: {Path(meta['live_nav_file']).name}")
        print(f"  窗口: {div['dates'][0]} ~ {div['dates'][-1]} "
              f"({s['n_overlap_days']} 天)")
        print()
        print(f"  live 累计收益   : {s['live_total_return']:+.2%}")
        print(f"  backtest 累计收益: {s['backtest_total_return']:+.2%}")
        print(f"  累计偏差        : {s['total_delta']:+.2%}")
        print(f"  日均偏差        : {s['mean_daily_delta']:+.4%}")
        print(f"  偏差 σ         : {s['std_daily_delta']:.4%}")
        print(f"  最大单日偏差    : {s['max_abs_daily_delta']:+.2%} "
              f"(on {s['max_abs_daily_date']})")

        # 简短诊断线索
        print()
        if abs(s["total_delta"]) < 0.005:
            print("  结论: 偏差 < 0.5%，实盘基本追上回测")
        elif abs(s["mean_daily_delta"]) < 1e-4 and s["std_daily_delta"] > 0.005:
            print("  结论: 日均偏差≈0、σ 较大 → 纯噪声，无系统性漂移")
        else:
            direction = "少赚" if s["total_delta"] < 0 else "多赚"
            print(f"  结论: 有系统性漂移，实盘{direction} {abs(s['total_delta']):.2%}")

    if save:
        save_path = Path(save)
        save_path.parent.mkdir(parents=True, exist_ok=True)
        save_path.write_text(render_markdown_report(div), encoding="utf-8")
        print(f"\n  已保存报告: {save_path}")
