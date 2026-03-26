# Skipped Verifications

## 2026-03-24: strategy_eval.py 运行验证

- **原因**: 本地无 A 股价格数据，脚本在数据加载阶段超时
- **已验证**: import 正常（compute_ic_series, ic_summary, quintile_backtest）
- **代码变更**: 纯逻辑替换，无新 API 调用，类型和签名匹配已人工核实

## 2026-03-25: v6 admission eval — baseline vs 止损对照

- **命令**: python scripts/v6_admission_eval.py --stop-loss --output auto
- **失败原因**: 本地无 A 股数据，data/cache/pb_wide.parquet 不存在
- **所需数据**:
  - data/cache/pb_wide.parquet — 宽表格式的市净率（PB）数据，需在有行情数据的机器上提前运行缓存脚本生成
  - 全量股票价格数据（load_price_wide 从本地 data/ 目录读取）
  - 沪深300指数历史行情（get_index_history）
- **已验证**: 所有模块 import 正常（utils.data_loader, utils.metrics, utils.factor_analysis），脚本语法 OK（ast.parse 通过）
- **代码状态**: 无错误，纯数据缺失，需在有本地行情数据的环境中重跑
- **对应任务**: v6 admission eval with stop-loss comparison, journal output
