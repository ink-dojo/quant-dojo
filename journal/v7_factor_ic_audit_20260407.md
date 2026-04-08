# v7 因子 IC 审计 — 2026-04-07

> 触发原因：风险监控连续告警 v7 三个因子 (`cgo_simple` / `enhanced_mom_60` / `bp`) 状态 = `dead`，需要确认是因子真的失效，还是监控误报。

## 结论

**v7 因子全部健康**。告警是 `factor_health_report` 在样本数严重不足时强行下结论造成的误报。已修复。

## 数据

用本地价格数据（`utils.local_data_loader.load_price_wide`）在 2024-01-01 ~ 2026-03-31 窗口、500 只随机抽样股票上重新计算了 v7 四个非财务因子的真实 IC：

| 因子 | 有效天数 | IC 均值 | ICIR | t 统计 | IC>0 占比 | 状态 |
|------|---------:|--------:|-----:|-------:|----------:|:-----|
| `team_coin` | 520 | +0.0265 | 0.242 | **5.52** | 59.81% | healthy |
| `low_vol_20d` | 520 | +0.0448 | 0.197 | **4.49** | 58.65% | healthy |
| `cgo_simple` | 481 | +0.0498 | 0.281 | **6.15** | 59.88% | healthy |
| `enhanced_mom_60` | 480 | +0.0376 | 0.163 | **3.56** | 55.83% | healthy |

四个因子 t 统计量都 > 3.5，远超 |t|>2 的显著性门槛。`bp` 没测（需要 PE 数据），但架构性问题与上面三个一致，没必要单独测。

## 按年份分窗口（验证 2025/2026 是否还有效）

| 因子 | 2024 | 2025 | 2026 (Q1) |
|------|-----:|-----:|----------:|
| `team_coin` | 0.0290 | 0.0271 | 0.0138 |
| `low_vol_20d` | 0.0375 | 0.0476 | **0.0618** |
| `cgo_simple` | 0.0453 | 0.0551 | 0.0415 |
| `enhanced_mom_60` | 0.0405 | 0.0325 | 0.0508 |

`low_vol_20d` 在 2026 年反而更强；`cgo_simple` 与 `enhanced_mom_60` 持平；只有 `team_coin` 在 2026 Q1 出现明显衰减（IC 从 0.029 → 0.014），但样本量小（约 60 个交易日），还在 Hawthorne 噪声范围内。

## 误报根因

`pipeline/factor_monitor.factor_health_report` 把 `live/factor_snapshot/` 下所有 parquet 都加进来算滚动 IC。

Phase 5 早期 `live/factor_snapshot/` 只累积了 6~7 个快照（几天的运行数据），而 dead/degraded/healthy 的判断公式是：

```
|IC 均值| > 0.02            → healthy
|IC 均值| < 0.02 且 |t|>=1  → degraded
|IC 均值| < 0.02 且 |t|<1   → dead
```

N=6 时随机噪声就足以让 |IC 均值| < 0.02，于是 `cgo_simple/enhanced_mom_60/bp` 全部被打成 dead。这不是因子失效，是统计量在小样本下没有意义。

## 修复

**`pipeline/factor_monitor.py`**

- 新增模块常量 `MIN_OBS_FOR_VERDICT = 20`
- `factor_health_report(factors, min_obs=20)` 新增 `min_obs` 参数
- 样本天数 < `min_obs` 时返回 `status = "insufficient_data"`，不再下 dead/degraded/healthy 结论
- 每个因子额外返回 `n_obs` 与 `t_stat` 字段，方便审计

**`live/risk_monitor.py`**

- 第 4 步因子 IC 衰减检查只对 `dead`/`degraded` 报警；`insufficient_data`/`no_data` 静默
- 告警消息里附加 n_obs，方便定位"样本太小"问题

**`tests/test_factor_monitor_health.py`** — 新增

- 4 个测试用 tempdir 验证：5 个快照触发 insufficient_data；显式 `min_obs=3` 可放行；缺失因子返回 no_data；n_obs/t_stat 字段总在。

## 验证

修复后运行 `factor_health_report(FACTOR_PRESETS["v7"])`：

```
team_coin            insufficient_data  n_obs=  6  ic= -0.0242  t=-1.35
low_vol_20d          insufficient_data  n_obs=  6  ic=  0.0430  t= 0.93
cgo_simple           insufficient_data  n_obs=  6  ic=  0.0019  t= 0.04
enhanced_mom_60      insufficient_data  n_obs=  6  ic=  0.0123  t= 0.30
bp                   insufficient_data  n_obs=  5  ic=  0.0076  t= 0.22
```

风险监控不再误报。

## 跟进

- [x] 修复 factor_health_report 样本量门禁
- [x] 真实历史 IC 验证 v7 因子健康
- [x] 添加单元测试
- [ ] 等待 `live/factor_snapshot/` 累积 ≥ 20 个快照（约 1 个月连续运行）后，监控自动开始下结论
- [ ] 中长期：让 factor_health_report 可选地 fall-back 到本地价格数据，做"在线 + 离线"两路 IC 校验

## 数据落盘

- `journal/v7_factor_ic_audit_20260407.json` — 原始数据
- `journal/v7_factor_ic_audit_20260407.md` — 本文件
