# RX Factor Monitor 首轮观察纪要 — 2026-04-22

> 基础设施: `pipeline/rx_factor_monitor.py` + `scripts/monitor_rx_factors.py`
> 自动报告: `journal/rx_factor_health_20260422.md` + `logs/rx_factor_health_20260422.json`
> 本文: 人工判读 + 行动建议

## 六个因子的最新状态

| 因子 | 1 年窗口 IC | 6 月窗口 IC | 1 年状态 | 6 月状态 | 判读 |
|---|---:|---:|---|---|---|
| **RIAD** | -0.052 | -0.045 | ✅ | ✅ | 唯一两窗口都过门槛, 微弱衰减但仍显著 |
| **LULR** | +0.042 | +0.039 | ✅ | ✅ | 正 IC 颠覆了原 baseline 的'反转'假设 |
| MFD | -0.028 | -0.002 | ⚠️ | ❌ | 6 月窗口已掉 dead, factor decay 进行中 |
| BGFD | +0.004 | +0.011 | ❌ | ❌ | 去年的 'follow consensus' alpha 消失 |
| THCC_inst | -0.009 | -0.013 | ❌ | ❌ | 季报滞后 1.5 月 + 反向信号本身弱 |
| SB | -0.002 | +0.007 | ❌ | ❌ | 一贯 null, 无意外 |

## 判读与行动

### 1. RIAD — 持续 healthy 但有趋弱迹象

- 1 年 IC -0.052 vs 3 年累计 -0.070 → **约弱 26%**
- 6 月 IC -0.045 vs 1 年 -0.052 → **再弱 14%**
- Fold 3 诊断 (Issue #36) 找到的 3 个原因正在验证:
  结构性 long leg 失效 + 散户题材板块反转 + stk_surv 数据滞后
- **行动**:
  - 不 live, 不调参 (pre-reg 红线)
  - 每月跑一次 monitor, 如 6 月 IC 掉 < -0.03 → 触发研究重评
  - 等 2025 Q4 stk_surv 数据补录 (tushare 3-6 月后 refresh) 重算 Fold 3 的 inst leg

### 2. LULR — 正 IC 是新发现, 颠覆原假设

- 原研究 (evaluate_lulr) 用 "做空高连板" 假设, IS 2019-2023 失败, 2024 开始反转
- 现在 1 年 IC +0.042 (显著!) 意味着 **高连板股实际跑赢炸板股**
- 这不是反转, 是 **动量回归**
- 可能解释:
  - 2025 年量化打板策略已被"打爆后反弹"策略吃掉一部分, 新的"封板坚定 = 龙头股确认"逻辑抬头
  - 游资回暖 + 监管放松 (9·24 后) 让连板题材持续更久
- **行动**:
  - 不能直接 "开反方向 LULR 策略" — 这违反 pre-reg
  - 开新研究轨道 **LULR v2** (momentum hypothesis), 独立 pre-reg + 样本外回测
  - 继续用现状监控, 看 sign flip 是 regime 还是 persistent

### 3. MFD — 半失效, 即将 KILL

- 1 年 degraded, 6 月 dead
- 反转假设 ("大单净流入 ≠ smart money") 最近失效
- 可能原因: tushare elg 分类算法更新? 或者 2025 后半年市场结构变化让尾盘对倒减少
- **行动**:
  - 连续 2 个月 dead → 从 registry 移除或标记为 historical
  - 不再扩展 / 不再合成

### 4. BGFD / THCC / SB — 稳定 dead

- 从首轮就没过门槛, 最新监控确认
- 无 further action, 保留在 registry 作为对照

## 基础设施的下一步 (研究导向)

### 4.1 每周自动跑 cron (未来可选)

```bash
# crontab -e (或 launchd)
# 每周六本地 10:00 跑 monitor
0 10 * * 6  cd /Users/karan/work/quant-dojo && \
    /usr/local/bin/python3 scripts/monitor_rx_factors.py --window 252 --short-window 120 \
    >> logs/rx_monitor_cron.log 2>&1
```

暂时不急设置 (研究为主, 非 live).

### 4.2 集成到 weekly_report (未来可选)

`pipeline/weekly_report.py` 已有 `_try_factor_health()` + `_render_factor_health_section()`,
调用的是 legacy factor_monitor. 可加一个 `_try_rx_factor_health()` 把本 monitor 输出拼到周报.

### 4.3 扩展 registry (等 D 阶段挖新因子时)

每个新因子只需:
1. 写 `research/factors/<name>/factor.py` 里的 `compute_xxx()` 返回 wide df
2. 在 `pipeline/rx_factor_monitor.py` 加一个 `_build_xxx` 包装 + 在 `RX_REGISTRY` 注册
3. CLI 自动包含

## 红线

- 不基于 6 月 IC 结果调 RIAD/MFD/... 参数 (本文是 monitoring, 不是 re-fit)
- LULR 正 IC 是"新研究问题", 必须开新 pre-reg, 不能直接 flip 策略方向
- 每次监控结果与历史记录对比 (journal/rx_factor_health_YYYYMMDD.md 按日期存档)

— 记录: jialong
— 更新: 2026-04-22
