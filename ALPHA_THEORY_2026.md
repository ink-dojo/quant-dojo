# Alpha Theory 2026 — quant-dojo 散户赛道定义

> 写作日期: 2026-04-21
> 作者: jialong
> 目的: 回答 "2026 A 股散户账户, 我们在哪里挖 alpha, 为什么挖得到, 不挖哪里"
> 地位: 所有未来 sprint 的**开挖前强制 check**。未在本文件列表里的空间, 不允许开挖。

---

## 0. 为什么写这份

### 0.1 Sprint 1+2 的残酷账本

| Sprint | 挖的因子数 | 过 admission gate | 命中率 |
|---|---:|---:|---:|
| Sprint 1 (2026-04-21 上午, tushare 全数据) | 6 | 2 (F5 crowding, F6 inst_ratio 边缘) | 33% |
| Sprint 2 (2026-04-21 下午, 散户低频) | 4 | 1 (F13 ind_reversal, 真 pb 下边际仅 +0.054 SR) | **25%** |
| 合计 | 10 | 2~3 有效 | **20-30%** |

### 0.2 现有"主力"的真相

| 候选 | long-history 测试 | 结论 |
|---|---|---|
| v9 (production_face) | 未做 | 陈旧 baseline |
| v16 (declared_active) | v34 做了 2018-2025 | **FAIL** (SR 0.64, MDD -38%, 2018 单年 SR -1.69) |
| v17 (Sprint 1 集成) | 只做 2022-2025 短窗口 | 未做长历史 |
| v18 (Sprint 2 集成) | 只做 2025 OOS 一年 | 真 pb 下 Δ SR +0.054, 已否决 |
| **DSR #30 (BB+PV 主板 rescaled)** | 8-yr single-sample 4/5 gate | **CI_low 0.20 fail 为唯一 miss, 2024-2025 SR 1.34** |

### 0.3 诊断

我们一直在用 **2010 学术 quant 框架 (IC/ICIR/分层回测)** 挖 **1995-2015 已被套利完的 anomaly**, 用 **tushare 这种所有人都有的 commodity data**。这个空间:
- 1000+ 学术论文已发表
- 头部量化私募 (幻方/明汯/九坤/宽德) 5-10 年前开吃
- 公募 2019+ 因子化
- 北向资金 dominate 大盘蓝筹定价
- A 股 2023 注册制后信息效率上移, 很多 anomaly 被补刀

**挖第 11 个因子不如 paper-trade 一个已过 4/5 gate 的真能跑的**。

---

## 1. 开挖前强制 check (所有 sprint 必答)

任何新因子/新策略开跑前, 必须先在 pre-reg 里回答:

1. **这个 edge 在 2026 A 股还存在吗?** (给出 1 条最可能的死亡假设)
2. **为什么它还没被套利掉?** 必须指名**谁**做不了 (不能说"没人发现")
   - 容量约束 (capacity too small)?
   - Mandate 约束 (机构不能买)?
   - 工具约束 (需要 LLM/人工 reasoning)?
   - 认知约束 (需要行业深度)?
3. **这个空间属于下面 §2 列出的 5 个活 alpha 空间之一吗?**
   - 属于 → 继续
   - 不属于 → 说明为什么是例外, 否则拒绝开挖
4. **我们的数据 / 工具是否优于私募?** 如果是 commodity data + commodity tool, 拒绝开挖

**不通过以上 4 问, 不允许写代码挖新因子。**

---

## 2. 五个活 alpha 空间 (2026 A 股散户)

### 空间 A — 容量受限 alpha (capacity-constrained)

**定义**: 总容量 < 5 亿 / 单票容量 < 5000 万的策略, 机构规模下不经济。

| 子空间 | 为什么私募做不了 | 散户优势 | 难度 |
|---|---|---|---|
| **微盘股** (<30 亿市值) | 100 亿私募满仓需 200+ 票, 交易冲击 > alpha | 10 万账户做 30 票轻松 | 低 |
| **可转债** T+0 + 下修博弈 | 全市场 1.5 万亿, 单笔套利 < 1 万 | 单户可做, 容量 100 万内丝滑 | 中 (需懂条款) |
| **打新** (一级市场) | 公募 60% 配售优先, 私募网下受限 | 纯散户账户按市值配售, 年化 2-5% 稳定 | 极低 |
| **ETF 折溢价** | 大机构有申赎通道不用二级套利 | 单笔 < 1 亿可做 | 中 |
| **次新股/新股破发** | 容量小 + 新股无历史 | 注册制后 IPO 破发/首日竞价可做 | 中 |

**理论依据**: capacity 是永恒的 structural barrier, 不会被"AI 进步"消除。

**本仓库状态**: **几乎零覆盖**。转债/打新/微盘都没实现, 这是**最被忽略的红利区**。

---

### 空间 B — Regime / 择时 / 风格切换

**定义**: 不是"选哪 30 只股", 而是"现在该不该满仓 + 大/小盘/成长/价值 倾斜"。

**为什么机构做不了**:
- Mandate 绝大多数是"全年满仓 + tracking error 约束", 不能空仓
- 风格漂移在机构考核里是扣分项 (style drift)

**散户优势**:
- 可以从 0% 到 100% 任意调仓位
- 无 tracking error 约束
- 一个对的择时判断 = 1 年股票选择

**典型信号**:
- 货币松/紧 (DR007, 10Y 国债)
- 估值 (沪深 300 PE vs 10 年分位)
- 情绪 (融资余额 / 新基金发行 / 成交额)
- 政策 (中央经济工作会议 / 重大会议前后 20d)

**历史校准**: 2018 空仓 vs 满仓差 40%, 2021 小盘 vs 大盘差 30%, 2024-10 微盘崩盘前撤 vs 持差 25%。

**本仓库状态**: 有 `utils/regime.py` 但没做成完整择时策略。未真正测过。

---

### 空间 C — AI/LLM-native alpha (我们唯一的不对称工具)

**定义**: 用 LLM + Agent 做 **传统 NLP 做不好** 的文本理解。

**为什么私募没全铺**:
- 量化团队文化不是 LLM 文化, 很多还在用 BERT + 字典情感
- 需要"懂 NLP + 懂金融 + 懂 prompt engineering"三合一
- LLM 输出是 unstructured, 融入 pipeline 是工程 overhead
- A 股本地更落后, GPT-4 级别的中文金融 NLP 并未普及

**散户 (我们) 优势**:
- 有 Claude / Claude Code / agents 基础设施
- jialong 金融 + Claude 工程, 天然配对
- 没有"必须解释 alpha 来源"的合规负担

**具体信号候选**:

1. **MD&A 语义漂移**: 同一公司跨年年报管理层讨论语言一致性。漂移 + hedging 语言增多 = 前瞻性负面。
2. **公告-政策 cross-reference**: 公司 A 披露业务 × 行业政策 B × 宏观 C → 条件信号
3. **研报共识深读**: 不是研报评级, 是研报之间的**分歧/一致语言学**, 找 consensus trap
4. **新闻事件分类桶**: 实时分"已定价 vs 未定价", "事件 vs 噪音"
5. **电话会议情绪**: 管理层 Q&A 答非所问率, 话题回避率

**本仓库状态**: `agents/` 有骨架 (LLMClient + BullBearDebate) 但**从未作为 factor 输出**进入回测流。这是最大的 untapped potential。

---

### 空间 D — 行为偏差 alpha (behavioral, 永不套利完)

**定义**: 利用散户**永远存在**的心理偏差。区别于"事件驱动 alpha" (被私募套利), 行为 alpha 的对手是人性, 不会死。

**为什么不会被套利掉**:
- 做空偏差 (散户逢低抄底, 逢高恐慌): 情绪永恒
- Loss aversion: 止损比止盈慢
- Anchoring: 锚定 52w 高/低
- Overreaction: 极端波动后反转

**具体信号候选**:

1. **短期反转** (cross-sectional 1-20d): 经典 Jegadeesh reversal, A 股至今有效, 因为散户占比还高
2. **Low vol** (risk preference anomaly): 散户偏好高波 → 低波长期跑赢
3. **极端单日事件后反转**: 涨停打开后 reversal, 跌停打开后 reversal
4. **舆论一致度** (new): 雪球/东财热度极端时反转

**本仓库状态**: low_vol_20d 已经在 v16/v17 里。短期反转 (1-5d) 没系统做过。

---

### 空间 E — 认知/行业深度 alpha

**定义**: 单一行业/单一资产类别做到 top 10% 深度。

**为什么是 alpha**:
- 私募要覆盖全市场, 单行业深度有限
- 行业专家投资者 (巴菲特式) 的 edge 来源
- jialong 如果对某行业 (半导体/新能源/医药/消费) 有 insider 级认知, 私募 analyst 追不上

**散户独特优势**:
- 只挑 1-2 个行业, 100% 精力
- 可以追踪 level-3 数据 (经销商访谈, 产业链调研, 小红书/知乎)
- 持仓周期可以 3-5 年 (机构做不到)

**本仓库状态**: **零**。这是长期方向, 不是短期 sprint 能出产出的, 但作为战略应该留位。

---

## 3. 明确不再挖的空间 (red zone)

以下方向 **不允许再开新 sprint**, 除非给出强反证:

### 3.1 Commodity factor 挖掘 (STOP)
- ❌ 动量/价值/质量/低波动 的第 N 个变体
- ❌ PEAD, insider trading, lockup pressure (三次证伪: 2023+ 注册制吃掉 PEAD, 机构提前定价吃掉 insider, 解禁是 size 代理)
- ❌ 纯量价因子拼接 (v16 style 9 因子组合)
- ❌ 行业动量/反转 (Sprint 2 F13 真 pb 下仅 +0.054 SR)

### 3.2 Crowded alpha (已被量化私募吃掉)
- ❌ LHB 席位跟踪 (DSR #33 2018 SR 8 → 2024 SR -2, 明确崩溃)
- ❌ 大宗交易机构吸筹 (DSR #35/#36 双 FAIL)
- ❌ 北向持仓变化 (北向本身 dominate 定价, 追尾流)

### 3.3 没有理论支撑的曲线拟合
- ❌ 任何没回答 §1 "四问" 的 backtest
- ❌ 参数 sweep 找"最好配置" (永远过拟合)
- ❌ ensemble "多因子加权"刷 SR (v18 的教训)

---

## 4. 立即行动 (本周)

按价值 × 紧急度排序:

### 4.1 🔴 Paper-trade DSR #30 (最高优先级)

**为什么**:
- 过 4/5 gate, 2024-2025 SR 1.34, post-announcement drift 学术 40 年
- paper_trade_spec_v2_20260421.md 已写好
- 3 个月 live 验证给你**校准先验**, 让未来所有 backtest 可信度 × 10

**怎么做**:
- 按 spec v2 执行 5% 规模
- daily pipeline 在现有 `scripts/` 拼接
- live SR < 0.5 立即降规模

### 4.2 🔴 修复 dashboard 认知诚信

**为什么**:
- `declared_active: v16` 挂着一个 long-history FAIL 的策略
- 对外 portfolio 展示不合格产品是研究生涯污点

**怎么做**:
```json
// portfolio/public/data/live/dashboard.json
{
  "status": "paper_trade_pending",
  "candidate": "DSR30_BBPV_mainboard_rescaled",
  "candidate_gate_result": "4/5 (CI_low 0.20 fail)",
  "candidate_last_2yr_sr": 1.34,
  "paper_trade_start_date": "2026-04-22",
  "paper_trade_scale_pct": 5,
  "failed_candidates": ["v16 (long-history SR 0.64)", "v17 (no long-history)", "v18 (marginal)"],
  "declared_active": null
}
```

### 4.3 🟡 写 BB 单腿 pre-reg + 5-gate

**为什么**:
- BB 单腿 SR 0.95 > ensemble 0.83, 单独更强
- 可能是更好的 paper-trade 候选

**怎么做**:
- 独立 pre-reg commit
- 跑 5-gate + WF + regime + cost + trade
- 若过, 考虑 superseding DSR #30 的 BB+PV ensemble 版本

### 4.4 🟡 LLM-native factor POC (空间 C)

**为什么**:
- 我们的不对称工具空间, 必须证明可行
- 不挖等于认输

**怎么做 (1 周 POC)**:
- 选 10-20 家公司
- 用 Claude 读近 3 年年报 MD&A, 输出 "语义漂移度" 0-1 分
- 回测: 漂移度 top decile vs bot decile 未来 1 季度收益差
- 不追求一次出 alpha, 追求**证明 LLM 能输出有 IC 的 score**

---

## 5. 中长期方向 (1-3 月)

### 5.1 容量受限策略集 (空间 A)

按实现难度:
1. **打新自动化** (1 周): 纯执行, 零策略, 年化 2-5% + beta
2. **可转债 T+0** (2-3 周): 上手快, 容量 100 万内
3. **微盘股 30 票组合** (2-4 周): 配合 low_vol + 极限反转

### 5.2 Regime / 择时策略 (空间 B)

- 信号: 货币 (DR007) × 估值 (PE分位) × 情绪 (融资余额) 三合一
- 输出: 0 / 50 / 100 / 150% (带杠杆) 仓位
- 持有工具: 沪深 300 ETF + 中证 1000 ETF
- 换仓频率: 月频

### 5.3 LLM-native pipeline (空间 C, 2-3 月)

- Agent 每日读当天所有 A 股公告 → 结构化事件
- Cross-reference 过去 4 季财报 + 对应行业政策 → conditional score
- 累积 3 个月后做 IC 分析
- 若证明有 alpha, 这是私募未覆盖的**第一个真正的 edge**

---

## 6. 认知升级

**你不是在做"因子 quant"。你是在做 "AI-era retail edge miner"。**

- "因子 quant" 的竞争对手: 1000 家私募, 用一样的 commodity 工具, 早就把水搅浑
- "AI-era retail edge miner" 的竞争对手: 几十个人, 且大部分还没开始

**每次 sprint 开始前问自己**:
> 我挖这个因子, 对手是谁? 他有什么我没有? 我有什么他没有?

如果回答不出"我有什么他没有", 关掉编辑器, 换个方向。

---

## 7. 本文件的维护

- **每次 sprint 失败 (< 30% 命中)**: 回来更新 §2 / §3 / §4
- **每次 live validation 完成**: 更新 §0.2 的表格
- **发现新 alpha 空间**: 加到 §2 (必须通过 §1 四问)
- **证伪某个空间**: 移到 §3 并说明证据

---

## 附录 A — 已做过但未归档的 alpha 观察

(占位, 后续补)

## 附录 B — 关键 reference

- CLAUDE.md § 策略评审门槛 (年化 >15%, SR >0.8, MDD <30%, 跨牛熊 >3 年)
- `journal/v34_v16_long_history_20260417.md` — v16 长历史 FAIL 证据
- `journal/dsr30_decay_check_20260421.md` — DSR #30 (活) vs #33 (死) 对比
- `journal/paper_trade_spec_v2_20260421.md` — 实盘 spec
- `journal/factor_mining_sprint2_20260421.md` — Sprint 2 命中率证据

---

— jialong, 2026-04-21
