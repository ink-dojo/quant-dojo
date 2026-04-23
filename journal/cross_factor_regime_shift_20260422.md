# 跨因子 2024 → 2025 Regime Shift 观察

> 日期: 2026-04-22
> 背景: Issue #36 RIAD Fold 3 诊断之后, 继续挖 D1 SRR + D2 MCHG 两个新因子,
>      **独立证实** 了 2024/2025 的 structural shift 不是 RIAD 单一问题.

## 一句话总结

**2024 → 2025 A 股市场出现 structural regime shift**, 在至少 5 个独立因子上引发方向翻转或失效.
这不是某个因子 decay, 是市场微观结构 / 散户情绪 / 监管环境的系统性变化.

## 各因子 2024 vs 2025 对比

| 因子 | 2024 (IS) | 2025 (OOS) | 翻转性质 |
|---|---|---|---|
| **RIAD** (Issue #36) | +IC 0.076 | +IC 0.043 (衰减 44%) | 弱化但未翻转, 但 long leg 失效加剧 |
| **LULR** | 反转 (Short Q5) | **动量** (Long Q5, 正 IC +0.042) | 方向翻转 |
| **MFD** | 反转 healthy IC -0.028 | 最近 6 月 dead IC -0.002 | 弱化接近 dead |
| **SRR** (本轮) | **+IC 0.055** (长停 → 涨) | **-IC 0.077** (长停 → 跌) | **方向翻转** |
| **MCHG** (本轮) | -IC 0.011 degraded | +IC 0.031 healthy | **方向翻转** |
| BGFD | IC ≈ 0 | IC ≈ 0 | 一直 dead |
| THCC | 反向 alpha | 反向 alpha | 稳定 dead |
| SB | null | null | 稳定 null |

## 五个因子的 regime shift pattern

1. **RIAD** — 散户关注度多 → 跑输机构关注度多; 2025 H2 在题材板块失效
2. **LULR** — 2024 "高连板 → 反转" 变 2025 "高连板 → 继续涨" (动量回归)
3. **SRR** — 2022-2024 "长停 → 复牌涨" (重组假设) 变 2025 "长停 → 复牌跌" (监管/崩盘)
4. **MCHG** — 2022-2024 "高管变动 → 跑输" 变 2025 "高管变动 → 跑赢"
5. **MFD** — 2024 "大单 ≠ smart money 反转" 弱化, 但未明显翻转

## 可能的 macro 驱动

(仅假设, 未验证)

- **9·24 后政策信号密集** → 机构 / 游资 / 散户在"政策受益股"共同追涨, attention bias 假设失灵
- **量化策略泛化** → 连板反转 / 打板 / 资金流 factor 被套利成本抬升 → 经典 crowd trades 收敛到 0
- **监管风格变化** → 长停复牌失败率上升, SRR IS → OOS 翻转
- **注册制全面实施** → 高管变动从"治理信号"变"常态披露", MCHG 解释变化
- **散户占比回升 + 经济预期修复** → 题材炒作延续时间增长, LULR 从反转到动量

## 对研究方法的启示

### 1. 不要基于单一窗口的 IC 下结论

- RIAD 若只看 FULL IC -0.07 会 over-confident; 分 IS/OOS/Fold 才看到衰减
- 新因子如果只跑 OOS 2025 单段会看到 +IC 或 -IC, 需要 IS 对照

### 2. 多因子 cross-validation

- 若单个因子方向翻转, 可能是 noise
- **多个独立因子共同翻转**, 大概率是市场 structural shift
- 因子间的 orthogonality (Issue #33) 反而让 cross-validation 更可靠

### 3. 诚实 pre-reg + 不事后调参

- SRR 的 IS +IC 0.055 本来看着 healthy, 若事后把样本切到 2022-2024 然后在 2025 launch 就会踩雷
- pre-reg OOS 2025 评估让我们在 live 之前发现

### 4. Factor monitor 是活的, 不是归档

- `pipeline/rx_factor_monitor.py::RX_REGISTRY` 已加入 SRR + MCHG (共 8 因子)
- 每周/每月跑一次, 可以观察 regime shift 的边界是否持续
- 若 2026 H1 shift 趋稳或进一步加剧, monitor 会早期 flag

## 对 paper-trade 的 implication

- **v4 spec (RIAD + DSR #30 合成) 不再适合**. 原因: v4 假设 RIAD IC 0.07 一致, 事实上已在衰减
- **DSR #30 BB-only v3 单独继续** 是当前唯一推荐 paper-trade 目标 (已 live shadow)
- **RIAD 等新因子全部进入 monitor / shadow, 不进真钱**

## 下一步 (研究方向)

1. 继续扩展 RX registry (D 阶段), 让 cross-factor monitor 更宽
2. 等 tushare 2025 Q4 全量数据补录, 重估 SRR/MCHG/MFD 的 OOS 样本
3. 给 Fold 3 诊断 + 本 regime shift 报告合成一个 "2026-Q2 研究小结" 季度报告
4. 考虑加入 "宏观 regime features" (HS300 6M return, vol, 换手率) 作为 factor 的 conditional gate
