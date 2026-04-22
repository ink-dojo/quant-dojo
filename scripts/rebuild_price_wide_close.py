"""
重建 data/processed/price_wide_close_2014-01-01_2025-12-31_qfq_5477stocks.parquet

该宽表被 scripts/regime_robust_factor_scan.py 依赖但本地缺失。
重建逻辑：读取 data/cache/local/*.parquet (5477 只股票)，通过 pct_change
累积复利构建前复权等效价格宽表，保存为 parquet。
"""
import sys
from pathlib import Path
import pandas as pd

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

from utils.local_data_loader import load_adj_price_wide, get_all_symbols


def main() -> None:
    start, end = "2014-01-01", "2025-12-31"
    out_dir = ROOT / "data" / "processed"
    out_dir.mkdir(parents=True, exist_ok=True)

    symbols = sorted(get_all_symbols())
    print(f"发现本地股票: {len(symbols)} 只")

    print(f"构建前复权宽表 ({start} ~ {end})...")
    wide = load_adj_price_wide(symbols, start, end)

    if wide.empty:
        sys.exit("❌ 宽表为空，检查 ~/quant-data/ 是否有数据")

    n_stocks = wide.shape[1]
    fname = f"price_wide_close_{start}_{end}_qfq_{n_stocks}stocks.parquet"
    path = out_dir / fname
    wide.to_parquet(path)

    print(f"✅ 宽表 shape: {wide.shape}")
    print(f"   日期范围: {wide.index.min().date()} ~ {wide.index.max().date()}")
    print(f"   保存: {path}")
    print(f"   大小: {path.stat().st_size / 1024 / 1024:.1f} MB")

    # 数据质量检查
    assert wide.shape[0] > 1000, f"日期行数异常: {wide.shape[0]}"
    assert wide.shape[1] > 4000, f"股票列数异常: {wide.shape[1]}"
    null_pct = wide.isnull().mean().mean()
    print(f"   整体缺失率: {null_pct:.1%} (正常，新股上市前为 NaN)")


if __name__ == "__main__":
    main()
