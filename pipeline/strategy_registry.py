"""
策略注册表 — 所有可通过控制面调用的策略在此注册

每个策略以 StrategyEntry 注册，包含：
  - 唯一 id、名称、描述
  - 支持的参数及其默认值
  - 工厂函数（根据参数创建可运行的策略实例）

使用方式：
  from pipeline.strategy_registry import list_strategies, get_strategy, run_strategy

  # 列出可用策略
  entries = list_strategies()

  # 获取并运行
  entry = get_strategy("multi_factor")
  result = run_strategy("multi_factor", start="2023-01-01", end="2024-12-31")
"""
from __future__ import annotations

import importlib
import logging
from dataclasses import dataclass, field
from typing import Callable, Optional

import pandas as pd

_log = logging.getLogger(__name__)


@dataclass
class StrategyParam:
    """
    策略参数定义

    属性:
        name: 参数名
        description: 参数说明
        default: 默认值
        type_hint: 类型提示字符串（展示用）
    """
    name: str
    description: str
    default: object = None
    type_hint: str = "str"


@dataclass
class StrategyEntry:
    """
    策略注册条目

    属性:
        id: 唯一标识符（英文 snake_case）
        name: 人类可读名称
        description: 策略描述
        hypothesis: 策略假设（为什么能赚钱）
        params: 支持的参数列表
        default_lookback_days: 默认回看天数
        data_type: 数据类型 "single"（单只股票 OHLCV）或 "wide"（价格宽表）
        factory: 工厂函数 (params_dict) -> BaseStrategy 实例
    """
    id: str
    name: str
    description: str
    hypothesis: str = ""
    params: list[StrategyParam] = field(default_factory=list)
    default_lookback_days: int = 750
    data_type: str = "wide"  # "single" 或 "wide"
    factory: Optional[Callable] = None


# ══════════════════════════════════════════════════════════════
# 内部注册表
# ══════════════════════════════════════════════════════════════
_REGISTRY: dict[str, StrategyEntry] = {}


def register(entry: StrategyEntry) -> None:
    """
    注册一个策略到注册表

    参数:
        entry: 策略条目
    """
    if entry.id in _REGISTRY:
        raise ValueError(f"策略 '{entry.id}' 已注册")
    _REGISTRY[entry.id] = entry


def list_strategies() -> list[StrategyEntry]:
    """
    列出所有已注册策略

    返回:
        策略条目列表
    """
    return list(_REGISTRY.values())


def get_strategy(strategy_id: str) -> StrategyEntry:
    """
    获取策略条目

    参数:
        strategy_id: 策略唯一标识符

    返回:
        StrategyEntry

    异常:
        KeyError: 策略不存在
    """
    if strategy_id not in _REGISTRY:
        available = ", ".join(_REGISTRY.keys()) or "(无)"
        raise KeyError(f"未知策略 '{strategy_id}'，可用策略：{available}")
    return _REGISTRY[strategy_id]


def run_strategy(
    strategy_id: str,
    start: str,
    end: str,
    params: Optional[dict] = None,
) -> dict:
    """
    通过注册表运行策略回测

    参数:
        strategy_id: 策略唯一标识符
        start: 回测开始日期 YYYY-MM-DD
        end: 回测结束日期 YYYY-MM-DD
        params: 覆盖策略默认参数（可选）

    返回:
        dict: {
            strategy_id, params, start, end, status,
            results_df, metrics, error
        }
    """
    entry = get_strategy(strategy_id)
    merged_params = {p.name: p.default for p in entry.params}
    if params:
        merged_params.update(params)

    try:
        strategy = entry.factory(merged_params)
        data = _load_data(entry, start, end, merged_params)
        results_df = strategy.run(data)
        metrics = _compute_metrics(results_df)
        return {
            "strategy_id": strategy_id,
            "params": merged_params,
            "start": start,
            "end": end,
            "status": "success",
            "results_df": results_df,
            "metrics": metrics,
            "error": None,
        }
    except Exception as e:
        return {
            "strategy_id": strategy_id,
            "params": merged_params,
            "start": start,
            "end": end,
            "status": "failed",
            "results_df": None,
            "metrics": None,
            "error": str(e),
        }


def _load_industry_map(symbols: list) -> Optional[dict]:
    """
    尝试加载股票行业分类，返回 {symbol: industry_code} 字典。

    失败时打 warning 并返回 None，调用方应降级为不做中性化。

    参数:
        symbols : 股票代码列表

    返回:
        dict 或 None
    """
    try:
        from utils.fundamental_loader import get_industry_classification
        ind_df = get_industry_classification(symbols)
        if ind_df.empty or "industry_code" not in ind_df.columns:
            _log.warning("行业分类数据为空，跳过中性化")
            return None
        ind_map = ind_df.set_index("symbol")["industry_code"].to_dict()
        covered = sum(1 for s in symbols if s in ind_map)
        _log.info("行业分类加载完成：%d / %d 只股票有行业标签", covered, len(symbols))
        return ind_map if covered > 0 else None
    except Exception as exc:
        _log.warning("加载行业分类失败，跳过中性化: %s", exc)
        return None


def _load_data(entry: StrategyEntry, start: str, end: str, params: dict) -> pd.DataFrame:
    """
    根据策略数据类型加载回测数据

    参数:
        entry: 策略条目
        start: 开始日期
        end: 结束日期
        params: 策略参数

    返回:
        DataFrame（单只股票 OHLCV 或价格宽表）
    """
    if entry.data_type == "single":
        # 单只股票策略
        symbol = params.get("symbol", "000001")
        data_loader = importlib.import_module("utils.data_loader")
        return data_loader.get_stock_history(symbol, start, end)
    else:
        # 宽表策略 — 加载本地 CSV 或通过 data_loader
        try:
            local_loader = importlib.import_module("utils.local_data_loader")
            symbols = local_loader.get_all_symbols()
            return local_loader.load_price_wide(symbols, start, end, field="close")
        except ModuleNotFoundError:
            # 本地数据模块不存在，降级到远程数据
            data_loader = importlib.import_module("utils.data_loader")
            return data_loader.load_price_matrix(start, end)


def _compute_metrics(results_df: pd.DataFrame) -> dict:
    """
    从回测结果 DataFrame 提取标准绩效指标

    参数:
        results_df: 策略 run() 返回的 DataFrame

    返回:
        dict: {annualized_return, sharpe, max_drawdown, total_return, ...}
    """
    # 兼容不同列名
    if "returns" in results_df.columns:
        returns = results_df["returns"]
    elif "portfolio_return" in results_df.columns:
        returns = results_df["portfolio_return"]
    else:
        raise ValueError("无法识别收益率列：期望 'returns' 或 'portfolio_return'")

    returns = returns.dropna()
    if len(returns) < 2:
        raise ValueError(f"数据不足（{len(returns)} 行），无法计算指标")

    # 复用 utils/metrics.py 的 performance_summary 计算核心指标
    try:
        metrics_mod = importlib.import_module("utils.metrics")
        ann_ret = float(metrics_mod.annualized_return(returns))
        ann_vol = float(metrics_mod.annualized_volatility(returns))
        sharpe = float(metrics_mod.sharpe_ratio(returns))
        max_dd = float(metrics_mod.max_drawdown(returns))
        win = float(metrics_mod.win_rate(returns))
    except Exception as _e:
        _log.warning("utils.metrics 计算异常，降级到内置 fallback: %s", _e)
        # fallback: 手动计算
        total_return = float((1 + returns).prod() - 1)
        n_days = len(returns)
        # 年化因子上限为 10，防止短回测爆炸
        ann_factor = min(252 / n_days, 10.0) if n_days > 0 else 1
        ann_ret = float((1 + total_return) ** ann_factor - 1)
        ann_vol = float(returns.std() * (252 ** 0.5))
        sharpe = float(ann_ret / ann_vol) if ann_vol > 0 else 0.0
        cum = (1 + returns).cumprod()
        max_dd = float((cum / cum.cummax() - 1).min())
        win = float((returns > 0).mean())

    total_return = float((1 + returns).prod() - 1)
    n_days = len(returns)

    # IR 计算（需要 benchmark_return 列）
    ir = None
    if "benchmark_return" in results_df.columns:
        try:
            metrics_mod2 = importlib.import_module("utils.metrics")
            ir = float(metrics_mod2.information_ratio(returns, results_df["benchmark_return"]))
        except Exception:
            pass

    return {
        "total_return": round(total_return, 6),
        "annualized_return": round(ann_ret, 6),
        "volatility": round(ann_vol, 6),
        "sharpe": round(sharpe, 4),
        "max_drawdown": round(max_dd, 6),
        "win_rate": round(win, 4),
        "n_trading_days": n_days,
        "start_date": str(returns.index[0].date()) if hasattr(returns.index[0], 'date') else str(returns.index[0]),
        "end_date": str(returns.index[-1].date()) if hasattr(returns.index[-1], 'date') else str(returns.index[-1]),
        "information_ratio": round(ir, 4) if ir is not None else None,
    }


# ══════════════════════════════════════════════════════════════
# 内置策略注册
# ══════════════════════════════════════════════════════════════

def _register_builtins() -> None:
    """注册仓库自带的策略"""

    # ── 1. 双均线策略 ──────────────────────────────────────────
    def _dual_ma_factory(params: dict):
        from strategies.base import StrategyConfig
        from strategies.examples.dual_ma import DualMACrossStrategy
        config = StrategyConfig(
            name=f"dual_ma_{params.get('fast_period', 20)}_{params.get('slow_period', 60)}",
            params={
                "fast_period": params.get("fast_period", 20),
                "slow_period": params.get("slow_period", 60),
            },
        )
        return DualMACrossStrategy(config)

    register(StrategyEntry(
        id="dual_ma",
        name="双均线交叉策略",
        description="短期均线上穿长期均线买入，下穿卖出。经典趋势跟踪入门策略。",
        hypothesis="均线交叉捕捉中期趋势，金叉做多、死叉清仓。",
        params=[
            StrategyParam("symbol", "股票代码", "000001", "str"),
            StrategyParam("fast_period", "快线周期", 20, "int"),
            StrategyParam("slow_period", "慢线周期", 60, "int"),
        ],
        default_lookback_days=500,
        data_type="single",
        factory=_dual_ma_factory,
    ))

    # ── 2. 多因子选股策略 ────────────────────────────────────
    def _multi_factor_factory(params: dict):
        from strategies.base import StrategyConfig
        from strategies.multi_factor import MultiFactorStrategy
        import numpy as np

        n_stocks = params.get("n_stocks", 30)
        config = StrategyConfig(name=f"multi_factor_top{n_stocks}")

        # 因子在 run 时动态计算，此处返回一个延迟绑定的包装
        return _MultiFactorAdapter(config, n_stocks=n_stocks)

    register(StrategyEntry(
        id="multi_factor",
        name="多因子等权选股策略",
        description="动量/价值/低波/换手四因子等权合成，月频选前N只等权持有。",
        hypothesis="多因子综合评分能捕捉截面收益差异，分散化持有降低个股风险。",
        params=[
            StrategyParam("n_stocks", "每次选股数量", 30, "int"),
        ],
        default_lookback_days=750,
        data_type="wide",
        factory=_multi_factor_factory,
    ))

    # ── 3. auto_gen 自动生成策略 ─────────────────────────────
    def _auto_gen_factory(params: dict):
        """
        auto_gen 工厂函数，返回 _AutoGenAdapter 实例。

        参数:
            params : 策略参数 dict（auto_gen 当前无可调参数，预留扩展）
        """
        from strategies.base import StrategyConfig
        return _AutoGenAdapter(StrategyConfig(name="auto_gen"))

    register(StrategyEntry(
        id="auto_gen",
        name="AI自动生成策略",
        description="由 idea_to_strategy 流水线根据自然语言想法自动生成的因子组合策略。",
        hypothesis="由 IdeaParser 解析用户想法后自动选因子，每次运行前需先执行 idea pipeline。",
        params=[],
        default_lookback_days=750,
        data_type="wide",
        factory=_auto_gen_factory,
    ))


class _MultiFactorAdapter:
    """
    多因子策略适配器 — 在 run() 时自动从价格宽表计算因子

    这是一个轻量包装，让 MultiFactorStrategy 可以接受纯价格宽表输入，
    而不需要调用者手动构造因子。
    """

    def __init__(self, config, n_stocks: int = 30):
        self.config = config
        self.n_stocks = n_stocks
        self.results = None

    def run(self, price_wide: pd.DataFrame) -> pd.DataFrame:
        """
        从价格宽表计算因子并运行多因子策略。

        会尝试加载行业分类做中性化；失败时降级为不中性化并打 warning。

        参数:
            price_wide: 价格宽表 (date × symbol)

        返回:
            回测结果 DataFrame
        """
        import numpy as np
        from strategies.base import StrategyConfig
        from strategies.multi_factor import MultiFactorStrategy

        # 计算因子
        factors = {}

        # 动量因子：20 日收益率
        momentum = price_wide.pct_change(20)
        factors["momentum_20"] = (momentum, 1)

        # 低波动因子：20 日波动率取负
        volatility = price_wide.pct_change().rolling(20).std()
        factors["low_vol"] = (volatility, -1)

        # 换手反转因子（以5日价格反转近似；如有量数据可替换为 volume.pct_change(5)）
        reversal_5d = price_wide.pct_change(5)
        factors["reversal_5d"] = (reversal_5d, -1)

        # 尝试加载行业分类，用于中性化
        industry_map = _load_industry_map(list(price_wide.columns))

        strategy = MultiFactorStrategy(
            config=self.config,
            factors=factors,
            n_stocks=self.n_stocks,
            neutralize=(industry_map is not None),
            industry_map=industry_map,
        )
        result = strategy.run(price_wide)
        self.results = strategy.results
        return result

    def get_returns(self):
        """获取日收益率"""
        if self.results is None:
            raise RuntimeError("请先调用 run()")
        return self.results["returns"]


class _AutoGenAdapter:
    """
    auto_gen 策略适配器 — 在 run() 时从 auto_gen_latest.json 加载因子定义，
    计算因子后交给 MultiFactorStrategy 运行。

    每次 run() 都会重新读取 JSON，确保因子定义始终使用最新版本。
    """

    def __init__(self, config):
        self.config = config
        self.results = None

    def run(self, price_wide: pd.DataFrame) -> pd.DataFrame:
        """
        加载 auto_gen 因子定义并运行多因子策略。

        会尝试加载行业分类做中性化；失败时降级为不中性化并打 warning。

        参数:
            price_wide : 价格宽表 (date × symbol)，由 run_strategy 的 _load_data 传入

        返回:
            回测结果 DataFrame
        """
        from strategies.multi_factor import MultiFactorStrategy
        from pipeline.auto_gen_loader import load_auto_gen_definition, compute_auto_gen_factors
        from utils.local_data_loader import get_all_symbols

        strategy_def = load_auto_gen_definition()
        symbols = list(price_wide.columns)
        start = str(price_wide.index[0].date())
        end = str(price_wide.index[-1].date())

        factors = compute_auto_gen_factors(strategy_def, price_wide, symbols, start, end)

        # 尝试加载行业分类，用于中性化
        industry_map = _load_industry_map(symbols)

        n_stocks = strategy_def.get("n_stocks", 30)
        strategy = MultiFactorStrategy(
            config=self.config,
            factors=factors,
            n_stocks=n_stocks,
            neutralize=(industry_map is not None),
            industry_map=industry_map,
        )
        result = strategy.run(price_wide)
        self.results = strategy.results
        return result

    def get_returns(self):
        """获取日收益率"""
        if self.results is None:
            raise RuntimeError("请先调用 run()")
        return self.results["returns"]


# 模块加载时自动注册
_register_builtins()


if __name__ == "__main__":
    # 快速验证
    entries = list_strategies()
    print(f"已注册 {len(entries)} 个策略：")
    for e in entries:
        print(f"  - {e.id}: {e.name}")
        for p in e.params:
            print(f"      {p.name} ({p.type_hint}): {p.description} [默认: {p.default}]")
    print("✅ strategy_registry import ok")
