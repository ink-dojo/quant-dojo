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
            # PIT 股票池：只加载在 [start, end] 期间曾经上市且未退市的股票，
            # 修复 get_all_symbols() 导致的幸存者偏差（listing_metadata.py 已实现）
            try:
                listing = importlib.import_module("utils.listing_metadata")
                symbols = listing.universe_alive_during(start, end, require_local_data=True)
                if not symbols:
                    _log.warning("universe_alive_during 返回空集，降级 get_all_symbols")
                    symbols = local_loader.get_all_symbols()
            except Exception as exc:
                _log.warning("PIT universe 加载失败，降级 get_all_symbols: %s", exc)
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

    # ── 4. 多因子选股策略 v2（含基本面因子）────────────────────
    register(StrategyEntry(
        id="multi_factor_v2",
        name="多因子选股策略 v2（含基本面）",
        description="动量/低波/反转/EP/BP/ROE 六因子，IC加权合成，行业中性化。基本面数据不可用时自动降级为纯价格因子。",
        hypothesis="价格动量 + 价值估值 + 质量三维度联合选股，覆盖更宽的 alpha 来源。",
        params=[
            StrategyParam("n_stocks", "选股数量", 30, "int"),
        ],
        default_lookback_days=750,
        data_type="wide",
        factory=lambda params: _MultiFactorV2Adapter(n_stocks=params.get("n_stocks", 30)),
    ))

    # ── 5. 多因子选股策略 v9（新因子集，增强正交性）────────────
    register(StrategyEntry(
        id="multi_factor_v9",
        name="多因子选股策略 v9（正交增强）",
        description=(
            "v7 三核心因子（low_vol_20d/team_coin/bp）+ 三新因子（idiosyncratic_vol/"
            "industry_momentum/insider_buying_proxy），IC加权合成，行业中性化。"
            "覆盖技术/行为金融/基本面/风险/行业轮动/微观结构六个维度。"
            "high/low/volume/行业分类不可用时各对应因子自动降级跳过。"
        ),
        hypothesis=(
            "在 v7 proven 因子基础上，加入与已有因子正交的新维度："
            "特质波动率异象（Ang et al.）、行业动量轮动（Moskowitz）、机构积累代理信号，"
            "通过增加 alpha 来源的多样性提升整体 IC 稳定性。"
        ),
        params=[
            StrategyParam("n_stocks", "选股数量", 30, "int"),
        ],
        default_lookback_days=750,
        data_type="wide",
        factory=lambda params: _MultiFactorV9Adapter(n_stocks=params.get("n_stocks", 30)),
    ))

    # ── 6. 多因子选股策略 v10（因子审计推荐，5 因子无冗余）──────────
    register(StrategyEntry(
        id="multi_factor_v10",
        name="多因子选股策略 v10（审计精选，5 因子）",
        description=(
            "基于 2022-2025 因子审计结果，保留 ICIR>0.37 且 t>2.0 且互不高度相关的 5 个因子："
            "low_vol_20d（ICIR=0.72）/ team_coin（ICIR=0.63）/ shadow_lower（ICIR=-0.49，方向取反）/"
            "amihud_illiq（ICIR=0.38）/ price_vol_divergence（ICIR=0.38）。"
            "全部 IC 加权合成 + 行业中性化；high/low/volume 不可用时对应因子跳过。"
        ),
        hypothesis=(
            "剔除 v9 中 IC 不显著（bp、industry_momentum、insider_buying_proxy）"
            "及高相关冗余（idiosyncratic_vol 与 low_vol_20d 相关 0.76）因子，"
            "用流动性溢价（amihud）和价量背离替换，提升因子正交性和信号稳定性。"
        ),
        params=[
            StrategyParam("n_stocks", "选股数量", 30, "int"),
        ],
        default_lookback_days=750,
        data_type="wide",
        factory=lambda params: _MultiFactorV10Adapter(n_stocks=params.get("n_stocks", 30)),
    ))

    # ── 7. 多因子选股策略 v11（v10 + 2 正交新因子，2026-04-14）─────
    register(StrategyEntry(
        id="multi_factor_v11",
        name="多因子选股策略 v11（8 因子，正交扩展）",
        description=(
            "v10 五因子基础上，加入因子挖掘会话筛选的 3 个正交因子："
            "turnover_accel（ICIR=0.605）/ high_52w（A 股 52 周反转，ICIR=0.324）/ "
            "skewness_20d（彩票效应，ICIR=0.348）。共 8 因子，IC 加权 + 行业中性化。"
        ),
        hypothesis=(
            "在 v10 基础上增加换手率加速（资金轮动信号）、52 周锚定反转（A 股行为偏差）"
            "和收益偏度（彩票需求溢价）三个维度，提升因子多样性，降低单因子集中风险。"
        ),
        params=[StrategyParam("n_stocks", "选股数量", 30, "int")],
        default_lookback_days=750,
        data_type="wide",
        factory=lambda params: _MultiFactorV11Adapter(n_stocks=params.get("n_stocks", 30)),
    ))

    # ── 8. 多因子选股策略 v12（v11 + 主力净买入代理，2026-04-14）──
    register(StrategyEntry(
        id="multi_factor_v12",
        name="多因子选股策略 v12（8 因子，含主力净买代理）",
        description=(
            "v11 七因子基础上增加 close_minus_open_volume（主力净买入代理）："
            "(close-open)/close * vol_ratio 的 rolling mean，ICIR=-0.565，"
            "简化回测增量贡献 +2.8% 年化。共 8 因子，IC 加权 + 行业中性化。"
        ),
        hypothesis=(
            "A 股日内 (close-open)*volume 是资金方向信号，持续放量阳线代表主力吸筹，"
            "持续放量阴线代表主力出货；rolling 20d 均值降低单日涨跌停干扰。"
            "与 turnover_accel 机制不同：后者看换手速度，前者看量能方向性。"
        ),
        params=[StrategyParam("n_stocks", "选股数量", 30, "int")],
        default_lookback_days=750,
        data_type="wide",
        factory=lambda params: _MultiFactorV12Adapter(n_stocks=params.get("n_stocks", 30)),
    ))

    # ── 10. 多因子选股策略 v14（v13 + RSI-14 超买超卖，2026-04-14）──
    register(StrategyEntry(
        id="multi_factor_v14",
        name="多因子选股策略 v14（9 因子，含 RSI 超卖信号）",
        description=(
            "v13 八因子基础上增加 rsi_factor（RSI-14 相对强弱指数）："
            "RSI-14 ICIR=-0.309，t=-2.273；与 v13 最大相关 0.572（shadow_lower）。"
            "方向=-1（高 RSI = 超买 = 看空；选超卖股票）。共 9 因子，IC 加权 + 行业中性化。"
        ),
        hypothesis=(
            "RSI 超卖信号（低 RSI）在 A 股散户主导市场中代表过度悲观，"
            "均值回归动能显著；14 日窗口捕捉中短期的超买超卖节奏，"
            "与 shadow_lower（单日形态）和 turnover_accel（资金速度）互补。"
        ),
        params=[StrategyParam("n_stocks", "选股数量", 30, "int")],
        default_lookback_days=750,
        data_type="wide",
        factory=lambda params: _MultiFactorV14Adapter(n_stocks=params.get("n_stocks", 30)),
    ))

    # ── 21. 多因子选股策略 v25（v16 + regime-gated 止损，2026-04-16）
    register(StrategyEntry(
        id="multi_factor_v25",
        name="多因子选股策略 v25（v16 + HS300-regime 门控止损）",
        description=(
            "v16 九因子 + regime_gated_half_position_stop 叠加层。"
            "用 HS300 < MA120 作为熊市判别，仅在熊市期启用半仓止损"
            "（threshold=-0.10），牛市/震荡市永远满仓。"
            "v10/v11 的教训：'一刀切' 止损在 2025 震荡市误杀信号；本版通过"
            "外生 regime 门控只在真实熊市保护，不干扰震荡市因子发挥。"
        ),
        hypothesis=(
            "v16 MDD -43% 集中在 2022/2024 熊市段；2023/2025 震荡市里 v16 因子"
            "本身表现良好，不需要止损。用 HS300 120日均线做 regime 判别："
            "熊市（HS300<MA120）开启止损→压低大回撤；牛市/震荡市关闭止损→"
            "保留因子 alpha。预期 sharpe≥0.80 同时 MDD<-30% 满足 admission gate。"
        ),
        params=[StrategyParam("n_stocks", "选股数量", 30, "int")],
        default_lookback_days=750,
        data_type="wide",
        factory=lambda params: _MultiFactorV25Adapter(n_stocks=params.get("n_stocks", 30)),
    ))

    # ── 20. 多因子选股策略 v24（v16 + 更宽持仓，2026-04-16）────────
    register(StrategyEntry(
        id="multi_factor_v24",
        name="多因子选股策略 v24（v16 九因子，60 只持仓）",
        description=(
            "v16 九因子完全相同，唯一区别：n_stocks 从 30 提升至 60。"
            "不改因子、不加止损，纯粹用更宽的持仓稀释个股尾部风险。"
            "预期：ann 略降（平均 score 下沉），但 MDD 显著改善。"
        ),
        hypothesis=(
            "v16 -43% MDD 一部分来自 30 只持仓的尾部集中度；组合内个股"
            "'踩雷' 占权重 3.3%。扩大到 60 只 → 单股权重降到 1.7%，"
            "idiosyncratic 回撤减半。若 MDD<-30% 达标且 sharpe 降幅<0.1，"
            "这是比止损更干净的解（无 regime 依赖、无状态机）。"
        ),
        params=[StrategyParam("n_stocks", "选股数量", 60, "int")],
        default_lookback_days=750,
        data_type="wide",
        factory=lambda params: _MultiFactorV24Adapter(n_stocks=params.get("n_stocks", 60)),
    ))

    # ── 19. 多因子选股策略 v23（v16 + 自适应回撤控制，2026-04-16）──
    register(StrategyEntry(
        id="multi_factor_v23",
        name="多因子选股策略 v23（v16 + 自适应半仓止损）",
        description=(
            "v16 九因子 + adaptive_half_position_stop 叠加层："
            "baseline_threshold=-0.10, vol_window=60, ref_vol=0.15。"
            "累计回撤触发阈值随 60 日组合实现波动率缩放；"
            "回撤突破阈值时仓位降为 50%，净值创新高后恢复满仓。"
            "目的：把 v16 的 -43% MDD 压到 -30% 以内，保持 Sharpe。"
        ),
        hypothesis=(
            "v16 的因子信号强但尾部风险大（MDD -43% 违反 admission gate）。"
            "A 股震荡行情里仓位管理的边际贡献 > 因子选择。用自适应半仓止损把"
            "MDD 限制在 -30% 以内的同时，高波动期的 '假回调' 不会误杀。"
            "IS 扫描：sharpe 0.74 → 0.84，MDD -43% → -26%，年化 22.9% → 18.2%。"
        ),
        params=[StrategyParam("n_stocks", "选股数量", 30, "int")],
        default_lookback_days=750,
        data_type="wide",
        factory=lambda params: _MultiFactorV23Adapter(n_stocks=params.get("n_stocks", 30)),
    ))

    # ── 18. 多因子选股策略 v22（正交性剪枝，2026-04-16）────────────
    register(StrategyEntry(
        id="multi_factor_v22",
        name="多因子选股策略 v22（5 独立因子，正交剪枝）",
        description=(
            "基于 v16 正交性分析（scripts/factor_orthogonality_analysis.py）："
            "Gram-Schmidt 残差化后，win_rate_60d / mom_6m_skip1m / high_52w / "
            "amihud_illiq 的残差 IC 95%CI 都跨零，边际贡献不显著。剔除这 4 个"
            "冗余因子，保留 5 个独立信号：low_vol_20d / team_coin / shadow_lower"
            " / price_vol_divergence / turnover_accel。IC 加权 + 行业中性化。"
        ),
        hypothesis=(
            "候选池 σ 窄（DSR≈Sharpe 排名）暗示 v16 九因子存在冗余，剪枝后"
            "单因子信号强度（avg raw ICIR）从 0.310 提升至 0.458，同时释放"
            "IC 加权权重给真实独立因子，预期 out-of-sample sharpe 更稳健。"
        ),
        params=[StrategyParam("n_stocks", "选股数量", 30, "int")],
        default_lookback_days=750,
        data_type="wide",
        factory=lambda params: _MultiFactorV22Adapter(n_stocks=params.get("n_stocks", 30)),
    ))

    # ── 17. 多因子选股策略 v21（v16 中用 w_reversal 替换 high_52w，2026-04-14）
    register(StrategyEntry(
        id="multi_factor_v21",
        name="多因子选股策略 v21（9 因子，W反转替换52w）",
        description=(
            "基于 v16，用 w_reversal（ICIR=+0.546）替换 high_52w（ICIR=-0.245）："
            "two为 v16 中最弱信号，w_reversal 信号更强且与其他 8 因子最大相关 0.569。"
            "共 9 因子，IC 加权 + 行业中性化。"
        ),
        hypothesis=(
            "high_52w 在 v16 中 ICIR 仅 -0.245，是最弱因子；"
            "w_reversal ICIR=0.546（高于 high_52w 一倍），且与 high_52w 相关仅 -0.336。"
            "用更强信号替换弱信号，保持 9 因子规模，预期提升 IC 加权组合的整体信噪比。"
        ),
        params=[StrategyParam("n_stocks", "选股数量", 30, "int")],
        default_lookback_days=750,
        data_type="wide",
        factory=lambda params: _MultiFactorV21Adapter(n_stocks=params.get("n_stocks", 30)),
    ))

    # ── 16. 多因子选股策略 v20（v16 + w_reversal，2026-04-14）──────────
    register(StrategyEntry(
        id="multi_factor_v20",
        name="多因子选股策略 v20（10 因子，含 W 型反转）",
        description=(
            "v16 九因子基础上增加 w_reversal（W 型价格反转因子）："
            "ICIR=+0.546，t=+4.013；与 v16 最大相关 0.569（pv_div），正交性良好。"
            "方向=+1（高值=真实 W 型结构=双底确认=看多）。共 10 因子。"
        ),
        hypothesis=(
            "w_reversal 检测 W 型双底反转结构：价格形成第一个低点后反弹，再次回落，"
            "若第二次低点高于第一次（不创新低）则为强 W 型，后续反弹概率高。"
            "A 股散户在第二个低点止跌后追涨，形成量价共振；用换手率加权。"
            "与 pv_div 最大相关 0.569，与其余 8 因子相关均 < 0.45。"
        ),
        params=[StrategyParam("n_stocks", "选股数量", 30, "int")],
        default_lookback_days=750,
        data_type="wide",
        factory=lambda params: _MultiFactorV20Adapter(n_stocks=params.get("n_stocks", 30)),
    ))

    # ── 15. 多因子选股策略 v19（v16 + vol_concentration，2026-04-14）──
    register(StrategyEntry(
        id="multi_factor_v19",
        name="多因子选股策略 v19（10 因子，含量能集中度）",
        description=(
            "v16 九因子基础上增加 volume_concentration（量能集中度）："
            "ICIR=-0.388，t=-2.854；与 v16 最大相关 0.365，正交性优异。"
            "方向=-1（成交量集中在单日=事件驱动散户拥入=均值回归看空）。共 10 因子。"
        ),
        hypothesis=(
            "volume_concentration = max(vol_20d) / sum(vol_20d)，高值代表近 20 日成交量集中在某一天，"
            "说明是消息刺激的一次性散户拥入，而非持续性机构积累；"
            "这类股票通常在事件后量能萎缩，价格均值回归。"
            "与所有 v16 因子最大相关 0.365（vs low_vol），与胜率/换手等相关近乎为零。"
        ),
        params=[StrategyParam("n_stocks", "选股数量", 30, "int")],
        default_lookback_days=750,
        data_type="wide",
        factory=lambda params: _MultiFactorV19Adapter(n_stocks=params.get("n_stocks", 30)),
    ))

    # ── 14. 多因子选股策略 v18（v16 + network_scc 关联度，2026-04-14）──
    register(StrategyEntry(
        id="multi_factor_v18",
        name="多因子选股策略 v18（10 因子，含网络关联度）",
        description=(
            "v16 九因子基础上增加 network_scc（股票相关性网络强连通分量）："
            "ICIR=-0.394，t=-2.554；与 v16 最大相关 0.218，正交性极佳。"
            "方向=-1（高网络中心度=强相关群体中心=看空；选孤立股票）。共 10 因子。"
        ),
        hypothesis=(
            "network_scc 衡量每只股票在滚动 20 日相关性网络中的强连通度；"
            "高中心度股票在机构集中持有的热门板块中，容易遭遇同步踩踏；"
            "低中心度（孤立股票）可能是被市场忽略的低估机会，与 alpha 来源更纯净。"
            "与所有 v16 因子的最大相关 0.218，捕捉完全独立的网络拓扑信息。"
        ),
        params=[StrategyParam("n_stocks", "选股数量", 30, "int")],
        default_lookback_days=750,
        data_type="wide",
        factory=lambda params: _MultiFactorV18Adapter(n_stocks=params.get("n_stocks", 30)),
    ))

    # ── 13. 多因子选股策略 v17（v16 + vol_asymmetry，2026-04-14）─────────
    register(StrategyEntry(
        id="multi_factor_v17",
        name="多因子选股策略 v17（10 因子，含波动率非对称）",
        description=(
            "v16 九因子基础上增加 vol_asymmetry（上涨/下跌波动率比）："
            "ICIR=+0.565，t=+4.149；与 v16 最大相关 0.402（low_vol_20d），正交性优异。"
            "方向=+1（高 vol_down/vol_up = 股票下跌时反应更激烈 = 超卖信号 = 看多）。共 10 因子。"
        ),
        hypothesis=(
            "vol_asymmetry = std(负收益日) / std(正收益日)，高比值代表股票在下跌时反应过度，"
            "在上涨时克制——典型的 A 股散户抛售导致的超卖格局。"
            "与所有 v16 因子独立（最大相关 0.402），捕捉纯粹的波动率不对称维度。"
            "ICIR=0.565 为本会话最强单因子信号（强于 turnover_accel 的 0.605）。"
        ),
        params=[StrategyParam("n_stocks", "选股数量", 30, "int")],
        default_lookback_days=750,
        data_type="wide",
        factory=lambda params: _MultiFactorV17Adapter(n_stocks=params.get("n_stocks", 30)),
    ))

    # ── 12. 多因子选股策略 v16（v13 + win_rate_60d 胜率因子，2026-04-14）──
    register(StrategyEntry(
        id="multi_factor_v16",
        name="多因子选股策略 v16（9 因子，含 60 日胜率反转）",
        description=(
            "v13 八因子基础上增加 win_rate_60d（60 日正收益天数占比）："
            "ICIR=-0.402，t=-2.953；与 v13 最大相关 0.376（high_52w），正交性优异。"
            "方向=-1（高胜率=持续上涨=超买=均值回归看空）。共 9 因子。"
        ),
        hypothesis=(
            "60 日胜率代表价格趋势的连贯性：高胜率意味着每日都在上涨，"
            "A 股散户集体追涨形成过热格局，后续均值回归压力显著。"
            "与 high_52w（年度级别）和 mom_6m_skip1m（月度级别）互补，"
            "捕捉日频层面的超买信号。最大共线性 0.376，高度正交。"
        ),
        params=[StrategyParam("n_stocks", "选股数量", 30, "int")],
        default_lookback_days=750,
        data_type="wide",
        factory=lambda params: _MultiFactorV16Adapter(n_stocks=params.get("n_stocks", 30)),
    ))

    # ── 11. 多因子选股策略 v15（用 MA60 替换 high_52w，2026-04-14）──
    register(StrategyEntry(
        id="multi_factor_v15",
        name="多因子选股策略 v15（8 因子，MA60 替换 high_52w）",
        description=(
            "基于 v13，用 price_dist_ma60（ICIR=-0.510，t=-3.750）替换 high_52w（ICIR=-0.245）："
            "(price-MA60)/MA60 捕捉中期均值回归；与 v13 其他因子最大相关 0.454，正交充分。"
            "共 8 因子，IC 加权 + 行业中性化。"
        ),
        hypothesis=(
            "price_dist_ma60 比 high_52w 信号更强（ICIR 0.510 vs 0.245），且两者高度相关（r=0.683），"
            "用强信号替换弱信号可提升因子组合的信息比率。60 日 MA 均线偏离代表中期趋势过度，"
            "A 股散户在均线上方追高后面临更强的均值回归压力。"
        ),
        params=[StrategyParam("n_stocks", "选股数量", 30, "int")],
        default_lookback_days=750,
        data_type="wide",
        factory=lambda params: _MultiFactorV15Adapter(n_stocks=params.get("n_stocks", 30)),
    ))

    # ── 9. 多因子选股策略 v13（v11 + 中期反转，2026-04-14）──────────
    register(StrategyEntry(
        id="multi_factor_v13",
        name="多因子选股策略 v13（8 因子，含中期反转）",
        description=(
            "v11 七因子基础上增加 momentum_6m_skip1m（6 个月跳过最近 1 月中期反转）："
            "price.shift(21)/price.shift(126)-1，ICIR=-0.326，t=-2.349。"
            "与 v11 各因子最大相关 0.441，正交性充分。共 8 因子，IC 加权 + 行业中性化。"
        ),
        hypothesis=(
            "A 股中期动量（6M skip 1M）呈现反转效应（非美股动量延续），因为散户在过去 6 月"
            "强势股上追高，产生均值回归压力；与 high_52w 相关仅 0.311，捕捉不同时间维度的超买。"
        ),
        params=[StrategyParam("n_stocks", "选股数量", 30, "int")],
        default_lookback_days=750,
        data_type="wide",
        factory=lambda params: _MultiFactorV13Adapter(n_stocks=params.get("n_stocks", 30)),
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
        # 小组合（n_stocks <= 50）对合成质量更敏感，默认开启 IC 加权
        self.ic_weighting: bool = n_stocks <= 50

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
            ic_weighting=self.ic_weighting,
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


class _MultiFactorV2Adapter:
    """
    多因子策略 v2 适配器 — 含基本面因子。

    在 v1（动量/低波/反转）基础上尝试加入：
      - EP（盈利收益率，来自 pe_ttm）
      - BP（账面市值比，来自 pb）
      - ROE（质量，来自 pb/pe）

    如果财务宽表不可用，自动降级到 v1 因子集。
    """

    def __init__(self, n_stocks: int = 30):
        self.n_stocks = n_stocks
        self.results = None

    def run(self, price_wide: pd.DataFrame) -> pd.DataFrame:
        """
        从价格宽表计算 v1 价格因子，并尝试加载基本面因子（EP/BP/ROE）。
        基本面数据不可用时静默降级为纯价格因子，不中断回测。

        参数:
            price_wide: 价格宽表 (date × symbol)

        返回:
            回测结果 DataFrame
        """
        from utils.alpha_factors import (
            enhanced_momentum, low_vol_20d, reversal_1m,
            ep_factor, bp_factor, roe_factor,
        )
        from strategies.multi_factor import MultiFactorStrategy
        from strategies.base import StrategyConfig

        factors = {}

        # v1 因子（价格）— 始终可用
        momentum = enhanced_momentum(price_wide, 60)
        factors["enhanced_mom"] = (momentum, 1)
        volatility = low_vol_20d(price_wide)
        factors["low_vol"] = (volatility, 1)   # low_vol_20d 内部已取负号
        reversal = reversal_1m(price_wide)
        factors["reversal_1m"] = (reversal, 1)  # reversal_1m 内部已取负号

        # v2 因子（基本面）— 尝试加载，失败时降级
        try:
            from utils.fundamental_loader import build_pe_pb_wide
            symbols = list(price_wide.columns)
            start = str(price_wide.index[0].date())
            end = str(price_wide.index[-1].date())

            wide = build_pe_pb_wide(symbols, start, end, fields=["pe_ttm", "pb"])
            pe_wide = wide.get("pe_ttm")
            pb_wide = wide.get("pb")

            if pe_wide is not None and not pe_wide.empty:
                factors["ep"] = (ep_factor(pe_wide).reindex_like(price_wide), 1)

            if pb_wide is not None and not pb_wide.empty:
                factors["bp"] = (bp_factor(pb_wide).reindex_like(price_wide), 1)

            if pe_wide is not None and pb_wide is not None:
                factors["roe"] = (roe_factor(pe_wide, pb_wide).reindex_like(price_wide), 1)

        except Exception as e:
            _log.warning("基本面因子加载失败，使用纯价格因子: %s", e)

        # 加载行业分类（可选）
        industry_map = _load_industry_map(list(price_wide.columns))

        config = StrategyConfig(name="multi_factor_v2")
        strategy = MultiFactorStrategy(
            config=config,
            factors=factors,
            n_stocks=self.n_stocks,
            ic_weighting=True,
            industry_map=industry_map,
            neutralize=bool(industry_map),
        )
        result = strategy.run(price_wide)
        self.results = getattr(strategy, 'results', None)
        return result

    def get_returns(self):
        """获取日收益率"""
        if self.results is None:
            raise RuntimeError("请先调用 run()")
        return self.results["returns"]


class _MultiFactorV9Adapter:
    """
    多因子策略 v9 适配器 — 新因子集，提升因子正交性。

    核心逻辑：
      - 保留 v7 三个 proven 因子：low_vol_20d / team_coin / bp
      - 新增三个正交维度：
          idiosyncratic_vol (特质波动率异象，方向=-1，函数内部已取负)
          industry_momentum (行业动量轮动，需要行业分类)
          insider_buying_proxy (机构积累代理，需要 high/low/volume)
      - 全部启用 IC 加权合成 + 行业中性化
      - 任一依赖数据不可用时，对应因子跳过，不中断回测
    """

    def __init__(self, n_stocks: int = 30):
        self.n_stocks = n_stocks
        self.results = None

    def run(self, price_wide: pd.DataFrame) -> pd.DataFrame:
        """
        计算 v9 因子集并运行多因子策略。

        参数:
            price_wide: 收盘价宽表 (date × symbol)

        返回:
            回测结果 DataFrame
        """
        from utils.alpha_factors import (
            low_vol_20d,
            team_coin,
            bp_factor,
            idiosyncratic_volatility,
            industry_momentum,
            insider_buying_proxy,
        )
        from strategies.multi_factor import MultiFactorStrategy
        from strategies.base import StrategyConfig

        factors = {}
        symbols = list(price_wide.columns)
        start = str(price_wide.index[0].date())
        end = str(price_wide.index[-1].date())

        # ── 核心因子（v7 proven，始终可用）─────────────────────
        try:
            factors["low_vol_20d"] = (low_vol_20d(price_wide), 1)  # 内部已处理方向
        except Exception as e:
            _log.warning("low_vol_20d 计算失败，跳过: %s", e)

        try:
            factors["team_coin"] = (team_coin(price_wide), 1)
        except Exception as e:
            _log.warning("team_coin 计算失败，跳过: %s", e)

        # bp 因子需要 PB 财务数据
        try:
            from utils.fundamental_loader import build_pe_pb_wide
            wide = build_pe_pb_wide(symbols, start, end, fields=["pb"])
            pb_wide = wide.get("pb")
            if pb_wide is not None and not pb_wide.empty:
                factors["bp"] = (bp_factor(pb_wide).reindex_like(price_wide), 1)
        except Exception as e:
            _log.warning("bp 因子（PB数据）不可用，跳过: %s", e)

        # ── 新增因子 ─────────────────────────────────────────────

        # idiosyncratic_vol：特质波动率，函数内部已取负（方向=-1 → 正向信号）
        try:
            factors["idiosyncratic_vol"] = (idiosyncratic_volatility(price_wide), 1)
        except Exception as e:
            _log.warning("idiosyncratic_vol 计算失败，跳过: %s", e)

        # industry_momentum：需要行业分类字典
        industry_map = _load_industry_map(symbols)
        if industry_map is not None:
            try:
                ind_mom = industry_momentum(price_wide, industry_map)
                factors["industry_momentum"] = (ind_mom, 1)
            except Exception as e:
                _log.warning("industry_momentum 计算失败，跳过: %s", e)
        else:
            _log.warning("行业分类不可用，industry_momentum 跳过")

        # insider_buying_proxy：需要 high / low / volume 宽表
        try:
            from utils.local_data_loader import load_price_wide as _lpw
            high_wide = _lpw(symbols, start, end, field="high")
            low_wide = _lpw(symbols, start, end, field="low")
            vol_wide = _lpw(symbols, start, end, field="volume")
            if not high_wide.empty and not low_wide.empty and not vol_wide.empty:
                ibp = insider_buying_proxy(price_wide, high_wide, low_wide, vol_wide)
                factors["insider_buying_proxy"] = (ibp, 1)
        except Exception as e:
            _log.warning("insider_buying_proxy 计算失败（high/low/volume 不可用），跳过: %s", e)

        # ── 行业分类（用于中性化）────────────────────────────────
        # industry_map 已在上方加载，直接复用
        config = StrategyConfig(name="multi_factor_v9")
        strategy = MultiFactorStrategy(
            config=config,
            factors=factors,
            n_stocks=self.n_stocks,
            ic_weighting=True,
            industry_map=industry_map,
            neutralize=bool(industry_map),
        )
        result = strategy.run(price_wide)
        self.results = getattr(strategy, "results", None)
        return result

    def get_returns(self):
        """获取日收益率"""
        if self.results is None:
            raise RuntimeError("请先调用 run()")
        return self.results["returns"]


class _MultiFactorV10Adapter:
    """
    多因子策略 v10 适配器 — 因子审计精选，5 个互不高度相关的有效因子。

    因子组合（2022-2025 审计结果）：
      - low_vol_20d        ICIR=+0.72，纯价格
      - team_coin          ICIR=+0.63，纯价格
      - shadow_lower       ICIR=-0.49，方向取反（需要 low 宽表）
      - amihud_illiq       ICIR=+0.38（需要 volume 宽表）
      - price_vol_divergence ICIR=+0.38（需要 volume 宽表）
    """

    def __init__(self, n_stocks: int = 30):
        self.n_stocks = n_stocks
        self.results = None

    def run(self, price_wide: pd.DataFrame) -> pd.DataFrame:
        """
        计算 v10 因子集并运行多因子策略。

        参数:
            price_wide: 收盘价宽表 (date × symbol)

        返回:
            回测结果 DataFrame
        """
        from utils.alpha_factors import (
            low_vol_20d,
            team_coin,
            shadow_lower,
            amihud_illiquidity,
            price_volume_divergence,
        )
        from strategies.multi_factor import MultiFactorStrategy
        from strategies.base import StrategyConfig

        factors = {}
        symbols = list(price_wide.columns)
        start = str(price_wide.index[0].date())
        end = str(price_wide.index[-1].date())

        # ── 纯价格因子（始终可用）────────────────────────────────
        try:
            factors["low_vol_20d"] = (low_vol_20d(price_wide), 1)
        except Exception as e:
            _log.warning("low_vol_20d 计算失败，跳过: %s", e)

        try:
            factors["team_coin"] = (team_coin(price_wide), 1)
        except Exception as e:
            _log.warning("team_coin 计算失败，跳过: %s", e)

        # ── 需要 low 宽表 ─────────────────────────────────────────
        try:
            from utils.local_data_loader import load_price_wide as _lpw
            low_wide = _lpw(symbols, start, end, field="low")
            if not low_wide.empty:
                sl = shadow_lower(price_wide, low_wide.reindex_like(price_wide))
                factors["shadow_lower"] = (sl, -1)  # 负向因子：IC=-0.056
            else:
                _log.warning("low 宽表为空，shadow_lower 跳过")
        except Exception as e:
            _log.warning("shadow_lower 计算失败（low 数据不可用），跳过: %s", e)

        # ── 需要 volume 宽表 ──────────────────────────────────────
        vol_wide = None
        try:
            from utils.local_data_loader import load_price_wide as _lpw
            vol_wide = _lpw(symbols, start, end, field="volume")
            if vol_wide.empty:
                vol_wide = None
                _log.warning("volume 宽表为空，amihud_illiq / price_vol_divergence 跳过")
        except Exception as e:
            _log.warning("volume 数据加载失败，跳过: %s", e)

        if vol_wide is not None:
            try:
                factors["amihud_illiq"] = (
                    amihud_illiquidity(price_wide, vol_wide.reindex_like(price_wide)), 1
                )
            except Exception as e:
                _log.warning("amihud_illiq 计算失败，跳过: %s", e)

            try:
                factors["price_vol_divergence"] = (
                    price_volume_divergence(price_wide, vol_wide.reindex_like(price_wide)), 1
                )
            except Exception as e:
                _log.warning("price_vol_divergence 计算失败，跳过: %s", e)

        # ── 行业分类（中性化）────────────────────────────────────
        industry_map = _load_industry_map(symbols)

        config = StrategyConfig(name="multi_factor_v10")
        strategy = MultiFactorStrategy(
            config=config,
            factors=factors,
            n_stocks=self.n_stocks,
            ic_weighting=True,
            industry_map=industry_map,
            neutralize=bool(industry_map),
        )
        result = strategy.run(price_wide)
        self.results = getattr(strategy, "results", None)
        return result

    def get_returns(self):
        """获取日收益率"""
        if self.results is None:
            raise RuntimeError("请先调用 run()")
        return self.results["returns"]


class _MultiFactorV11Adapter:
    """
    多因子策略 v11 适配器 — v10 + 2 个正交新因子（2026-04-14 因子挖掘）。

    v10 基础（5 因子）：
      low_vol_20d / team_coin / shadow_lower / amihud_illiq / price_vol_divergence

    新增 2 个正交因子（回测验证 > IC 测试）：
      high_52w_ratio  ICIR=-0.324，vs_low_vol=0.139（A 股 52 周反转；独立回测 18.7%/0.61 Sharpe）
      turnover_accel  ICIR=-0.605，vs_low_vol=0.078（换手率加速反转；与 high_52w 协同效应确认）

    注：skewness_20d 在 IC 测试通过（0.348）但回测中拖累表现（20日窗口估计噪声大），已剔除。
    """

    def __init__(self, n_stocks: int = 30):
        self.n_stocks = n_stocks
        self.results = None

    def run(self, price_wide: pd.DataFrame) -> pd.DataFrame:
        """
        计算 v11 因子集并运行多因子策略。

        参数:
            price_wide: 收盘价宽表 (date × symbol)
        返回:
            回测结果 DataFrame
        """
        from utils.alpha_factors import (
            low_vol_20d, team_coin, shadow_lower,
            amihud_illiquidity, price_volume_divergence,
            turnover_acceleration, high_52w_ratio,
        )
        from strategies.multi_factor import MultiFactorStrategy
        from strategies.base import StrategyConfig

        factors = {}
        symbols = list(price_wide.columns)
        start = str(price_wide.index[0].date())
        end   = str(price_wide.index[-1].date())

        # ── v10 核心因子 ──────────────────────────────────────
        for name, fn, direction in [
            ("low_vol_20d", lambda: low_vol_20d(price_wide), 1),
            ("team_coin",   lambda: team_coin(price_wide),   1),
        ]:
            try:
                factors[name] = (fn(), direction)
            except Exception as e:
                _log.warning("%s 计算失败，跳过: %s", name, e)

        # shadow_lower 需要 low 宽表（方向=-1）
        try:
            from utils.local_data_loader import load_price_wide as _lpw
            low_wide = _lpw(symbols, start, end, field="low")
            if not low_wide.empty:
                factors["shadow_lower"] = (shadow_lower(price_wide, low_wide.reindex_like(price_wide)), -1)
        except Exception as e:
            _log.warning("shadow_lower 跳过: %s", e)

        # amihud_illiq + price_vol_divergence 需要 volume
        vol_wide = None
        try:
            from utils.local_data_loader import load_price_wide as _lpw
            vol_wide = _lpw(symbols, start, end, field="volume")
            if vol_wide.empty:
                vol_wide = None
        except Exception as e:
            _log.warning("volume 加载失败: %s", e)

        if vol_wide is not None:
            va = vol_wide.reindex_like(price_wide)
            try:
                factors["amihud_illiq"] = (amihud_illiquidity(price_wide, va), 1)
            except Exception as e:
                _log.warning("amihud_illiq 跳过: %s", e)
            try:
                factors["price_vol_divergence"] = (price_volume_divergence(price_wide, va), 1)
            except Exception as e:
                _log.warning("price_vol_divergence 跳过: %s", e)

        # ── v11 新增因子 ──────────────────────────────────────

        # turnover_accel: 需要换手率宽表（方向=-1）
        try:
            from utils.local_data_loader import load_factor_wide as _lfw
            tv = _lfw(symbols, "turnover", start, end)
            if not tv.empty:
                factors["turnover_accel"] = (
                    turnover_acceleration(tv.reindex_like(price_wide)), -1
                )
        except Exception as e:
            _log.warning("turnover_accel 跳过: %s", e)

        # high_52w_ratio: 纯价格（方向=-1，A 股 52 周反转）
        try:
            factors["high_52w"] = (high_52w_ratio(price_wide), -1)
        except Exception as e:
            _log.warning("high_52w 跳过: %s", e)

        # ── 行业中性化 + 运行 ────────────────────────────────
        industry_map = _load_industry_map(symbols)
        config = StrategyConfig(name="multi_factor_v11")
        strategy = MultiFactorStrategy(
            config=config,
            factors=factors,
            n_stocks=self.n_stocks,
            ic_weighting=True,
            industry_map=industry_map,
            neutralize=bool(industry_map),
        )
        result = strategy.run(price_wide)
        self.results = getattr(strategy, "results", None)
        return result

    def get_returns(self):
        if self.results is None:
            raise RuntimeError("请先调用 run()")
        return self.results["returns"]


class _MultiFactorV12Adapter:
    """
    多因子策略 v12 适配器 — v11 + close_minus_open_volume（主力净买入代理）。

    新增因子：
      close_minus_open_volume  ICIR=-0.565，vs_low_vol=-0.417
        = (close-open)/close * vol_ratio，rolling 20d mean
        方向=-1（持续负值=出货压力=看空，取反后：低值=出货=避开）

    与 turnover_accel 区别：
      - turnover_accel：换手率加速（速度）
      - close_minus_open_volume：量能方向性（方向）
    """

    def __init__(self, n_stocks: int = 30):
        self.n_stocks = n_stocks
        self.results = None

    def run(self, price_wide: pd.DataFrame) -> pd.DataFrame:
        from utils.alpha_factors import (
            low_vol_20d, team_coin, shadow_lower,
            amihud_illiquidity, price_volume_divergence,
            turnover_acceleration, high_52w_ratio,
            close_minus_open_volume,
        )
        from strategies.multi_factor import MultiFactorStrategy
        from strategies.base import StrategyConfig

        factors = {}
        symbols = list(price_wide.columns)
        start = str(price_wide.index[0].date())
        end   = str(price_wide.index[-1].date())

        # ── v11 因子（全部保留）───────────────────────────────
        for name, fn, d in [
            ("low_vol_20d", lambda: low_vol_20d(price_wide), 1),
            ("team_coin",   lambda: team_coin(price_wide),   1),
            ("high_52w",    lambda: high_52w_ratio(price_wide), -1),
        ]:
            try: factors[name] = (fn(), d)
            except Exception as e: _log.warning("%s 跳过: %s", name, e)

        try:
            from utils.local_data_loader import load_price_wide as _lpw
            low_wide = _lpw(symbols, start, end, field="low")
            if not low_wide.empty:
                factors["shadow_lower"] = (shadow_lower(price_wide, low_wide.reindex_like(price_wide)), -1)
        except Exception as e: _log.warning("shadow_lower 跳过: %s", e)

        vol_wide = None
        try:
            from utils.local_data_loader import load_price_wide as _lpw
            vol_wide = _lpw(symbols, start, end, field="volume")
            if vol_wide.empty: vol_wide = None
        except Exception as e: _log.warning("volume 加载失败: %s", e)

        if vol_wide is not None:
            va = vol_wide.reindex_like(price_wide)
            try: factors["amihud_illiq"]       = (amihud_illiquidity(price_wide, va), 1)
            except Exception as e: _log.warning("amihud_illiq 跳过: %s", e)
            try: factors["price_vol_divergence"] = (price_volume_divergence(price_wide, va), 1)
            except Exception as e: _log.warning("price_vol_div 跳过: %s", e)

        try:
            from utils.local_data_loader import load_factor_wide as _lfw
            tv = _lfw(symbols, "turnover", start, end)
            if not tv.empty:
                factors["turnover_accel"] = (turnover_acceleration(tv.reindex_like(price_wide)), -1)
        except Exception as e: _log.warning("turnover_accel 跳过: %s", e)

        # ── v12 新增因子 ──────────────────────────────────────
        try:
            from utils.local_data_loader import load_price_wide as _lpw
            open_wide = _lpw(symbols, start, end, field="open")
            if not open_wide.empty and vol_wide is not None:
                factors["close_minus_open_vol"] = (
                    close_minus_open_volume(
                        price_wide, open_wide.reindex_like(price_wide),
                        vol_wide.reindex_like(price_wide)
                    ), -1
                )
        except Exception as e: _log.warning("close_minus_open_vol 跳过: %s", e)

        industry_map = _load_industry_map(symbols)
        config = StrategyConfig(name="multi_factor_v12")
        strategy = MultiFactorStrategy(
            config=config, factors=factors, n_stocks=self.n_stocks,
            ic_weighting=True, industry_map=industry_map, neutralize=bool(industry_map),
        )
        result = strategy.run(price_wide)
        self.results = getattr(strategy, "results", None)
        return result

    def get_returns(self):
        if self.results is None:
            raise RuntimeError("请先调用 run()")
        return self.results["returns"]


class _MultiFactorV23Adapter:
    """
    多因子策略 v23 — v16 + adaptive_half_position_stop 叠加层（2026-04-16）。

    纯叠加层，不改动 v16 的因子与信号逻辑：先用 V16Adapter 跑出
    portfolio_return，再施加 adaptive_half_position_stop，生成新的
    日收益序列和 cumulative_return。

    参数来自 scripts/sweep_v16_dd_overlay.py 的 IS 扫描（2022-01 ~ 2025-12）
    前 2 名：baseline_threshold=-0.10, vol_window=60, ref_vol=0.15。

    IS 表现（警告：参数来自 14 组 IS 扫描，有 selection bias）：
      sharpe 0.740 → 0.837  ann 22.87% → 18.21%  MDD -43.06% → -26.42%

    产出的 DataFrame 列：date, portfolio_return, cumulative_return
    （与 v16 同 schema，便于下游消费）。
    """

    # 参数固定，避免 DSR 漏洞——下次调参要用 WF 学，别 IS 挑最好
    BASELINE_THRESHOLD = -0.10
    VOL_WINDOW = 60
    REF_VOL = 0.15
    MIN_SCALE = 0.5
    MAX_SCALE = 2.0

    def __init__(self, n_stocks: int = 30):
        self.n_stocks = n_stocks
        self.results = None
        self._v16 = _MultiFactorV16Adapter(n_stocks=n_stocks)

    def run(self, price_wide: pd.DataFrame) -> pd.DataFrame:
        from utils.stop_loss import adaptive_half_position_stop

        base_result = self._v16.run(price_wide)
        if "portfolio_return" in base_result.columns:
            base_ret = base_result["portfolio_return"].astype(float)
        elif "returns" in base_result.columns:
            base_ret = base_result["returns"].astype(float)
        else:
            raise RuntimeError(
                f"V16 未产出 portfolio_return / returns 列: {base_result.columns.tolist()}"
            )

        overlay = adaptive_half_position_stop(
            base_ret,
            baseline_threshold=self.BASELINE_THRESHOLD,
            vol_window=self.VOL_WINDOW,
            ref_vol=self.REF_VOL,
            min_scale=self.MIN_SCALE,
            max_scale=self.MAX_SCALE,
        )

        out = pd.DataFrame({
            "portfolio_return": overlay.values,
            "cumulative_return": (1 + overlay).cumprod().values - 1,
        }, index=overlay.index)
        out.index.name = "date"

        self.results = out
        return out

    def get_returns(self):
        if self.results is None:
            raise RuntimeError("请先调用 run()")
        return self.results["portfolio_return"]


class _MultiFactorV25Adapter:
    """
    多因子策略 v25 — v16 + regime_gated_half_position_stop（2026-04-16）。

    思路（Route B from journal/v10_icir_stoploss_eval_20260416.md）：
    只在 HS300 跌破 120 日均线（= 长期熊市）时开启半仓止损，
    牛市/震荡市永远满仓。避开 v10/v11 的教训（一刀切止损在 2025 震荡市误杀）。

    参数固定，不调：threshold=-0.10（历史验证的直觉阈值），ma_window=120。
    调参要走 WF，不在 IS 挑最好。

    产出列：portfolio_return, cumulative_return（与 v16 同 schema）。
    """

    THRESHOLD = -0.10
    MA_WINDOW = 120
    HS300_SYMBOL = "399300"  # 沪深300 指数本地存储代码

    def __init__(self, n_stocks: int = 30):
        self.n_stocks = n_stocks
        self.results = None
        self._v16 = _MultiFactorV16Adapter(n_stocks=n_stocks)

    def run(self, price_wide: pd.DataFrame) -> pd.DataFrame:
        from utils.stop_loss import (
            regime_gated_half_position_stop,
            hs300_bear_regime,
        )
        from utils.local_data_loader import load_price_wide as _lpw

        base_result = self._v16.run(price_wide)
        if "portfolio_return" in base_result.columns:
            base_ret = base_result["portfolio_return"].astype(float)
        elif "returns" in base_result.columns:
            base_ret = base_result["returns"].astype(float)
        else:
            raise RuntimeError(
                f"V16 未产出 portfolio_return / returns 列: {base_result.columns.tolist()}"
            )

        # 加载 HS300 并计算 regime（shift=1 已在函数内做）
        start = str(price_wide.index[0].date())
        end = str(price_wide.index[-1].date())
        hs300_wide = _lpw([self.HS300_SYMBOL], start, end, field="close")
        if hs300_wide.empty or self.HS300_SYMBOL not in hs300_wide.columns:
            raise RuntimeError(
                f"无法加载 HS300 ({self.HS300_SYMBOL}) 作为 regime 指标"
            )
        hs300_close = hs300_wide[self.HS300_SYMBOL].dropna()
        regime_bear = hs300_bear_regime(
            hs300_close, ma_window=self.MA_WINDOW, shift_days=1,
        )
        # 对齐到策略日期
        regime_bear = regime_bear.reindex(base_ret.index).fillna(False).astype(bool)

        bear_days = int(regime_bear.sum())
        _log.info(
            "v25 regime 统计: 总 %d 日，熊市 %d 日 (%.1f%%)",
            len(regime_bear), bear_days, 100.0 * bear_days / max(len(regime_bear), 1),
        )

        overlay = regime_gated_half_position_stop(
            base_ret, regime_bear, threshold=self.THRESHOLD,
        )

        out = pd.DataFrame({
            "portfolio_return": overlay.values,
            "cumulative_return": (1 + overlay).cumprod().values - 1,
        }, index=overlay.index)
        out.index.name = "date"

        self.results = out
        return out

    def get_returns(self):
        if self.results is None:
            raise RuntimeError("请先调用 run()")
        return self.results["portfolio_return"]


class _MultiFactorV24Adapter:
    """
    多因子策略 v24 — v16 九因子，n_stocks=60（2026-04-16）。

    完全继承 v16 的因子/权重逻辑，仅修改持仓数量参数。
    思路：用更宽的持仓稀释个股尾部风险，不依赖 regime 判别或止损状态机。

    产出 schema 与 v16 一致（返回 strategy.run() 直接结果）。
    """

    def __init__(self, n_stocks: int = 60):
        self.n_stocks = n_stocks
        self._v16 = _MultiFactorV16Adapter(n_stocks=n_stocks)
        self.results = None

    def run(self, price_wide: pd.DataFrame) -> pd.DataFrame:
        result = self._v16.run(price_wide)
        self.results = self._v16.results
        return result

    def get_returns(self):
        if self.results is None:
            raise RuntimeError("请先调用 run()")
        return self.results["returns"]


class _MultiFactorV22Adapter:
    """
    多因子策略 v22 — v16 正交性剪枝（2026-04-16）。

    保留 5 个独立因子（Gram-Schmidt 残差 IC 95%CI 均不跨零）：
      low_vol_20d (+1), team_coin (+1), shadow_lower (-1),
      price_vol_divergence (+1), turnover_accel (-1)

    剔除 4 个冗余因子（残差 CI 跨零）：
      win_rate_60d, mom_6m_skip1m, high_52w, amihud_illiq

    分析文档：journal/factor_orthogonality_v16_20260416.md
    """

    def __init__(self, n_stocks: int = 30):
        self.n_stocks = n_stocks
        self.results = None

    def run(self, price_wide: pd.DataFrame) -> pd.DataFrame:
        from utils.alpha_factors import (
            low_vol_20d, team_coin, shadow_lower,
            price_volume_divergence, turnover_acceleration,
        )
        from strategies.multi_factor import MultiFactorStrategy
        from strategies.base import StrategyConfig

        factors = {}
        symbols = list(price_wide.columns)
        start = str(price_wide.index[0].date())
        end   = str(price_wide.index[-1].date())

        # ── 纯价格因子 ────────────────────────────────────────
        for name, fn, d in [
            ("low_vol_20d", lambda: low_vol_20d(price_wide), 1),
            ("team_coin",   lambda: team_coin(price_wide),   1),
        ]:
            try: factors[name] = (fn(), d)
            except Exception as e: _log.warning("%s 跳过: %s", name, e)

        # ── shadow_lower 需要 low ────────────────────────────
        try:
            from utils.local_data_loader import load_price_wide as _lpw
            low_wide = _lpw(symbols, start, end, field="low")
            if not low_wide.empty:
                factors["shadow_lower"] = (shadow_lower(price_wide, low_wide.reindex_like(price_wide)), -1)
        except Exception as e: _log.warning("shadow_lower 跳过: %s", e)

        # ── price_vol_divergence 需要 volume ─────────────────
        vol_wide = None
        try:
            from utils.local_data_loader import load_price_wide as _lpw
            vol_wide = _lpw(symbols, start, end, field="volume")
            if vol_wide.empty: vol_wide = None
        except Exception as e: _log.warning("volume 加载失败: %s", e)

        if vol_wide is not None:
            va_vol = vol_wide.reindex_like(price_wide)
            try: factors["price_vol_divergence"] = (price_volume_divergence(price_wide, va_vol), 1)
            except Exception as e: _log.warning("price_vol_div 跳过: %s", e)

        # ── turnover_accel 需要 turnover ─────────────────────
        try:
            from utils.local_data_loader import load_factor_wide as _lfw
            tv = _lfw(symbols, "turnover", start, end)
            if not tv.empty:
                factors["turnover_accel"] = (turnover_acceleration(tv.reindex_like(price_wide)), -1)
        except Exception as e: _log.warning("turnover_accel 跳过: %s", e)

        industry_map = _load_industry_map(symbols)
        config = StrategyConfig(name="multi_factor_v22")
        strategy = MultiFactorStrategy(
            config=config, factors=factors, n_stocks=self.n_stocks,
            ic_weighting=True, industry_map=industry_map, neutralize=bool(industry_map),
        )
        result = strategy.run(price_wide)
        self.results = getattr(strategy, "results", None)
        return result

    def get_returns(self):
        if self.results is None:
            raise RuntimeError("请先调用 run()")
        return self.results["returns"]


class _MultiFactorV21Adapter:
    """
    多因子策略 v21 — v16 中用 w_reversal 替换 high_52w（2026-04-14）。

    9 因子（替换后）：
      low_vol_20d / team_coin / shadow_lower / amihud_illiq /
      price_vol_divergence / w_reversal / turnover_accel /
      mom_6m_skip1m / win_rate_60d

    替换理由：
      high_52w: ICIR=-0.245（v16 中最弱）
      w_reversal: ICIR=+0.546（强信号），与 high_52w 相关 -0.336
    """

    def __init__(self, n_stocks: int = 30):
        self.n_stocks = n_stocks
        self.results = None

    def run(self, price_wide: pd.DataFrame) -> pd.DataFrame:
        from utils.alpha_factors import (
            low_vol_20d, team_coin, shadow_lower,
            amihud_illiquidity, price_volume_divergence,
            turnover_acceleration, momentum_6m_skip1m,
            win_rate_60d, w_reversal,
        )
        from strategies.multi_factor import MultiFactorStrategy
        from strategies.base import StrategyConfig

        factors = {}
        symbols = list(price_wide.columns)
        start = str(price_wide.index[0].date())
        end   = str(price_wide.index[-1].date())

        # ── 纯价格因子 ────────────────────────────────────────
        for name, fn, d in [
            ("low_vol_20d",   lambda: low_vol_20d(price_wide),        1),
            ("team_coin",     lambda: team_coin(price_wide),           1),
            ("mom_6m_skip1m", lambda: momentum_6m_skip1m(price_wide), -1),
            ("win_rate_60d",  lambda: win_rate_60d(price_wide),       -1),
        ]:
            try: factors[name] = (fn(), d)
            except Exception as e: _log.warning("%s 跳过: %s", name, e)

        try:
            from utils.local_data_loader import load_price_wide as _lpw
            low_wide = _lpw(symbols, start, end, field="low")
            if not low_wide.empty:
                factors["shadow_lower"] = (shadow_lower(price_wide, low_wide.reindex_like(price_wide)), -1)
        except Exception as e: _log.warning("shadow_lower 跳过: %s", e)

        vol_wide = None
        try:
            from utils.local_data_loader import load_price_wide as _lpw
            vol_wide = _lpw(symbols, start, end, field="volume")
            if vol_wide.empty: vol_wide = None
        except Exception as e: _log.warning("volume 加载失败: %s", e)

        if vol_wide is not None:
            va_vol = vol_wide.reindex_like(price_wide)
            try: factors["amihud_illiq"]        = (amihud_illiquidity(price_wide, va_vol), 1)
            except Exception as e: _log.warning("amihud_illiq 跳过: %s", e)
            try: factors["price_vol_divergence"] = (price_volume_divergence(price_wide, va_vol), 1)
            except Exception as e: _log.warning("price_vol_div 跳过: %s", e)

        tv_wide = None
        try:
            from utils.local_data_loader import load_factor_wide as _lfw
            tv_data = _lfw(symbols, "turnover", start, end)
            if not tv_data.empty:
                tv_wide = tv_data.reindex_like(price_wide)
                factors["turnover_accel"] = (turnover_acceleration(tv_wide), -1)
        except Exception as e: _log.warning("turnover_accel 跳过: %s", e)

        # w_reversal: 替换 high_52w
        try:
            factors["w_reversal"] = (w_reversal(price_wide, tv_wide), 1)
        except Exception as e: _log.warning("w_reversal 跳过: %s", e)

        industry_map = _load_industry_map(symbols)
        config = StrategyConfig(name="multi_factor_v21")
        strategy = MultiFactorStrategy(
            config=config, factors=factors, n_stocks=self.n_stocks,
            ic_weighting=True, industry_map=industry_map, neutralize=bool(industry_map),
        )
        result = strategy.run(price_wide)
        self.results = getattr(strategy, "results", None)
        return result

    def get_returns(self):
        if self.results is None:
            raise RuntimeError("请先调用 run()")
        return self.results["returns"]


class _MultiFactorV20Adapter:
    """
    多因子策略 v20 适配器 — v16 + w_reversal（W 型反转，2026-04-14）。

    v16 基础（9 因子）+ 新增：
      w_reversal  ICIR=+0.546，t=+4.013
        = W 型双底反转结构分数（换手率加权）
        方向=+1（高值=W 型形态=均值回归看多）
        与 v16 各因子最大相关 0.569（vs pv_div）— 正交合格
    """

    def __init__(self, n_stocks: int = 30):
        self.n_stocks = n_stocks
        self.results = None

    def run(self, price_wide: pd.DataFrame) -> pd.DataFrame:
        from utils.alpha_factors import (
            low_vol_20d, team_coin, shadow_lower,
            amihud_illiquidity, price_volume_divergence,
            turnover_acceleration, high_52w_ratio,
            momentum_6m_skip1m, win_rate_60d, w_reversal,
        )
        from strategies.multi_factor import MultiFactorStrategy
        from strategies.base import StrategyConfig

        factors = {}
        symbols = list(price_wide.columns)
        start = str(price_wide.index[0].date())
        end   = str(price_wide.index[-1].date())

        # ── v16 因子（全部保留）───────────────────────────────
        for name, fn, d in [
            ("low_vol_20d",   lambda: low_vol_20d(price_wide),        1),
            ("team_coin",     lambda: team_coin(price_wide),           1),
            ("high_52w",      lambda: high_52w_ratio(price_wide),     -1),
            ("mom_6m_skip1m", lambda: momentum_6m_skip1m(price_wide), -1),
            ("win_rate_60d",  lambda: win_rate_60d(price_wide),       -1),
        ]:
            try: factors[name] = (fn(), d)
            except Exception as e: _log.warning("%s 跳过: %s", name, e)

        try:
            from utils.local_data_loader import load_price_wide as _lpw
            low_wide = _lpw(symbols, start, end, field="low")
            if not low_wide.empty:
                factors["shadow_lower"] = (shadow_lower(price_wide, low_wide.reindex_like(price_wide)), -1)
        except Exception as e: _log.warning("shadow_lower 跳过: %s", e)

        vol_wide = None
        try:
            from utils.local_data_loader import load_price_wide as _lpw
            vol_wide = _lpw(symbols, start, end, field="volume")
            if vol_wide.empty: vol_wide = None
        except Exception as e: _log.warning("volume 加载失败: %s", e)

        if vol_wide is not None:
            va_vol = vol_wide.reindex_like(price_wide)
            try: factors["amihud_illiq"]        = (amihud_illiquidity(price_wide, va_vol), 1)
            except Exception as e: _log.warning("amihud_illiq 跳过: %s", e)
            try: factors["price_vol_divergence"] = (price_volume_divergence(price_wide, va_vol), 1)
            except Exception as e: _log.warning("price_vol_div 跳过: %s", e)

        # turnover_accel + w_reversal 需要换手率宽表
        tv_wide = None
        try:
            from utils.local_data_loader import load_factor_wide as _lfw
            tv_data = _lfw(symbols, "turnover", start, end)
            if not tv_data.empty:
                tv_wide = tv_data.reindex_like(price_wide)
                factors["turnover_accel"] = (turnover_acceleration(tv_wide), -1)
        except Exception as e: _log.warning("turnover_accel 跳过: %s", e)

        # ── v20 新增因子 ──────────────────────────────────────
        try:
            tv_for_wr = tv_wide  # 复用上面加载的换手率（如可用）
            factors["w_reversal"] = (w_reversal(price_wide, tv_for_wr), 1)
        except Exception as e: _log.warning("w_reversal 跳过: %s", e)

        industry_map = _load_industry_map(symbols)
        config = StrategyConfig(name="multi_factor_v20")
        strategy = MultiFactorStrategy(
            config=config, factors=factors, n_stocks=self.n_stocks,
            ic_weighting=True, industry_map=industry_map, neutralize=bool(industry_map),
        )
        result = strategy.run(price_wide)
        self.results = getattr(strategy, "results", None)
        return result

    def get_returns(self):
        if self.results is None:
            raise RuntimeError("请先调用 run()")
        return self.results["returns"]


class _MultiFactorV19Adapter:
    """
    多因子策略 v19 适配器 — v16 + volume_concentration（量能集中度，2026-04-14）。

    v16 基础（9 因子）+ 新增：
      volume_concentration  ICIR=-0.388，t=-2.854
        = max_vol_20d / sum_vol_20d，方向=-1（高集中=散户一次性拥入=看空）
        与 v16 各因子最大相关 0.365 — 优异正交性
    """

    def __init__(self, n_stocks: int = 30):
        self.n_stocks = n_stocks
        self.results = None

    def run(self, price_wide: pd.DataFrame) -> pd.DataFrame:
        from utils.alpha_factors import (
            low_vol_20d, team_coin, shadow_lower,
            amihud_illiquidity, price_volume_divergence,
            turnover_acceleration, high_52w_ratio,
            momentum_6m_skip1m, win_rate_60d, volume_concentration,
        )
        from strategies.multi_factor import MultiFactorStrategy
        from strategies.base import StrategyConfig

        factors = {}
        symbols = list(price_wide.columns)
        start = str(price_wide.index[0].date())
        end   = str(price_wide.index[-1].date())

        # ── v16 因子（全部保留）───────────────────────────────
        for name, fn, d in [
            ("low_vol_20d",   lambda: low_vol_20d(price_wide),        1),
            ("team_coin",     lambda: team_coin(price_wide),           1),
            ("high_52w",      lambda: high_52w_ratio(price_wide),     -1),
            ("mom_6m_skip1m", lambda: momentum_6m_skip1m(price_wide), -1),
            ("win_rate_60d",  lambda: win_rate_60d(price_wide),       -1),
        ]:
            try: factors[name] = (fn(), d)
            except Exception as e: _log.warning("%s 跳过: %s", name, e)

        try:
            from utils.local_data_loader import load_price_wide as _lpw
            low_wide = _lpw(symbols, start, end, field="low")
            if not low_wide.empty:
                factors["shadow_lower"] = (shadow_lower(price_wide, low_wide.reindex_like(price_wide)), -1)
        except Exception as e: _log.warning("shadow_lower 跳过: %s", e)

        vol_wide = None
        try:
            from utils.local_data_loader import load_price_wide as _lpw
            vol_wide = _lpw(symbols, start, end, field="volume")
            if vol_wide.empty: vol_wide = None
        except Exception as e: _log.warning("volume 加载失败: %s", e)

        if vol_wide is not None:
            va_vol = vol_wide.reindex_like(price_wide)
            try: factors["amihud_illiq"]        = (amihud_illiquidity(price_wide, va_vol), 1)
            except Exception as e: _log.warning("amihud_illiq 跳过: %s", e)
            try: factors["price_vol_divergence"] = (price_volume_divergence(price_wide, va_vol), 1)
            except Exception as e: _log.warning("price_vol_div 跳过: %s", e)
            try: factors["vol_concentration"]   = (volume_concentration(va_vol), -1)
            except Exception as e: _log.warning("vol_concentration 跳过: %s", e)

        try:
            from utils.local_data_loader import load_factor_wide as _lfw
            tv = _lfw(symbols, "turnover", start, end)
            if not tv.empty:
                factors["turnover_accel"] = (turnover_acceleration(tv.reindex_like(price_wide)), -1)
        except Exception as e: _log.warning("turnover_accel 跳过: %s", e)

        industry_map = _load_industry_map(symbols)
        config = StrategyConfig(name="multi_factor_v19")
        strategy = MultiFactorStrategy(
            config=config, factors=factors, n_stocks=self.n_stocks,
            ic_weighting=True, industry_map=industry_map, neutralize=bool(industry_map),
        )
        result = strategy.run(price_wide)
        self.results = getattr(strategy, "results", None)
        return result

    def get_returns(self):
        if self.results is None:
            raise RuntimeError("请先调用 run()")
        return self.results["returns"]


class _MultiFactorV18Adapter:
    """
    多因子策略 v18 适配器 — v16 + network_scc（网络关联度，2026-04-14）。

    v16 基础（9 因子）+ 新增：
      network_scc  ICIR=-0.394，t=-2.554
        = 20 日相关性网络中的强连通分量集群系数
        方向=-1（高中心度=系统性风险敞口大=看空；选孤立/低关联股票）
        与 v16 各因子最大相关 0.218 — 极佳正交性（信息全新）
    """

    def __init__(self, n_stocks: int = 30):
        self.n_stocks = n_stocks
        self.results = None

    def run(self, price_wide: pd.DataFrame) -> pd.DataFrame:
        from utils.alpha_factors import (
            low_vol_20d, team_coin, shadow_lower,
            amihud_illiquidity, price_volume_divergence,
            turnover_acceleration, high_52w_ratio,
            momentum_6m_skip1m, win_rate_60d, network_scc,
        )
        from strategies.multi_factor import MultiFactorStrategy
        from strategies.base import StrategyConfig

        factors = {}
        symbols = list(price_wide.columns)
        start = str(price_wide.index[0].date())
        end   = str(price_wide.index[-1].date())

        # ── v16 因子（全部保留）───────────────────────────────
        for name, fn, d in [
            ("low_vol_20d",   lambda: low_vol_20d(price_wide),        1),
            ("team_coin",     lambda: team_coin(price_wide),           1),
            ("high_52w",      lambda: high_52w_ratio(price_wide),     -1),
            ("mom_6m_skip1m", lambda: momentum_6m_skip1m(price_wide), -1),
            ("win_rate_60d",  lambda: win_rate_60d(price_wide),       -1),
        ]:
            try: factors[name] = (fn(), d)
            except Exception as e: _log.warning("%s 跳过: %s", name, e)

        try:
            from utils.local_data_loader import load_price_wide as _lpw
            low_wide = _lpw(symbols, start, end, field="low")
            if not low_wide.empty:
                factors["shadow_lower"] = (shadow_lower(price_wide, low_wide.reindex_like(price_wide)), -1)
        except Exception as e: _log.warning("shadow_lower 跳过: %s", e)

        vol_wide = None
        try:
            from utils.local_data_loader import load_price_wide as _lpw
            vol_wide = _lpw(symbols, start, end, field="volume")
            if vol_wide.empty: vol_wide = None
        except Exception as e: _log.warning("volume 加载失败: %s", e)

        if vol_wide is not None:
            va_vol = vol_wide.reindex_like(price_wide)
            try: factors["amihud_illiq"]        = (amihud_illiquidity(price_wide, va_vol), 1)
            except Exception as e: _log.warning("amihud_illiq 跳过: %s", e)
            try: factors["price_vol_divergence"] = (price_volume_divergence(price_wide, va_vol), 1)
            except Exception as e: _log.warning("price_vol_div 跳过: %s", e)

        try:
            from utils.local_data_loader import load_factor_wide as _lfw
            tv = _lfw(symbols, "turnover", start, end)
            if not tv.empty:
                factors["turnover_accel"] = (turnover_acceleration(tv.reindex_like(price_wide)), -1)
        except Exception as e: _log.warning("turnover_accel 跳过: %s", e)

        # ── v18 新增因子 ──────────────────────────────────────
        try:
            factors["network_scc"] = (network_scc(price_wide, window=20), -1)
        except Exception as e: _log.warning("network_scc 跳过: %s", e)

        industry_map = _load_industry_map(symbols)
        config = StrategyConfig(name="multi_factor_v18")
        strategy = MultiFactorStrategy(
            config=config, factors=factors, n_stocks=self.n_stocks,
            ic_weighting=True, industry_map=industry_map, neutralize=bool(industry_map),
        )
        result = strategy.run(price_wide)
        self.results = getattr(strategy, "results", None)
        return result

    def get_returns(self):
        if self.results is None:
            raise RuntimeError("请先调用 run()")
        return self.results["returns"]


class _MultiFactorV17Adapter:
    """
    多因子策略 v17 适配器 — v16 + vol_asymmetry（波动率非对称，2026-04-14）。

    v16 基础（9 因子）+ 新增：
      vol_asymmetry  ICIR=+0.565，t=+4.149
        = std(负收益日) / std(正收益日)，rolling 60d
        方向=+1（高比值=超卖状态=看多）
        与 v16 各因子最大相关 0.402 — 极佳正交性
    """

    def __init__(self, n_stocks: int = 30):
        self.n_stocks = n_stocks
        self.results = None

    def run(self, price_wide: pd.DataFrame) -> pd.DataFrame:
        from utils.alpha_factors import (
            low_vol_20d, team_coin, shadow_lower,
            amihud_illiquidity, price_volume_divergence,
            turnover_acceleration, high_52w_ratio,
            momentum_6m_skip1m, win_rate_60d, vol_asymmetry,
        )
        from strategies.multi_factor import MultiFactorStrategy
        from strategies.base import StrategyConfig

        factors = {}
        symbols = list(price_wide.columns)
        start = str(price_wide.index[0].date())
        end   = str(price_wide.index[-1].date())

        # ── v16 因子（全部保留）───────────────────────────────
        for name, fn, d in [
            ("low_vol_20d",   lambda: low_vol_20d(price_wide),        1),
            ("team_coin",     lambda: team_coin(price_wide),           1),
            ("high_52w",      lambda: high_52w_ratio(price_wide),     -1),
            ("mom_6m_skip1m", lambda: momentum_6m_skip1m(price_wide), -1),
            ("win_rate_60d",  lambda: win_rate_60d(price_wide),       -1),
            ("vol_asymmetry", lambda: vol_asymmetry(price_wide),      +1),
        ]:
            try: factors[name] = (fn(), d)
            except Exception as e: _log.warning("%s 跳过: %s", name, e)

        try:
            from utils.local_data_loader import load_price_wide as _lpw
            low_wide = _lpw(symbols, start, end, field="low")
            if not low_wide.empty:
                factors["shadow_lower"] = (shadow_lower(price_wide, low_wide.reindex_like(price_wide)), -1)
        except Exception as e: _log.warning("shadow_lower 跳过: %s", e)

        vol_wide = None
        try:
            from utils.local_data_loader import load_price_wide as _lpw
            vol_wide = _lpw(symbols, start, end, field="volume")
            if vol_wide.empty: vol_wide = None
        except Exception as e: _log.warning("volume 加载失败: %s", e)

        if vol_wide is not None:
            va_vol = vol_wide.reindex_like(price_wide)
            try: factors["amihud_illiq"]        = (amihud_illiquidity(price_wide, va_vol), 1)
            except Exception as e: _log.warning("amihud_illiq 跳过: %s", e)
            try: factors["price_vol_divergence"] = (price_volume_divergence(price_wide, va_vol), 1)
            except Exception as e: _log.warning("price_vol_div 跳过: %s", e)

        try:
            from utils.local_data_loader import load_factor_wide as _lfw
            tv = _lfw(symbols, "turnover", start, end)
            if not tv.empty:
                factors["turnover_accel"] = (turnover_acceleration(tv.reindex_like(price_wide)), -1)
        except Exception as e: _log.warning("turnover_accel 跳过: %s", e)

        industry_map = _load_industry_map(symbols)
        config = StrategyConfig(name="multi_factor_v17")
        strategy = MultiFactorStrategy(
            config=config, factors=factors, n_stocks=self.n_stocks,
            ic_weighting=True, industry_map=industry_map, neutralize=bool(industry_map),
        )
        result = strategy.run(price_wide)
        self.results = getattr(strategy, "results", None)
        return result

    def get_returns(self):
        if self.results is None:
            raise RuntimeError("请先调用 run()")
        return self.results["returns"]


class _MultiFactorV16Adapter:
    """
    多因子策略 v16 适配器 — v13 + win_rate_60d（60 日胜率反转，2026-04-14）。

    v13 基础（8 因子）+ 新增：
      win_rate_60d  ICIR=-0.402，t=-2.953
        = rolling_60d_mean(daily_ret > 0)，方向=-1（高胜率=超买=看空）
        与 v13 各因子最大相关 0.376（high_52w）— 优异正交性
    """

    def __init__(self, n_stocks: int = 30):
        self.n_stocks = n_stocks
        self.results = None

    def run(self, price_wide: pd.DataFrame) -> pd.DataFrame:
        from utils.alpha_factors import (
            low_vol_20d, team_coin, shadow_lower,
            amihud_illiquidity, price_volume_divergence,
            turnover_acceleration, high_52w_ratio,
            momentum_6m_skip1m, win_rate_60d,
        )
        from strategies.multi_factor import MultiFactorStrategy
        from strategies.base import StrategyConfig

        factors = {}
        symbols = list(price_wide.columns)
        start = str(price_wide.index[0].date())
        end   = str(price_wide.index[-1].date())

        # ── v13 因子（全部保留）───────────────────────────────
        for name, fn, d in [
            ("low_vol_20d",   lambda: low_vol_20d(price_wide),      1),
            ("team_coin",     lambda: team_coin(price_wide),         1),
            ("high_52w",      lambda: high_52w_ratio(price_wide),   -1),
            ("mom_6m_skip1m", lambda: momentum_6m_skip1m(price_wide), -1),
            ("win_rate_60d",  lambda: win_rate_60d(price_wide),     -1),
        ]:
            try: factors[name] = (fn(), d)
            except Exception as e: _log.warning("%s 跳过: %s", name, e)

        try:
            from utils.local_data_loader import load_price_wide as _lpw
            low_wide = _lpw(symbols, start, end, field="low")
            if not low_wide.empty:
                factors["shadow_lower"] = (shadow_lower(price_wide, low_wide.reindex_like(price_wide)), -1)
        except Exception as e: _log.warning("shadow_lower 跳过: %s", e)

        vol_wide = None
        try:
            from utils.local_data_loader import load_price_wide as _lpw
            vol_wide = _lpw(symbols, start, end, field="volume")
            if vol_wide.empty: vol_wide = None
        except Exception as e: _log.warning("volume 加载失败: %s", e)

        if vol_wide is not None:
            va = vol_wide.reindex_like(price_wide)
            try: factors["amihud_illiq"]        = (amihud_illiquidity(price_wide, va), 1)
            except Exception as e: _log.warning("amihud_illiq 跳过: %s", e)
            try: factors["price_vol_divergence"] = (price_volume_divergence(price_wide, va), 1)
            except Exception as e: _log.warning("price_vol_div 跳过: %s", e)

        try:
            from utils.local_data_loader import load_factor_wide as _lfw
            tv = _lfw(symbols, "turnover", start, end)
            if not tv.empty:
                factors["turnover_accel"] = (turnover_acceleration(tv.reindex_like(price_wide)), -1)
        except Exception as e: _log.warning("turnover_accel 跳过: %s", e)

        industry_map = _load_industry_map(symbols)
        config = StrategyConfig(name="multi_factor_v16")
        strategy = MultiFactorStrategy(
            config=config, factors=factors, n_stocks=self.n_stocks,
            ic_weighting=True, industry_map=industry_map, neutralize=bool(industry_map),
        )
        result = strategy.run(price_wide)
        self.results = getattr(strategy, "results", None)
        return result

    def get_returns(self):
        if self.results is None:
            raise RuntimeError("请先调用 run()")
        return self.results["returns"]


class _MultiFactorV15Adapter:
    """
    多因子策略 v15 适配器 — v13 但用 price_dist_ma60 替换 high_52w（2026-04-14）。

    因子集（8 个）：
      low_vol_20d / team_coin / shadow_lower / amihud_illiq /
      price_vol_divergence / price_dist_ma60 / turnover_accel / mom_6m_skip1m

    替换理由：
      high_52w:    ICIR=-0.245（弱），IC 方向=-1（A 股反转）
      price_dist_ma60: ICIR=-0.510（强），t=-3.750，与 high_52w r=0.683 高度相关
      → 用更强的因子替代弱因子，保持因子组合多样性
      → price_dist_ma60 与其余 7 因子最大相关 0.454，正交性良好
    """

    def __init__(self, n_stocks: int = 30):
        self.n_stocks = n_stocks
        self.results = None

    def run(self, price_wide: pd.DataFrame) -> pd.DataFrame:
        from utils.alpha_factors import (
            low_vol_20d, team_coin, shadow_lower,
            amihud_illiquidity, price_volume_divergence,
            turnover_acceleration, momentum_6m_skip1m,
            price_distance_from_ma,
        )
        from strategies.multi_factor import MultiFactorStrategy
        from strategies.base import StrategyConfig

        factors = {}
        symbols = list(price_wide.columns)
        start = str(price_wide.index[0].date())
        end   = str(price_wide.index[-1].date())

        # ── 纯价格因子 ────────────────────────────────────────
        for name, fn, d in [
            ("low_vol_20d",      lambda: low_vol_20d(price_wide),            1),
            ("team_coin",        lambda: team_coin(price_wide),               1),
            ("mom_6m_skip1m",    lambda: momentum_6m_skip1m(price_wide),     -1),
            ("price_dist_ma60",  lambda: price_distance_from_ma(price_wide, 60), -1),
        ]:
            try: factors[name] = (fn(), d)
            except Exception as e: _log.warning("%s 跳过: %s", name, e)

        # shadow_lower 需要 low 宽表
        try:
            from utils.local_data_loader import load_price_wide as _lpw
            low_wide = _lpw(symbols, start, end, field="low")
            if not low_wide.empty:
                factors["shadow_lower"] = (shadow_lower(price_wide, low_wide.reindex_like(price_wide)), -1)
        except Exception as e: _log.warning("shadow_lower 跳过: %s", e)

        # amihud + price_vol_div 需要 volume
        vol_wide = None
        try:
            from utils.local_data_loader import load_price_wide as _lpw
            vol_wide = _lpw(symbols, start, end, field="volume")
            if vol_wide.empty: vol_wide = None
        except Exception as e: _log.warning("volume 加载失败: %s", e)

        if vol_wide is not None:
            va = vol_wide.reindex_like(price_wide)
            try: factors["amihud_illiq"]        = (amihud_illiquidity(price_wide, va), 1)
            except Exception as e: _log.warning("amihud_illiq 跳过: %s", e)
            try: factors["price_vol_divergence"] = (price_volume_divergence(price_wide, va), 1)
            except Exception as e: _log.warning("price_vol_div 跳过: %s", e)

        # turnover_accel 需要换手率宽表
        try:
            from utils.local_data_loader import load_factor_wide as _lfw
            tv = _lfw(symbols, "turnover", start, end)
            if not tv.empty:
                factors["turnover_accel"] = (turnover_acceleration(tv.reindex_like(price_wide)), -1)
        except Exception as e: _log.warning("turnover_accel 跳过: %s", e)

        industry_map = _load_industry_map(symbols)
        config = StrategyConfig(name="multi_factor_v15")
        strategy = MultiFactorStrategy(
            config=config, factors=factors, n_stocks=self.n_stocks,
            ic_weighting=True, industry_map=industry_map, neutralize=bool(industry_map),
        )
        result = strategy.run(price_wide)
        self.results = getattr(strategy, "results", None)
        return result

    def get_returns(self):
        if self.results is None:
            raise RuntimeError("请先调用 run()")
        return self.results["returns"]


class _MultiFactorV13Adapter:
    """
    多因子策略 v13 适配器 — v11 + momentum_6m_skip1m（中期反转，2026-04-14）。

    v11 基础（7 因子）：
      low_vol_20d / team_coin / shadow_lower / amihud_illiq /
      price_vol_divergence / high_52w_ratio / turnover_accel

    新增因子：
      momentum_6m_skip1m  ICIR=-0.326，t=-2.349
        = price.shift(21)/price.shift(126)-1
        方向=-1（高 6 月收益 → 均值回归 → 看空；A 股反转效应）
        最大共线性：vs low_vol r=-0.441，vs high_52w r=0.311（均独立）
    """

    def __init__(self, n_stocks: int = 30):
        self.n_stocks = n_stocks
        self.results = None

    def run(self, price_wide: pd.DataFrame) -> pd.DataFrame:
        from utils.alpha_factors import (
            low_vol_20d, team_coin, shadow_lower,
            amihud_illiquidity, price_volume_divergence,
            turnover_acceleration, high_52w_ratio,
            momentum_6m_skip1m,
        )
        from strategies.multi_factor import MultiFactorStrategy
        from strategies.base import StrategyConfig

        factors = {}
        symbols = list(price_wide.columns)
        start = str(price_wide.index[0].date())
        end   = str(price_wide.index[-1].date())

        # ── v11 因子（全部保留）───────────────────────────────
        for name, fn, d in [
            ("low_vol_20d", lambda: low_vol_20d(price_wide), 1),
            ("team_coin",   lambda: team_coin(price_wide),   1),
            ("high_52w",    lambda: high_52w_ratio(price_wide), -1),
        ]:
            try: factors[name] = (fn(), d)
            except Exception as e: _log.warning("%s 跳过: %s", name, e)

        try:
            from utils.local_data_loader import load_price_wide as _lpw
            low_wide = _lpw(symbols, start, end, field="low")
            if not low_wide.empty:
                factors["shadow_lower"] = (shadow_lower(price_wide, low_wide.reindex_like(price_wide)), -1)
        except Exception as e: _log.warning("shadow_lower 跳过: %s", e)

        vol_wide = None
        try:
            from utils.local_data_loader import load_price_wide as _lpw
            vol_wide = _lpw(symbols, start, end, field="volume")
            if vol_wide.empty: vol_wide = None
        except Exception as e: _log.warning("volume 加载失败: %s", e)

        if vol_wide is not None:
            va = vol_wide.reindex_like(price_wide)
            try: factors["amihud_illiq"]       = (amihud_illiquidity(price_wide, va), 1)
            except Exception as e: _log.warning("amihud_illiq 跳过: %s", e)
            try: factors["price_vol_divergence"] = (price_volume_divergence(price_wide, va), 1)
            except Exception as e: _log.warning("price_vol_div 跳过: %s", e)

        try:
            from utils.local_data_loader import load_factor_wide as _lfw
            tv = _lfw(symbols, "turnover", start, end)
            if not tv.empty:
                factors["turnover_accel"] = (turnover_acceleration(tv.reindex_like(price_wide)), -1)
        except Exception as e: _log.warning("turnover_accel 跳过: %s", e)

        # ── v13 新增因子 ──────────────────────────────────────
        # momentum_6m_skip1m: 中期反转（方向=-1，A 股过去 6 月强势股均值回归）
        try:
            factors["mom_6m_skip1m"] = (momentum_6m_skip1m(price_wide), -1)
        except Exception as e: _log.warning("mom_6m_skip1m 跳过: %s", e)

        industry_map = _load_industry_map(symbols)
        config = StrategyConfig(name="multi_factor_v13")
        strategy = MultiFactorStrategy(
            config=config, factors=factors, n_stocks=self.n_stocks,
            ic_weighting=True, industry_map=industry_map, neutralize=bool(industry_map),
        )
        result = strategy.run(price_wide)
        self.results = getattr(strategy, "results", None)
        return result

    def get_returns(self):
        if self.results is None:
            raise RuntimeError("请先调用 run()")
        return self.results["returns"]


class _MultiFactorV14Adapter:
    """
    多因子策略 v14 适配器 — v13 + rsi_factor（RSI-14 超买超卖，2026-04-14）。

    v13 基础（8 因子）：
      low_vol_20d / team_coin / shadow_lower / amihud_illiq /
      price_vol_divergence / high_52w_ratio / turnover_accel / mom_6m_skip1m

    新增因子：
      rsi_factor(window=14)  ICIR=-0.309，t=-2.273
        = RSI-14 超买超卖指标，方向=-1（高 RSI=超买=看空）
        最大共线性：vs shadow_lower r=0.572（低于 0.6 阈值，正交合格）
    """

    def __init__(self, n_stocks: int = 30):
        self.n_stocks = n_stocks
        self.results = None

    def run(self, price_wide: pd.DataFrame) -> pd.DataFrame:
        from utils.alpha_factors import (
            low_vol_20d, team_coin, shadow_lower,
            amihud_illiquidity, price_volume_divergence,
            turnover_acceleration, high_52w_ratio,
            momentum_6m_skip1m, rsi_factor,
        )
        from strategies.multi_factor import MultiFactorStrategy
        from strategies.base import StrategyConfig

        factors = {}
        symbols = list(price_wide.columns)
        start = str(price_wide.index[0].date())
        end   = str(price_wide.index[-1].date())

        # ── v13 因子（全部保留）───────────────────────────────
        for name, fn, d in [
            ("low_vol_20d",   lambda: low_vol_20d(price_wide),      1),
            ("team_coin",     lambda: team_coin(price_wide),         1),
            ("high_52w",      lambda: high_52w_ratio(price_wide),   -1),
            ("mom_6m_skip1m", lambda: momentum_6m_skip1m(price_wide), -1),
        ]:
            try: factors[name] = (fn(), d)
            except Exception as e: _log.warning("%s 跳过: %s", name, e)

        try:
            from utils.local_data_loader import load_price_wide as _lpw
            low_wide = _lpw(symbols, start, end, field="low")
            if not low_wide.empty:
                factors["shadow_lower"] = (shadow_lower(price_wide, low_wide.reindex_like(price_wide)), -1)
        except Exception as e: _log.warning("shadow_lower 跳过: %s", e)

        vol_wide = None
        try:
            from utils.local_data_loader import load_price_wide as _lpw
            vol_wide = _lpw(symbols, start, end, field="volume")
            if vol_wide.empty: vol_wide = None
        except Exception as e: _log.warning("volume 加载失败: %s", e)

        if vol_wide is not None:
            va = vol_wide.reindex_like(price_wide)
            try: factors["amihud_illiq"]        = (amihud_illiquidity(price_wide, va), 1)
            except Exception as e: _log.warning("amihud_illiq 跳过: %s", e)
            try: factors["price_vol_divergence"] = (price_volume_divergence(price_wide, va), 1)
            except Exception as e: _log.warning("price_vol_div 跳过: %s", e)

        try:
            from utils.local_data_loader import load_factor_wide as _lfw
            tv = _lfw(symbols, "turnover", start, end)
            if not tv.empty:
                factors["turnover_accel"] = (turnover_acceleration(tv.reindex_like(price_wide)), -1)
        except Exception as e: _log.warning("turnover_accel 跳过: %s", e)

        # ── v14 新增因子 ──────────────────────────────────────
        try:
            factors["rsi_14"] = (rsi_factor(price_wide, window=14), -1)
        except Exception as e: _log.warning("rsi_14 跳过: %s", e)

        industry_map = _load_industry_map(symbols)
        config = StrategyConfig(name="multi_factor_v14")
        strategy = MultiFactorStrategy(
            config=config, factors=factors, n_stocks=self.n_stocks,
            ic_weighting=True, industry_map=industry_map, neutralize=bool(industry_map),
        )
        result = strategy.run(price_wide)
        self.results = getattr(strategy, "results", None)
        return result

    def get_returns(self):
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
