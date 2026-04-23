# LULR v2 Pre-Registration — 动量假设
_2026-04-22 pre-registration, 触发条件 = `journal/regime_decision_tree_20260422.md` Scenario C1_

## 修订理由 (vs LULR v1)

**v1 (`research/factors/limit_up_ladder/factor.py`)**:
- 假设: 高位连板 + 封板紧 = 情绪末端 → **做空** LULR 高 (sign = -1)
- IS (2019-2023) 失败, OOS (2024+) 反转
- 2025 起 1 年 IC = **+0.042** (`pipeline/rx_factor_monitor.py` 监控读出, 详见
  `journal/rx_factor_monitor_first_readout_20260422.md`)

**v2 (本 spec)**:
- 假设: 高位连板 + 封板紧 = **龙头确认** → **做多** LULR 高 (sign = +1)
- IS = 2024-09 ~ 2025-09 (12 月), OOS = 2025-10 ~ 2025-12 (3 月) + 待续 paper trade
- 这是 **新研究问题**, 不是 v1 的参数调整, 必须独立 pre-reg + 独立 5-gate

> **红线**: 不能直接 flip v1 的 sign 上线. 必须把 v2 当全新策略走完 WF + gate.
> 之所以走这条路, 是因为 rx_factor_monitor 持续读出正 IC 不是巧合, 而是
> 2024-09 后 9·24 政策 + 量化打板逻辑反转的结构性变化 (见 cross_factor_regime_shift).

---

## 1. 因子定义 (照搬 v1 compute_lulr_factor)

**信号源**: `research/factors/limit_up_ladder/factor.py::compute_lulr_factor`
**因子值**:
```
tightness  = 1.0 if limit_type == 'U' else 0.3 if 'Z' else -1.0  (D 跌停)
fragility  = open_times (当日炸板数)
streak     = up_stat 'N/M' 的 N (连板天数)
LULR_raw   = log1p(streak) * tightness - 0.3 * log1p(fragility)
```

**v2 信号方向**: **做多 LULR 高**, 做空 LULR 低 (与 v1 完全相反)
**Universe**: 当日出现在 `data/raw/tushare/limit_list/limit_list_YYYYMMDD.parquet`
              的所有股票 (约 100 只 / 日)
**Cross-section**: 仅在 universe 内排序, 不做全 A 截面

---

## 2. 信号生成节奏 + 持仓窗口

**调仓**: 每日 EOD 生成信号, 次日开盘交易 (shift-1 已生效)
**持仓窗口**: 5 交易日 (短周期, 与 v1 一致)
**实现路径**: `pipeline/lulr_v2_signal.py` (新建, 待 jialong 批准 v2 spec 后实现)

```python
# 伪代码 — 不在本 commit 实现, 只是 spec
def generate_lulr_v2_signal(date_t):
    long = load_limit_list(date_t - 1, date_t)  # 当日上榜
    wide = compute_lulr_factor(long)            # raw factor
    latest = wide.iloc[-1].dropna()
    if len(latest) < 20:
        return None  # 上榜数太少, 不交易
    long_list = latest.nlargest(int(len(latest) * 0.3))   # 高 LULR 做多
    short_list = latest.nsmallest(int(len(latest) * 0.3)) # 低 LULR 做空
    return {"long": long_list.index, "short": short_list.index}
```

---

## 3. Universe 过滤 (强制)

| 过滤项 | 来源 | 影响 |
|---|---|---|
| ST / *ST | `tradability_filter` | long & short 都剔 |
| 新股 (上市 < 60 日) | `tradability_filter` | long & short 都剔 |
| 停牌 | suspend 数据 | long & short 都剔 |
| 涨停封死无法买入 | `daily_basic.up_limit` | long 当日剔 (排队不到) |
| 跌停封死无法卖出 | `daily_basic.down_limit` | short 当日剔 |
| 不在两融标的 | `margin universe` | short 剔 |

**注意**: limit_list universe 本身就是涨停股, **当日做多无法成交**.
策略实际是"次日开盘买入今日 LULR 高的股", 必须在回测里用次日 open 价成交,
不是 close. 详见 §6.

---

## 4. 中性化

v1 没做中性化 (universe 已天然过滤). v2 沿用:
- **不做** size 中性化 (上榜股市值分布有信息: 龙头确认通常发生在中盘 30-200 亿)
- **不做** industry 中性化 (题材本身是 industry-clustered, 中性化掉就没信号)
- **做** beta 中性化的 long-short 等市值组合 (long gross = short gross)

> 与 RIAD/MFD 不同, LULR v2 是事件驱动 + 短周期, 不需要传统中性化.

---

## 5. 加权 + 仓位

**Long-Short 等市值** (gross 1.0):
- long leg 等权 (一组 ~30 只)
- short leg 等权 (一组 ~30 只)
- 总 gross = long gross + short gross = 1.0

**单股上限**: 5% gross (因 universe 小, 防止单股权重过高)

**调仓换手**: 每日重新平衡上榜股, 估计单边换手 ~30% / 日 (高换手是 LULR 的固有成本)

**成本**: 单边 0.15% (双边 0.30%) × 30% 换手 = 9 bps / 日 = 22.5% 年化成本

> **警示**: 这是非常高的成本, 必须在回测里精确扣除. v2 如果不能跑出年化 > 30% 毛收益,
> 净收益就是负的. 这是 v2 能否过 gate 的核心难点.

---

## 6. Walk-Forward 验证计划

**总样本**: 2024-09 ~ 2025-12 (16 个月, 约 320 个交易日)

| Fold | Train | Test | 备注 |
|---|---|---|---|
| 1 | 2024-09 ~ 2025-02 (6 月) | 2025-03 ~ 2025-05 (3 月) | 早期 sample |
| 2 | 2024-12 ~ 2025-05 (6 月) | 2025-06 ~ 2025-08 (3 月) | 中期 |
| 3 | 2025-03 ~ 2025-08 (6 月) | 2025-09 ~ 2025-11 (3 月) | 近期 |

**注意**: 训练窗口仅用于"确认正 IC 持续", 不调参. v2 不在 WF 期间 tune 任何参数,
所有参数在本 spec 锁死, 仅用 WF 验证策略稳定性.

**实现**: `utils/walk_forward.py::walk_forward_test` 可直接用,
传入 `pipeline/lulr_v2_signal.py::generate_lulr_v2_signal` 作为 `strategy_fn`.

---

## 7. 5-Gate 标准 (硬门槛)

参照 spec v3 §10 的 4/5 gate 标准:

| 指标 | 阈值 | 说明 |
|---|---|---|
| Sharpe (净收益) | > 0.8 | 扣 22.5% 成本后 |
| Sharpe (毛收益) | > 1.5 | 必须高, 因为成本高 |
| Annualized Return (净) | > 15% | |
| Max Drawdown | < 30% | |
| DSR | > 0.95 | 选择偏差校正后 |
| PSR | > 0.95 | Probabilistic SR |
| WF 中位 Sharpe | > 0.5 | 3 fold 中位 |
| WF Q25 Sharpe | > 0 | 3 fold Q25 |

**最低过 4/5** 才能上线 paper trade. **过 5/5** 才能进 live (5%).

---

## 8. 触发条件 (when to deploy)

v2 spec **只在以下情况激活**:

1. `journal/regime_decision_tree_20260422.md` 判读为 **Scenario C** (RIAD 彻底失效)
2. **且** jialong 选择 C1 路径 (用 LULR v2 替代 RIAD 腿)
3. **且** v2 在 WF 上过 4/5 gate

否则本 spec 仅作为"备选 spec"存档, 不实施.

---

## 9. Kill 条件 (post-deploy)

如果 v2 上线 (paper 或 live), 任一触发即 kill:

| 条件 | 阈值 | 动作 |
|---|---|---|
| LIVE 1 月 Sharpe | < 0 | WARN |
| LIVE 2 月 Sharpe | < 0 | HALVE 仓位 |
| LIVE 3 月 Sharpe | < 0 连续 | HALT |
| LIVE 单月 MDD | > 8% | COOL_OFF (停 2 周) |
| 实际成本 / 模拟成本 | > 1.3x | 重估 spec, 暂停 |
| 上榜股 < 50 只 / 日 持续 1 周 | (universe 萎缩) | HALT |

实现路径: 沿用 `live/event_kill_switch.py`, 只需加 LULR 专属的成本和 universe 监控.

---

## 10. 与 v3 BB-only / RIAD 的关系

| Spec | 状态 | LULR v2 触发后 |
|---|---|---|
| v3 BB-only (DSR#30) | live 5% (待 jialong 批准) | 不动 |
| v4 RIAD + DSR#30 50/50 | pending 批准 | 若 RIAD 死, v4 砍 RIAD 腿 |
| v5 (本 spec 触发) | LULR v2 + DSR#30 50/50 | 等价于"v4 把 RIAD 换成 LULR v2" |

**正交性要求**: v5 上线前必须验证 LULR v2 vs DSR#30 BB-only 的 60d rolling correlation
p90 < 0.30 (与 RIAD 同样的 stacking 门槛).

---

## 11. 实现 checklist (jialong 批准后)

- [ ] 实现 `pipeline/lulr_v2_signal.py` (锁定参数)
- [ ] 跑 WF: `python -m utils.walk_forward --strategy lulr_v2 --train 6m --test 3m`
- [ ] 跑 5-gate: `python -m pipeline.risk_gate --metrics outputs/lulr_v2_metrics.json`
- [ ] 算正交性: `python scripts/orthogonality_check.py --pair lulr_v2,dsr30_bb`
- [ ] 写 spec v5: `journal/paper_trade_spec_v5_lulr_v2_dsr30_combo_YYYYMMDD.md`
- [ ] paper trade 1 月对照
- [ ] live 5% (再 1 月观察)

---

## 12. 红线 (必读)

1. **本 spec 不在 commit 时实施**, 只是预注册文档. 触发条件未满足前不做任何代码改动
2. **不能因为 LULR 现在 IC +0.042 就直接 flip v1 上线** — 必须走完 WF + 5-gate
3. **Universe 萎缩风险**: 如果 2026 后涨停股数下降 (注册制 + 全面 T+0?),
   v2 universe 可能不足以支撑组合. 必须监控 universe size.
4. **正反方向独立 pre-reg**: 即使 v2 失败, 也不能再返回 v1 (v1 已死). 任何新假设必须新 spec.
5. **不允许 v1 + v2 同时存在** — 二者方向相反, 同时上线就是对冲掉自己

---

— 记录: xingyu (按 jialong 同意的研究方向)
— 触发: regime_boundary_analysis.py 结果显示 Scenario C
— 状态: pending (待 jialong 批准 + WF 通过)
