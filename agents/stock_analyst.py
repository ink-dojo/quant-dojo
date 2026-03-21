"""
单只股票综合分析 Agent
整合价格数据、估值指标、财务质量，并触发牛熊辩论得出投资观点
"""
import math
from typing import Optional

import numpy as np

from agents.base import LLMClient, BaseAgent
from agents.debate import BullBearDebate


class StockAnalyst(BaseAgent):
    """
    单只股票综合分析 Agent

    流程：
        1. 拉取日线价格数据 → 计算价格摘要
        2. 拉取 PE/PB 估值指标 → 计算价值因子暴露
        3. 拉取财务摘要 → 计算质量因子暴露
        4. 构建 context 文本，触发 BullBearDebate
        5. 返回结构化结果 dict

    使用示例:
        analyst = StockAnalyst()
        result = analyst.analyze("000001", "2023-01-01", "2024-01-01")
        print(analyst.format_report(result))
    """

    def __init__(self, llm: Optional[LLMClient] = None):
        """
        初始化 StockAnalyst

        参数:
            llm: LLMClient 实例；为 None 时自动创建（用于牛熊辩论）
                 如果 LLM 后端不可用，辩论步骤会被跳过
        """
        if llm is None:
            llm = LLMClient()
        super().__init__(llm)

    # ------------------------------------------------------------------
    # 公开接口
    # ------------------------------------------------------------------

    def analyze(self, symbol: str, start: str, end: str, **kwargs) -> dict:
        """
        对单只股票执行综合分析

        参数:
            symbol : 股票代码，如 "000001"（不带后缀）
            start  : 开始日期，如 "2023-01-01"
            end    : 结束日期，如 "2024-01-01"

        返回:
            dict，包含以下键：
                symbol          : 股票代码
                price_summary   : 价格摘要（最新价、年化收益、年化波动、Sharpe）
                factor_exposure : 因子暴露（momentum, value, quality, low_vol）
                fundamental     : 财务摘要（PE, PB, ROE, 净利率等）
                debate          : 牛熊辩论结论（LLM 不可用时为 None）
        """
        # ── 1. 价格数据 ──────────────────────────────────────────────
        price_summary = self._compute_price_summary(symbol, start, end)
        if not price_summary:
            return {}

        # ── 2. 估值指标 ──────────────────────────────────────────────
        pe_pb_data = self._fetch_pe_pb(symbol, start, end)

        # ── 3. 财务摘要 ──────────────────────────────────────────────
        financials_data = self._fetch_financials(symbol)

        # ── 4. 因子暴露（存根） ──────────────────────────────────────
        factor_exposure = self._compute_factor_exposure(pe_pb_data, financials_data)

        # ── 5. 整理 fundamental 摘要 ─────────────────────────────────
        fundamental = self._build_fundamental(pe_pb_data, financials_data)

        # ── 6. 牛熊辩论 ──────────────────────────────────────────────
        debate_result = self._run_debate(symbol, price_summary, fundamental)

        return {
            "symbol": symbol,
            "price_summary": price_summary,
            "factor_exposure": factor_exposure,
            "fundamental": fundamental,
            "debate": debate_result,
        }

    # ------------------------------------------------------------------
    # 内部辅助方法
    # ------------------------------------------------------------------

    def _compute_price_summary(self, symbol: str, start: str, end: str) -> dict:
        """
        计算价格摘要指标

        参数:
            symbol : 股票代码
            start  : 开始日期
            end    : 结束日期

        返回:
            dict，包含 latest_price, annualized_return, annualized_vol, sharpe
            失败时返回空 dict（调用方应直接 return {}）
        """
        try:
            from utils.data_loader import get_stock_history
            df = get_stock_history(symbol, start, end)
        except Exception as e:
            print(f"[StockAnalyst] 获取价格数据失败 {symbol}: {e}")
            return {}

        if df.empty or len(df) < 2:
            print(f"[StockAnalyst] 价格数据不足 {symbol}，行数={len(df)}")
            return {}

        close = df["close"]
        latest_price = float(close.iloc[-1])
        n_days = len(close)

        # 年化收益（几何）
        total_return = close.iloc[-1] / close.iloc[0] - 1
        years = n_days / 252
        annualized_return = float((1 + total_return) ** (1 / years) - 1) if years > 0 else float("nan")

        # 年化波动
        daily_ret = close.pct_change().dropna()
        annualized_vol = float(daily_ret.std() * math.sqrt(252))

        # Sharpe（无风险利率 = 0）
        sharpe = annualized_return / annualized_vol if annualized_vol > 0 else float("nan")

        return {
            "latest_price": round(latest_price, 2),
            "annualized_return": round(annualized_return, 4),
            "annualized_vol": round(annualized_vol, 4),
            "sharpe": round(sharpe, 4),
            "start_date": str(df.index[0].date()),
            "end_date": str(df.index[-1].date()),
            "n_days": n_days,
        }

    def _fetch_pe_pb(self, symbol: str, start: str, end: str) -> dict:
        """
        获取最新 PE/PB 估值指标

        参数:
            symbol : 股票代码
            start  : 开始日期
            end    : 结束日期

        返回:
            dict，包含 pe_ttm, pb, pcf（取区间最后一个有效值）
            失败时返回空 dict
        """
        try:
            from utils.fundamental_loader import get_pe_pb
            df = get_pe_pb(symbol, start, end)
        except Exception as e:
            print(f"[StockAnalyst] 获取估值数据失败 {symbol}: {e}")
            return {}

        if df.empty:
            return {}

        result = {}
        for col in ["pe_ttm", "pb", "pcf"]:
            if col in df.columns:
                series = df[col].dropna()
                result[col] = float(series.iloc[-1]) if not series.empty else float("nan")
        return result

    def _fetch_financials(self, symbol: str) -> dict:
        """
        获取最新财务摘要（取最近一期有效值）

        参数:
            symbol : 股票代码

        返回:
            dict，包含 roe, roa, debt_ratio, net_margin, net_profit_growth, revenue_growth
            失败时返回空 dict
        """
        try:
            from utils.fundamental_loader import get_financials
            df = get_financials(symbol)
        except Exception as e:
            print(f"[StockAnalyst] 获取财务数据失败 {symbol}: {e}")
            return {}

        if df.empty:
            return {}

        result = {}
        for col in ["roe", "roa", "debt_ratio", "net_margin", "net_profit_growth", "revenue_growth"]:
            if col in df.columns:
                series = df[col].dropna()
                result[col] = float(series.iloc[-1]) if not series.empty else float("nan")
        return result

    def _compute_factor_exposure(self, pe_pb: dict, financials: dict) -> dict:
        """
        计算因子暴露（部分为存根）

        参数:
            pe_pb      : _fetch_pe_pb() 的返回值
            financials : _fetch_financials() 的返回值

        返回:
            dict，包含：
                momentum : NaN（复杂计算，暂为存根）
                value    : EP = 1/PE_TTM（如有）
                quality  : 最新 ROE（如有）
                low_vol  : NaN（复杂计算，暂为存根）
        """
        # momentum: 需要截面数据，此处为存根
        momentum = float("nan")

        # value: EP = 1 / PE_TTM
        pe_ttm = pe_pb.get("pe_ttm", float("nan"))
        if pe_ttm and not math.isnan(pe_ttm) and pe_ttm > 0:
            value = round(1.0 / pe_ttm, 6)
        else:
            value = float("nan")

        # quality: 最新 ROE
        roe = financials.get("roe", float("nan"))
        quality = roe if (roe and not math.isnan(roe)) else float("nan")

        # low_vol: 需要截面数据，此处为存根
        low_vol = float("nan")

        return {
            "momentum": momentum,
            "value": value,
            "quality": quality,
            "low_vol": low_vol,
        }

    def _build_fundamental(self, pe_pb: dict, financials: dict) -> dict:
        """
        整合 PE/PB 和财务数据为统一的 fundamental 摘要

        参数:
            pe_pb      : _fetch_pe_pb() 的返回值
            financials : _fetch_financials() 的返回值

        返回:
            合并后的 fundamental dict
        """
        result = {}
        result.update(pe_pb)
        result.update(financials)
        return result

    def _run_debate(self, symbol: str, price_summary: dict, fundamental: dict) -> Optional[dict]:
        """
        基于价格和估值数据触发牛熊辩论

        参数:
            symbol        : 股票代码
            price_summary : _compute_price_summary() 的结果
            fundamental   : _build_fundamental() 的结果

        返回:
            BullBearDebate.analyze() 的结果 dict；LLM 不可用时返回 None
        """
        if self.llm is None or self.llm._backend == "none":
            print(f"[StockAnalyst] LLM 不可用，跳过牛熊辩论")
            return None

        # 构建 context 文本
        context_lines = [
            f"股票代码: {symbol}",
            f"区间: {price_summary.get('start_date')} ~ {price_summary.get('end_date')}",
            f"最新价: {price_summary.get('latest_price')}",
            f"年化收益: {price_summary.get('annualized_return', float('nan')):.2%}",
            f"年化波动: {price_summary.get('annualized_vol', float('nan')):.2%}",
            f"Sharpe: {price_summary.get('sharpe', float('nan')):.2f}",
        ]

        if fundamental.get("pe_ttm") and not math.isnan(fundamental.get("pe_ttm", float("nan"))):
            context_lines.append(f"PE_TTM: {fundamental['pe_ttm']:.2f}")
        if fundamental.get("pb") and not math.isnan(fundamental.get("pb", float("nan"))):
            context_lines.append(f"PB: {fundamental['pb']:.2f}")
        if fundamental.get("roe") and not math.isnan(fundamental.get("roe", float("nan"))):
            context_lines.append(f"ROE: {fundamental['roe']:.2f}%")
        if fundamental.get("net_profit_growth") and not math.isnan(fundamental.get("net_profit_growth", float("nan"))):
            context_lines.append(f"净利润增速: {fundamental['net_profit_growth']:.2f}%")

        context_text = "\n".join(context_lines)

        try:
            debate = BullBearDebate(self.llm)
            return debate.analyze(
                topic=f"{symbol} 股票投资价值",
                context=context_text,
            )
        except Exception as e:
            print(f"[StockAnalyst] 牛熊辩论失败: {e}")
            return None


if __name__ == "__main__":
    analyst = StockAnalyst()
    result = analyst.analyze("000001", "2023-01-01", "2024-01-01")
    print("返回的键：", list(result.keys()))
    if result:
        print("\n── price_summary ──")
        for k, v in result.get("price_summary", {}).items():
            print(f"  {k}: {v}")
        print("\n── factor_exposure ──")
        for k, v in result.get("factor_exposure", {}).items():
            print(f"  {k}: {v}")
        print("\n── fundamental ──")
        for k, v in result.get("fundamental", {}).items():
            print(f"  {k}: {v}")
        if result.get("debate"):
            print("\n── debate conclusion ──")
            print(f"  {result['debate'].get('conclusion')}")
    print("\n✅ StockAnalyst 验证完成")
