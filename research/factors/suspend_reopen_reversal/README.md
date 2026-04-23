# SRR — Suspend-Reopen Reversal

**状态**: 2026-04-22 首轮评估完成, **regime-dependent**, 不稳定 alpha.
**Issue**: #33 差异化因子轨道

## 假设

A 股停牌常见原因 (资产重组 / 澄清公告 / 监管关注 / ST 检核), 复牌后有显著的
"信息重新 price-in" 过程. 停牌 duration 作为 cross-section signal, 预测
T+1~T+5 反应方向.

## 数据

- `data/raw/tushare/suspend/suspend_YYYYMMDD.parquet` (2015+, 每日 S/R 事件)
- 实际 R (复牌) 记录稀疏, 改用 "连续 S 结束" 推导复牌日

## 构造

1. 扫描所有 suspend_*.parquet 为 long 表 [ts_code, trade_date, suspend_type]
2. 每只股票按日期排序 S 事件, 相邻 gap > 1 交易日即 "前一段停牌结束"
3. resume_date = 最后一个 S 日的下一交易日; duration = 该段 S 跨度天数
4. 过滤 duration >= 3 (剔除技术性停牌)
5. 复牌后 hold_days=5 天内 factor 值保留 (log1p(duration)), 其他日 NaN

## 首轮结果 (2022-01 ~ 2025-12, fwd=5, sample_cadence=1, min_stocks=3)

| 分段 | n | IC | ICIR | HAC t | Status |
|---|---:|---:|---:|---:|---|
| FULL | 101 | -0.005 | -0.009 | -0.07 | ❌ dead |
| IS (2022-2024) | 55 | **+0.055** | +0.088 | +0.54 | ✅ healthy (但 t 不显著) |
| **OOS 2025** | 46 | **-0.077** | -0.159 | -0.95 | ✅ healthy (方向翻转) |

关键发现:
- **IS 和 OOS 符号翻转**: 2022-2024 长停 → 复牌涨 (资产重组解释), 2025 长停 → 复牌跌 (监管/崩盘解释)
- HAC t 都 < 1, 所有段统计不显著
- 样本量小 (每日平均 6 只有效股), cross-section IC 信噪比差

## 结论

**不适合独立做策略**:
- regime-dependent, 符号翻转本身就是 warning
- 样本稀疏, IC 置信区间宽
- 若要用, 必须配 A 股 2025 后监管框架变化的 regime 分类 (不在本因子 scope 内)

## 可能后续 (不急)

- 拆停牌原因分组评估 (需要 anns_d 公告数据, tushare token 缺权限)
- 结合 pledge/financial_distress 状态: 长停 + 高质押 → 更可能崩
- Event study (T+1~T+20 累计 excess return) 替代 cross-section IC

## 验证 framework/runner

本因子作为 `research/factors/_template/` 的首个新因子, 验证:
- ✅ `factor.py::compute_factor(start, end)` 标准接口 work
- ✅ `scripts/run_factor_evaluation.py` runner 支持 `--min-stocks 3` 事件因子模式
- ✅ 自动生成 `journal/<mod>_eval_YYYYMMDD.md` + `logs/*.json`

runner 发现的 limitation:
- quintile_backtest 需要 min_stocks=n_groups*5=25, 事件因子 (~6 股/日) 会返回 NaN 分层
- 已 gracefully 处理 (分层显示 n/a), 不影响 IC 部分
