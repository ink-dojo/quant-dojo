"""
PEAD 因子 alphalens 审计

因子: research/factors/earnings_pead/surprise_yoy_z.parquet
含义: 业绩超预期 z-score（YoY），跨截面日度因子
跑法:
    python research/alphalens_audits/audit_surprise_yoy_z.py
"""
from __future__ import annotations

from pathlib import Path
import sys

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))

from research.alphalens_audits._runner import run_audit  # noqa: E402


FACTOR_PATH = (
    PROJECT_ROOT / "research" / "factors" / "earnings_pead" / "surprise_yoy_z.parquet"
)


def main():
    factor = pd.read_parquet(FACTOR_PATH)
    print(f"loaded factor: {factor.shape}, idx={factor.index.dtype}")

    run_audit(
        factor_name="surprise_yoy_z",
        factor_wide=factor,
        periods=(1, 5, 10, 20),
        quantiles=5,
    )


if __name__ == "__main__":
    main()
