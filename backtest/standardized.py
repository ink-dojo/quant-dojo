"""
backtest/standardized.py — 标准化回测框架

自动化回测管道：用户只需提供策略名+日期范围，
其余数据加载、因子计算、组合构建、绩效评估全部自动完成。

核心保证:
  1. 确定性：相同输入 → 相同输出（固定随机种子，排序操作）
  2. 无未来函数：因子 shift(1)，训练/测试窗口严格分离
  3. 标准化输出：统一的 BacktestResult 格式
  4. 自动持久化：通过 run_store 保存每次运行记录

用法:
    from backtest.standardized import run_backtest, BacktestConfig
    result = run_backtest(BacktestConfig(strategy="v7", start="2024-01-01", end="2026-03-31"))
    print(result.metrics)
"""
from __future__ import annotations

import logging
import warnings
from dataclasses import dataclass, field, asdict
from datetime import datetime
from typing import Optional

import numpy as np
import pandas as pd

from strategies.base import StrategyConfig
from strategies.multi_factor import MultiFactorStrategy
from utils.local_data_loader import load_price_wide, get_all_symbols, load_factor_wide
from utils.metrics import (
    annualized_return,
    annualized_volatility,
    sharpe_ratio,
    max_drawdown,
    calmar_ratio,
    win_rate,
    profit_loss_ratio,
)

logger = logging.getLogger(__name__)


# ══════════════════════════════════════════════════════════════
# 配置与结果数据类
# ══════════════════════════════════════════════════════════════

# 策略 → 因子映射（与 daily_signal.py / factor_monitor.py 保持一致）
STRATEGY_FACTORS = {
    "v7": ["team_coin", "low_vol_20d", "cgo_simple", "enhanced_mom_60", "bp"],
    "v8": ["team_coin", "low_vol_20d", "cgo_simple", "enhanced_mom_60", "bp", "shadow_lower"],
    "ad_hoc": ["momentum_20", "ep", "low_vol", "turnover_rev"],
}


@dataclass
class BacktestConfig:
    """回测输入配置 — 用户只需填这些"""
    strategy: str = "v7"                  # 策略名：v7, v8, ad_hoc
    start: str = ""                       # 回测开始日期 YYYY-MM-DD
    end: str = ""                         # 回测结束日期 YYYY-MM-DD
    n_stocks: int = 30                    # 每期选股数量
    commission: float = 0.0003            # 单边手续费率
    initial_capital: float = 1_000_000    # 初始资金
    benchmark: str = "000300"             # 基准指数代码
    neutralize: bool = True               # 是否做行业中性化
    random_seed: int = 42                 # 随机种子（确定性保证）
    lookback_years: int = 1               # 因子计算回看年数
    min_price: float = 2.0                # 最低股价过滤
    min_listing_days: int = 60            # 最短上市天数


@dataclass
class BacktestResult:
    """回测输出结果 — 标准化格式"""
    config: BacktestConfig
    metrics: dict = field(default_factory=dict)
    equity_curve: Optional[pd.DataFrame] = None
    trade_log: list = field(default_factory=list)
    factor_stats: dict = field(default_factory=dict)
    run_id: str = ""
    status: str = "pending"
    error: Optional[str] = None
    created_at: str = ""


# ══════════════════════════════════════════════════════════════
# 因子计算
# ══════════════════════════════════════════════════════════════

def _compute_factors(
    strategy: str,
    price_wide: pd.DataFrame,
    symbols: list,
    start: str,
    end: str,
    neutralize: bool = True,
) -> dict[str, tuple[pd.DataFrame, int]]:
    """
    根据策略名计算因子宽表。

    返回:
        dict: {因子名: (因子宽表, 方向)}，方向 1=正向 -1=反向
    """
    from utils.alpha_factors import (
        team_coin,
        low_vol_20d,
        enhanced_momentum,
        bp_factor,
        shadow_lower,
    )

    factors = {}

    if strategy in ("v7", "v8"):
        # team_coin
        try:
            factors["team_coin"] = (team_coin(price_wide), 1)
        except Exception as e:
            logger.warning("team_coin 计算失败: %s", e)

        # low_vol_20d
        try:
            factors["low_vol_20d"] = (low_vol_20d(price_wide), 1)
        except Exception as e:
            logger.warning("low_vol_20d 计算失败: %s", e)

        # cgo_simple = -(price / price.rolling(60).mean() - 1)
        cgo = -(price_wide / price_wide.rolling(60).mean() - 1)
        factors["cgo_simple"] = (cgo, 1)

        # enhanced_momentum
        try:
            factors["enhanced_mom_60"] = (enhanced_momentum(price_wide), 1)
        except Exception as e:
            logger.warning("enhanced_momentum 计算失败: %s", e)

        # bp
        try:
            pb_wide = load_factor_wide(symbols, "pb", start, end)
            if not pb_wide.empty:
                factors["bp"] = (bp_factor(pb_wide), 1)
        except Exception as e:
            logger.warning("bp 因子计算失败: %s", e)

        # v8: shadow_lower
        if strategy == "v8":
            try:
                low_wide = load_price_wide(symbols, start, end, field="low")
                if not low_wide.empty:
                    factors["shadow_lower"] = (shadow_lower(price_wide, low_wide), -1)
            except Exception as e:
                logger.warning("shadow_lower 计算失败: %s", e)

        # 行业中性化
        if neutralize:
            factors = _neutralize_factors(factors, symbols)

    else:
        # ad_hoc 策略
        ret_wide = price_wide.pct_change()

        # momentum_20
        mom = price_wide.pct_change(20)
        factors["momentum_20"] = (mom, 1)

        # ep (1/PE)
        try:
            pe_wide = load_factor_wide(symbols, "pe_ttm", start, end)
            ep = (1.0 / pe_wide).replace([np.inf, -np.inf], np.nan)
            ep[pe_wide <= 0] = np.nan
            factors["ep"] = (ep, 1)
        except Exception as e:
            logger.warning("EP 因子计算失败: %s", e)

        # low_vol (-20d volatility)
        vol_20 = ret_wide.rolling(20).std() * np.sqrt(252)
        factors["low_vol"] = (vol_20, -1)

        # turnover_rev
        try:
            turnover_wide = load_factor_wide(symbols, "turnover", start, end)
            turnover_20 = turnover_wide.rolling(20).mean()
            factors["turnover_rev"] = (turnover_20, -1)
        except Exception as e:
            logger.warning("换手率因子计算失败: %s", e)

    return factors


def _neutralize_factors(
    factors: dict[str, tuple[pd.DataFrame, int]],
    symbols: list,
) -> dict[str, tuple[pd.DataFrame, int]]:
    """对所有因子做行业中性化"""
    try:
        from utils.factor_analysis import neutralize_factor_by_industry
        from utils.fundamental_loader import get_industry_classification
        industry_df = get_industry_classification(symbols=symbols)
    except Exception as e:
        logger.warning("行业分类加载失败，跳过中性化: %s", e)
        return factors

    neutralized = {}
    for name, (fac_wide, direction) in factors.items():
        try:
            neutral = neutralize_factor_by_industry(fac_wide, industry_df)
            neutralized[name] = (neutral, direction)
        except Exception as e:
            logger.warning("中性化失败 %s: %s", name, e)
            neutralized[name] = (fac_wide, direction)

    return neutralized


# ══════════════════════════════════════════════════════════════
# 绩效计算
# ══════════════════════════════════════════════════════════════

def _compute_metrics(returns: pd.Series) -> dict:
    """计算标准绩效指标"""
    if returns.empty:
        return {}

    total_ret = float((1 + returns).prod() - 1)
    return {
        "total_return": round(total_ret, 6),
        "annualized_return": round(float(annualized_return(returns)), 6),
        "annualized_volatility": round(float(annualized_volatility(returns)), 6),
        "sharpe": round(float(sharpe_ratio(returns)), 4),
        "max_drawdown": round(float(max_drawdown(returns)), 6),
        "calmar": round(float(calmar_ratio(returns)), 4),
        "win_rate": round(float(win_rate(returns)), 4),
        "profit_loss_ratio": round(float(profit_loss_ratio(returns)), 4),
        "n_trading_days": len(returns),
        "volatility": round(float(annualized_volatility(returns)), 6),
    }


# ══════════════════════════════════════════════════════════════
# 主入口
# ══════════════════════════════════════════════════════════════

def run_backtest(config: BacktestConfig) -> BacktestResult:
    """
    运行标准化回测。

    流程:
        1. 验证配置
        2. 设置随机种子（确定性）
        3. 加载价格数据（含回看窗口）
        4. 计算因子宽表
        5. 加载 ST 数据（排除 ST 股）
        6. 构建 MultiFactorStrategy
        7. 运行回测
        8. 计算绩效指标
        9. 持久化到 run_store
       10. 返回 BacktestResult

    参数:
        config: BacktestConfig 实例

    返回:
        BacktestResult 实例
    """
    result = BacktestResult(
        config=config,
        created_at=datetime.now().isoformat(),
    )

    try:
        _validate_config(config)
        np.random.seed(config.random_seed)

        print(f"[回测] 策略={config.strategy} | {config.start} ~ {config.end} | "
              f"选股={config.n_stocks} | 手续费={config.commission}")

        # ── 1. 加载价格数据 ──────────────────────────────────
        print("  加载价格数据...")
        symbols = get_all_symbols()
        # 回看窗口：因子计算需要历史数据
        lookback_start = str(int(config.start[:4]) - config.lookback_years) + config.start[4:]

        price_wide = load_price_wide(symbols, lookback_start, config.end, field="close")
        if price_wide.empty:
            raise ValueError("无法加载价格数据")

        print(f"  价格数据: {price_wide.shape[0]} 天 x {price_wide.shape[1]} 只股票")

        # ── 2. 计算因子 ──────────────────────────────────────
        print("  计算因子...")
        factors = _compute_factors(
            strategy=config.strategy,
            price_wide=price_wide,
            symbols=symbols,
            start=lookback_start,
            end=config.end,
            neutralize=config.neutralize,
        )

        if not factors:
            raise ValueError("无有效因子可用")

        factor_names = list(factors.keys())
        print(f"  因子: {', '.join(factor_names)}")

        # 因子统计
        from utils.factor_analysis import compute_ic_series
        ret_wide = price_wide.pct_change()
        factor_stats = {}
        for name, (fac_wide, direction) in factors.items():
            try:
                ic_s = compute_ic_series(fac_wide, ret_wide, method="spearman")
                if not ic_s.empty:
                    factor_stats[name] = {
                        "ic_mean": round(float(ic_s.mean()), 6),
                        "ic_std": round(float(ic_s.std()), 6),
                        "icir": round(float(ic_s.mean() / ic_s.std()), 4) if ic_s.std() > 0 else 0,
                        "direction": direction,
                    }
            except Exception:
                pass
        result.factor_stats = factor_stats

        # ── 3. 加载 ST 数据 ──────────────────────────────────
        print("  加载 ST 数据...")
        is_st_wide = None
        try:
            is_st_wide = load_factor_wide(symbols, "is_st", lookback_start, config.end)
            if is_st_wide.empty:
                is_st_wide = None
        except Exception:
            logger.warning("ST 数据加载失败，跳过 ST 过滤")

        # ── 4. 截取回测窗口 ──────────────────────────────────
        # 因子宽表包含回看期数据，但回测只在 start~end 内进行
        # MultiFactorStrategy.run() 会用 price_wide 的日期范围做回测
        # 所以需要确保 price_wide 从 lookback 开始（因子计算需要），
        # 但我们在最终结果中只取 start~end 的部分

        # ── 5. 构建策略并运行回测 ─────────────────────────────
        print("  运行回测...")
        strategy_config = StrategyConfig(
            name=f"{config.strategy}_backtest",
            initial_capital=config.initial_capital,
            commission=config.commission,
            benchmark=config.benchmark,
        )

        strategy = MultiFactorStrategy(
            config=strategy_config,
            factors=factors,
            is_st_wide=is_st_wide,
            n_stocks=config.n_stocks,
        )

        bt_result = strategy.run(price_wide)

        # 截取回测窗口
        start_ts = pd.Timestamp(config.start)
        end_ts = pd.Timestamp(config.end)
        bt_result = bt_result.loc[
            (bt_result.index >= start_ts) & (bt_result.index <= end_ts)
        ]

        if bt_result.empty:
            raise ValueError(f"回测窗口 {config.start}~{config.end} 内无交易数据")

        # ── 6. 计算绩效指标 ──────────────────────────────────
        returns = bt_result["portfolio_return"]
        metrics = _compute_metrics(returns)
        result.metrics = metrics
        result.equity_curve = bt_result
        result.status = "success"

        # 打印摘要
        print(f"\n{'='*50}")
        print(f"  回测完成: {config.strategy}")
        print(f"{'='*50}")
        print(f"  区间: {config.start} ~ {config.end}")
        print(f"  交易天数: {metrics.get('n_trading_days', 0)}")
        print(f"  总收益: {metrics.get('total_return', 0):.2%}")
        print(f"  年化收益: {metrics.get('annualized_return', 0):.2%}")
        print(f"  夏普比率: {metrics.get('sharpe', 0):.2f}")
        print(f"  最大回撤: {metrics.get('max_drawdown', 0):.2%}")
        print(f"  胜率: {metrics.get('win_rate', 0):.2%}")
        print(f"{'='*50}")

        # ── 7. 持久化 ────────────────────────────────────────
        run_id = _persist_result(result)
        result.run_id = run_id
        print(f"  运行记录已保存: {run_id}")

    except Exception as e:
        result.status = "failed"
        result.error = str(e)
        logger.error("回测失败: %s", e, exc_info=True)
        print(f"  回测失败: {e}")

        # 失败也持久化
        try:
            run_id = _persist_result(result)
            result.run_id = run_id
        except Exception:
            pass

    return result


def _validate_config(config: BacktestConfig) -> None:
    """验证回测配置"""
    if not config.start or not config.end:
        raise ValueError("必须指定 start 和 end 日期")
    if config.start >= config.end:
        raise ValueError(f"start ({config.start}) 必须早于 end ({config.end})")
    if config.strategy not in STRATEGY_FACTORS:
        raise ValueError(
            f"未知策略: {config.strategy}，可选: {list(STRATEGY_FACTORS.keys())}"
        )
    if config.n_stocks < 1:
        raise ValueError(f"n_stocks 必须 >= 1，当前: {config.n_stocks}")
    if config.commission < 0:
        raise ValueError(f"commission 必须 >= 0，当前: {config.commission}")


def _persist_result(result: BacktestResult) -> str:
    """通过 run_store 持久化回测结果"""
    from pipeline.run_store import RunRecord, generate_run_id, save_run

    config = result.config
    run_id = generate_run_id(
        strategy_id=config.strategy,
        start=config.start,
        end=config.end,
        params={
            "n_stocks": config.n_stocks,
            "commission": config.commission,
            "neutralize": config.neutralize,
        },
    )

    record = RunRecord(
        run_id=run_id,
        strategy_id=config.strategy,
        strategy_name=f"{config.strategy} 标准化回测",
        params=asdict(config),
        start_date=config.start,
        end_date=config.end,
        status=result.status,
        metrics=result.metrics,
        error=result.error,
        created_at=result.created_at,
    )

    save_run(record, equity_df=result.equity_curve)
    return run_id


if __name__ == "__main__":
    print("标准化回测框架")
    print("用法: from backtest.standardized import run_backtest, BacktestConfig")
    print("      result = run_backtest(BacktestConfig(strategy='v7', start='2024-01-01', end='2026-03-31'))")
