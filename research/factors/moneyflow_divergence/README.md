# MFD — MoneyFlow Divergence

**状态**: 2026-04-22 首轮评估完成, **反转因子** (原做多假设被证伪), 单独 IC < 0.03 门槛不过
**Issue**: #33

## 原假设 (被证伪)

elg (超大单) = 机构资金, sm (小单) = 散户资金, 两者 cross-section divergence 给 smart vs dumb 信号.
**期望**: elg 净流入高 + sm 净流入低 = bullish.

## 实证结果 (5.5 年样本)

**IC 稳定为负**. 即 elg 净流入高的股票**未来收益跑输**:

| 分段 | n | IC | ICIR | HAC t |
|---|---:|---:|---:|---:|
| FULL 2020-06~2025-12 | 268 | −0.020 | −0.33 | −4.28 |
| OOS 2025 | 45 | −0.024 | −0.45 | −4.19 |

## 对失败的真实解读

1. tushare moneyflow 的 elg 按单笔金额分类 (> 100 万元), 不等于机构真实资金
2. 尾盘对倒拉高出货 / 主力派发都会制造 "elg 净流入" 假象, 引散户接盘
3. 2025 年量化化上升后这个 trap 更加稳定, OOS IC 绝对值甚至比 IS 更大
4. **真正方向**: 做空 elg 净流入假象高的股, 做多 sm 净流入 (散户恐慌低位筹码) 的股 — 不过 IC 绝对值 0.02 仍不过门槛

## 和 RIAD 的关系

- 二者都是 smart/dumb divergence mechanism
- 合成 (RIAD+MFD) IC=0.069 ≈ RIAD 单独 0.070 → MFD 无增量
- 推测原因: RIAD 已抓到 retail-attention 层面, MFD 的资金流层面 correlated

## 下一步候选方向

- [ ] 时间窗改短 (5 日) 测拉高出货 T+2 反转是否更强
- [ ] 和 `limit_list/` 涨停事件联动: 涨停当日 elg 净流入 → 次日 T+1 反转概率
- [ ] 和 `daily_basic.turnover_rate_f` 联动: 只在高换手股上 (retail-dense) 打分

## 代码

- `factor.py` — MFD 因子计算
- `evaluate_mfd.py` — IC/ICIR + 分层回测
- `combined_eval.py` — 与 RIAD 合成评估
