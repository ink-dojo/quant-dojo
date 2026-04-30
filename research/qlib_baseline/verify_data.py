"""
qlib cn_data 自检脚本

检查:
    1. qlib 能否初始化
    2. calendar 范围（应该到 2022-12-30，因为我们装的是 v3）
    3. CSI300 instruments 数（应该 ~690 含历史成分股）
    4. 一只样本股能否拉到 OHLCV + Alpha158 特征样本

跑法:
    source research/qlib_baseline/.venv/bin/activate
    python research/qlib_baseline/verify_data.py
"""
from __future__ import annotations

import qlib
from qlib.contrib.data.handler import Alpha158
from qlib.data import D


def main():
    qlib.init(provider_uri="~/.qlib/qlib_data/cn_data", region="cn")

    cal = D.calendar(freq="day")
    print(f"[calendar] {cal[0].date()} ~ {cal[-1].date()} ({len(cal)} days)")

    inst = D.instruments(market="csi300")
    syms = D.list_instruments(instruments=inst, as_list=True)
    print(f"[csi300]   {len(syms)} instruments, sample: {syms[:5]}")

    sample = D.features(
        ["SH600000"],
        ["$open", "$high", "$low", "$close", "$volume"],
        start_time="2022-12-01",
        end_time="2022-12-30",
        freq="day",
    )
    print(f"[ohlcv]    SH600000 last month shape={sample.shape}")
    print(sample.tail(3))

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
