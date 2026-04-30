"""
qlib cn_data 自检脚本

检查:
    1. qlib 能否初始化
    2. calendar 范围（应该到 2022-12-30，v3）
    3. CSI300 instruments 数（应该 ~690 含历史成分股）
    4. **幸存者偏差红线**: instruments 列表里必须有"已退出 CSI300"的股票
       —— 否则违反 CLAUDE.md 红线 #2 (幸存者偏差)
    5. 一只样本股能否拉到 OHLCV + Alpha158 特征样本

跑法:
    source research/qlib_baseline/.venv/bin/activate
    python research/qlib_baseline/verify_data.py
"""
from __future__ import annotations

import os

import qlib
from qlib.contrib.data.handler import Alpha158
from qlib.data import D

QLIB_DATA_DIR = os.environ.get("QLIB_DATA_DIR", "~/.qlib/qlib_data/cn_data")


def main():
    qlib.init(provider_uri=QLIB_DATA_DIR, region="cn")

    cal = D.calendar(freq="day")
    print(f"[calendar] {cal[0].date()} ~ {cal[-1].date()} ({len(cal)} days)")

    inst = D.instruments(market="csi300")
    syms = D.list_instruments(instruments=inst, as_list=True)
    print(f"[csi300]   {len(syms)} instruments, sample: {syms[:5]}")

    # 幸存者偏差红线: PIT-correct universe 应该
    #   a) 有 stocks 在 universe 起点之后才入选 (start > universe_start)
    #   b) 有 stocks 在 universe 结束之前就被踢 (end < universe_end)
    # 否则就是 current snapshot, 违反 CLAUDE.md 红线 #2
    inst_dict = D.list_instruments(instruments=inst, as_list=False)
    all_starts = [start for ranges in inst_dict.values() for start, _ in ranges]
    all_ends = [end for ranges in inst_dict.values() for _, end in ranges]
    universe_start = min(all_starts)
    universe_end = max(all_ends)
    late_join = sum(1 for s in all_starts if s > universe_start)
    early_kick = sum(1 for e in all_ends if e < universe_end)
    print(f"[pit]      universe range: {universe_start.date()} ~ {universe_end.date()}")
    print(f"           中途入选: {late_join}, 中途被踢: {early_kick}")
    assert late_join > 50 and early_kick > 50, (
        f"CSI300 universe 不是 PIT-correct (late_join={late_join}, early_kick={early_kick}). "
        f"违反 CLAUDE.md 红线 #2 幸存者偏差。"
    )
    if universe_end.year < 2022:
        print(
            f"[warn]     universe end {universe_end.date()} < 2022; "
            f"backtest 区间超过这一天将退化成 current snapshot —— Phase B test_end 不要超过此日"
        )

    sample = D.features(
        ["SH600000"],
        ["$open", "$high", "$low", "$close", "$volume"],
        start_time="2022-12-01",
        end_time="2022-12-30",
        freq="day",
    )
    print(f"[ohlcv]    SH600000 last month shape={sample.shape}")
    print(sample.tail(3))

    # Alpha158 烟雾测试: 5 只股票半年 fit, 验证 handler 能跑通
    # Phase B 实跑用 fit=2008-2014 / valid=2015-2016 / test=2018-2022
    handler = Alpha158(
        instruments=syms[:5],
        start_time="2022-01-04",
        end_time="2022-12-30",
        fit_start_time="2022-01-04",
        fit_end_time="2022-06-30",
    )
    feat = handler.fetch()
    print(f"[alpha158] features shape={feat.shape}, n_features={len(feat.columns)}")
    print(f"           sample features: {feat.columns.tolist()[:8]}")


if __name__ == "__main__":
    main()
