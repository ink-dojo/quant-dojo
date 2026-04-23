# Phase 8 风控基建 ROADMAP — 可执行版
_2026-04-23, 10 项 must/should + 5 项 defer, 总周期 3-4 月_

> 这是 ROADMAP.md 第 8 阶段 "Real-Money Readiness" 的具体化分解.
> 4 个 Tier, 每个 Tier 内每个 item 给文件路径 / 函数签名 / 验收标准 / 测试命令.
> **按 checkbox 顺序执行**, Tier 1 全做完才能进 Tier 2; Tier 1 内可并行.

---

## 总览矩阵

| Tier | # | Item | 周期 | 触发条件 |
|---|---|---|---|---|
| **1 (must)** | 1.1 | Vol Targeting | 1 周 | 立刻开始 |
| 1 | 1.2 | Capacity Monitoring | 1 周 | 立刻开始 (可与 1.1 并行) |
| 1 | 1.3 | Stress Test | 1 周 | 立刻开始 (可与 1.1/1.2 并行) |
| 1 | 1.4 | Live vs Backtest 强化 | 3 天 | 立刻开始 |
| **2 (should)** | 2.1 | Cross-sectional Dispersion | 2 天 | live 5% 跑 1 月后 |
| 2 | 2.2 | 北向 + 两融信号 | 3 天 | live 5% 跑 1 月后 |
| 2 | 2.3 | Drawdown Control 升级 | 5 天 | live 5% 跑 1 月后 |
| **3 (enhancement)** | 3.1 | Ensemble Regime Models | 1 周 | scale 30%+ 前 |
| 3 | 3.2 | Pre-trade Gate | 5 天 | scale 30%+ 前 |
| 3 | 3.3 | Auto Factor Decay 减权 | 5 天 | scale 30%+ 前 |
| **4 (defer)** | — | Tail hedge / HMM / TDA / DXY / Microstructure | — | 管理 ¥3000 万+ 后再说 |

---

## 阶段触发关卡

```
当前 (paper trade) ──┐
                    │
         Tier 1 完成 (4 项) ──→ 通过则进入 live 5%
                    │
         live 5% 跑 1 月 ──→ 触发 Tier 2 (3 项)
                    │
         Tier 2 完成 + live 跑稳 3 月 ──→ 触发 Tier 3 (3 项)
                    │
         Tier 3 完成 ──→ 准备 scale 到 30%+
                    │
         AUM > ¥3000 万 ──→ 才考虑 Tier 4
```

---

## Tier 1 — Must Have (live 5% 之前必须全做完)

### 1.1 Vol Targeting

**目标**: 把组合年化波动率维持在 12%, vol 上升时自动减仓, 防止尾部爆仓.

**为什么必须**: 你目前 spec v4 是固定 50/50 权重. 一旦 RIAD 或 DSR#30 单腿在高波动期 vol 飙升, 整个组合 vol 跟着飙. 历史看 2015-08 / 2020-02 这种月份, 没 vol target 的策略组合 vol 能从 15% 飙到 35%, MDD 翻倍.

**文件结构**:
```
pipeline/vol_targeting.py   ← 新建
tests/pipeline/test_vol_targeting.py   ← 新建
```

**接口**:
```python
def compute_vol_scale(
    nav_series: pd.Series,
    target_vol: float = 0.12,
    lookback_days: int = 60,
    min_scale: float = 0.30,
    max_scale: float = 1.50,
) -> float:
    """
    根据 nav 历史, 计算当前应施加的 gross 缩放系数.

    Args:
        nav_series: 策略历史 NAV (日频)
        target_vol: 目标年化波动率 (默认 12%)
        lookback_days: 计算实现波动率的窗口 (默认 60d)
        min_scale: 最小缩放 (防止全现金, 默认 0.30)
        max_scale: 最大缩放 (防止过度杠杆, 默认 1.50)

    Returns:
        scale ∈ [min_scale, max_scale], 直接乘到 target gross 上
    """
    pass

def apply_vol_target_to_positions(
    positions: dict[str, float],
    scale: float,
) -> dict[str, float]:
    """所有 position 等比例缩放."""
    pass
```

**实施步骤**:
- [ ] 新建 `pipeline/vol_targeting.py`, 实现 `compute_vol_scale` + `apply_vol_target_to_positions`
- [ ] 在 `pipeline/active_strategy.py` 的下单前一步调用 vol target (具体行号: 找到 `generate_target_positions` 之后, 下单之前)
- [ ] 单元测试: 喂入合成 NAV (固定 vol 8% / 12% / 18%), 验证 scale 分别为 1.5 / 1.0 / 0.67
- [ ] 集成测试: 跑历史回测 2014-2025, 对比 vol target 前后的 max DD
- [ ] 接受标准:
  - 60d 实际 vol 在 [10%, 14%] 内 (目标 ±2%)
  - max DD 比无 target 版本至少减 20%
  - Sharpe 不下降超过 0.1 (vol target 通常稍升)

**验证命令**:
```bash
python pipeline/vol_targeting.py   # 内置 __main__ 最小验证
pytest tests/pipeline/test_vol_targeting.py -v
python -m pipeline.experiment_runner --strategy spec_v4 --vol-target 0.12 --compare-baseline
```

**风险**:
- 缩放系数过低 → 错过反弹. 用 min_scale=0.30 兜底
- 缩放系数过高 → 过度杠杆. 用 max_scale=1.50 兜底
- vol 估计噪声大 → 用 60d 而非 20d, 接受滞后

**预计工作量**: 1 周 (3 天 implement + 2 天 backtest + 2 天 review)

---

### 1.2 Capacity Monitoring

**目标**: 监控每个目标 position 的 ADV (Average Daily Volume) 占比, 防止 scaling 时 slippage 失控.

**为什么必须**: 你 paper trade 在 5% AUM 下, 每只股 5% × 7.5% = 0.375% 头寸, slippage 约 5 bps, 没事. 但 scale 到 100% AUM (¥1000 万 / 一只股 7.5% = ¥75 万), 在小盘股上单日成交可能占 ADV 的 20%+, slippage 可能飙到 50-100 bps, 一次调仓吃掉 0.3% 收益. **slippage 不是线性的, 是凸的**.

**文件结构**:
```
pipeline/capacity_monitor.py   ← 新建
data/raw/tushare/daily/*.parquet   ← 已有, 依赖 vol 字段
```

**接口**:
```python
@dataclass
class CapacityReport:
    ts_code: str
    target_value_yuan: float
    adv_20d_yuan: float
    pct_of_adv: float
    estimated_slippage_bps: float
    flag: str  # "ok" | "warn" | "blocked"

def check_capacity(
    target_positions: dict[str, float],   # ts_code → 目标市值 (元)
    aum: float,                            # 当前 AUM (元)
    adv_lookback_days: int = 20,
    warn_pct_of_adv: float = 0.05,         # 5% ADV → warn
    block_pct_of_adv: float = 0.10,        # 10% ADV → 减仓到 5%
) -> list[CapacityReport]:
    """
    对每个 target position, 计算 ADV 占比, 估算 slippage.

    Slippage 模型 (Almgren-Chriss 简化):
        slippage_bps = 50 * (pct_of_adv) ^ 0.6
        例: 5% ADV → 9 bps; 10% ADV → 13 bps; 20% ADV → 20 bps

    Returns:
        按 pct_of_adv 降序的 CapacityReport 列表.
        flag = blocked 的 position 在 caller 端应被砍到 5% ADV 上限内.
    """
    pass

def cap_positions_to_capacity(
    target_positions: dict[str, float],
    capacity_reports: list[CapacityReport],
) -> dict[str, float]:
    """对 flag=blocked 的 position 缩到 5% ADV 上限."""
    pass
```

**实施步骤**:
- [ ] 新建 `pipeline/capacity_monitor.py`, 实现 `check_capacity` + `cap_positions_to_capacity`
- [ ] slippage 模型: 用简化 Almgren-Chriss (50 × pct^0.6), 后续可校准实盘 slippage
- [ ] 在 `pipeline/active_strategy.py` 下单前调用, 输出报告 + 自动 cap
- [ ] 加日志: 任何 flag != "ok" 都写 logs/capacity_warnings_YYYYMMDD.json
- [ ] 单元测试: 合成 ADV + 目标头寸, 验证 flag 正确
- [ ] 集成测试: 用历史 daily 数据跑 spec v4 在 ¥100/500/1000 万 AUM 下的 capacity 报告
- [ ] 接受标准:
  - ¥1000 万 AUM 下, spec v4 全部 30 只股都不触发 blocked
  - 估算 slippage 在 spec v4 backtest 里被显式扣除, 净 SR 仍 > 0.8

**验证命令**:
```bash
python pipeline/capacity_monitor.py   # __main__ 最小验证
pytest tests/pipeline/test_capacity_monitor.py -v
python -m pipeline.capacity_monitor --strategy spec_v4 --aum 10000000   # ¥1000 万 capacity check
```

**风险**:
- ADV 计算未考虑停牌日 → 用 trailing 20 个**有交易日**而非自然日
- 小盘股 ADV 波动大 → 用中位数而非均值
- slippage 模型过度乐观 → live 后用真实 slippage 校准, 系数从 50 调到 80-100

**预计工作量**: 1 周

---

### 1.3 Stress Test

**目标**: 主动模拟当前组合在历史极端日 / 极端周的 PnL, 知道下限是多少.

**为什么必须**: 你的回测覆盖 2014-2025, 看的是平均表现. 但 "平均年化 20%, max DD 5%" 不代表你能扛住 "2015-08-26 单日跌 8%". 实盘里, 一次没扛住的 stress 就出局. **必须知道 worst case, 不是 average case**.

**文件结构**:
```
scripts/stress_test.py   ← 新建
data/processed/stress_dates.json   ← 新建, 维护极端事件日历
journal/stress_test_results_YYYYMMDD.md   ← 输出报告
```

**接口**:
```python
@dataclass
class StressEvent:
    name: str               # "2015-08-26 千股跌停"
    start_date: str
    end_date: str
    benchmark_return: float  # HS300 return
    description: str

STRESS_EVENTS = [
    StressEvent("2015-08-26 千股跌停", "2015-08-24", "2015-08-26", -0.182, "杠杆牛崩盘"),
    StressEvent("2016-01 熔断", "2016-01-04", "2016-01-08", -0.166, "熔断机制触发"),
    StressEvent("2018-10 贸易战", "2018-10-08", "2018-10-19", -0.083, "中美贸易战恶化"),
    StressEvent("2020-02 疫情", "2020-02-03", "2020-02-03", -0.078, "复工后单日恐慌"),
    StressEvent("2024-09 政策反转", "2024-09-24", "2024-10-08", +0.275, "政策大幅宽松"),
    # ... 更多
]

def stress_test_strategy(
    strategy_signal_fn: Callable,
    stress_events: list[StressEvent],
    price_data: pd.DataFrame,
    aum: float = 10_000_000,
) -> pd.DataFrame:
    """
    对每个 stress event, 模拟"如果当时持有当前组合的等价 exposure, PnL 是多少".

    方法:
        1. 在 stress event 当日, 取当前 spec v4 的因子暴露 (size / industry / 因子)
        2. 在 stress event 历史日, 找暴露最相近的 portfolio
        3. 用历史价格算 PnL
        4. 也算"信号当时如果重新生成, 会买什么", 用 stress 期价格回测

    Returns:
        DataFrame: event_name | model_pnl | signal_pnl | benchmark_pnl | worst_day | worst_day_pnl
    """
    pass
```

**实施步骤**:
- [ ] 新建 `scripts/stress_test.py`
- [ ] 在 `data/processed/stress_dates.json` 整理 8-10 个 A 股历史极端事件 (2015-06, 2015-08, 2016-01 熔断, 2016-02 注销盘, 2018-10, 2020-02, 2022-04 上海封城, 2024-09 政策, 2024-02 雪球)
- [ ] 实现 stress_test_strategy, 同时算 model_pnl (固定持仓 replay) + signal_pnl (重新跑信号)
- [ ] 输出 `journal/stress_test_results_YYYYMMDD.md`, 含每事件的 model/signal PnL + worst day
- [ ] 接受标准:
  - 任何单日 stress loss < 8% (硬门槛)
  - 任何单周 stress loss < 15%
  - 累计 max stress DD < 25%
  - 触发任一硬门槛 → 不上线 live, 重做 spec

**验证命令**:
```bash
python scripts/stress_test.py --strategy spec_v4 --aum 10000000 --output journal/
```

**风险**:
- 历史 stress 不代表未来 stress (Black Swan 性质) → 这是不可避免的, 但有比没有强
- 信号在 stress 当日可能不可执行 (停牌 / 涨跌停) → tradability filter 必须打开
- 信号回放容易过拟合 → 仅用作 sanity, 不调参

**预计工作量**: 1 周

---

### 1.4 Live vs Backtest 强化

**目标**: 实盘上线后每日自动算 PnL 偏差, 偏差 > 2σ 自动 alert.

**为什么必须**: 你已有 `pipeline/live_vs_backtest.py`, 但只是周度比对. live 5% 期间, 任何 model decay / data bug / execution slippage 失控都需要在 1-2 天内发现, 不是 1 周.

**文件结构**:
```
pipeline/live_vs_backtest.py   ← 已有, 升级
pipeline/alert_notifier.py     ← 已有, 加 channel
tests/pipeline/test_live_vs_backtest.py   ← 已有, 加 case
```

**新增功能**:
```python
def daily_pnl_divergence(
    live_nav: pd.Series,
    backtest_nav: pd.Series,
    lookback_days: int = 30,
) -> dict:
    """
    计算最近 N 日 live PnL vs backtest 同期 PnL 的偏差.

    Returns:
        {
            "tracking_error_30d": float,
            "live_pnl_total": float,
            "backtest_pnl_total": float,
            "divergence_zscore": float,  # 偏差 / 历史 σ
            "alert_level": str,           # "ok" | "warn" | "critical"
        }
    alert_level:
        ok       : |zscore| < 2
        warn     : 2 ≤ |zscore| < 3
        critical : |zscore| ≥ 3 → 自动 halve 仓位 (与 kill switch 联动)
    """
    pass

def check_and_alert(report: dict) -> None:
    """根据 alert_level 决定是否调 alert_notifier."""
    if report["alert_level"] == "warn":
        notify_warn(...)
    elif report["alert_level"] == "critical":
        notify_critical(...)
        trigger_kill_switch(action="HALVE", reason="live vs backtest divergence > 3σ")
```

**实施步骤**:
- [ ] 在 `pipeline/live_vs_backtest.py` 加 `daily_pnl_divergence` + `check_and_alert`
- [ ] 在 `live/event_kill_switch.py` 加新 trigger reason: "tracking_divergence"
- [ ] 加 cron / launchd job 每日 16:00 (收盘后 1h) 自动跑
- [ ] 测试: 喂入 live + backtest 模拟数据, 验证 zscore 计算 + alert 触发
- [ ] 接受标准:
  - 偏差 > 3σ 在 24 小时内必 alert
  - alert 触发后 kill switch 在下一调仓日自动 halve
  - false positive rate < 5% (用历史回测 vs 模拟实盘的偏差校准)

**验证命令**:
```bash
pytest tests/pipeline/test_live_vs_backtest.py -v
python -m pipeline.live_vs_backtest --daily --strategy spec_v4 --alert-on
```

**风险**:
- 第一周样本不足 → lookback_days < 30 时只 monitor 不 alert
- 调仓日的偏差天然大 → 调仓日 zscore 阈值放宽到 4σ
- alert noise → 要求连续 2 日 critical 才触发 kill, 单日仅记录

**预计工作量**: 3 天

---

## Tier 2 — Should Have (live 5% 跑稳 1 月后做)

### 2.1 Cross-sectional Dispersion 监控

**目标**: 监控 A 股截面波动率分布, 判断当前是 stock-picker market (高 dispersion, 有 alpha) 还是齐涨齐跌 (低 dispersion, 没 alpha).

**为什么 should**: 当 dispersion 持续低 (5+ 日), 说明所有股票一起涨跌, 任何 alpha 因子都难赚钱, 此时该减仓而非维持原 gross.

**文件结构**:
```
pipeline/dispersion_monitor.py   ← 新建
```

**接口**:
```python
def compute_cross_sectional_dispersion(
    returns_wide: pd.DataFrame,   # 日频, 行=日期, 列=ts_code
    rolling_days: int = 20,
) -> pd.Series:
    """
    每日计算所有股票当日收益率的 cross-section 标准差.
    高 = 个股表现差异大, alpha 多
    低 = 齐涨齐跌, 没 alpha
    """
    pass

def compute_avg_pairwise_correlation(
    returns_wide: pd.DataFrame,
    rolling_days: int = 60,
) -> pd.Series:
    """
    每日计算所有股票两两相关性的均值.
    高 (> 0.5) = systemic shock 期 (2020-03 / 2015-06)
    低 (< 0.2) = 正常
    """
    pass

def alpha_environment_score(
    returns_wide: pd.DataFrame,
    rolling_days: int = 20,
) -> pd.Series:
    """
    综合指标: dispersion / pairwise_corr → 高分 = 适合 trade, 低分 = 该减仓.
    """
    pass
```

**实施步骤**:
- [ ] 新建 `pipeline/dispersion_monitor.py`
- [ ] 接入 `pipeline/regime_detector.py` 作为额外 macro feature
- [ ] 加 rule: alpha_score 在 5d 均值 < 历史 20% 分位 → 减仓 50%
- [ ] 接受标准: 在 2018-02 / 2020-03 / 2024-02 雪球 期间, 信号能提前 1-3 日预警

**预计工作量**: 2 天

---

### 2.2 北向资金 + 两融余额信号

**目标**: 国内特色 macro 信号, 比通用 vol_ratio 更 leading.

**为什么 should**: tushare 有现成数据 (moneyflow_hsgt + margin_detail), 数据质量高, 跟 A 股关联性强.

**文件结构**:
```
pipeline/macro_signals_china.py   ← 新建
data/raw/tushare/hsgt/   ← 新建目录, 拉取北向数据
data/raw/tushare/margin/   ← 已有, 增量更新
```

**接口**:
```python
def get_northbound_features(start: str, end: str) -> pd.DataFrame:
    """
    Returns DataFrame with cols:
        date | hsgt_net_yuan | hsgt_5d_ma | hsgt_20d_ma | hsgt_pct_rank_1y
    """
    pass

def get_margin_features(start: str, end: str) -> pd.DataFrame:
    """
    Returns DataFrame with cols:
        date | margin_balance | margin_5d_chg_pct | margin_pct_rank_1y
    """
    pass

def integrate_to_regime_detector(macro_panel: pd.DataFrame) -> pd.DataFrame:
    """把上述 features 合并到 regime_detector 用的 macro_data."""
    pass
```

**实施步骤**:
- [ ] 在 `scripts/data_pipeline_tushare.py` 加 hsgt 拉取任务
- [ ] 新建 `pipeline/macro_signals_china.py`
- [ ] 在 `pipeline/regime_detector.py` 的 `macro_data` 接受这些新 features
- [ ] 重跑 `scripts/regime_boundary_analysis.py` (jialong 机器) 看新 features 的 lag 相关性
- [ ] 接受标准: 至少 1 个新 feature 与 factor health 的 lag corr > 0.4

**预计工作量**: 3 天

---

### 2.3 Drawdown Control 升级 (proactive 版)

**目标**: 现在的 kill switch 是 reactive (亏了再 halve). 升级成 proactive (DD 在恶化中就 halve).

**为什么 should**: reactive kill 在尾部事件中起作用慢, 30d Sharpe 跌到 0 时, 已经亏了 10%+. 加 velocity 检测能提前 5-10 日反应.

**文件结构**:
```
live/event_kill_switch.py   ← 已有, 升级
```

**新增逻辑**:
```python
def check_drawdown_velocity(
    nav_series: pd.Series,
    window_days: int = 10,
    velocity_threshold_per_day: float = 0.005,  # 0.5%/日
) -> bool:
    """
    最近 N 日, NAV 平均每日下跌速度是否超过阈值?
    超过 → 即使 DD 还没到硬门槛, 也触发 HALVE.
    """
    pass

def check_equity_curve_filter(
    nav_series: pd.Series,
    ma_window: int = 60,
) -> bool:
    """
    NAV 是否跌破 60d MA?
    跌破 → HALVE; 重回 → 恢复. 简单但有效的 trend filter.
    """
    pass
```

**实施步骤**:
- [ ] 在 `live/event_kill_switch.py` 加 2 个新 check
- [ ] 加新 severity level: PROACTIVE_HALVE (比 HALVE 轻一档)
- [ ] 测试: 用 2015-06 / 2024-02 历史数据回放, 验证 proactive 比 reactive 早多少日触发
- [ ] 接受标准: proactive 在 stress 期比 reactive 早触发 ≥ 3 日, false positive rate < 10%

**预计工作量**: 5 天

---

## Tier 3 — Enhancement (scale 30%+ 之前做)

### 3.1 Ensemble Regime Models

**目标**: 当前 regime_detector 只有 1 个简单规则 (vol_ratio + ret_6m). 升级成 3 模型 ensemble.

**为什么不是 Tier 1/2**: 单模型先跑稳 3 个月再讲 ensemble, 否则 ensemble 也是过拟合.

**文件结构**:
```
pipeline/regime_ensemble.py   ← 新建
pipeline/regime_models/   ← 新建目录
    rule_based.py   ← 当前 vol_ratio + ret_6m
    hmm.py          ← Hidden Markov Model (2 state)
    change_point.py ← Bayesian Online Change Point Detection (BOCPD)
```

**接口**:
```python
def ensemble_regime(
    macro_data: pd.DataFrame,
    date: pd.Timestamp,
    voting: str = "majority",   # "majority" | "unanimous" | "weighted"
) -> RegimeReport:
    """
    3 模型独立判断当前 regime, 投票决定最终结论.
    需 majority (2/3) 一致才视为 regime shift.
    """
    pass
```

**实施步骤**:
- [ ] 在 `pipeline/regime_models/` 实现 HMM (用 hmmlearn) + BOCPD
- [ ] 实现 ensemble voting + hysteresis (避免高频翻转)
- [ ] 用 2014-2025 历史数据 backfill, 对比 ensemble vs 单模型的 false positive
- [ ] 接受标准: ensemble false positive rate 比单模型降 50%, true positive rate 不下降

**预计工作量**: 1 周

---

### 3.2 Pre-trade Gate

**目标**: 把 regime gate 扩展为综合 pre-trade check: macro regime + capacity + drawdown state + factor concentration, 任 2 项 fail 就 block.

**为什么不是 Tier 1**: 各组件 (regime / capacity / DD) 必须先单独跑稳, 才能整合.

**文件结构**:
```
pipeline/pre_trade_gate.py   ← 新建
```

**接口**:
```python
@dataclass
class PreTradeReport:
    checks_passed: list[str]
    checks_failed: list[str]
    action: str  # "PROCEED" | "REDUCE" | "BLOCK"
    reason: str

def pre_trade_check(
    target_positions: dict[str, float],
    macro_data: pd.DataFrame,
    nav_series: pd.Series,
    aum: float,
    date: pd.Timestamp,
) -> PreTradeReport:
    """
    综合 4 项 check, 决定本次调仓的 action.

    Checks:
        1. regime_state ≠ HIGH_VOL_LOW_GROWTH
        2. capacity 全部 ≤ 5% ADV
        3. drawdown 状态 ≠ PROACTIVE_HALVE
        4. 因子集中度 (单因子贡献 / 总贡献 ≤ 60%)

    Action:
        4/4 pass → PROCEED
        3/4 pass → REDUCE (50% gross)
        ≤ 2/4 pass → BLOCK
    """
    pass
```

**实施步骤**:
- [ ] 新建 `pipeline/pre_trade_gate.py`, 整合 4 个已有模块
- [ ] 集成到 `pipeline/active_strategy.py`
- [ ] 加日志: 每次 pre-trade 决策完整记录到 `logs/pre_trade_decisions/`
- [ ] 接受标准: 历史回测对比, pre_trade_gate 应在 2018-10 / 2020-02 / 2024-02 时触发 BLOCK, 其余正常 PROCEED 比例 > 90%

**预计工作量**: 5 天

---

### 3.3 Auto Factor Decay 减权

**目标**: rx_factor_monitor 现在是 alert (人去看). 升级为自动: 因子 6 月 IC < 阈值就自动减组合权重.

**为什么不是 Tier 1**: 自动化前必须先有人工监控 6 个月, 确认阈值靠谱.

**文件结构**:
```
pipeline/rx_factor_monitor.py   ← 已有, 升级
pipeline/active_strategy.py     ← 已有, 接入 weight 调整
```

**新增逻辑**:
```python
def compute_factor_weight_adjustment(
    factor_name: str,
    ic_6m: float,
    ic_1y: float,
    base_weight: float,
) -> float:
    """
    根据最近 IC 决定 weight 缩放.

    Rules:
        ic_6m > 0 (且方向正确): weight = base
        ic_6m ∈ [-0.02, 0]: weight = base × 0.7  (轻度衰减)
        ic_6m ∈ [-0.04, -0.02]: weight = base × 0.4  (严重衰减)
        ic_6m < -0.04 持续 2 月: weight = 0  (退役)
    """
    pass
```

**实施步骤**:
- [ ] 在 `pipeline/rx_factor_monitor.py` 加 `compute_factor_weight_adjustment`
- [ ] 在 `pipeline/active_strategy.py` 每月 1 日自动调用, 更新 strategy registry 权重
- [ ] 加 audit log: 每次自动调权写 `journal/factor_weight_changes_YYYYMMDD.json`
- [ ] 接受标准: 历史回测对比, auto-decay 比 fixed-weight 在 2024-2025 期间 max DD 减 ≥ 15%

**预计工作量**: 5 天

---

## Tier 4 — Defer (现阶段不做)

| 项目 | 为什么 defer | 重新评估条件 |
|---|---|---|
| **Tail Hedge (Universa-style OTM puts)** | 永久持仓成本 1-2%/年, 你的 alpha 净收益不够覆盖 | AUM > ¥1 亿 时考虑 |
| **HMM / Markov Switching 形式化** | 学术经典, 实证常常输给简单规则. 等简单的不够再升 | Tier 3.1 ensemble 跑完, 发现简单规则 false positive 仍 > 20% |
| **TDA / Transformer regime classifier** | 前沿不成熟, 需要大算力 + 标注数据 | 团队扩到 5+ 人, 有专职 ML 工程师 |
| **DXY / US10Y / VIX 跨资产** | A 股是相对封闭市场, 北向已捕捉外资 view, 直接看 DXY 噪声大 | 涉足港股 / 中概股策略 时 |
| **Microstructure (order book, limit order arrival)** | 中频策略不需要, 数据成本高 | 上高频策略 (持仓 < 1 日) 时 |
| **Risk Parity / HRP** | 你现在 2 腿, parity 没意义 | 组合 ≥ 5 腿时 |
| **CVaR Optimization** | 比 vol target 复杂 5x, 收益边际 | Tier 1.1 vol target 跑稳 1 年, 仍有尾部超预期时 |

---

## 跨 Tier 依赖关系

```
1.1 Vol Target  ──┐
                  │
1.2 Capacity   ──┼──→ 都进 active_strategy.py 下单前 hook
                  │
1.4 Live monitor ─┘
                  │
1.3 Stress test ──→ 独立, 输出验收数据

[Tier 1 全过]──→ live 5% 上线
                  │
                  ↓
2.1 Dispersion ──┐
                 │
2.2 北向/两融  ──┼──→ 都接入 regime_detector.py 的 macro_data
                 │
                 │
2.3 DD 升级 ────→ 接入 event_kill_switch.py

[Tier 2 全过]──→ live 5% 跑稳 3 月
                  │
                  ↓
3.1 Ensemble regime ──→ 替换 regime_detector 内部
3.2 Pre-trade gate ──→ 整合 1.2 + 2.3 + 3.1 + factor_concentration
3.3 Auto decay ──→ 接入 active_strategy.py weight 调整

[Tier 3 全过]──→ scale 到 30%+
```

---

## 失败回滚策略

每个 item 都必须有"如果上线后实测发现问题, 怎么退"的方案.

| Item | 退出方式 |
|---|---|
| 1.1 Vol Target | scale=1.0 永久, 等价于关闭 |
| 1.2 Capacity | warn_pct/block_pct 调到 1.0 (永远不触发) |
| 1.3 Stress | 仅 reporting, 没有实时 hook, 自动"关闭" |
| 1.4 Live monitor | alert_on=False, 仅记录 |
| 2.1 Dispersion | 不接入 regime_detector, 只 monitor |
| 2.2 北向/两融 | 不接入 regime_detector, 只 monitor |
| 2.3 DD 升级 | 把 proactive_threshold 调到 0 (永远不触发) |
| 3.1 Ensemble | 退回 rule_based 单模型 |
| 3.2 Pre-trade | 全部 check 默认 PROCEED |
| 3.3 Auto decay | 关闭 auto, 退回人工 monitor |

**每个 item 上线时必须先在 paper trade 跑 2 周** (或回测验证), 确认 false positive rate 可接受, 才接到 live.

---

## 工作排期 (示意)

```
Month 1 (Tier 1 全做):
  Week 1: 1.1 Vol Target + 1.4 Live monitor 强化 (并行)
  Week 2: 1.2 Capacity Monitor
  Week 3: 1.3 Stress Test
  Week 4: 集成测试 + 验收 + 上 live 5%

Month 2 (Tier 2, live 5% 期间):
  Week 1: 2.1 Dispersion + 2.2 北向/两融 (并行)
  Week 2: 2.3 DD 升级
  Week 3-4: 集成 + 验收 + live 5% 续观察

Month 3 (Tier 3, live 5% 跑稳 3 月后):
  Week 1: 3.1 Ensemble regime
  Week 2: 3.2 Pre-trade gate
  Week 3: 3.3 Auto decay
  Week 4: 集成 + 验收 + 准备 scale 30%

Month 4+ (scaling):
  根据 live performance 决定何时 scale, 何时 revisit Tier 4
```

---

## 红线 (必读)

1. **Tier 1 不全做完不能上 live 5%** — 没 vol target / capacity / stress / monitor 任一项, 实盘出事就是必然
2. **每个 item 都必须有 unit test + 集成 test + 回滚方案** — 没测试不上线
3. **Tier 2/3 不能跳过 Tier 1** — 没基础就建上层是空中楼阁
4. **AUM scaling 与 Tier 完成度绑定** — 5% (Tier 1) → 30% (Tier 2) → 100% (Tier 3) → ¥1 亿+ (Tier 4)
5. **任何 item 实盘失效 → 立刻退到 fallback 模式, 不修补** — 修复在 paper / backtest 完成

---

## 验收 checklist (打勾即可上线)

### Tier 1 (4 项, must-have)
- [ ] 1.1 Vol Targeting — `pipeline/vol_targeting.py` + 单元 + 集成 + DD 减 20%
- [ ] 1.2 Capacity Monitoring — `pipeline/capacity_monitor.py` + ¥1000 万 AUM 无 blocked
- [ ] 1.3 Stress Test — `scripts/stress_test.py` + 单日 < 8% / 单周 < 15%
- [ ] 1.4 Live vs Backtest 强化 — daily zscore + 3σ alert + kill 联动

### Tier 2 (3 项, should-have)
- [ ] 2.1 Cross-sectional Dispersion — 2018-02/2020-03/2024-02 提前 1-3 日预警
- [ ] 2.2 北向 + 两融信号 — 至少 1 个 feature 的 lag corr > 0.4
- [ ] 2.3 Drawdown Control 升级 — proactive 比 reactive 早触发 ≥ 3 日

### Tier 3 (3 项, enhancement)
- [ ] 3.1 Ensemble Regime — false positive 降 50%
- [ ] 3.2 Pre-trade Gate — stress 期触发 BLOCK, 正常期 > 90% PROCEED
- [ ] 3.3 Auto Factor Decay — auto-decay vs fixed-weight, max DD 减 ≥ 15%

### Tier 4 (defer)
- [ ] 不做, 等触发条件

---

## 附录: 与现有文件的整合点

| 新增文件 | 整合到 | 整合方式 |
|---|---|---|
| `pipeline/vol_targeting.py` | `pipeline/active_strategy.py` | 下单前 hook, 缩放 target gross |
| `pipeline/capacity_monitor.py` | `pipeline/active_strategy.py` | 下单前 hook, cap 单股头寸 |
| `pipeline/dispersion_monitor.py` | `pipeline/regime_detector.py` | macro_data 加 features |
| `pipeline/macro_signals_china.py` | `pipeline/regime_detector.py` | macro_data 加 features |
| `pipeline/regime_models/*.py` | `pipeline/regime_ensemble.py` | 子模型 |
| `pipeline/pre_trade_gate.py` | `pipeline/active_strategy.py` | 下单前 hook, BLOCK 时跳过本次 |
| `live/event_kill_switch.py` (升级) | `pipeline/live_data_service.py` | 已接入, 加新 trigger |

---

— 记录: jialong + xingyu
— 起始: 2026-04-23
— 完成预期: 2026-07-31 (3 个月内 Tier 1+2+3 全过)
— 状态: planning, 待 jialong 批准 priority + 资源分配
