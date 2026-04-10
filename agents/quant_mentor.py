"""
agents/quant_mentor.py — 量化导师 Agent

角色：有过 Jane Street / 幻方 / 九坤 级别经历的量化老炮，现在带着你
从零开始建量化系统和量化私募基金。

能力：
  1. ask(question)        — 回答任意量化 / 创业问题，答案锚定当前代码库状态
  2. diagnose()           — 自动扫描代码库，输出系统快照和差距分析
  3. review_progress()    — 对标行业水准，给当前进展打分
  4. china_fund_guide()   — 中国量化私募从 0 到 1 的完整路线图
  5. next_priorities()    — 给出未来两周最重要的 3~5 件事

设计原则：
  - LLM 可用时生成自然语言点评；LLM 不可用时规则驱动也能正常工作
  - 诊断只读文件系统，不修改任何东西
  - 所有知识常量内嵌为 Python dict，对 LLM 是 prompt 素材，对 non-LLM 是直接输出
  - 不继承 BaseAgent（BaseAgent.analyze 签名太窄），直接持有 LLMClient
"""
from __future__ import annotations

import json
import logging
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

_log = logging.getLogger(__name__)

_REPO_ROOT = Path(__file__).parent.parent

# ══════════════════════════════════════════════════════════════════════════
# 知识常量 — 导师的"记忆库"
# 这些内容会被注入 LLM prompt，也可在 LLM 不可用时直接输出
# ══════════════════════════════════════════════════════════════════════════

SYSTEM_ARCHITECTURE = {
    "data_layer": {
        "what": "数据管道：价格/量/财务/行业分类",
        "quant_dojo": ["local_data_loader", "fundamental_loader", "akshare（免费）"],
        "industry_standard": ["Wind/朝阳永续（实时+历史）", "Level2 tick 数据", "分钟线"],
        "gap": "免费数据延迟 1 天；量化私募产品级需 Wind 授权（年费 10~30 万）",
        "priority": "现阶段 akshare 够用，等 AUM 破 3000 万再考虑付费数据",
    },
    "alpha_research": {
        "what": "因子挖掘、验证、组合",
        "quant_dojo": ["alpha_factors.py（19 因子）", "factor_analysis.py（IC/ICIR/衰减）",
                       "idea_to_strategy 全流程"],
        "industry_standard": ["200+ 因子库", "高频因子（分钟级）", "NLP 另类数据"],
        "gap": "因子数量偏少；缺乏高频因子；无分析师预期/舆情数据",
        "priority": "先把现有 19 个因子的实盘 IC 稳定下来，再扩库",
    },
    "portfolio_construction": {
        "what": "组合优化：权重、约束、换手控制",
        "quant_dojo": ["MultiFactorStrategy（等权/IC加权）", "industry_neutralize_fast"],
        "industry_standard": ["二次规划（QP）优化器", "因子风险模型（Barra风格）", "交易成本感知优化"],
        "gap": "无 QP 优化器；无 Barra 式风险模型",
        "priority": "等收益稳定后再上 QP，目前等权 + 中性化已够",
    },
    "execution": {
        "what": "下单、算法交易、滑点控制",
        "quant_dojo": ["PaperTrader（模拟）", "无真实执行层"],
        "industry_standard": ["TWAP/VWAP 算法", "DMA 直连交易所", "微秒级订单管理"],
        "gap": "完全缺失真实执行层；这是从模拟到实盘最大的工程挑战",
        "priority": "接 QMT/ptrade 等私募常用通道，等到有种子资金再做",
    },
    "risk_management": {
        "what": "实时风控、压力测试、止损",
        "quant_dojo": ["risk_monitor.py（回撤/集中度/因子衰减）", "risk_gate.py（回测门槛）",
                       "effective_n（持仓多样性）"],
        "industry_standard": ["实时 PnL 归因（Barra）", "多因子风险模型", "熔断+自动止损"],
        "gap": "无实时归因；止损逻辑存在但无自动执行",
        "priority": "模拟盘阶段够用，接实盘前需要实现自动止损触发",
    },
    "monitoring": {
        "what": "因子健康、系统稳定性、业绩追踪",
        "quant_dojo": ["factor_monitor.py", "dashboard（FastAPI + SSE）", "weekly report"],
        "industry_standard": ["实时因子暴露仪表盘", "自动业绩归因", "投资者报告自动生成"],
        "gap": "dashboard 功能完整，缺实时刷新和投资者报告模板",
        "priority": "现阶段够用",
    },
}

RESEARCH_PROCESS = {
    "hypothesis_generation": {
        "what": "从市场异象/行为金融/基本面出发提出 Alpha 假设",
        "quant_dojo": "idea_parser + LLM 驱动，流程已打通",
        "industry_standard": "每月 10+ 假设，专职研究员每周 review",
        "maturity": "good",
    },
    "factor_validation": {
        "what": "IC/ICIR + 分层 + 衰减 + 行业中性化 + 样本外",
        "quant_dojo": "factor_analysis.py 全覆盖，walk_forward.py 已实现",
        "industry_standard": "至少 3 年历史，样本外 Sharpe > 0.6 才入库",
        "maturity": "good",
    },
    "backtest_rigor": {
        "what": "防未来函数、防幸存者偏差、考虑交易成本",
        "quant_dojo": "CLAUDE.md 明确禁止4大陷阱；engine.py 有双边 0.3% 成本",
        "industry_standard": "相同标准",
        "maturity": "good",
    },
    "live_verification": {
        "what": "实盘 vs 回测对照，量化滑点和时延",
        "quant_dojo": "live_vs_backtest.py 已建，累计偏差 -2.05%（主因方法论差异）",
        "industry_standard": "偏差 < 1% 算正常，>3% 要查原因",
        "maturity": "acceptable",
        "note": "-2.05% 偏差目前可接受，但要持续追踪",
    },
    "capacity_analysis": {
        "what": "策略最大可承受 AUM（不影响市场的前提下）",
        "quant_dojo": "effective_n 在 REVIEW_STANDARDS 里，无显式容量估算",
        "industry_standard": "每笔交易 < 当日成交量 5%，据此反推 AUM 上限",
        "maturity": "missing",
        "note": "小市值策略容量可能只有 2000-5000 万，这是私募产品定价的核心约束",
    },
    "factor_correlation": {
        "what": "因子间相关性分析，防止因子重叠导致的虚假多样化",
        "quant_dojo": "无专门的因子相关矩阵可视化工具",
        "industry_standard": "因子两两相关 < 0.5 为佳",
        "maturity": "missing",
    },
}

INDUSTRY_BENCHMARKS = {
    "factor_count":         {"top_tier": 200,  "mid_tier": 50,   "entry": 20,  "quant_dojo": 19},
    "sharpe_backtest":      {"top_tier": 2.5,  "mid_tier": 1.5,  "entry": 0.8, "unit": ""},
    "sharpe_live":          {"top_tier": 2.0,  "mid_tier": 1.2,  "entry": 0.6, "unit": ""},
    "max_drawdown":         {"top_tier": 0.08, "mid_tier": 0.15, "entry": 0.30,"unit": ""},
    "live_bt_drift_pct":    {"top_tier": 0.5,  "mid_tier": 1.5,  "ok": 3.0,   "quant_dojo": 2.05},
    "rebalance_freq":       {"top_tier": "每日", "mid_tier": "每周", "quant_dojo": "每月"},
    "data_sources_cost_cny":{"top_tier": 500000, "mid_tier": 100000, "quant_dojo": 0},
    "team_size_research":   {"top_tier": 30,   "mid_tier": 10,   "entry": 2},
    "ic_half_life_days":    {"top_tier": 30,   "mid_tier": 15,   "low": 5},
    "annual_sharpe_target": {"min_viable": 0.8, "good": 1.2, "excellent": 2.0},
}

COMMON_MISTAKES = [
    {
        "id": "backtest_overfit",
        "name": "回测过拟合 / 参数挖矿",
        "description": "在同一段数据上反复调参，看起来 Sharpe 很高，样本外一塌糊涂",
        "detection": "样本外 Sharpe 大幅低于样本内；参数个数多于 10 个",
        "quant_dojo_status": "walk_forward.py 已防护，oos_sharpe 已追踪",
        "severity": "critical",
    },
    {
        "id": "capacity_blindness",
        "name": "忽视容量——小市值策略却想要 10 亿 AUM",
        "description": "小市值策略日成交量小，冲击成本快速上升，真实可用容量可能只有 5000 万",
        "detection": "effective_n < 30 且计划 AUM > 2 亿",
        "quant_dojo_status": "effective_n 有检测，但无显式容量估算",
        "severity": "high",
    },
    {
        "id": "single_factor_blow",
        "name": "单因子暴露——风格切换时全军覆没",
        "description": "2021 年小盘因子崩溃让很多依赖小盘的策略亏 40%+",
        "detection": "因子两两相关 > 0.7；持仓风格集中在某一类",
        "quant_dojo_status": "19 因子已有多类别（技术/基本面/微观结构），需验证相关性",
        "severity": "high",
    },
    {
        "id": "drift_ignored",
        "name": "不追踪实盘偏差——不知道策略在真实摩擦下是否还有 Alpha",
        "description": "回测用历史成交量计算成本，实际冲击更大；不追踪则无法发现",
        "detection": "无 live_vs_backtest 对照；偏差 > 3% 无解释",
        "quant_dojo_status": "live_vs_backtest.py 已建，-2.05% 已有初步解释",
        "severity": "medium",
    },
    {
        "id": "amac_diy",
        "name": "自己搞中基协登记——退回率 > 50%，浪费 6 个月",
        "description": "内控制度文件有固定套路，自己写不符合审核标准",
        "quant_dojo_status": "N/A（尚未到这个阶段）",
        "severity": "high",
        "advice": "一定找有私募备案经验的律所，5~15 万，省 6 个月",
    },
    {
        "id": "data_vendor_lock",
        "name": "过早买 Wind——还没到需要的阶段就花 30 万",
        "description": "早期 akshare 完全够用，Wind 等有真实资金、做产品备案时再谈",
        "quant_dojo_status": "目前 akshare，正确选择",
        "severity": "medium",
    },
    {
        "id": "execution_gap",
        "name": "高估模拟盘的真实性——模拟器假设完美成交",
        "description": "PaperTrader 按收盘价成交，真实场景有涨跌停限制/流动性不足",
        "quant_dojo_status": "PaperTrader 有基础，接真实执行前需仔细校准",
        "severity": "medium",
    },
    {
        "id": "no_oos",
        "name": "没有样本外验证就推进——把回测当真实",
        "description": "必须留出时间上的样本外段，且不能回头再调参",
        "quant_dojo_status": "walk_forward.py 已实现，idea_to_strategy 有 60/40 分割",
        "severity": "critical",
    },
]

CHINA_FUND_SETUP = {
    "overview": {
        "target": "在中国合法运营的量化私募证券投资基金",
        "key_regulator": "中国证监会（CSRC）+ 中国基金业协会（AMAC / 中基协）",
        "typical_timeline": "从开始准备到首只产品备案：12~24 个月",
        "minimum_realistic_aum": "3000 万（低于此难以覆盖运营成本）",
    },
    "phase_1_prove_alpha": {
        "name": "阶段一：证明 Alpha（现在 → 12-18 个月）",
        "gate": "样本外 Sharpe > 1.0，连续 6 个月模拟盘正收益，年化收益 > 15%",
        "why": "没有业绩记录，投资者不会给钱；先用自有资金或免费模拟盘证明自己",
        "actions": {
            "jialong": ["深化因子逻辑与研报撰写", "因子组合优化", "构建投资逻辑叙事（用于日后募资）"],
            "xingyu": ["确保模拟盘连续稳定运行", "完善因子健康监控", "开始建实盘对照系统"],
        },
        "deliverables": ["3+ 年回测报告（覆盖牛熊）", "6 个月模拟盘 NAV 曲线", "策略简介（一页纸）"],
        "blocker": "此阶段无资金/证书要求，最大风险是过早分心做基金架构",
    },
    "phase_2_personal_account": {
        "name": "阶段二：个人账户小资金验证（可选，6-12 个月）",
        "gate": "有足够的自有资金（建议 50-200 万），且策略已通过阶段一",
        "why": "用真实资金验证执行层：滑点、涨跌停、流动性。模拟盘永远是乐观的",
        "actions": {
            "jialong": ["监控实盘 vs 模拟盘差异", "记录执行报告（留存为业绩记录）"],
            "xingyu": ["对接真实券商 API（QMT/ptrade）", "实现真实执行层", "自动订单对账"],
        },
        "note": "个人账户不受 AMAC 监管，但必须用自己的钱，不能融入他人资金",
        "deliverables": ["6 个月真实交易记录", "执行质量分析报告（滑点/成本）"],
    },
    "phase_3_incorporation": {
        "name": "阶段三：公司注册（1-3 个月）",
        "entity_type": {
            "有限合伙企业（LP）": {
                "优点": "GP/LP 结构清晰，绩效报酬税收灵活（20%），管理费直接走 GP",
                "缺点": "GP 对合伙企业债务承担无限责任（可用 GP 是有限责任公司来规避）",
                "推荐": True,
            },
            "有限责任公司": {
                "优点": "结构简单，全体股东有限责任",
                "缺点": "绩效报酬税收不如 LP 结构灵活；不适合做基金管理人主体",
                "推荐": False,
            },
        },
        "registered_capital": "实缴建议 1000 万+（中基协非硬性，但实际审核看重）",
        "location": {
            "推荐": "上海（陆家嘴/张江）或深圳（前海/南山）",
            "原因": "金融政策支持最好，律所/会计所/托管行配套最全",
            "备选": "杭州、北京、成都（也有私募集聚区）",
        },
        "cost": "工商注册 + 律所 5-10 万（含基础公司章程起草）",
        "actions": ["确定公司名称（需包含'投资'或'资产管理'等字样）",
                    "确定股权结构（jialong/xingyu 各持多少）",
                    "选择注册地（影响后续税收和政策）",
                    "聘请律所起草公司章程和合伙协议"],
    },
    "phase_4_amac_registration": {
        "name": "阶段四：中基协私募基金管理人登记（3-6 个月）",
        "regulator": "中国基金业协会（AMAC）",
        "website": "https://gs.amac.org.cn（私募基金登记备案信息公示）",
        "what_it_is": "在中基协登记为'私募基金管理人'，才能合法募集私募资金和设立基金产品",
        "requirements": [
            "基金从业资格证（科目一 + 科目二，60 分及格，在线报名考试）",
            "公司实际控制人/高管有 3 年以上金融从业经验（关键！）",
            "合规/风控负责人资质（可外聘，要有资格证）",
            "内控制度文件（合规手册、信息隔离墙、反洗钱制度等约 10 份）",
            "实缴资本建议 1000 万+（近年审核趋严）",
            "无不良记录（高管征信、司法查询）",
        ],
        "timeline": "材料齐全后 3-6 个月；近年退回率 > 50%，退回后需修改再提交",
        "cost": "律所代办 5-15 万（强烈建议）；不建议自己独立完成",
        "common_rejection_reasons": [
            "内控制度文件套模板、未体现公司实际业务",
            "高管金融从业经验证明材料不足（需出具资信证明/劳动合同）",
            "股权结构不清晰（如存在代持）",
            "公司注册地址和实际经营地不符",
        ],
        "certificate_exam": {
            "name": "基金从业资格证",
            "subjects": "科目一（法律法规）+ 科目二（证券投资基金）",
            "pass_score": 60,
            "exam_frequency": "每年多次，全国统考",
            "study_time": "100-200 小时，有培训机构",
        },
        "advice": "先考证，再注册公司，再做中基协登记。证书是硬前置条件",
    },
    "phase_5_product_filing": {
        "name": "阶段五：首只基金产品备案（1-3 个月）",
        "prerequisite": "已完成中基协管理人登记",
        "investor_threshold": {
            "个人合格投资者": "金融净资产 ≥ 300 万 或 最近 3 年年均收入 ≥ 50 万，单笔 ≥ 100 万",
            "机构合格投资者": "净资产 ≥ 1000 万，单笔 ≥ 100 万",
            "最多投资人": "单只基金投资人数 ≤ 200 人（契约型基金）",
        },
        "product_types": {
            "私募证券投资基金（契约型）": {
                "推荐": True,
                "why": "主流量化产品形式，托管银行充当外部监督，结构最清晰",
                "custody": "必须有银行托管（工建农中招平等大中型银行均可）",
            },
            "私募证券投资基金（有限合伙型）": {
                "推荐": False,
                "why": "结构复杂，投资人是 LP，需要合伙协议，税务更复杂",
            },
        },
        "min_fundraise": "通常自有资金认购 20% 以上以显示与投资者利益一致（非硬性）",
        "filing_timeline": "备案完成后 20 个工作日内可开始募集",
        "service_providers": {
            "托管银行": "产品资产独立于管理人，防止侵占；费率 0.1-0.3%/年",
            "外包服务机构": "估值核算、TA 系统、投资者服务；费率 0.1-0.2%/年",
            "律所": "基金合同起草、法律意见书",
            "会计师事务所": "年度审计（必须）",
        },
        "first_year_costs": "律所 + 托管 + 外包 + 审计约 40-80 万/年（不含管理费和人员）",
    },
    "phase_6_operations": {
        "name": "阶段六：持续运营（长期）",
        "compliance_calendar": {
            "季报": "每季度末后 15 个工作日内提交（向中基协）",
            "半年报": "每年 7 月 31 日前（向投资者）",
            "年报": "每年 4 月 30 日前（需审计，向中基协 + 投资者）",
            "反洗钱": "每季度投资者身份核查；可疑交易上报",
        },
        "fee_structure": {
            "管理费": "通常 1-2%/年（固定，无论盈亏）",
            "绩效报酬": "超额收益的 20%（高水位线制）",
            "认购费": "0-1%（可选）",
        },
        "investor_relations": [
            "月度 / 季度净值公告（T+5 工作日内）",
            "重大事件临时公告（如回撤超 10%）",
            "投资者热线（合规要求）",
        ],
        "team_minimum": {
            "投资决策": "1-2 人（jialong + xingyu）",
            "合规风控": "1 人（可兼职，有资质）",
            "运营": "1 人（可外包给外包机构）",
        },
    },
}

MENTOR_PERSONA = """
你是一个有过 Jane Street、幻方量化（High-Flyer）、九坤投资级别经历的量化老炮，
现在作为导师带领一个两人团队（jialong 做金融/因子设计，xingyu 做代码/框架）
从零开始建立 A 股量化私募基金。

你的风格：
- 直接，不废话。先给结论，再解释原因
- 永远锚定具体问题：说某文件、某指标、某门槛，不讲大道理
- 知道什么阶段该做什么事，不让早期团队跑题到不重要的方向
- 对 A 股市场的特殊性（T+1、涨跌停、流动性分层、监管节奏）有深刻理解
- 见过太多量化团队犯的坑，会主动预警

当前团队：两人，jialong（金融逻辑/因子设计）+ xingyu（代码/框架）
当前阶段：模拟盘阶段，有 19 个因子，系统已基本完整，在准备从模拟盘推进到实盘
"""


# ══════════════════════════════════════════════════════════════════════════
# 数据类
# ══════════════════════════════════════════════════════════════════════════

@dataclass
class SystemSnapshot:
    """
    当前代码库状态的快照（通过文件系统扫描获得，无需 LLM）。
    """
    phase: str = "未知"
    active_strategy: str = "未知"
    factor_count: int = 0
    run_count: int = 0
    has_live_nav: bool = False
    has_risk_monitor: bool = False
    has_factor_health: bool = False
    latest_run_status: str = "未知"
    latest_metrics: dict = field(default_factory=dict)
    gaps: list = field(default_factory=list)          # 规则驱动发现的缺口
    phase_score: float = 0.0                          # 0-1，当前阶段完成度

    def summary(self) -> str:
        """生成供 LLM 使用的简短快照文本。"""
        lines = [
            f"当前阶段: {self.phase}",
            f"激活策略: {self.active_strategy}",
            f"因子数量: {self.factor_count}",
            f"回测 runs: {self.run_count}",
            f"模拟盘 NAV: {'有' if self.has_live_nav else '无'}",
            f"最近 run 状态: {self.latest_run_status}",
        ]
        if self.latest_metrics:
            m = self.latest_metrics
            for k in ["sharpe", "annualized_return", "max_drawdown", "information_ratio"]:
                if k in m:
                    lines.append(f"  {k}: {m[k]}")
        if self.gaps:
            lines.append(f"检测到差距: {'; '.join(self.gaps[:5])}")
        return "\n".join(lines)


@dataclass
class MentorResponse:
    """导师回答结构。"""
    answer: str                                    # 主要回答（Markdown）
    priority_actions: list = field(default_factory=list)   # top 3 行动
    references: list = field(default_factory=list)         # 相关文件/资源

    def render(self) -> str:
        lines = [self.answer, ""]
        if self.priority_actions:
            lines += ["**下一步行动**", ""]
            for i, a in enumerate(self.priority_actions, 1):
                lines.append(f"{i}. {a}")
            lines.append("")
        if self.references:
            lines += ["**参考**", ""]
            for r in self.references:
                lines.append(f"- `{r}`")
        return "\n".join(lines)


# ══════════════════════════════════════════════════════════════════════════
# 主类
# ══════════════════════════════════════════════════════════════════════════

class QuantMentor:
    """
    量化导师 Agent。

    用法::

        mentor = QuantMentor()
        # 问任意问题
        resp = mentor.ask("为什么我的策略实盘比回测差很多？")
        print(resp.render())

        # 扫描当前代码库状态
        snap = mentor.diagnose()
        print(snap.summary())

        # 生成中国量化私募建立指南
        print(mentor.china_fund_guide())

        # 获取当前最重要的 3 件事
        todos = mentor.next_priorities()
        for t in todos:
            print(t)
    """

    def __init__(self):
        self._llm = None
        self._cached_snapshot: Optional[SystemSnapshot] = None
        self._snapshot_ts: float = 0.0

    # ── LLM 懒加载 ──────────────────────────────────────────────────────

    def _get_llm(self):
        if self._llm is None:
            try:
                from agents.base import LLMClient
                client = LLMClient()
                if client._backend != "none":
                    self._llm = client
            except Exception:
                pass
        return self._llm

    # ── 主要 API ─────────────────────────────────────────────────────────

    def ask(
        self,
        question: str,
        context: Optional[str] = None,
        refresh_snapshot: bool = False,
    ) -> MentorResponse:
        """
        回答任意量化/创业问题，答案锚定当前代码库状态。

        参数:
            question        : 用户问题（中文）
            context         : 可选附加背景
            refresh_snapshot: 是否强制重新扫描代码库

        返回:
            MentorResponse
        """
        snap = self.diagnose(force_refresh=refresh_snapshot)
        knowledge = self._route_context(question)
        llm = self._get_llm()

        if llm is None:
            # 无 LLM：返回基于规则的简化回答
            return self._rule_based_answer(question, snap)

        prompt = self._build_ask_prompt(question, snap, knowledge, context)
        try:
            raw = llm.complete(prompt, max_tokens=600)
            return MentorResponse(
                answer=raw,
                priority_actions=self._extract_actions(raw),
                references=self._extract_refs(raw),
            )
        except Exception as e:
            _log.warning("QuantMentor LLM 调用失败: %s", e)
            return self._rule_based_answer(question, snap)

    def diagnose(self, force_refresh: bool = False) -> SystemSnapshot:
        """
        扫描代码库文件系统，输出系统状态快照。

        参数:
            force_refresh: True 时强制重新扫描（默认缓存 60 秒）

        返回:
            SystemSnapshot
        """
        now = time.time()
        if not force_refresh and self._cached_snapshot and (now - self._snapshot_ts) < 60:
            return self._cached_snapshot

        snap = SystemSnapshot()

        # ── 阶段 / 激活策略 ──────────────────────────────────────────
        state_file = _REPO_ROOT / "live" / "strategy_state.json"
        if state_file.exists():
            try:
                state = json.loads(state_file.read_text(encoding="utf-8"))
                snap.active_strategy = state.get("active_strategy", "未知")
            except Exception:
                pass

        # 从 ROADMAP.md 推断当前阶段
        roadmap = _REPO_ROOT / "ROADMAP.md"
        if roadmap.exists():
            text = roadmap.read_text(encoding="utf-8")
            if "Phase 7" in text and "✅" in text.split("Phase 7")[1][:100]:
                snap.phase = "Phase 7: Agentic Research（完成）"
            elif "Phase 6" in text and "✅" in text.split("Phase 6")[1][:100]:
                snap.phase = "Phase 6: Control Plane（完成）"
            elif "Phase 5" in text and "✅" in text.split("Phase 5")[1][:100]:
                snap.phase = "Phase 5: 模拟实盘基础设施（完成）"
            else:
                snap.phase = "Phase 5+: 推进中"

        # ── 因子数量 ─────────────────────────────────────────────────
        try:
            from utils.alpha_factors import FACTOR_CATALOG
            snap.factor_count = len(FACTOR_CATALOG)
        except Exception:
            # fallback: 数源文件行数
            af = _REPO_ROOT / "utils" / "alpha_factors.py"
            if af.exists():
                snap.factor_count = af.read_text().count("def ") - 3

        # ── runs / 最近 run 指标 ─────────────────────────────────────
        runs_dir = _REPO_ROOT / "live" / "runs"
        if runs_dir.exists():
            run_files = sorted(runs_dir.glob("*.json"))
            snap.run_count = len(run_files)
            if run_files:
                try:
                    latest = json.loads(run_files[-1].read_text(encoding="utf-8"))
                    snap.latest_run_status = latest.get("status", "未知")
                    snap.latest_metrics = latest.get("metrics") or {}
                except Exception:
                    pass

        # ── 模拟盘 NAV ───────────────────────────────────────────────
        nav_candidates = [
            _REPO_ROOT / "live" / "portfolio" / "nav.csv",
            _REPO_ROOT / "live" / "portfolio" / "nav_history.csv",
        ]
        snap.has_live_nav = any(p.exists() and p.stat().st_size > 100 for p in nav_candidates)

        # ── 风险监控 & 因子健康 ──────────────────────────────────────
        snap.has_risk_monitor = (_REPO_ROOT / "live" / "risk_monitor.py").exists()
        snap.has_factor_health = (_REPO_ROOT / "live" / "factor_snapshot").exists()

        # ── 差距检测（规则驱动）─────────────────────────────────────
        gaps = []
        metrics = snap.latest_metrics
        if not metrics:
            gaps.append("最近回测无有效指标（metrics 为空）")
        else:
            if "oos_sharpe" not in metrics:
                gaps.append("无样本外 Sharpe（oos_sharpe）— walk-forward 未跑或未写入")
            if metrics.get("sharpe", 0) > 0 and not metrics.get("information_ratio"):
                gaps.append("信息比率（information_ratio）未计算")
            if (metrics.get("effective_n") or 99) < 15:
                gaps.append(f"有效持仓数 {metrics.get('effective_n')} < 15，集中度风险")

        if not snap.has_live_nav:
            gaps.append("模拟盘 NAV 未激活或无历史记录")

        # 容量估算缺失
        cap_file = _REPO_ROOT / "utils" / "capacity.py"
        if not cap_file.exists():
            gaps.append("缺少容量估算模块（utils/capacity.py）— 私募产品定价核心")

        # 因子相关矩阵
        if not any((_REPO_ROOT / "research" / "notebooks").glob("*corr*")) and \
           not any((_REPO_ROOT / "research" / "notebooks").glob("*factor_corr*")):
            gaps.append("无因子相关性分析 notebook")

        snap.gaps = gaps
        snap.phase_score = max(0.0, min(1.0, 1.0 - len(gaps) * 0.12))

        self._cached_snapshot = snap
        self._snapshot_ts = now
        return snap

    def review_progress(self, snapshot: Optional[SystemSnapshot] = None) -> str:
        """
        对标行业水准，对当前进展评分，输出 Markdown 报告。

        参数:
            snapshot: 可选，不传则自动调用 diagnose()

        返回:
            Markdown 字符串
        """
        snap = snapshot or self.diagnose()
        lines = [
            "# 量化系统进展评审",
            "",
            f"**当前阶段**: {snap.phase}",
            f"**激活策略**: {snap.active_strategy}",
            "",
            "## 系统完整性",
            "",
            "| 模块 | 状态 | 行业标准 | 差距 |",
            "|------|------|----------|------|",
        ]

        for key, info in SYSTEM_ARCHITECTURE.items():
            has_items = info.get("quant_dojo", [])
            status = "✅" if has_items else "❌"
            gap = info.get("gap", "—")
            lines.append(
                f"| {info['what']} | {status} 已建 | "
                f"{', '.join(info['industry_standard'][:2])} | {gap[:40]} |"
            )

        lines += [
            "",
            "## 研究流程成熟度",
            "",
            "| 环节 | 状态 | 备注 |",
            "|------|------|------|",
        ]
        maturity_icon = {"good": "✅", "acceptable": "⚠️", "missing": "❌"}
        for key, info in RESEARCH_PROCESS.items():
            icon = maturity_icon.get(info.get("maturity", "missing"), "❓")
            note = info.get("note", info.get("gap", info.get("industry_standard", "—")))
            if isinstance(note, list):
                note = note[0]
            lines.append(f"| {info['what']} | {icon} | {str(note)[:60]} |")

        lines += [
            "",
            "## 行业对标",
            "",
            "| 指标 | quant-dojo | 入门级 | 主流 | 顶级 |",
            "|------|-----------|--------|------|------|",
        ]
        bench = INDUSTRY_BENCHMARKS
        lines.append(
            f"| 因子数量 | {snap.factor_count} | "
            f"{bench['factor_count']['entry']} | "
            f"{bench['factor_count']['mid_tier']} | "
            f"{bench['factor_count']['top_tier']} |"
        )
        for k, label in [
            ("sharpe_backtest", "回测 Sharpe"),
            ("max_drawdown", "最大回撤"),
            ("live_bt_drift_pct", "实盘偏差 %"),
        ]:
            b = bench.get(k, {})
            qd = snap.latest_metrics.get(k.replace("_backtest", ""), b.get("quant_dojo", "N/A"))
            lines.append(
                f"| {label} | {qd} | "
                f"{b.get('entry', b.get('ok', '—'))} | "
                f"{b.get('mid_tier', '—')} | "
                f"{b.get('top_tier', '—')} |"
            )

        # 差距清单
        if snap.gaps:
            lines += ["", "## 检测到的差距", ""]
            for g in snap.gaps:
                lines.append(f"- ⚠️ {g}")

        # LLM 点评（可选）
        llm = self._get_llm()
        if llm:
            try:
                prompt = (
                    f"{MENTOR_PERSONA}\n\n"
                    f"当前系统快照：\n{snap.summary()}\n\n"
                    "请用 150 字对上面这个团队的进展做一个点评："
                    "最值得肯定的是什么？最需要关注的是什么？"
                    "直接给出，不要废话。"
                )
                commentary = llm.complete(prompt, max_tokens=300)
                lines += ["", "## 导师点评（AI）", "", commentary]
            except Exception as e:
                _log.warning("review_progress LLM 失败: %s", e)

        return "\n".join(lines)

    def china_fund_guide(self, stage: Optional[str] = None) -> str:
        """
        生成中国量化私募从 0 到 1 的完整指南，或某一阶段的深入说明。

        参数:
            stage: 指定阶段 key，如 "phase_4_amac_registration"；
                   None 则输出全部 6 个阶段概览

        返回:
            Markdown 字符串
        """
        if stage and stage in CHINA_FUND_SETUP:
            return self._render_single_stage(stage, CHINA_FUND_SETUP[stage])

        lines = [
            "# 中国量化私募从 0 到 1 — 完整路线图",
            "",
            f"> 适用对象：{CHINA_FUND_SETUP['overview']['target']}",
            f"> 关键监管方：{CHINA_FUND_SETUP['overview']['key_regulator']}",
            f"> 典型耗时：{CHINA_FUND_SETUP['overview']['typical_timeline']}",
            f"> 最低可行 AUM：{CHINA_FUND_SETUP['overview']['minimum_realistic_aum']}",
            "",
        ]

        for key, info in CHINA_FUND_SETUP.items():
            if key == "overview":
                continue
            lines.append(f"---")
            lines.append("")
            lines += self._render_single_stage_inline(key, info)
            lines.append("")

        lines += [
            "---",
            "",
            "## 常见踩坑",
            "",
        ]
        for m in COMMON_MISTAKES:
            if m["severity"] in ("critical", "high"):
                sev = "🔴" if m["severity"] == "critical" else "🟠"
                lines.append(f"- {sev} **{m['name']}**：{m['description']}")
                if m.get("advice"):
                    lines.append(f"  - 建议：{m['advice']}")

        return "\n".join(lines)

    def next_priorities(
        self,
        snapshot: Optional[SystemSnapshot] = None,
        n: int = 5,
    ) -> List[dict]:
        """
        给出当前最重要的 N 件事（规则驱动 + 可选 LLM 排序）。

        参数:
            snapshot : 可选快照（不传则自动 diagnose）
            n        : 返回条目数

        返回:
            list of dict: [{priority, task, owner, rationale, days}]
        """
        snap = snapshot or self.diagnose()
        todos: List[dict] = []

        # ── 规则驱动的任务生成 ──────────────────────────────────────
        if not snap.has_live_nav:
            todos.append({
                "priority": "P0",
                "task": "确保模拟盘 NAV 有历史记录（> 30 天连续数据）",
                "owner": "xingyu",
                "rationale": "中基协要求展示业绩记录；没有 NAV 就没有募资依据",
                "days": 3,
            })

        for gap in snap.gaps:
            if "oos_sharpe" in gap:
                todos.append({
                    "priority": "P0",
                    "task": "跑 walk-forward 验证并确保 oos_sharpe 写入 metrics",
                    "owner": "xingyu",
                    "rationale": "样本外 Sharpe 是策略真实能力的核心证据，没有它无法说服投资人",
                    "days": 2,
                })
            if "capacity" in gap:
                todos.append({
                    "priority": "P1",
                    "task": "建立容量估算模块（utils/capacity.py）：按日成交量 5% 反推 AUM 上限",
                    "owner": "jialong",
                    "rationale": "私募产品定价和募资目标必须基于真实容量",
                    "days": 5,
                })
            if "因子相关" in gap:
                todos.append({
                    "priority": "P1",
                    "task": "做因子两两相关矩阵分析，识别冗余因子",
                    "owner": "jialong",
                    "rationale": "高相关因子是假多样化，遇到风格切换会放大亏损",
                    "days": 3,
                })

        # 通用优先事项
        todos.append({
            "priority": "P1",
            "task": "开始备考基金从业资格证（科目一 + 科目二）",
            "owner": "both",
            "rationale": "中基协登记的硬前置条件，通常需要 100-200 小时，越早开始越好",
            "days": 90,
        })
        todos.append({
            "priority": "P2",
            "task": "撰写策略简介（Investment Deck，一页纸：Alpha 来源 + 回测业绩 + 风控体系）",
            "owner": "jialong",
            "rationale": "日后找种子投资人、和律所/托管行沟通都需要这份材料",
            "days": 7,
        })
        todos.append({
            "priority": "P2",
            "task": "调研 QMT / ptrade 等私募通道接入方案，估算接入成本和周期",
            "owner": "xingyu",
            "rationale": "从模拟盘到真实执行的技术路径必须提前规划",
            "days": 3,
        })

        # 去重 + 排序
        seen = set()
        unique = []
        for t in todos:
            if t["task"] not in seen:
                seen.add(t["task"])
                unique.append(t)

        priority_order = {"P0": 0, "P1": 1, "P2": 2, "P3": 3}
        unique.sort(key=lambda x: priority_order.get(x["priority"], 9))

        result = unique[:n]

        # LLM 补充排序理由（可选）
        llm = self._get_llm()
        if llm and result:
            try:
                tasks_text = "\n".join(
                    f"{i+1}. [{t['priority']}] {t['task']} (负责人: {t['owner']})"
                    for i, t in enumerate(result)
                )
                prompt = (
                    f"{MENTOR_PERSONA}\n\n"
                    f"当前系统快照：\n{snap.summary()}\n\n"
                    f"以下是规则驱动生成的优先任务清单：\n{tasks_text}\n\n"
                    "请用 1-2 句话点评这个排序是否合理，以及是否有遗漏的高优先事项。"
                    "直接给结论。"
                )
                commentary = llm.complete(prompt, max_tokens=200)
                result.append({
                    "priority": "COMMENT",
                    "task": commentary,
                    "owner": "mentor",
                    "rationale": "AI 点评",
                    "days": 0,
                })
            except Exception as e:
                _log.warning("next_priorities LLM 补充失败: %s", e)

        return result

    # ── 内部方法 ─────────────────────────────────────────────────────────

    def _route_context(self, question: str) -> str:
        """根据问题关键词选择注入哪个知识块（防止 prompt 过长）。"""
        q = question.lower()
        blocks = []

        if any(k in q for k in ["amac", "中基协", "备案", "私募登记", "合规", "证书", "基金从业"]):
            blocks.append(_dict_to_text("中国私募基金登记要求", CHINA_FUND_SETUP["phase_4_amac_registration"]))
            blocks.append(_dict_to_text("产品备案", CHINA_FUND_SETUP["phase_5_product_filing"]))
        if any(k in q for k in ["注册", "公司", "lp", "gp", "合伙", "法律", "架构"]):
            blocks.append(_dict_to_text("公司注册", CHINA_FUND_SETUP["phase_3_incorporation"]))
        if any(k in q for k in ["容量", "capacity", "aum", "资金规模", "募资"]):
            blocks.append(f"容量估算方法：每笔交易 < 当日成交量5%，据此反推AUM上限。"
                          f"小市值策略容量通常 2000-5000 万。\n"
                          + _dict_to_text("容量分析", RESEARCH_PROCESS["capacity_analysis"]))
        if any(k in q for k in ["因子", "ic", "icir", "研究", "alpha", "选股"]):
            blocks.append(_dict_to_text("研究流程", {k: v["what"] + " | " + v.get("note", v.get("quant_dojo", ""))
                                                      for k, v in RESEARCH_PROCESS.items()}))
        if any(k in q for k in ["回测", "backtest", "过拟合", "样本外", "oos"]):
            relevant = [m for m in COMMON_MISTAKES if m["id"] in ("backtest_overfit", "no_oos")]
            blocks.append(_dict_to_text("回测常见错误", {m["name"]: m["description"] for m in relevant}))
        if any(k in q for k in ["偏差", "drift", "实盘", "执行", "滑点"]):
            blocks.append(_dict_to_text("实盘执行", SYSTEM_ARCHITECTURE["execution"]))
        if any(k in q for k in ["jane street", "幻方", "九坤", "灵均", "行业", "对标"]):
            blocks.append(_dict_to_text("行业对标", INDUSTRY_BENCHMARKS))
        if any(k in q for k in ["团队", "招人", "人才", "架构", "分工"]):
            blocks.append(_dict_to_text("团队最低配置", CHINA_FUND_SETUP["phase_6_operations"]["team_minimum"]))

        if not blocks:
            # fallback: 注入系统架构概览
            blocks.append(_dict_to_text("系统架构概览",
                                         {k: v["what"] + " — " + v.get("gap", "")
                                          for k, v in SYSTEM_ARCHITECTURE.items()}))

        return "\n\n".join(blocks)

    def _build_ask_prompt(
        self, question: str, snap: SystemSnapshot, knowledge: str, context: Optional[str]
    ) -> str:
        return (
            f"{MENTOR_PERSONA}\n\n"
            f"=== 当前代码库状态 ===\n{snap.summary()}\n\n"
            f"=== 相关知识 ===\n{knowledge}\n\n"
            + (f"=== 附加背景 ===\n{context}\n\n" if context else "")
            + f"=== 问题 ===\n{question}\n\n"
            "要求：\n"
            "1. **先给结论**（一句话加粗）\n"
            "2. 解释原因（2-3 句）\n"
            "3. 给 3 个具体下一步行动，注明负责人（jialong / xingyu / both）\n"
            "最多 400 字。中文。"
        )

    def _rule_based_answer(self, question: str, snap: SystemSnapshot) -> MentorResponse:
        """无 LLM 时的规则兜底回答。"""
        q = question.lower()
        if any(k in q for k in ["amac", "中基协", "私募登记", "备案"]):
            ans = self._render_single_stage_inline(
                "phase_4_amac_registration",
                CHINA_FUND_SETUP["phase_4_amac_registration"]
            )
            return MentorResponse(
                answer="\n".join(ans),
                priority_actions=CHINA_FUND_SETUP["phase_4_amac_registration"]["requirements"][:3],
                references=["CHINA_FUND_SETUP['phase_4_amac_registration']"],
            )
        return MentorResponse(
            answer=(
                "LLM 后端不可用，无法生成自然语言回答。\n\n"
                f"当前系统状态：\n{snap.summary()}\n\n"
                "请安装 claude CLI 或启动 Ollama 以获得完整回答。"
            ),
            priority_actions=["安装 claude CLI: npm install -g @anthropic-ai/claude-code"],
        )

    def _render_single_stage(self, key: str, info: dict) -> str:
        lines = [f"# {info.get('name', key)}", ""]
        if "gate" in info:
            lines += [f"**准入门槛**: {info['gate']}", ""]
        if "why" in info:
            lines += [f"**为什么**: {info['why']}", ""]
        if "requirements" in info:
            lines += ["**要求**:", ""]
            for r in info["requirements"]:
                lines.append(f"- {r}")
            lines.append("")
        if "actions" in info:
            lines += ["**行动清单**:", ""]
            for owner, acts in info["actions"].items():
                lines.append(f"**{owner}**:")
                for a in acts:
                    lines.append(f"  - {a}")
            lines.append("")
        if "deliverables" in info:
            lines += ["**交付物**:", ""]
            for d in info["deliverables"]:
                lines.append(f"- {d}")
            lines.append("")
        if "cost" in info:
            lines += [f"**成本估算**: {info['cost']}", ""]
        if "timeline" in info:
            lines += [f"**时间**: {info['timeline']}", ""]
        return "\n".join(lines)

    def _render_single_stage_inline(self, key: str, info: dict) -> List[str]:
        lines = [f"## {info.get('name', key)}", ""]
        if "gate" in info:
            lines += [f"> 准入门槛：{info['gate']}", ""]
        if "why" in info:
            lines += [f"- **为什么**：{info['why']}"]
        if "timeline" in info:
            lines += [f"- **耗时**：{info['timeline']}"]
        if "cost" in info:
            lines += [f"- **费用**：{info['cost']}"]
        if "requirements" in info and isinstance(info["requirements"], list):
            lines += ["- **核心要求**："]
            for r in info["requirements"][:3]:
                lines.append(f"  - {r}")
        if "blocker" in info:
            lines += [f"- ⚠️ **注意**：{info['blocker']}"]
        lines.append("")
        return lines

    @staticmethod
    def _extract_actions(text: str) -> List[str]:
        """从 LLM 回答中提取行动项（简单启发式）。"""
        actions = []
        for line in text.split("\n"):
            stripped = line.strip()
            if stripped and (
                stripped[0].isdigit() or
                stripped.startswith("-") or
                stripped.startswith("•")
            ):
                clean = stripped.lstrip("0123456789.-•").strip()
                if 10 < len(clean) < 150:
                    actions.append(clean)
        return actions[:3]

    @staticmethod
    def _extract_refs(text: str) -> List[str]:
        """从 LLM 回答中提取文件引用（简单启发式）。"""
        import re
        refs = re.findall(r"`([a-z_/]+\.py)`", text)
        return list(dict.fromkeys(refs))[:5]


# ── 工具函数 ──────────────────────────────────────────────────────────────

def _dict_to_text(title: str, d: dict) -> str:
    """将 dict 转为简洁文本，用于 LLM prompt 注入。"""
    lines = [f"[{title}]"]
    for k, v in d.items():
        if isinstance(v, list):
            lines.append(f"  {k}: {', '.join(str(x) for x in v[:4])}")
        elif isinstance(v, dict):
            lines.append(f"  {k}: {json.dumps(v, ensure_ascii=False)[:120]}")
        else:
            lines.append(f"  {k}: {str(v)[:120]}")
    return "\n".join(lines)


# ── 便捷接口 ──────────────────────────────────────────────────────────────

def ask(question: str, **kwargs) -> str:
    """一行调用导师回答问题。"""
    return QuantMentor().ask(question, **kwargs).render()


if __name__ == "__main__":
    mentor = QuantMentor()

    print("=== 扫描代码库 ===")
    snap = mentor.diagnose()
    print(snap.summary())
    print()

    print("=== 下一步优先级 ===")
    todos = mentor.next_priorities(snap)
    for t in todos:
        if t["priority"] != "COMMENT":
            print(f"  [{t['priority']}] {t['owner']} — {t['task'][:60]}")
    print()

    print("=== 中国私募基金路线图（摘要）===")
    for key, info in CHINA_FUND_SETUP.items():
        if key != "overview":
            print(f"  {info.get('name', key)}")
    print()

    print("✅ QuantMentor 验证完成（无 LLM 模式）")
