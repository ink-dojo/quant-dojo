"""
MD&A LLM drift pilot (v2) — 5 维度 drift + 脱敏 + placebo swap.

目的:
    Tier 1 TF-IDF drift KILL 后, 想试 "让 LLM 直接评 MD&A 跨年信心变化" 这种信号.
    改进自 v1:
        - drift 不 level (对齐 Lazy Prices 原 thesis)
        - 5 维度拆开 (specificity / hedging / tone / forward / transparency)
        - 公司身份脱敏 (防 LLM cutoff 泄漏)
        - placebo swap test (反序喂文本, 分数应反号)

Pilot 过门槛:
    (a) 至少 3/5 维度 std > 0.2 (维度有区分度)
    (b) Placebo swap 正反两次, 每维度平均 |正 + 反| < 0.3 (不对称性小, 即非身份偷跑)
    (c) 中石油 2020→2019 (油价崩) vs 2021→2020 (恢复) 的 tone_drift 或 hedging_drift
        应呈现相反符号
    (d) rationale 的 key_shifts 引用句必须来自脱敏后文本, 不 leak 外部知识
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import pandas as pd

from agents.base import LLMClient
from utils.mda_anonymize import anonymize_mda


TOKENS_DIR = Path("data/processed/mda_tokens")
OUT_DIR = Path("journal")

# 10 对 (symbol, year_curr) — 均已验证 mda_len >= 15000, 且 year-1 也有 tokens
PAIRS = [
    ("601857", 2020, "中国石油", "油价崩, 预期 tone/hedge drift 明显 -"),
    ("601857", 2021, "中国石油", "油价恢复, 预期 + drift"),
    ("601857", 2024, "中国石油", "油价回落, 预期 - drift"),
    ("300450", 2022, "先导智能", "锂电景气顶, 预期 + drift"),
    ("300450", 2023, "先导智能", "顶到下行, 预期 - drift"),
    ("300094", 2022, "国联水产", "疫情爆亏, 预期 - drift"),
    ("002302", 2024, "西部建设", "建材周期"),
    ("600559", 2024, "老白干酒", "白酒消费"),
    ("600378", 2024, "昊华科技", "化工"),
    ("300197", 2024, "节能铁汉", "环保 PPP"),
]

MAX_EXCERPT_CHARS = 10000  # 每年 10000 字, 两年共 20000, Opus prompt 可接受


PROMPT_TEMPLATE = """你是一位只能基于所给文本做判断的研究助手。下面是一家 A 股上市公司**两个连续财年**的 MD&A(管理层讨论与分析)摘要。

⚠️ 严格规则:
1. 公司身份已脱敏(名字替换为"本公司",年份替换为"Year T"/"Year T-1")。你**不得**推测、猜测公司身份。
2. 你**禁止**使用任何你在训练时见过的、关于任何特定公司的后续股价/业绩/新闻/事件信息。
3. **只基于下面两段脱敏文本**做判断,不引入外部知识(包括行业走势、宏观判断、公司历史)。
4. 若你怀疑自己在用外部记忆,在 rationale 里标记 "[外部知识泄漏疑虑]" 并给中性分。

[该公司 {prev_label} MD&A 摘要(前 {max_chars} 字)]
{mda_prev}

[该公司 {curr_label} MD&A 摘要(前 {max_chars} 字)]
{mda_curr}

[任务]
对比上述两段文本,评分 **{curr_label} 相对 {prev_label}** 在以下 5 个**文本特征维度**上的**变化**(drift),每维度 -1.0 到 +1.0:

1. **specificity_drift**: 具体化程度变化
   +1 = 从模糊动词变为大量量化目标(订单金额/产能/市占率)
   -1 = 从具体数字变为全 "推进/优化/加强" 类模糊动词

2. **hedging_drift**: hedging 密度变化(正号 = 好)
   +1 = hedging 词("可能/预计/力争/努力/有望")变**少**
   -1 = hedging 词变**多**

3. **tone_drift**: 措辞自信度变化
   +1 = 从 defensive 变为 assertive
   -1 = 从自信变为回避

4. **forward_drift**: 前瞻性变化
   +1 = 对未来规划论述占比变**大**,且具体
   -1 = 从谈未来转向只讲过去业绩

5. **transparency_drift**: 坦率度变化
   +1 = 从回避核心矛盾变为明确讨论风险 + 应对
   -1 = 从坦率变为遮掩

**拉开分数**: 如果两年文本明显不同,请给出幅度分数(±0.3 到 ±1.0)。全打 0 是被惩罚的。

严格输出 JSON(禁止 markdown 代码块,禁止前后解释):
{{
  "specificity_drift": <float>,
  "hedging_drift": <float>,
  "tone_drift": <float>,
  "forward_drift": <float>,
  "transparency_drift": <float>,
  "key_shifts": [
    {{"dim": "specificity|hedging|tone|forward|transparency",
      "prev_quote": "<{prev_label} 里的原句, 必须来自上面文本>",
      "curr_quote": "<{curr_label} 里的原句, 必须来自上面文本>",
      "shift": "<一句话说清变化方向>"}}
  ],
  "external_leak_suspicion": "<是/否: 我是否怀疑自己用了外部知识>"
}}
"""


def load_mda_text(symbol: str, fiscal_year: int) -> str:
    """从 tokens parquet 还原 MD&A (jieba token 空格 join)."""
    path = TOKENS_DIR / f"{symbol}_{fiscal_year}.parquet"
    df = pd.read_parquet(path)
    return " ".join(df["token"].tolist())


DIMS = ["specificity_drift", "hedging_drift", "tone_drift",
        "forward_drift", "transparency_drift"]


def run_one(client: LLMClient, symbol: str, year_curr: int, swap: bool = False) -> dict:
    """
    跑一次 pilot.
    swap=True: 交换 prev/curr label 位置 (placebo) — 文本位置对调, label 也对调,
               实际上传给 LLM 的是 (真实 curr 标成 "Year T-1", 真实 prev 标成 "Year T")
               如 LLM 只看文本, 分数应该**反号**; 如 LLM 在用身份/年份记忆偷跑, 分数可能一致.
    """
    year_prev = year_curr - 1
    text_curr = load_mda_text(symbol, year_curr)
    text_prev = load_mda_text(symbol, year_prev)

    # 脱敏 — label 对应文档所标的年份 (swap 下要对调 label)
    if not swap:
        anon_curr = anonymize_mda(text_curr[:MAX_EXCERPT_CHARS], symbol, "Year T")
        anon_prev = anonymize_mda(text_prev[:MAX_EXCERPT_CHARS], symbol, "Year T-1")
        prev_label, curr_label = "Year T-1", "Year T"
        mda_prev, mda_curr = anon_prev, anon_curr
    else:
        # swap: 把真实 prev 标成 Year T, 真实 curr 标成 Year T-1 (反过来)
        anon_curr = anonymize_mda(text_curr[:MAX_EXCERPT_CHARS], symbol, "Year T-1")
        anon_prev = anonymize_mda(text_prev[:MAX_EXCERPT_CHARS], symbol, "Year T")
        prev_label, curr_label = "Year T-1", "Year T"
        mda_prev, mda_curr = anon_curr, anon_prev  # 位置对调!

    prompt = PROMPT_TEMPLATE.format(
        prev_label=prev_label, curr_label=curr_label,
        max_chars=MAX_EXCERPT_CHARS,
        mda_prev=mda_prev, mda_curr=mda_curr,
    )

    t0 = time.time()
    try:
        resp = client.complete_json(prompt)
    except Exception as e:
        return {"error": repr(e), "latency_s": round(time.time() - t0, 1)}
    dt = time.time() - t0
    resp["_latency_s"] = round(dt, 1)
    return resp


def main() -> int:
    client = LLMClient()

    # Phase A: 正向 10 份
    print("=" * 70)
    print("Phase A: 正向 drift pilot (10 对, 真实 prev→curr)")
    print("=" * 70)
    forward_results = []
    for sym, yr_curr, name, hyp in PAIRS:
        print(f"\n[A] {sym}_{yr_curr} (vs {yr_curr-1}) {name} — 预期: {hyp}")
        r = run_one(client, sym, yr_curr, swap=False)
        if "error" in r:
            print(f"  ERROR: {r['error']}")
            continue
        scores = {d: r.get(d) for d in DIMS}
        print(f"  scores: " + "  ".join(
            f"{d.split('_')[0]}={scores[d]:+.2f}" if isinstance(scores[d], (int,float)) else f"{d.split('_')[0]}=NA"
            for d in DIMS
        ))
        leak = r.get("external_leak_suspicion", "NA")
        shifts = r.get("key_shifts", [])
        print(f"  external_leak_suspicion: {leak}   ({r['_latency_s']}s)")
        if shifts:
            sh = shifts[0]
            print(f"  sample shift ({sh.get('dim')}): {sh.get('shift', '')}")

        forward_results.append({
            "symbol": sym, "year_curr": yr_curr, "name": name,
            "hypothesis": hyp, "swap": False, **r,
        })

    # Phase B: Placebo swap — 同 10 对, label 位置对调
    print("\n" + "=" * 70)
    print("Phase B: Placebo swap (同 10 对, label 对调 — 分数应反号)")
    print("=" * 70)
    swap_results = []
    for sym, yr_curr, name, _ in PAIRS:
        print(f"\n[B-swap] {sym}_{yr_curr}")
        r = run_one(client, sym, yr_curr, swap=True)
        if "error" in r:
            print(f"  ERROR: {r['error']}")
            continue
        scores = {d: r.get(d) for d in DIMS}
        print(f"  scores: " + "  ".join(
            f"{d.split('_')[0]}={scores[d]:+.2f}" if isinstance(scores[d], (int,float)) else f"{d.split('_')[0]}=NA"
            for d in DIMS
        ))
        swap_results.append({
            "symbol": sym, "year_curr": yr_curr, "name": name,
            "swap": True, **r,
        })

    # === Analysis ===
    print("\n\n" + "=" * 70)
    print("=== Distribution (forward) ===")
    for d in DIMS:
        vals = [r.get(d) for r in forward_results if isinstance(r.get(d), (int, float))]
        if vals:
            s = pd.Series(vals)
            print(f"  {d:24s}  n={len(s)}  mean={s.mean():+.3f}  std={s.std():+.3f}  range=[{s.min():+.2f},{s.max():+.2f}]")

    print("\n=== Placebo symmetry (forward + swap, 应趋近 0) ===")
    # 配对: 同 (symbol, year_curr) 的 forward 和 swap 结果
    swap_map = {(r["symbol"], r["year_curr"]): r for r in swap_results}
    for d in DIMS:
        diffs = []
        for r in forward_results:
            key = (r["symbol"], r["year_curr"])
            if key in swap_map:
                f_s = r.get(d)
                s_s = swap_map[key].get(d)
                if isinstance(f_s, (int, float)) and isinstance(s_s, (int, float)):
                    diffs.append(f_s + s_s)
        if diffs:
            s = pd.Series(diffs)
            print(f"  {d:24s}  n={len(s)}  mean|forward+swap|={s.abs().mean():.3f}  (过门槛: < 0.3)")

    print("\n=== Sanity: 中石油 油价 cycle ===")
    fwd = {(r["symbol"], r["year_curr"]): r for r in forward_results}
    cases = [("601857", 2020, "油价崩"), ("601857", 2021, "恢复"), ("601857", 2024, "回落")]
    for s, y, note in cases:
        if (s, y) in fwd:
            r = fwd[(s, y)]
            print(f"  {s}_{y} ({note}): tone={r.get('tone_drift'):+.2f}  hedge={r.get('hedging_drift'):+.2f}  spec={r.get('specificity_drift'):+.2f}")

    # save
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    out_path = OUT_DIR / "mda_llm_pilot_v2_20260422.json"
    with open(out_path, "w") as f:
        json.dump({"forward": forward_results, "swap": swap_results}, f,
                  ensure_ascii=False, indent=2)
    print(f"\n[saved] {out_path}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
