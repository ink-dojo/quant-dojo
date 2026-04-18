"""
事件驱动数据加载模块
提供 A 股公司财报披露日 + 业绩代理变量 (EPS YoY).

数据源 (按预注册优先级):
  1. akshare 免费接口 (主): ak.stock_financial_abstract_ths / stock_report_disclosure
  2. tushare 120 积分 (备): pro.disclosure_date / pro.forecast
  3. 不使用: Wind / CapitalIQ / 自建爬虫

设计约束 (来自 research/event_driven/README.md 预注册):
  - 零未来函数: announcement_date 严格晚于 report_period_end_date
  - 零 look-ahead: EPS 代理用"公告日已知"值, 不用事后修正
  - 缓存: data/raw/events/{symbol}_anns.parquet

本模块当前是 Phase 0 骨架 — API 签名就位, 实现留给 Phase 1 (tushare 配额
重置后 + akshare 实测后). 骨架先让上层代码可以 import 并做 dry-run 结构设计.
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional

import pandas as pd

logger = logging.getLogger(__name__)

RAW_DIR = Path(__file__).parent.parent / "data" / "raw" / "events"


# ─────────────────────────────────────────────
# API 设计 (Phase 0 骨架)
# ─────────────────────────────────────────────

def get_earning_announcements(
    symbols: list[str],
    start: str = "2018-01-01",
    end: str = "2025-12-31",
    use_cache: bool = True,
) -> pd.DataFrame:
    """
    获取多只股票的财报披露日 + EPS 代理时序.

    参数:
        symbols  : 股票代码列表, 如 ["000001", "600000"]
        start    : 覆盖区间开始日期 (按公告日过滤)
        end      : 覆盖区间结束日期 (按公告日过滤)
        use_cache: 是否读/写 parquet 缓存

    返回:
        DataFrame, columns:
          - symbol          : str, 6 位代码
          - report_period   : Timestamp, 报告期末 (如 2024-09-30)
          - announce_date   : Timestamp, 实际披露日 (事件日)
          - eps_basic       : float, 基本每股收益 (本期)
          - eps_yoy         : float, 本期 EPS / 去年同期 EPS - 1 (事件 surprise 代理)
          - revenue_yoy     : float, 营收同比 (辅助信号, 非主要 surprise)
          - net_profit_yoy  : float, 净利润同比 (辅助信号)

    未来函数防御 (验收标准):
        - announce_date > report_period 对所有行成立 (assert)
        - eps_yoy 用当日可得数据 (非后续 restated 数字)

    Phase 0 状态: 未实现 — Phase 1 akshare 实测后填充.
    """
    raise NotImplementedError(
        "Phase 0: API 签名就位, 实现留给 Phase 1. "
        "akshare 测试 + tushare 配额重置后补."
    )


def get_disclosure_calendar(
    start: str,
    end: str,
    quarter: Optional[str] = None,
) -> pd.DataFrame:
    """
    获取给定区间内的所有 A 股财报披露日历.

    参数:
        start    : 区间开始
        end      : 区间结束
        quarter  : 可选, 过滤报告期 ("annual", "Q3", "semi", "Q1") — None 返回全部

    返回:
        DataFrame, columns: symbol, report_period, announce_date
        用于: 在做 event study / cross-section 时, 预先算 "哪一天哪些公司披露"

    Phase 0 状态: 未实现.
    """
    raise NotImplementedError("Phase 0: API 签名就位, 实现留给 Phase 1.")


def build_eps_surprise_signal(
    anns: pd.DataFrame,
    holding_window: int = 20,
    use_yoy: bool = True,
) -> pd.DataFrame:
    """
    从披露数据构造日频 PEAD 信号矩阵.

    参数:
        anns            : get_earning_announcements() 的输出
        holding_window  : 公告后持仓天数 (默认 20, 即 T+1 ~ T+20)
        use_yoy         : True 用 eps_yoy 作为 surprise; False 用 eps_basic 绝对值

    返回:
        DataFrame, index=date, columns=symbol
        每只股票在公告日之后的 holding_window 日内, value = surprise 分数;
        其余日 value = NaN. 上层 top/bottom 30% 选股基于此矩阵做 cross-section.

    未来函数防御:
        - signal.shift(1) 在 backtest engine 端做 (本函数 signal 对齐到 announce_date)
        - 同一公司短期内多次公告 (如业绩预告+正式披露), 取最晚公告的 surprise

    Phase 0 状态: 未实现.
    """
    raise NotImplementedError("Phase 0: API 签名就位, 实现留给 Phase 1.")


# ─────────────────────────────────────────────
# 数据质量门 (Phase 1 实现时必跑)
# ─────────────────────────────────────────────

def _quality_gate(anns: pd.DataFrame) -> None:
    """
    数据质量检查 — Phase 1 实现后必在每次 load 末尾调用.

    检查项 (预注册):
        1. announce_date > report_period 对 100% 行成立 (未来函数红线)
        2. 覆盖率: 样本期内有公告的 symbol 占 PIT universe ≥ 80%
        3. announce_date 单调 (按 symbol 分组后)
        4. eps_yoy 缺失率 < 10% (缺失代表业绩披露格式异常)
        5. 极值截尾: eps_yoy |value| 超过 100x 的行标红人工审
    """
    raise NotImplementedError("Phase 0: 质量门 Phase 1 实现后启用.")


if __name__ == "__main__":
    print("event_loader Phase 0 骨架 — API 签名就位.")
    print("所有函数 raise NotImplementedError, 实现待 Phase 1.")
    print(f"缓存目录 (未创建): {RAW_DIR}")
