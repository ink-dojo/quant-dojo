"""
内幕增持 60 日（行业市值中性化版）alphalens 审计

因子: research/factors/insider_trading/net_buying_60d_ind_size_neu.parquet
含义: 大股东/高管 60 日窗口内净增持金额，对行业 + 市值做了中性化（去掉系统性偏差）
说明: 用 _ind_size_neu 版本而不是 raw net_buying_60d，因为 raw 87% 都是 0，
     无法做 quintile 切；中性化版 0 占比 0.04%，分布连续。
跑法:
    python research/alphalens_audits/audit_insider_net_buying_60d.py
"""
from __future__ import annotations

from pathlib import Path
import sys

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))

from research.alphalens_audits._runner import run_audit  # noqa: E402


FACTOR_PATH = (
    PROJECT_ROOT / "research" / "factors" / "insider_trading"
    / "net_buying_60d_ind_size_neu.parquet"
)


def main():
    factor = pd.read_parquet(FACTOR_PATH)
    # 这个 parquet 没保 index name；强制 DatetimeIndex 让 alphalens 对齐成功
    factor.index = pd.to_datetime(factor.index)
    print(f"loaded factor: {factor.shape}, idx={factor.index.dtype}")

    run_audit(
        factor_name="insider_net_buying_60d_ind_size_neu",
        factor_wide=factor,
        periods=(1, 5, 10, 20),
        quantiles=5,
    )


if __name__ == "__main__":
    main()
