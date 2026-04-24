# VERIFY.md — quant-dojo 验收检查点

每次运行 `/review` 时，逐项检查以下检查点，直到所有项为 ✅ 或 ⚠。

---

## 环境与安装

- ✅ `pip install -e .` 无报错
- ✅ `python -c "from utils import get_stock_history; from agents import LLMClient; print('ok')"` 输出 ok
- ✅ `python -m quant_dojo --help` 不报错，显示命令列表

## 核心 import

- ✅ `from utils.factor_analysis import compute_ic_series, quintile_backtest, ic_summary`
- ✅ `from utils.multi_factor import ic_weighted_composite, equal_weight_composite`
- ✅ `from utils.metrics import sharpe_ratio, max_drawdown, calmar_ratio`
- ✅ `from backtest.standardized import run_backtest, BacktestConfig`
- ✅ `from pipeline.daily_signal import run_daily_pipeline`
- ✅ `from live.paper_trader import PaperTrader`
- ✅ `from live.risk_monitor import check_risk_alerts`
- ✅ `from agents.base import LLMClient, BaseAgent`

## 单元测试

- ✅ `python -m pytest tests/ -q` 676 passed, 0 failed
- ✅ 无回归：`tests/test_phase5_regression.py` 全绿
- ✅ 无回归：`tests/test_control_plane.py` 全绿
- ✅ 无回归：`tests/test_risk_gate.py` 全绿

## 命令行功能

- ✅ `python -m quant_dojo status` — 不崩溃，`days_stale=None` 时显示 `[?] 延迟 未知`
- ✅ `python -m quant_dojo doctor` — 不崩溃，显示诊断信息
- ✅ `python -m quant_dojo update --dry-run` — baostock 未安装或网络不通时优雅跳过，日志提示

## 回测链路

- ✅ `BacktestConfig` 可以实例化并验证 start/end 日期
- ✅ `run_backtest` 在无数据时返回 `status=failed` 而不是崩溃
- ✅ 回测结果持久化失败时记录 warning（不 crash）

## 风险控制

- ✅ `_load_risk_thresholds()` 在配置不存在时返回默认值 `(-0.05, -0.10, 0.15)`
- ✅ `check_risk_alerts` 在空持仓时返回空列表

## 因子分析

- ✅ IC 统计计算失败时记录 warning（不 crash）
- ✅ `factor_decay_analysis` 在 curve_fit 失败时返回默认值（不 crash）
- ✅ `neutralize_factor` lstsq 失败时 fallback 到原始值（不 crash）

## 代码质量

- ✅ `backtest/standardized.py` 无静默 `except Exception: pass`（3 处改为 `logger.warning`）
- ✅ `pipeline/daily_signal.py` IC 计算失败有 `warnings.warn()`
- ✅ `providers/tushare_provider.py` daily_basic/ST 失败有 `logger.debug()`
- ✅ `pipeline/data_update.py` dry_run + baostock 未安装时跳过 provider 初始化

---

## 说明

- ✅ = 检查通过
- ⚠ = 已知限制（如需要本地数据才能完整运行）
- ❌ = 检查失败，需要修复
- ⬜ = 未检查
