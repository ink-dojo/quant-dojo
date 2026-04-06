"""
agents/factor_miner.py — 因子挖掘 Agent

职责:
  1. 从 27 因子库中批量计算所有快速因子
  2. 对每个因子计算 IC/ICIR/t-stat 等统计量
  3. 执行分层回测（五分位）
  4. 评估因子间相关性，避免共线性
  5. 输出因子排行榜，推荐最优因子组合

每周执行一次（或按需手动触发），结果保存到 live/factor_research/。
"""

import json
import logging
import warnings
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

RESEARCH_DIR = Path(__file__).parent.parent / "live" / "factor_research"


class FactorMiner:
    """
    因子挖掘 Agent：全因子库自动化筛选。

    工作流:
      1. 加载全市场价格数据（1年回看）
      2. 计算所有快速因子
      3. 对每个因子做 IC 分析 + 五分位回测
      4. 生成因子排行榜
      5. 推荐最优 Top-K 因子组合
    """

    def __init__(self):
        from utils.runtime_config import get_pipeline_param
        self.MIN_ABS_IC = get_pipeline_param("factor_mining.min_abs_ic", 0.015)
        self.MIN_ABS_ICIR = get_pipeline_param("factor_mining.min_abs_icir", 0.2)
        self.MIN_ABS_T_STAT = get_pipeline_param("factor_mining.min_abs_t_stat", 1.5)
        self.CORRELATION_THRESHOLD = get_pipeline_param("factor_mining.correlation_threshold", 0.7)
        self.TOP_K = get_pipeline_param("factor_mining.top_k", 5)

    # 回看窗口
    LOOKBACK_YEARS = 1

    def run(self, ctx: Any) -> dict:
        """
        执行因子挖掘流程。

        参数:
            ctx: PipelineContext

        返回:
            dict: {
              rankings: [{name, IC_mean, ICIR, t_stat, ls_sharpe, category}, ...],
              recommended: [推荐因子名列表],
              correlation_matrix: {factor: {factor: corr}},
              timestamp: str,
            }
        """
        from utils.alpha_factors import build_fast_factors, FACTOR_CATALOG
        from utils.factor_analysis import compute_ic_series, ic_summary, quintile_backtest
        from utils.local_data_loader import (
            load_price_wide,
            load_factor_wide,
            get_all_symbols,
        )

        print("  加载市场数据...")
        end_date = ctx.date
        start_date = str(int(end_date[:4]) - self.LOOKBACK_YEARS) + end_date[4:]

        symbols = get_all_symbols()
        if not symbols:
            return {"error": "无本地数据"}

        # 加载各种宽表
        price_wide = load_price_wide(symbols, start_date, end_date, field="close")
        if price_wide.empty:
            return {"error": "价格数据为空"}

        high_wide = load_price_wide(symbols, start_date, end_date, field="high")
        low_wide = load_price_wide(symbols, start_date, end_date, field="low")
        open_wide = load_price_wide(symbols, start_date, end_date, field="open")

        pe_wide = None
        pb_wide = None
        try:
            pe_wide = load_factor_wide(symbols, "pe_ttm", start_date, end_date)
        except Exception:
            pass
        try:
            pb_wide = load_factor_wide(symbols, "pb", start_date, end_date)
        except Exception:
            pass

        # 市场收益率（等权平均）
        ret_wide = price_wide.pct_change()
        market_ret = ret_wide.mean(axis=1)

        # ── 1. 批量计算所有快速因子 ────────────────────────────
        print("  计算全因子库...")
        factors = build_fast_factors(
            price=price_wide,
            high=high_wide if not high_wide.empty else None,
            low=low_wide if not low_wide.empty else None,
            open_price=open_wide if not open_wide.empty else None,
            pe=pe_wide if pe_wide is not None and not pe_wide.empty else None,
            pb=pb_wide if pb_wide is not None and not pb_wide.empty else None,
            market_ret=market_ret,
        )

        # 额外添加 ROE 因子（如果 PE 和 PB 都可用）
        if pe_wide is not None and pb_wide is not None:
            from utils.alpha_factors import roe_factor
            try:
                factors["roe"] = roe_factor(pe_wide, pb_wide).reindex_like(price_wide)
            except Exception:
                pass

        print(f"  共计算 {len(factors)} 个因子")

        # ── 2. 逐因子 IC 分析 + 分层回测 ──────────────────────
        print("  IC 分析 + 分层回测...")
        # 次日收益（T+1 方向的因子值与 T+1 的收益做截面相关）
        fwd_ret = ret_wide.shift(-1)

        rankings = []
        ic_series_dict = {}

        for name, fac_wide in factors.items():
            if fac_wide is None or fac_wide.empty:
                continue

            # 检查有效数据量
            valid_pct = fac_wide.notna().mean().mean()
            if valid_pct < 0.1:
                continue

            try:
                # IC 分析
                ic_s = compute_ic_series(fac_wide, fwd_ret, method="spearman", min_stocks=30)
                ic_clean = ic_s.dropna()
                if len(ic_clean) < 20:
                    continue

                ic_mean = ic_clean.mean()
                ic_std = ic_clean.std()
                icir = ic_mean / ic_std if ic_std > 0 else 0
                t_stat = ic_mean / (ic_std / np.sqrt(len(ic_clean))) if ic_std > 0 else 0
                pct_pos = (ic_clean > 0).mean()

                # 五分位回测
                _, ls_ret = quintile_backtest(fac_wide, fwd_ret, n_groups=5)
                ls_clean = ls_ret.dropna()
                if len(ls_clean) > 10:
                    ls_ann = ls_clean.mean() * 252
                    ls_vol = ls_clean.std() * np.sqrt(252)
                    ls_sharpe = ls_ann / ls_vol if ls_vol > 0 else 0
                else:
                    ls_ann = 0
                    ls_sharpe = 0

                # 因子分类
                catalog_info = FACTOR_CATALOG.get(name, {})
                category = catalog_info.get("category", "其他")

                rankings.append({
                    "name": name,
                    "category": category,
                    "IC_mean": round(ic_mean, 4),
                    "IC_std": round(ic_std, 4),
                    "ICIR": round(icir, 4),
                    "t_stat": round(t_stat, 4),
                    "pct_pos": round(pct_pos, 4),
                    "ls_ann_ret": round(ls_ann, 4),
                    "ls_sharpe": round(ls_sharpe, 4),
                    "valid_pct": round(valid_pct, 4),
                })

                ic_series_dict[name] = ic_s

            except Exception as e:
                logger.warning("因子 %s 分析失败: %s", name, e)

        # ── 3. 排序：按 |ICIR| 降序 ───────────────────────────
        rankings.sort(key=lambda x: abs(x["ICIR"]), reverse=True)

        print(f"\n  因子排行榜 (共 {len(rankings)} 个):")
        print(f"  {'排名':<4} {'因子':<20} {'IC均值':>8} {'ICIR':>8} {'t统计量':>8} {'L/S夏普':>8} {'类别':<8}")
        print(f"  {'-'*72}")
        for i, r in enumerate(rankings, 1):
            marker = " ***" if abs(r["ICIR"]) >= self.MIN_ABS_ICIR else ""
            print(
                f"  {i:<4} {r['name']:<20} {r['IC_mean']:>8.4f} {r['ICIR']:>8.4f} "
                f"{r['t_stat']:>8.4f} {r['ls_sharpe']:>8.4f} {r['category']:<8}{marker}"
            )

        # ── 4. 因子间相关性 ───────────────────────────────────
        print("\n  计算因子间相关性...")
        # 取通过基础筛选的因子做相关性矩阵
        qualified = [r["name"] for r in rankings
                     if abs(r["ICIR"]) >= self.MIN_ABS_ICIR]

        corr_matrix = {}
        if len(qualified) >= 2 and ic_series_dict:
            ic_df = pd.DataFrame({
                name: ic_series_dict[name]
                for name in qualified
                if name in ic_series_dict
            }).dropna()
            if len(ic_df) > 20:
                corr = ic_df.corr()
                corr_matrix = {
                    row: {
                        col: round(corr.loc[row, col], 4)
                        for col in corr.columns
                    }
                    for row in corr.index
                }

        # ── 5. 推荐最优组合（贪心选因子，控制共线性） ─────────
        recommended = self._select_top_k(rankings, corr_matrix)
        print(f"\n  推荐因子组合: {recommended}")

        ctx.log_decision(
            "FactorMiner",
            f"推荐 {len(recommended)} 个因子: {recommended}",
            f"从 {len(rankings)} 个候选中筛选，|ICIR|>={self.MIN_ABS_ICIR}，相关性<{self.CORRELATION_THRESHOLD}",
        )
        ctx.set("factor_rankings", rankings)
        ctx.set("recommended_factors", recommended)
        ctx.set("factor_corr_matrix", corr_matrix)

        # ── 6. 保存研究结果 ───────────────────────────────────
        result = {
            "date": ctx.date,
            "rankings": rankings,
            "recommended": recommended,
            "correlation_matrix": corr_matrix,
            "timestamp": datetime.now().isoformat(),
        }
        self._save_result(result, ctx.date)

        return result

    def _select_top_k(self, rankings: list, corr_matrix: dict) -> list:
        """
        贪心选择 Top-K 因子，控制组合内共线性。

        算法:
          1. 按 |ICIR| 降序遍历
          2. 跳过不达标的因子（|IC|, |ICIR|, |t_stat|）
          3. 检查与已选因子的相关性，高于阈值则跳过
          4. 选够 TOP_K 个停止
        """
        selected = []

        for r in rankings:
            if len(selected) >= self.TOP_K:
                break

            # 基础筛选
            if abs(r["IC_mean"]) < self.MIN_ABS_IC:
                continue
            if abs(r["ICIR"]) < self.MIN_ABS_ICIR:
                continue
            if abs(r["t_stat"]) < self.MIN_ABS_T_STAT:
                continue

            # 共线性检查
            name = r["name"]
            too_correlated = False
            if corr_matrix and name in corr_matrix:
                for existing in selected:
                    if existing in corr_matrix.get(name, {}):
                        if abs(corr_matrix[name][existing]) > self.CORRELATION_THRESHOLD:
                            too_correlated = True
                            break

            if not too_correlated:
                selected.append(name)

        return selected

    def _save_result(self, result: dict, date: str):
        """保存因子研究结果"""
        RESEARCH_DIR.mkdir(parents=True, exist_ok=True)
        path = RESEARCH_DIR / f"mining_{date}.json"
        with open(path, "w", encoding="utf-8") as f:
            json.dump(result, f, ensure_ascii=False, indent=2)
        print(f"  研究结果已保存: {path}")
