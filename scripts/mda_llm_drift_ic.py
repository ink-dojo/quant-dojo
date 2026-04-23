"""
MD&A LLM drift mini-IC (2024 fiscal year, 450+ pairs).

目的:
    Pilot v2 过后 (5 维度 std 都够, tone 最稳), 跑 mini-IC 看 2024 cross-section
    是否有信号. Kill/pass 门槛:
        - 任一维度 IC > 0.04 → 有信号, 扩全量跨年
        - 所有维度 |IC| < 0.02 → KILL, 方法论不 work
        - 0.02 ~ 0.04 → 边缘, 人工决定

关键设计:
    - Random-order normalization: 每对随机选 forward/swap 喂 LLM,
      swap 组分数取负 → 消除 LLM 顺序偏置
    - 公司身份脱敏 (防 LLM cutoff 泄漏) — 复用 utils/mda_anonymize
    - ProcessPool 4 worker 并发 claude -p
    - 增量落盘 (每对跑完就写 parquet, 中断可恢复)
"""
from __future__ import annotations

import json
import logging
import random
import subprocess
import sys
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import numpy as np
import pandas as pd
from tqdm import tqdm

from research.factors.mda_drift.factor import DEFAULT_MANIFEST_PATH
from research.factors.mda_drift.outlook_extractor import extract_outlook_section
from utils.local_data_loader import load_adj_price_wide
from utils.factor_analysis import ic_summary
from utils.mda_anonymize import anonymize_mda

TOKENS_DIR = Path("data/processed/mda_tokens")
OUT_SCORES = Path("data/processed/mda_llm_drift_scores_2024.parquet")
OUT_SCORES_OUTLOOK = Path("data/processed/mda_llm_outlook_drift_scores_2024.parquet")
OUT_JOURNAL = Path("journal/mda_llm_drift_mini_ic_20260422.md")
OUT_JOURNAL_OUTLOOK = Path("journal/mda_llm_outlook_drift_mini_ic_20260422.md")

# 全文模式: 前 5000 字; outlook 模式: 整段展望 (median 2700 字, 天然 7k prompt 总长)
MAX_EXCERPT_CHARS = 5000
USE_OUTLOOK = False  # 通过 CLI flag 切换

# 硬锁 Haiku 4.5 — 不能默认继承 session model (否则跑 Opus, 贵 15x).
# 切模型要改这里 + 改 CLI flag. 参考 rules.md [2026-04-22] llm-cost-model.
LLM_MODEL = "haiku"
FWD_DAYS = 20
COST_BPS = 30
DIMS = ["specificity_drift", "hedging_drift", "tone_drift",
        "forward_drift", "transparency_drift"]

# Kill 门槛 (mini-IC, 只 2024 一年 cross-section)
KILL_IC_UPPER = 0.02
SIGNAL_IC_LOWER = 0.04

logger = logging.getLogger(__name__)


PROMPT_TEMPLATE = """你是一位只能基于所给文本做判断的研究助手。下面是一家 A 股上市公司**两个连续财年**的 MD&A 摘要。

⚠️ 严格规则:
1. 公司身份已脱敏(名字替换为"本公司",年份替换为"Year T"/"Year T-1")。你**不得**推测、猜测公司身份。
2. 你**禁止**使用任何你在训练时见过的、关于任何特定公司的后续股价/业绩/新闻/事件信息。
3. **只基于下面两段脱敏文本**做判断,不引入外部知识(包括行业走势、宏观判断、公司历史)。
4. 若你怀疑自己在用外部记忆,在 rationale 里标记 "[外部知识泄漏疑虑]" 并给中性分。

[该公司 Year T-1 MD&A 摘要(前 {max_chars} 字)]
{mda_prev}

[该公司 Year T MD&A 摘要(前 {max_chars} 字)]
{mda_curr}

[任务]
对比上述两段文本,评分 **Year T 相对 Year T-1** 在以下 5 个维度上的**变化**(drift),每维度 -1.0 到 +1.0:

1. specificity_drift: +1=变具体量化, -1=变模糊动词
2. hedging_drift: +1=hedging 词变少, -1=变多
3. tone_drift: +1=变 assertive, -1=变 defensive
4. forward_drift: +1=前瞻论述变多, -1=只讲过去
5. transparency_drift: +1=变坦率讨论风险, -1=变回避

**拉开分数**: 全打 0 视为评分失败。

严格输出 JSON(禁止 markdown 代码块,禁止前后解释):
{{
  "specificity_drift": <float>,
  "hedging_drift": <float>,
  "tone_drift": <float>,
  "forward_drift": <float>,
  "transparency_drift": <float>,
  "external_leak_suspicion": "<是/否>"
}}
"""


def load_mda_text(symbol: str, fiscal_year: int, use_outlook: bool = False) -> str:
    """返回 full MD&A 或 outlook 段."""
    path = TOKENS_DIR / f"{symbol}_{fiscal_year}.parquet"
    df = pd.read_parquet(path)
    full = " ".join(df["token"].tolist())
    if use_outlook:
        section = extract_outlook_section(full)
        return section if section else full[int(len(full)*0.67):]  # fallback
    return full


def _call_claude_json(prompt: str, timeout: int = 180, max_retries: int = 2) -> dict:
    """subprocess claude -p 直接调, 自己 parse JSON.
    returncode=1 重试 (多进程并发下 claude CLI 偶发 spurious fail).
    强制 --model haiku: 不继承 session 的 Opus 避免 15x 成本."""
    json_prompt = prompt + "\n\n请严格返回合法 JSON, 不要任何 markdown 代码块或前后文字."
    for attempt in range(max_retries + 1):
        try:
            result = subprocess.run(
                ["claude", "-p", "--model", LLM_MODEL, json_prompt],
                capture_output=True, text=True, timeout=timeout,
            )
        except subprocess.TimeoutExpired:
            if attempt < max_retries:
                time.sleep(2 * (attempt + 1))
                continue
            return {"_error": "timeout"}
        if result.returncode == 0:
            break
        if attempt < max_retries:
            time.sleep(2 * (attempt + 1))  # backoff 2s, 4s
            continue
    if result.returncode != 0:
        return {"_error": f"returncode={result.returncode}", "_stderr": result.stderr[:200]}
    raw = result.stdout.strip()
    # 提取 JSON
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        pass
    # ```json``` 块
    if "```json" in raw:
        try:
            start = raw.index("```json") + 7
            end = raw.index("```", start)
            return json.loads(raw[start:end].strip())
        except Exception:
            pass
    # 第一个 { 到最后一个 }
    if "{" in raw and "}" in raw:
        try:
            return json.loads(raw[raw.index("{"):raw.rindex("}") + 1])
        except Exception:
            pass
    return {"_error": "parse_failed", "_raw": raw[:200]}


def score_one_pair(args: tuple) -> dict:
    """
    Worker 函数 (可 pickle 传 ProcessPool).

    args = (symbol, year_curr, order, use_outlook)  # order ∈ {'fwd', 'swap'}
    """
    symbol, year_curr, order, use_outlook = args
    year_prev = year_curr - 1
    t0 = time.time()
    try:
        text_curr = load_mda_text(symbol, year_curr, use_outlook)[:MAX_EXCERPT_CHARS]
        text_prev = load_mda_text(symbol, year_prev, use_outlook)[:MAX_EXCERPT_CHARS]
    except Exception as e:
        return {"symbol": symbol, "year_curr": year_curr, "order": order,
                "_error": f"load_failed: {e!r}"}

    if order == "fwd":
        mda_prev = anonymize_mda(text_prev, symbol, "Year T-1")
        mda_curr = anonymize_mda(text_curr, symbol, "Year T")
    else:  # swap: 位置对调, 真 curr → "Year T-1" slot, 真 prev → "Year T" slot
        mda_prev = anonymize_mda(text_curr, symbol, "Year T-1")
        mda_curr = anonymize_mda(text_prev, symbol, "Year T")

    prompt = PROMPT_TEMPLATE.format(
        max_chars=MAX_EXCERPT_CHARS, mda_prev=mda_prev, mda_curr=mda_curr,
    )
    resp = _call_claude_json(prompt)
    resp["symbol"] = symbol
    resp["year_curr"] = year_curr
    resp["order"] = order
    resp["latency_s"] = round(time.time() - t0, 1)
    return resp


def pick_pairs(min_mda_len: int = 10000) -> list[tuple[str, int]]:
    """选出 2024 + 2023 两年 tokens 都存在且长度足够的 symbol 对."""
    lens = {}
    for p in TOKENS_DIR.glob("*.parquet"):
        df = pd.read_parquet(p)
        sym, yr = p.stem.split("_")
        lens[(sym, int(yr))] = df.attrs.get("mda_text_len", -1)
    pairs = [
        (sym, 2024) for (sym, yr) in lens
        if yr == 2024 and (sym, 2023) in lens
        and lens[(sym, 2024)] >= min_mda_len and lens[(sym, 2023)] >= min_mda_len
    ]
    return sorted(pairs)


def phase1_score(max_workers: int = 4, limit: int | None = None) -> pd.DataFrame:
    """跑 LLM 评分, 每对 random fwd/swap."""
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    pairs = pick_pairs()
    if limit:
        pairs = pairs[:limit]
    print(f"[phase1] {len(pairs)} pairs to score (max_workers={max_workers})")

    rng = random.Random(42)
    tasks = [(sym, yr, rng.choice(["fwd", "swap"]), USE_OUTLOOK) for sym, yr in pairs]

    # 增量恢复: 只跳过**成功**的 (有 tone_drift), failed 的要重跑
    done_ok = set()
    rows: list[dict] = []
    if OUT_SCORES.exists():
        prev = pd.read_parquet(OUT_SCORES)
        if "tone_drift" in prev.columns:
            ok_mask = ~prev["tone_drift"].isna()
            done_ok = set(zip(prev.loc[ok_mask, "symbol"], prev.loc[ok_mask, "year_curr"]))
            rows = prev.loc[ok_mask].to_dict("records")
            failed_n = int((~ok_mask).sum())
            print(f"[phase1] resume: kept {len(done_ok)} success, re-run {failed_n} failed")
        else:
            rows = prev.to_dict("records")
            done_ok = set(zip(prev.symbol, prev.year_curr))
    tasks = [t for t in tasks if (t[0], t[1]) not in done_ok]

    if not tasks:
        print("[phase1] nothing to do")
        return pd.DataFrame(rows)

    ok = 0
    err = 0
    with ProcessPoolExecutor(max_workers=max_workers) as pool:
        futures = {pool.submit(score_one_pair, t): t for t in tasks}
        pbar = tqdm(total=len(futures), desc="scoring")
        for fut in as_completed(futures):
            try:
                r = fut.result()
                if "_error" in r:
                    err += 1
                else:
                    ok += 1
                rows.append(r)
                # 增量落盘 (每 20 对)
                if (ok + err) % 20 == 0:
                    pd.DataFrame(rows).to_parquet(OUT_SCORES)
            except Exception as e:
                logger.warning("worker crash: %r", e)
                err += 1
            pbar.update(1)
        pbar.close()

    df = pd.DataFrame(rows)
    df.to_parquet(OUT_SCORES)
    print(f"[phase1] done. ok={ok}  err={err}  saved={OUT_SCORES}")
    return df


def phase2_ic(scores_df: pd.DataFrame, manifest: pd.DataFrame, prices: pd.DataFrame) -> dict:
    """
    Phase 2: 把 swap 组分数取反, 接 forward return, 算每维度 IC.

    返回 dict: 每维度的 ic_mean / ic_std / nw_t / pct>0 + 整体 decile spread + order-group diag
    """
    # normalize drift direction
    df = scores_df.copy()
    df = df[~df[DIMS[0]].isna()] if DIMS[0] in df.columns else df  # drop parse-failed
    for d in DIMS:
        if d not in df.columns:
            continue
        df[d] = df[d].astype(float)
        # swap 组分数取反
        df.loc[df["order"] == "swap", d] = -df.loc[df["order"] == "swap", d]
    df["publish_date"] = df.apply(
        lambda r: manifest[(manifest.symbol == r.symbol) &
                           (manifest.fiscal_year == r.year_curr)]["publish_date"].iloc[0]
        if len(manifest[(manifest.symbol == r.symbol) & (manifest.fiscal_year == r.year_curr)]) else None,
        axis=1,
    )
    df["publish_date"] = pd.to_datetime(df["publish_date"])
    df = df[~df["publish_date"].isna()]

    # 挂 forward return (20 日累乘)
    def fwd_return(row):
        sym = row["symbol"]
        pub = row["publish_date"]
        if sym not in prices.columns:
            return None
        sr = prices[sym].dropna()
        idx = sr.index.searchsorted(pub, side="right")
        if idx + FWD_DAYS >= len(sr):
            return None
        start_px = sr.iloc[idx]
        end_px = sr.iloc[idx + FWD_DAYS]
        if start_px <= 0 or pd.isna(start_px) or pd.isna(end_px):
            return None
        return float(end_px / start_px - 1 - COST_BPS / 10000)

    df["fwd_ret_20d"] = df.apply(fwd_return, axis=1)
    df = df[~df["fwd_ret_20d"].isna()]
    print(f"[phase2] panel n={len(df)}  unique months={df.publish_date.dt.to_period('M').nunique()}")

    # 每维度 IC (monthly Spearman)
    result = {"n_pairs": len(df), "per_dim": {}}
    for d in DIMS:
        if d not in df.columns:
            continue
        monthly = []
        for month, grp in df.groupby(df.publish_date.dt.to_period("M")):
            if len(grp) < 10:
                continue
            ic = grp[d].rank().corr(grp["fwd_ret_20d"].rank())
            if pd.notna(ic):
                monthly.append({"month": str(month), "ic": ic, "n": len(grp)})
        ic_s = pd.Series([m["ic"] for m in monthly])
        result["per_dim"][d] = {
            "n_months": len(ic_s),
            "ic_mean": float(ic_s.mean()) if len(ic_s) else None,
            "ic_std": float(ic_s.std()) if len(ic_s) > 1 else None,
            "icir": float(ic_s.mean() / ic_s.std()) if len(ic_s) > 1 and ic_s.std() > 0 else None,
            "pct_gt_0": float((ic_s > 0).mean()) if len(ic_s) else None,
        }

    # Pooled cross-section IC (ignore time grouping — 2024 发布多在 4 月, 月数少)
    result["per_dim_pooled"] = {}
    for d in DIMS:
        if d not in df.columns:
            continue
        ic = df[d].rank().corr(df["fwd_ret_20d"].rank())
        result["per_dim_pooled"][d] = {"pooled_ic": float(ic) if pd.notna(ic) else None}

    # Decile spread by each dim
    result["decile_spread"] = {}
    for d in DIMS:
        if d not in df.columns:
            continue
        df_sorted = df.sort_values(d)
        n = len(df_sorted)
        top = df_sorted.iloc[int(n*0.9):]["fwd_ret_20d"].mean()
        bot = df_sorted.iloc[:int(n*0.1)]["fwd_ret_20d"].mean()
        result["decile_spread"][d] = {"top10": float(top), "bot10": float(bot),
                                        "spread": float(top - bot)}

    # Order group diagnostic
    result["order_group_diag"] = {}
    for d in DIMS:
        if d not in df.columns:
            continue
        fwd_df = df[df.order == "fwd"]
        swap_df = df[df.order == "swap"]
        ic_fwd = fwd_df[d].rank().corr(fwd_df["fwd_ret_20d"].rank()) if len(fwd_df) > 10 else None
        ic_swap = swap_df[d].rank().corr(swap_df["fwd_ret_20d"].rank()) if len(swap_df) > 10 else None
        result["order_group_diag"][d] = {
            "n_fwd": len(fwd_df), "n_swap": len(swap_df),
            "ic_fwd": float(ic_fwd) if pd.notna(ic_fwd) else None,
            "ic_swap": float(ic_swap) if pd.notna(ic_swap) else None,
        }

    return result


def _fmt_num(x, fmt=".4f", na="NA") -> str:
    return f"{x:{fmt}}" if isinstance(x, (int, float)) else na


def write_report(result: dict, scores_df: pd.DataFrame) -> None:
    lines = [
        "# MD&A LLM drift mini-IC — 2024 cross-section (2026-04-22)",
        "",
        "战略锚: `research/space_c_llm_alpha/alpha_theory_space_c_research_20260421.md`",
        "Pre-reg: `scripts/mda_llm_drift_ic.py` (Tier 1b KILL 后的 Tier 2/3 方法论试验)",
        "",
        "## 样本 & 方法",
        "",
        f"- 样本 n = {result['n_pairs']} 对 (t=2024, t-1=2023, 两年 mda_len >= 10k)",
        f"- LLM: claude -p (Opus 4.7),  prompt: 5 维度 drift + 脱敏 + 禁止训练知识",
        f"- Random-order normalization: 每对随机 fwd/swap, swap 组分数取反",
        f"- forward return: 20 交易日累乘扣 30 bp",
        f"- publish_date → as-of 交易日映射: as_of = publish_date 后第 1 个交易日",
        "",
        "## 每维度 IC (monthly Spearman, 2024 年发布)",
        "",
        "| 维度 | n_months | IC mean | IC std | ICIR | IC>0 % |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for d in DIMS:
        s = result["per_dim"].get(d, {})
        pct = s.get("pct_gt_0")
        pct_str = f"{pct:.1%}" if isinstance(pct, (int, float)) else "NA"
        lines.append(
            f"| {d.replace('_drift','')} | {s.get('n_months') or 0} | "
            f"{_fmt_num(s.get('ic_mean'))} | {_fmt_num(s.get('ic_std'))} | "
            f"{_fmt_num(s.get('icir'), '.3f')} | {pct_str} |"
        )
    lines += [
        "",
        "## Pooled cross-section IC",
        "",
        "| 维度 | pooled IC |",
        "|---|---:|",
    ]
    for d in DIMS:
        s = result["per_dim_pooled"].get(d, {})
        lines.append(f"| {d.replace('_drift','')} | {_fmt_num(s.get('pooled_ic'))} |")
    lines += [
        "",
        "## Decile spread (top 10% - bot 10% by drift, forward return 差)",
        "",
        "| 维度 | top 10% | bot 10% | spread |",
        "|---|---:|---:|---:|",
    ]
    for d in DIMS:
        s = result["decile_spread"].get(d, {})
        lines.append(
            f"| {d.replace('_drift','')} | {_fmt_num(s.get('top10'))} | "
            f"{_fmt_num(s.get('bot10'))} | **{_fmt_num(s.get('spread'))}** |"
        )
    lines += [
        "",
        "## Order group diagnostic (检测 random-order normalization 效果)",
        "",
        "> 两组 IC 接近 → order bias 被平均掉, signal 真实; 差异大 → bias 主导",
        "",
        "| 维度 | n_fwd | n_swap | IC_fwd | IC_swap | 差 |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for d in DIMS:
        s = result["order_group_diag"].get(d, {})
        lines.append(
            f"| {d.replace('_drift','')} | {s.get('n_fwd') or 0} | {s.get('n_swap') or 0} | "
            f"{_fmt_num(s.get('ic_fwd'))} | {_fmt_num(s.get('ic_swap'))} | "
            f"{abs((s.get('ic_fwd') or 0) - (s.get('ic_swap') or 0)):.4f} |"
        )

    # 决策
    max_abs_ic = max(
        abs(result["per_dim_pooled"].get(d, {}).get("pooled_ic") or 0) for d in DIMS
    )
    if max_abs_ic >= SIGNAL_IC_LOWER:
        decision = f"🟢 **有信号** (max |pooled IC| = {max_abs_ic:.4f} >= {SIGNAL_IC_LOWER}). 扩全量跨年 Step 2."
    elif max_abs_ic < KILL_IC_UPPER:
        decision = f"🔴 **KILL** (max |pooled IC| = {max_abs_ic:.4f} < {KILL_IC_UPPER}). MD&A LLM 信心度方法在 A 股不 work."
    else:
        decision = f"🟡 **边缘** (max |pooled IC| = {max_abs_ic:.4f} 在 [{KILL_IC_UPPER}, {SIGNAL_IC_LOWER}]). 由 jialong 决定是否扩全量."

    lines += ["", "## 决策", "", decision, ""]

    OUT_JOURNAL.parent.mkdir(parents=True, exist_ok=True)
    OUT_JOURNAL.write_text("\n".join(lines), encoding="utf-8")
    print(f"[saved] {OUT_JOURNAL}")


def main() -> int:
    import argparse
    global USE_OUTLOOK, OUT_SCORES, OUT_JOURNAL
    p = argparse.ArgumentParser()
    p.add_argument("--workers", type=int, default=4)
    p.add_argument("--limit", type=int, default=None, help="只跑前 N 对 (调试)")
    p.add_argument("--skip-score", action="store_true", help="跳过 phase1, 只用已缓存 scores")
    p.add_argument("--use-outlook", action="store_true",
                   help="只用 MD&A 的'未来发展展望'段 (median 2700 字 vs 全文 24k), 信噪比更高")
    args = p.parse_args()

    if args.use_outlook:
        USE_OUTLOOK = True
        OUT_SCORES = OUT_SCORES_OUTLOOK
        OUT_JOURNAL = OUT_JOURNAL_OUTLOOK
        print(f"[mode] use outlook section. output → {OUT_SCORES}")

    if not args.skip_score:
        scores_df = phase1_score(max_workers=args.workers, limit=args.limit)
    else:
        scores_df = pd.read_parquet(OUT_SCORES)
        print(f"[phase1] skipped, loaded {len(scores_df)} scores from cache")

    # drop parse-failed
    good = scores_df[~scores_df[DIMS[0]].isna() if DIMS[0] in scores_df.columns else scores_df.index]
    print(f"[phase2] {len(good)} valid scored pairs")

    manifest = pd.read_parquet(DEFAULT_MANIFEST_PATH)
    manifest["publish_date"] = pd.to_datetime(manifest["publish_date"])
    symbols = list(good["symbol"].unique())
    start = "2024-01-01"
    end = "2026-04-21"
    prices = load_adj_price_wide(symbols=symbols, start=start, end=end)
    print(f"[phase2] prices shape={prices.shape}")

    result = phase2_ic(good, manifest, prices)

    # console summary
    def _fmt(x, fmt="+.4f"):
        return f"{x:{fmt}}" if isinstance(x, (int, float)) else "NA"
    print("\n=== Per-dim monthly IC ===")
    for d in DIMS:
        s = result["per_dim"].get(d, {})
        print(f"  {d:24s}  n_m={s.get('n_months') or 0:>2}  ic={_fmt(s.get('ic_mean'))}  icir={_fmt(s.get('icir'), '+.3f')}")
    print("\n=== Pooled IC ===")
    for d in DIMS:
        s = result["per_dim_pooled"].get(d, {})
        print(f"  {d:24s}  pooled_ic={_fmt(s.get('pooled_ic'))}")

    write_report(result, good)
    return 0


if __name__ == "__main__":
    sys.exit(main())
