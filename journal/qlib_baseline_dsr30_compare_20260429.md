# qlib Alpha158 baseline vs DSR #30 对照（2026-04-29）

> 关联 Issue #48；输入: `research/qlib_baseline/runs/20260429_223928/`
> 决策对象: jialong, xingyu

## 一句话结论

**DSR #30 BB 主板 rescaled 在 2.5y 重叠期点估计 Sharpe 1.03 vs qlib Alpha158-LightGBM 的 0.42**，方向一致。但**这是 single-point estimate**，并不能推翻 Phase 3 全期 OOS 已得的 CI_low 0.20 fail（bootstrap 95% 下界），所以**不能升级为 Tier 1+ 部署的依据**。ensemble 在 2.5y 重叠期同样比 BB 单脚弱（excess 1.21% vs 6.26%），与 jialong 2026-04-28 否决 spec v4 50/50 双腿的判断一致。

## 数据范围（重要 caveat）

| 项 | 值 |
|---|---|
| 重叠期 | 2018-01-02 ~ 2020-09-25 (~667 交易日, 2.5y) |
| 受限于 | qlib v3 PIT universe end 2020-09-25 |
| CLAUDE.md 红线 | "回测时间跨度 > 3 年" → **本次 < 3y 不达标** |

⚠️ 这意味着对照表只能作**参考性外部基线**，不能单独 go/no-go DSR #30 paper-trade —— 真正决策仍要看 DSR 完整 2018-2026 区间。

## 对照表（全部对齐 CSI300 benchmark + 单边 0.15% 成本）

| 候选 | n_days | 年化 net | 年化 excess | net Sharpe | excess Sharpe | MaxDD | 胜率 | 累计 net |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| qlib Alpha158-LightGBM | 667 | 7.74% | 3.08% | 0.42 | 0.35 | -28.6% | 51.9% | +21.8% |
| CSI300 benchmark | 667 | 4.86% | — | 0.33 | — | -32.5% | 51.4% | +13.4% |
| **DSR #30 BB 主板 rescaled** | **667** | **14.62%** | **6.26%** | **1.03** | **0.44** | **-17.5%** | **42.9%** | **+43.5%** |
| DSR #30 ensemble (BB+PV+recal) | 667 | 8.63% | 1.21% | 0.63 | 0.16 | -18.3% | 50.2% | +24.5% |

## 关键判断

### 1. BB 主板单脚在 2.5y 重叠期点估计**领先** baseline，但
- net Sharpe **1.03 通过 CLAUDE.md 门槛 > 0.8**（重叠期）
- 年化 14.62% **接近**（但略低于）门槛 15%（重叠期）
- MaxDD -17.5% **远低于**门槛 30%（重叠期）
- 胜率 42.9% < 50% —— 事件驱动 + 反转正常
- **统计有效性 caveat**：用 Lo 2002 公式 SE(annualized SR) ≈ √((1+SR²/2)/T)：T=2.5y, SR=1.03 → **SE ≈ 0.78**，95% CI [-0.5, +2.6]。BB vs qlib 的 Sharpe 差 0.61，**< 1σ**。点估计差距大，但单凭这次对照在统计上**不能 reject 两者 equality**。

### 2. Phase 3 全期 OOS（2018-2025, 7y）才是黄金参考 — 已有结论
来自 `journal/weekly/2026-W16.md:1331` 与 `paper_trade_spec_v4_riad_dsr30_combo_20260422.md`：

| 指标 | 全期 OOS 数字 | 门槛 | 状态 |
|---|---:|---:|---:|
| 年化 net | +15.99% | > 15% | ✅ |
| Sharpe net | 0.84 | > 0.8 | ✅ |
| MDD | -29.68% | < 30% | ✅（险过） |
| DSR | 0.996 | > 0.95 | ✅ |
| **bootstrap CI_low** | **0.20** | **> 0.5** | **❌ FAIL** |
| 总评 | **4/5** | 5/5 | 不达 |

**bootstrap CI_low 0.20 才是黄金标准**（用全期 7y 而非本次 2.5y 切片），它是直接的 Sharpe 不确定性度量。**本次 Phase C 的 single-point Sharpe 1.03 不构成对 CI_low 0.20 的反驳** —— 反而印证了 BB 在某些子区间能很高、但稳健性不够。

### 3. ensemble 比 BB 单脚显著差 → 印证 spec v4 否决
- BB 单脚 excess 6.26% / Sharpe 0.44（本次重叠期）
- ensemble excess 1.21% / Sharpe 0.16（本次重叠期）
- 与 jialong 2026-04-28 否决 spec v4 RIAD+DSR#30 50/50 一致：50/50 摊薄了 BB edge

### 4. qlib baseline 在 CLAUDE.md 成本下挣扎
- without cost: 年化超额 10.67% / IR 1.16
- with cost (单边 0.15%): 年化超额 3.08% / IR 0.35 / Sharpe 0.42
- **成本一刀砍掉 ~7pct 超额** —— A 股 cross-sectional ML 对换手敏感的本质（与 `feedback_ashare_alpha_nuance` 一致）

### 5. Live-Tier v1 框架（2026-04-29 ratified）映射

| Tier | 门槛 | BB 主板单脚现状 | 状态 |
|---|---|---|:---:|
| **Tier 0** (paper-only) | no lookahead + sharpe_net > 0 + 30d paper smoke | BB 全期 Sharpe 0.84 ✓；30d paper smoke 未跑 | **可启动** |
| **Tier 1** (1-5% NAV) | + sharpe_net > 0.5 (双边 0.5% cost) + 全 OOS 切片不 FAIL_IC_FLIP, 至多 1 个 FAIL_NEG_SHARPE | **CI_low 0.20 < 0.5 直接卡死**；切片 fail 状态待 Phase 3 重审 | **❌ 阻塞** |
| Tier 2 | + 60d Tier-1 live + DSR > 0.85 + capacity ¥50万 | 未到 | — |
| Tier 3 | + 12m Tier-2 live + sharpe > 1.0 + DSR > 0.95 + regime transitions | 未到 | — |

## 反方论证（必读）

让 jialong 在做决定前先质疑这次结果的强度：

1. **selection bias**：本次 2.5y 重叠期是 qlib 数据约束硬切的，不是预先 declared 的研究区间。Sharpe 1.03 含子区间运气：BB 在 2018-2021 SR 0.87，2022-2025 SR 1.03（见 `dsr30_decay_check_20260421.md`），**重叠期碰巧落在偏强的窗口**。
2. **CI_low 0.20 是稳健性的硬指标**：它是全期 7y bootstrap 的 95% 下界。点估计 Sharpe 1.03 在 2.5y 子区间的 SE ≈ 0.78，95% CI [-0.5, +2.6] —— 跟 CI_low 0.20 完全 consistent。**没有矛盾，所以不能用本次结果撤销 Phase 3 终结**。
3. **ensemble 拖累 BB 单脚的反向解读**：ensemble 弱 → BB 单脚被「样本内最好」挑出来，可能是 selection bias 而非 BB 真的强。
4. **capacity 上限**：`dsr30_mainboard_recal.py` 已经 leverage ×1.985，gross_cap=1.0 卡位。真实可投资金可能比理论低很多 —— Tier 1 的"1-5% NAV"也许 capacity 已不够。
5. **qlib v3 universe 2020-09-25 截止**：错过了 2021 茅指数瓦解 + 2022 中特估开端 + 2023 AI 行情 + 2024 中特估二段。这些是事件驱动反转策略 BB 最该承压的regime —— 重叠期回测**根本没考验过最坏情况**。

## 给 jialong 的建议（更新）

1. **Tier 0 (paper-only) 可启动**：BB 主板单脚跑 30 天 paper smoke，零部署风险，能积累 live tracking
2. **不要升 Tier 1**：Phase 3 已 4/5 + CI_low 0.20 fail。本次外部 baseline 对照不构成翻案依据 —— 升 Tier 1 需要新实验/新证据，**不是 Phase C 这种 ex post 视角下的 sub-period 对照**
3. **不再考虑 ensemble / 50-50 双腿**：数据明确显示 PV 腿稀释 BB 单脚（这一项 Phase C 与 Phase 3 一致）
4. **追加 issue 列表**（Phase C 不在范围）：
   - akshare 补 OHLCV 全量到 2024（让 baseline 能跑到 2024 含 2021-2024 关键 regime）
   - tushare close-only → qlib bin（issue body 原计划，由于 daily_basic 局限放弃，作为 future infra）
5. 这次外部 baseline 对照的真正价值：**A 股 cross-sectional ML 标准 pipeline 在 0.3% 双边成本下 Sharpe 0.42** —— 这是任何未来 cross-sectional 候选必须超过的硬门槛

## 局限与下一步

- 2.5y 重叠期 < 3y 评审门槛
- qlib v3 universe 2020-09-25 截止 —— 错过了 2021-2022 风格切换 + 2023-2024 中特估行情
- 想扩到 2024 需要 akshare 补 OHLCV 全量，约 1 周工作量，**作为未来 issue**（不在 #48 范围）

## artifacts

- baseline run: `research/qlib_baseline/runs/20260429_223928/`
  - `meta.json` — qlib 0.9.7, lightgbm 4.6.0, seed=2026, deterministic=True
  - `test_report.parquet` — 911 日 portfolio metric
  - `test_signals.parquet` — 273300 行预测分
  - `test_risk_analysis.csv` — qlib 标准 risk metrics
  - `compare_dsr30.json` — 本对照表的 JSON 版
- DSR #30 OOS 来源（已有，未改动）：
  - `research/event_driven/dsr30_mainboard_bb_oos.parquet`
  - `research/event_driven/dsr30_mainboard_recal_ensemble_oos.parquet`
- 对照脚本: `research/qlib_baseline/compare_dsr30.py`
