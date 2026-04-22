"""MD&A drift factor — Tier 1 evaluation runner.

### Pre-registration (2026-04-21, 锁参数, 跑完不调)

**战略锚**: `research/space_c_llm_alpha/alpha_theory_space_c_research_20260421.md`
**ALPHA_THEORY 引用**: §2.C (空间 C LLM-native alpha), §4.4 重写版
**Issue**: #25

**§1 四问回答**:
1. edge 还在吗: 存在. Cohen/Malloy/Nguyen (2020 JoF) 美股 5 年有效;
   A 股注册制后 2023+ 披露质量升级, 可能补活而非补死.
   死亡假设: A 股年报 boilerplate 过高 → 文本变化信号噪声比高.
2. 谁做不了: 国内私募有 BERT/字典 NLP 但 "跨年文本相似度" 特定 structural
   signal 铺开度低. 工具优势窗口 12-24 月. (注意: Tier 1 是 baseline,
   不声称结构 edge; 真 edge 留给 Tier 3 跨文档 reasoning)
3. 空间归属: §2.C, embedding 基线.
4. 数据/工具优势: 数据无 (年报公开), 工具无. 本 Tier 显式只作 baseline.

**锁定参数 (DriftConfig + 评估 setup)**:

| 项 | 值 | 理由 |
|---|---|---|
| ngram_range | (1, 2) | Lazy Prices 原文 setup |
| min_df / max_df | 1 / 1.0 | per-symbol corpus 小, 不做 df 过滤 |
| sublinear_tf | True | 抑制长文档 dominate |
| norm | l2 | cosine 前提 |
| corpus scope | per-symbol-all-years | 跨公司 IDF 不可比 |
| 评估区间 | fiscal 2018-2025 | 全 A 股, 覆盖至少 7 次相邻年 drift |
| universe | 非 ST, 非上市不足 1 年, 非停牌 (评估日) | 标准 tradability filter |
| factor as_of | fiscal_year+1 publish_date + 1 交易日 (避免未来函数) | 标准 lag(1) |
| forward return | 20 交易日 cumulative (月频的代理), 扣 0.3% 双边成本 | 和本项目其他因子一致 |
| IC 方法 | Spearman rank IC, 月频重采样 | 标准 |
| decile split | 10 分位 (非空 drift) | Cohen et al. decile |

**Admission / Kill criteria (单向决策, 不加工)**:

- 月度 rank IC < 0.015 → **STOP**. A 股 MD&A 漂移 anomaly 不活. 整个 Tier 1/2
  方向封死, 空间 C 转 Tier 3 (跨文档 reasoning)
- 月度 rank IC 0.015 ~ 0.025 → 进 Tier 2 (LLM hedging 密度做增量)
- 月度 rank IC > 0.025 → Tier 2/3 暂缓, 先把 Tier 1 推到 paper-trade

**附加必答 (不 kill 但要标注)**:

- 前 5 年 (2018-2022) vs 后 3 年 (2023-2025) IC 衰减 >= 50% → 注册制后 regime shift
- top 20 drift 公司行业集中 (HHI > 0.3 或单行业占比 > 30%) → 行业中性化版本重测

**运行模式**:

- `--smoke`   : 5 家公司 × 3 年, 验证 pipeline 端到端 (不做 IC)
- `--subset`  : 500 家随机抽样, 快速看 IC
- `--full`    : 全 A 股 ~5000 × 8 年 (预计 1-2 天下载 + 4-8h 处理)

结果产出:
- `data/processed/mda_drift_scores.parquet` — 因子宽表
- `journal/mda_drift_tier1_result_<YYYYMMDD>.md` — IC 报告 + kill 判读
"""
from __future__ import annotations

import argparse
import logging
import sys
import warnings
from datetime import date
from pathlib import Path

warnings.filterwarnings("ignore")
sys.path.insert(0, str(Path(__file__).parent.parent))

import pandas as pd

from research.factors.mda_drift.factor import (
    DEFAULT_DRIFT_PATH,
    compute_mda_drift_factor,
)
from research.factors.mda_drift.similarity import DriftConfig

logger = logging.getLogger(__name__)

# 锁定参数 — 改动需要新的 pre-reg commit
LOCKED_CONFIG = DriftConfig(
    ngram_min=1,
    ngram_max=2,
    min_df=1,
    max_df=1.0,
    sublinear_tf=True,
    norm="l2",
)

LOCKED_EVAL_START_YEAR = 2018
LOCKED_EVAL_END_YEAR = 2025

# Kill thresholds (锁定, 跑完不改)
KILL_IC_LOWER = 0.015   # < 此值 → stop
TIER2_IC_UPPER = 0.025  # > 此值 → Tier 1 进 paper-trade, 不做 Tier 2


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="MD&A drift factor Tier 1 evaluation")
    mode = p.add_mutually_exclusive_group(required=True)
    mode.add_argument("--smoke", action="store_true", help="5 家公司 × 3 年 smoke test")
    mode.add_argument("--subset", action="store_true", help="500 家随机抽样 IC 评估")
    mode.add_argument("--full", action="store_true", help="全 A 股 × 2018-2025 IC 评估")
    p.add_argument("--no-download", action="store_true", help="不下载 PDF, 只读现有缓存")
    p.add_argument("--out-path", default=str(DEFAULT_DRIFT_PATH), help="factor 宽表输出 parquet 路径")
    p.add_argument(
        "--delete-pdf-after-tokens", action="store_true",
        help="抽完 tokens 立即删 PDF (磁盘节流, full 跑推荐开)"
    )
    p.add_argument(
        "--workers", type=int, default=4,
        help="并发 worker 数, 默认 4. 全局 rate-limit lock 保证不击穿 cninfo."
    )
    return p.parse_args()


def resolve_universe(mode: str) -> list[str]:
    """根据模式选股票子集.

    smoke: 5 家知名大盘蓝筹 (数据最 clean)
    subset: 500 家随机抽样 (seed=42), 从 2018-01-01 已上市且非 ST 的集合中抽
    full: 2018-01-01 已上市且非 ST 的全 A 股

    universe 原则:
        - 上市 >= 2018-01-01 (评估区间起点前) → 确保有相邻年年报可比
        - 非 ST / *ST (名字过滤, listing_metadata 无专门列)
        - 非退市 (universe_alive_during 默认)
        - 非北交所 (板 = "北交所" 的代码 8 开头, 年报结构与沪深不同, 暂不收)
    """
    if mode == "smoke":
        return ["000001", "600036", "600519", "000858", "601318"]  # 平安/招商/茅台/五粮/平安

    from utils.listing_metadata import load_listing_metadata, universe_alive_during
    meta = load_listing_metadata().set_index("symbol")
    # 在 2018 ~ 今 任一时刻存活的所有 A 股 (已处理上市/退市)
    alive = universe_alive_during("2018-01-01", "2026-12-31", require_local_data=False)
    # 进一步过滤: 非 ST / *ST / 非北交所 / 2018-01-01 前已上市
    cutoff = pd.Timestamp("2018-01-01")
    keep: list[str] = []
    for s in alive:
        if s not in meta.index:
            continue
        row = meta.loc[s]
        name = str(row.get("name", ""))
        if "ST" in name or "*ST" in name or "退" in name:
            continue
        if str(row.get("exchange", "")) == "BJ":
            continue  # 北交所年报格式与沪深差异大, 本 pre-reg 不覆盖
        ld = row.get("list_date")
        if pd.isna(ld) or ld > cutoff:
            continue  # 2018 后上市, 跨年样本不足
        if len(s) != 6:
            continue
        keep.append(s)

    if mode == "subset":
        import numpy as np
        rng = np.random.default_rng(42)
        k = min(500, len(keep))
        return sorted(rng.choice(keep, size=k, replace=False).tolist())
    return sorted(keep)


def run(mode: str, download: bool, out_path: Path, delete_pdf_after_tokens: bool,
        max_workers: int) -> tuple[pd.DataFrame, pd.DataFrame]:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    start_year = 2022 if mode == "smoke" else LOCKED_EVAL_START_YEAR
    end_year = 2024 if mode == "smoke" else LOCKED_EVAL_END_YEAR

    symbols = resolve_universe(mode)
    print(f"[pre-reg] mode={mode} universe_n={len(symbols)} years={start_year}..{end_year}")
    print(f"[pre-reg] DriftConfig = {LOCKED_CONFIG.as_dict()}")
    print(f"[pre-reg] Kill: IC < {KILL_IC_LOWER} → stop; IC > {TIER2_IC_UPPER} → paper-trade")
    print(f"[pre-reg] delete_pdf_after_tokens = {delete_pdf_after_tokens}  workers={max_workers}")

    factor_wide, diag = compute_mda_drift_factor(
        symbols=symbols,
        start_year=start_year,
        end_year=end_year,
        config=LOCKED_CONFIG,
        download=download,
        show_progress=True,
        delete_pdf_after_tokens=delete_pdf_after_tokens,
        max_workers=max_workers,
    )
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    if not factor_wide.empty:
        factor_wide.to_parquet(out_path)
        print(f"[saved] {out_path}  shape={factor_wide.shape}")
    else:
        print("[empty] factor_wide empty — nothing to save")

    # diagnostics 摘要
    if not diag.empty and "status" in diag.columns:
        print("\n[diagnostics] status counts:")
        print(diag["status"].value_counts().to_string())

    return factor_wide, diag


def main() -> int:
    args = parse_args()
    mode = "smoke" if args.smoke else ("subset" if args.subset else "full")
    factor_wide, diag = run(
        mode=mode,
        download=not args.no_download,
        out_path=Path(args.out_path),
        delete_pdf_after_tokens=args.delete_pdf_after_tokens,
        max_workers=args.workers,
    )

    # smoke 模式只验证 pipeline, 不做 IC. 非 smoke 模式的 IC 评估在后续 journal 脚本完成
    # (这里不做, 保持 pre-reg 的唯一职责 = 产出 factor 宽表 + diagnostics)
    if mode == "smoke":
        ok = (not factor_wide.empty) or (diag is not None and not diag.empty)
        print(f"\n[smoke] pipeline {'OK' if ok else 'EMPTY — check network / cache'}")
        return 0 if ok else 1

    print("\n[next] 用 factor_wide 对接 utils.factor_analysis.compute_ic_series + quintile_backtest")
    print(f"[next] 结果写到 journal/mda_drift_tier1_result_{date.today():%Y%m%d}.md")
    return 0


if __name__ == "__main__":
    sys.exit(main())
