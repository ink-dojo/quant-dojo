"""
Stress Test — Tier 1.3 (Phase 8 风控)

对当前 paper-trade 持仓在 A 股历史极端事件期的 PnL 做定量模拟,
确定是否触发三道硬门槛:
  - 单日 stress loss < 8%
  - 单周 stress loss < 15%
  - 累计 max DD < 25%

触发任一 → fail, 不上线 live 或回到 spec 调整.

V1 只做 model_pnl (fixed portfolio replay): 把当前持仓权重 "时光机"
到历史事件期, 按实际价格路径重放. 对当时未上市 / 停牌的 symbol
用 HS300 收益率兜底 (标记为 missing, 在报告中披露).

signal_pnl (重新生成信号在 stress 期重放) 留接口, V1 不实现
(spec v4 signal 需要 tushare daily_basic 等数据, 跨窗口 replay
成本高, 与当前工作量预算 1 周不匹配).

使用:
    python scripts/stress_test.py                      # 默认读 paper_trade/state.json, AUM 1000 万
    python scripts/stress_test.py --aum 5000000
    python scripts/stress_test.py --positions <json>   # 手动指定持仓
    python scripts/stress_test.py --output journal/

输出:
    journal/stress_test_results_YYYYMMDD.md
    logs/stress_test/stress_report_YYYYMMDD.parquet  (per-event 指标面板)
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
log = logging.getLogger("stress_test")

# ─────────────────────────────────────────────────────────────
# 常量 & 路径
# ─────────────────────────────────────────────────────────────

PRICE_PATH = ROOT / "data" / "processed" / "price_wide_close_2014-01-01_2025-12-31_qfq_5477stocks.parquet"
HS300_PATH = ROOT / "data" / "raw" / "indices" / "sh000300.parquet"
EVENTS_PATH = ROOT / "data" / "processed" / "stress_dates.json"
STATE_PATH = ROOT / "portfolio" / "public" / "data" / "paper_trade" / "state.json"
OUT_DIR = ROOT / "logs" / "stress_test"
JOURNAL_DIR = ROOT / "journal"


# ─────────────────────────────────────────────────────────────
# 数据类
# ─────────────────────────────────────────────────────────────

@dataclass
class StressEvent:
    name: str
    start_date: str
    end_date: str
    benchmark_return: float
    category: str
    description: str


@dataclass
class StressResult:
    """单个 stress event 的重放结果."""
    event: StressEvent
    n_symbols: int
    n_symbols_traded: int
    n_symbols_missing: int
    model_return: float          # 累计收益率 (decimal)
    benchmark_return: float      # 参考值 (从事件 JSON)
    worst_day_date: str
    worst_day_return: float      # 单日最差
    worst_week_return: float     # rolling 5 交易日最差
    max_drawdown: float          # 峰谷最大回撤
    daily_returns: pd.Series = field(repr=False)   # 事件期每日组合收益率
    cum_curve: pd.Series = field(repr=False)       # 累计净值 (起点 1.0)


# ─────────────────────────────────────────────────────────────
# IO 与加载
# ─────────────────────────────────────────────────────────────

def load_events(path: Path = EVENTS_PATH) -> tuple[list[StressEvent], dict]:
    """加载事件日历及硬门槛配置."""
    payload = json.loads(path.read_text(encoding="utf-8"))
    events = [StressEvent(**e) for e in payload["events"]]
    return events, payload.get("hard_gates", {})


def load_positions_from_state(path: Path = STATE_PATH) -> dict[str, float]:
    """
    从 paper-trade state.json 读当前持仓, 返回 symbol → 权重 dict.

    权重按市值归一化到 sum 1.0 (未持仓的现金腿不计入 stress model),
    即假设 stress 当天被 fully invested 的情况.
    """
    if not path.exists():
        raise FileNotFoundError(f"state 文件不存在: {path}")
    state = json.loads(path.read_text(encoding="utf-8"))
    positions = state.get("positions", [])
    if not positions:
        raise ValueError("state.json 里 positions 为空, 无持仓可测")

    # 用 shares * current_price 作市值; 若无 current_price 退化为 cost_price
    weights = {}
    for p in positions:
        px = p.get("current_price") or p.get("cost_price") or 0.0
        mv = float(p.get("shares", 0)) * float(px)
        if mv > 0:
            weights[str(p["symbol"])] = mv

    total = sum(weights.values())
    if total <= 0:
        raise ValueError("持仓总市值 <= 0")
    return {s: w / total for s, w in weights.items()}


def load_price_data() -> tuple[pd.DataFrame, pd.Series]:
    """
    加载价格数据. 返回 (price_wide, hs300_close).

    price_wide: index=date, columns=6-digit symbols (str)
    hs300_close: index=date, values=收盘价
    """
    pw = pd.read_parquet(PRICE_PATH)
    pw.index = pd.to_datetime(pw.index)
    pw.columns = [str(c) for c in pw.columns]

    hs = pd.read_parquet(HS300_PATH)
    hs.index = pd.to_datetime(hs.index)
    hs_close = hs["close"].sort_index()

    return pw, hs_close


# ─────────────────────────────────────────────────────────────
# 核心重放 (纯函数, 易测)
# ─────────────────────────────────────────────────────────────

def replay_portfolio_in_event(
    weights: dict[str, float],
    event: StressEvent,
    price_wide: pd.DataFrame,
    hs300_close: pd.Series,
    missing_fill: str = "benchmark",   # "benchmark" | "zero"
) -> StressResult:
    """
    把组合权重 "时光机" 到事件期, 算每日组合收益率及累计净值.

    参数
    ----
    weights        : symbol → weight (sum to 1.0), 权重 = 事件那天的 mark-to-market
    event          : StressEvent
    price_wide     : 价格宽表 (date x symbol)
    hs300_close    : HS300 收盘序列, 用于 missing symbol 兜底
    missing_fill   : 当某 symbol 在事件期无价格时, 用 "benchmark" (HS300 收益率)
                     或 "zero" (视为当天不动). benchmark 在崩盘事件里是保守假设.

    返回
    ----
    StressResult. daily_returns 是"如果当时持有此组合的每日组合收益率".
    """
    # 事件期价格子集
    start = pd.Timestamp(event.start_date)
    end = pd.Timestamp(event.end_date)

    # 取事件期 + 事件前 1 个交易日, 用于计算第一天收益率
    event_dates = price_wide.loc[(price_wide.index >= start) & (price_wide.index <= end)].index
    if len(event_dates) == 0:
        raise ValueError(f"[{event.name}] 事件期在价格数据覆盖范围外 ({start} ~ {end})")

    # 算前一交易日作为 t0
    prior_mask = price_wide.index < event_dates[0]
    if not prior_mask.any():
        raise ValueError(f"[{event.name}] 事件起点之前无交易日, 数据覆盖不足")
    t0 = price_wide.index[prior_mask][-1]
    window_dates = [t0] + list(event_dates)
    window = price_wide.reindex(window_dates)

    # HS300 收益率 (对齐到同一 window)
    hs_window = hs300_close.reindex(window_dates).ffill()
    hs_ret = hs_window.pct_change().loc[event_dates]

    # 对每只 symbol: 若全窗口有价 → 用真实收益率; 否则按 missing_fill 兜底
    daily_ret_frame = pd.DataFrame(index=event_dates)
    n_traded = 0
    n_missing = 0

    for sym, w in weights.items():
        if sym in window.columns:
            ser = window[sym]
            # 有价的日子做 pct_change; nan 的日子用 benchmark / zero 填
            ret = ser.pct_change().loc[event_dates]
            valid = ret.notna()
            if valid.any():
                n_traded += 1
                if not valid.all():
                    # 部分日 NaN → 填
                    if missing_fill == "benchmark":
                        ret = ret.where(valid, hs_ret)
                    else:
                        ret = ret.where(valid, 0.0)
            else:
                n_missing += 1
                ret = hs_ret.copy() if missing_fill == "benchmark" else pd.Series(
                    0.0, index=event_dates
                )
        else:
            n_missing += 1
            ret = hs_ret.copy() if missing_fill == "benchmark" else pd.Series(
                0.0, index=event_dates
            )

        daily_ret_frame[sym] = ret * w

    # 加权求和得组合日收益率
    port_daily = daily_ret_frame.sum(axis=1)
    # 累计净值 (起点 1.0)
    cum = (1 + port_daily).cumprod()
    model_return = float(cum.iloc[-1] - 1.0)

    # 最差单日
    worst_day_idx = port_daily.idxmin()
    worst_day_ret = float(port_daily.min())
    # 最差 rolling 5 日 (含当日)
    week_window = min(5, len(port_daily))
    if week_window >= 2:
        worst_week_ret = float(
            ((1 + port_daily).rolling(week_window).apply(np.prod, raw=True) - 1).min()
        )
    else:
        worst_week_ret = worst_day_ret
    # 从峰到谷 max DD
    running_peak = cum.cummax()
    dd_curve = cum / running_peak - 1
    max_dd = float(dd_curve.min())

    return StressResult(
        event=event,
        n_symbols=len(weights),
        n_symbols_traded=n_traded,
        n_symbols_missing=n_missing,
        model_return=model_return,
        benchmark_return=event.benchmark_return,
        worst_day_date=worst_day_idx.strftime("%Y-%m-%d"),
        worst_day_return=worst_day_ret,
        worst_week_return=worst_week_ret,
        max_drawdown=max_dd,
        daily_returns=port_daily,
        cum_curve=cum,
    )


# ─────────────────────────────────────────────────────────────
# 硬门槛判定
# ─────────────────────────────────────────────────────────────

def check_hard_gates(results: list[StressResult], gates: dict) -> tuple[bool, list[str]]:
    """
    检查所有事件是否都通过硬门槛.
    返回 (all_pass, failure_messages).
    """
    failures = []
    d_limit = gates.get("single_day_loss_pct", 0.08)
    w_limit = gates.get("single_week_loss_pct", 0.15)
    dd_limit = gates.get("cumulative_max_dd_pct", 0.25)

    for r in results:
        if r.event.category == "rally":
            # rally 事件单独判: 若当前组合 **正相关**市场, 大涨期应该也涨,
            # 这里只看是否"被大涨反向烫到" (做空腿). 判 worst_day_return 别比 -d_limit 还低.
            if r.worst_day_return < -d_limit:
                failures.append(
                    f"[{r.event.name}] rally 事件里最差单日 {r.worst_day_return:+.2%} < -{d_limit:.0%}"
                )
            continue

        if r.worst_day_return < -d_limit:
            failures.append(
                f"[{r.event.name}] 单日 {r.worst_day_return:+.2%} < -{d_limit:.0%} "
                f"({r.worst_day_date})"
            )
        if r.worst_week_return < -w_limit:
            failures.append(
                f"[{r.event.name}] 单周 {r.worst_week_return:+.2%} < -{w_limit:.0%}"
            )
        if r.max_drawdown < -dd_limit:
            failures.append(
                f"[{r.event.name}] max DD {r.max_drawdown:+.2%} < -{dd_limit:.0%}"
            )

    return len(failures) == 0, failures


# ─────────────────────────────────────────────────────────────
# 报告输出
# ─────────────────────────────────────────────────────────────

def summarize_results(results: list[StressResult]) -> pd.DataFrame:
    """聚合 per-event 结果成 DataFrame, 便于写 parquet + 写 markdown 表."""
    rows = []
    for r in results:
        rows.append({
            "event": r.event.name,
            "start": r.event.start_date,
            "end": r.event.end_date,
            "category": r.event.category,
            "n_symbols": r.n_symbols,
            "n_traded": r.n_symbols_traded,
            "n_missing": r.n_symbols_missing,
            "model_return": r.model_return,
            "benchmark_return": r.benchmark_return,
            "relative": r.model_return - r.benchmark_return,
            "worst_day_date": r.worst_day_date,
            "worst_day_return": r.worst_day_return,
            "worst_week_return": r.worst_week_return,
            "max_drawdown": r.max_drawdown,
        })
    return pd.DataFrame(rows)


def write_journal(
    summary: pd.DataFrame,
    gate_pass: bool,
    failures: list[str],
    weights: dict[str, float],
    aum: float,
    out_path: Path,
) -> None:
    """写 journal markdown 报告."""
    today = date.today().isoformat()
    n_events = len(summary)
    verdict = "✅ PASS" if gate_pass else "🔴 FAIL"

    lines = [
        f"# Stress Test Results — {today}",
        "",
        f"> 当前持仓对 A 股历史极端事件的模拟回放. {n_events} 事件, 最终判定 **{verdict}**.",
        "",
        "## 输入",
        "",
        f"- **AUM (notional)**: ¥{aum:,.0f}",
        f"- **持仓数**: {len(weights)} 只",
        f"- **权重来源**: `portfolio/public/data/paper_trade/state.json`",
        f"- **事件清单**: `data/processed/stress_dates.json` ({n_events} 事件)",
        f"- **价格数据**: `{PRICE_PATH.name}`",
        f"- **Missing fill policy**: HS300 收益率替代 (保守, 崩盘期相当于承受 benchmark)",
        "",
        "## Per-event 结果",
        "",
        "| 事件 | 类型 | n持/n缺 | Model | Bench | Δ | 最差日 | 最差周 | MaxDD |",
        "|---|---|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for _, r in summary.iterrows():
        lines.append(
            f"| {r['event']} | {r['category']} "
            f"| {r['n_traded']}/{r['n_missing']} "
            f"| {r['model_return']:+.2%} "
            f"| {r['benchmark_return']:+.2%} "
            f"| {r['relative']:+.2%} "
            f"| {r['worst_day_return']:+.2%} ({r['worst_day_date']}) "
            f"| {r['worst_week_return']:+.2%} "
            f"| {r['max_drawdown']:+.2%} |"
        )

    lines += [
        "",
        "## 硬门槛判定",
        "",
        f"- 单日 loss 上限: 8%",
        f"- 单周 loss 上限: 15%",
        f"- 累计 max DD 上限: 25%",
        "",
        f"**结果**: {verdict}",
        "",
    ]
    if failures:
        lines.append("**失败项**:")
        lines.append("")
        for f in failures:
            lines.append(f"- {f}")
        lines += [
            "",
            "**后续动作**:",
            "- 不上线 live, 或退回 spec v3 重新评估",
            "- 检查失败事件的持仓是否 size / sector 过度集中",
            "- 考虑加 position cap / sector cap / vol targeting 降 exposure",
        ]
    else:
        lines += [
            "✅ 所有事件通过硬门槛. 可以继续 live Phase 1.",
            "",
            "**说明**: 通过不代表未来 stress 会通过. 仅表示当前组合对**已知历史形态**的 stress 有承受力.",
        ]

    lines += [
        "",
        "## 局限与假设",
        "",
        "1. **Missing symbol 处理**: 2015 事件里当前持仓大多 **尚未上市**, 用 HS300 兜底. "
        "这是保守估计: 崩盘期间 HS300 比个股抗跌 (大盘蓝筹主导), 实盘可能更差.",
        "2. **Fixed portfolio replay**: 只测 mark-to-market, 没有 stop-loss / vol targeting "
        "在 stress 中降 exposure. 代表 `完全不操作` 的情景.",
        "3. **无 slippage / 成本**: stress 期流动性崩盘单向成交, 实盘 exit 成本可能再吃 2-5%.",
        "4. **信号重放 (signal_pnl) 未实现**: 当前只跑 model_pnl. signal 重放需要事件期完整 "
        "factor panel, 跨 2015-2024 成本高, V1 跳过.",
        "",
        "## 持仓明细 (权重)",
        "",
        "| symbol | weight |",
        "|---|---:|",
    ]
    for sym, w in sorted(weights.items(), key=lambda x: -x[1]):
        lines.append(f"| {sym} | {w:.2%} |")

    lines += [
        "",
        "## 重现命令",
        "",
        "```bash",
        f"python scripts/stress_test.py --aum {int(aum)} --output journal/",
        "```",
        "",
        "---",
        "",
        "_auto-generated by `scripts/stress_test.py`_",
    ]

    out_path.write_text("\n".join(lines), encoding="utf-8")
    log.info(f"journal 报告已写: {out_path}")


# ─────────────────────────────────────────────────────────────
# CLI
# ─────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Phase 8 Tier 1.3 Stress Test")
    parser.add_argument("--aum", type=float, default=10_000_000,
                        help="AUM notional (CNY), 默认 1000 万")
    parser.add_argument("--positions", type=str, default=None,
                        help="(可选) 手动指定持仓 JSON 文件, 覆盖 paper-trade state.json")
    parser.add_argument("--output", type=str, default=str(JOURNAL_DIR),
                        help="journal 输出目录")
    parser.add_argument("--no-journal", action="store_true",
                        help="只跑不写 journal (用于开发时快速验证)")
    args = parser.parse_args()

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    Path(args.output).mkdir(parents=True, exist_ok=True)

    # 1. 持仓
    if args.positions:
        weights = json.loads(Path(args.positions).read_text())
        total = sum(weights.values())
        weights = {s: w / total for s, w in weights.items()}
        log.info(f"持仓来源: {args.positions}, {len(weights)} 只")
    else:
        weights = load_positions_from_state()
        log.info(f"持仓来源: paper_trade state.json, {len(weights)} 只")

    # 2. 数据
    events, gates = load_events()
    price_wide, hs300 = load_price_data()
    log.info(f"事件数: {len(events)}, 价格数据 {price_wide.shape}")

    # 3. 重放
    results = []
    for ev in events:
        try:
            r = replay_portfolio_in_event(weights, ev, price_wide, hs300)
            results.append(r)
            log.info(
                f"[{ev.name}] model={r.model_return:+.2%} bench={r.benchmark_return:+.2%} "
                f"worst_day={r.worst_day_return:+.2%} worst_week={r.worst_week_return:+.2%} "
                f"maxDD={r.max_drawdown:+.2%} ({r.n_symbols_traded}/{r.n_symbols_missing})"
            )
        except ValueError as e:
            log.warning(f"[{ev.name}] 跳过: {e}")

    # 4. 汇总 + 硬门槛
    summary = summarize_results(results)
    gate_pass, failures = check_hard_gates(results, gates)

    # 5. 落地
    today = date.today().strftime("%Y%m%d")
    parquet_path = OUT_DIR / f"stress_report_{today}.parquet"
    summary.to_parquet(parquet_path)
    log.info(f"per-event 面板已写: {parquet_path}")

    if not args.no_journal:
        journal_path = Path(args.output) / f"stress_test_results_{today}.md"
        write_journal(summary, gate_pass, failures, weights, args.aum, journal_path)

    # 6. 终端摘要
    print()
    print("=" * 70)
    print(f"Stress Test Summary — {len(results)} events")
    print("=" * 70)
    print(summary.to_string(index=False))
    print()
    print(f"Gate 判定: {'✅ PASS' if gate_pass else '🔴 FAIL'}")
    for f in failures:
        print(f"  - {f}")
    print()
    return 0 if gate_pass else 1


# ─────────────────────────────────────────────────────────────
# 最小验证
# ─────────────────────────────────────────────────────────────

if __name__ == "__main__":
    sys.exit(main())
