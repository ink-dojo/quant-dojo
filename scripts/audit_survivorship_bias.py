"""
幸存者偏差审计 — 对给定日期区间报告 universe 中死亡/存活股票的占比。

动机:
  `utils/local_data_loader.py` 已包含 289 只退市股票的完整历史
  (data/raw/listing_metadata.parquet 显示 5791 只, 289 is_delisted=True)。
  但常用过滤 `price.notna().sum() > 500` 会排除 "样本不足" 的死亡股,
  从而引入隐性幸存者偏差: 回测只看 "活过整个区间" 的股票, 高估收益。

工具输出 (给定 start/end):
  - 区间内活着的股票数 (list_date < start, not_delisted OR delist_date > start)
  - 其中在区间内死亡的股票数
  - 如果应用 notna>500 过滤, 会排除多少死亡股
  - 该偏差程度 (%) 对 small-universe 的估计敏感度

用法:
  python scripts/audit_survivorship_bias.py 2022-01-04 2025-12-31
  python scripts/audit_survivorship_bias.py 2015-01-01 2020-12-31

退出码:
  0: 报告生成成功
  2: 参数错误
"""
from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import pandas as pd


def _parse_date(s: str) -> pd.Timestamp:
    return pd.Timestamp(s)


def audit(start: pd.Timestamp, end: pd.Timestamp,
          min_obs: int = 500,
          meta_path: str = "data/raw/listing_metadata.parquet") -> dict:
    """对 [start, end] 区间做幸存者偏差审计, 返回统计字典."""
    meta = pd.read_parquet(meta_path)
    meta["list_date"] = pd.to_datetime(meta["list_date"])
    meta["delist_date"] = pd.to_datetime(meta["delist_date"])

    # 元数据质量检查: 若所有 delist_date 都落在最近 30 天, 说明
    # is_delisted 是 "最近停更" 而非真实历史退市, 无法做历史幸存者校正
    delisted_meta = meta[meta["is_delisted"] & meta["delist_date"].notna()]
    meta_quality_warning: str | None = None
    if len(delisted_meta) > 0:
        earliest = delisted_meta["delist_date"].min()
        latest = delisted_meta["delist_date"].max()
        span_days = (latest - earliest).days
        if span_days < 60:
            meta_quality_warning = (
                f"delist_date 全部集中在 {earliest.date()}~{latest.date()} "
                f"(跨度 {span_days} 天), 疑似 'scraper 快照' 而非真实退市历史。"
                " 本审计对历史区间的死亡计数会低估。"
            )

    # "期初已上市" 且 "期末之前未退市 (或期内退市的也算曾在市)"
    listed_before_start = meta["list_date"] <= start
    not_delisted = ~meta["is_delisted"]
    delisted_after_start = meta["is_delisted"] & (meta["delist_date"] > start)

    eligible_mask = listed_before_start & (not_delisted | delisted_after_start)
    eligible = meta[eligible_mask].copy()

    # 期内死亡的子集
    died_in_period = eligible["is_delisted"] & (
        (eligible["delist_date"] > start) & (eligible["delist_date"] <= end)
    )

    # 检查原始 CSV 数据是否有 (通过 local_data_loader 的 get_all_symbols,
    # 而不是 on-demand parquet cache — cache 只是实际用过的子集)
    try:
        from utils.local_data_loader import get_all_symbols
        available = set(get_all_symbols())
    except Exception:
        available = set()
    eligible["has_data"] = eligible["symbol"].isin(available)

    # 估算: notna>min_obs 过滤能保留多少死亡股
    # (真正要精确要加载 price, 这里给近似: 期内交易天数 = 死亡日 - start)
    trading_days = pd.bdate_range(start, end)
    n_days_in_period = len(trading_days)

    # 活着的整期至少 n_days_in_period 天 (notna)
    # 期内死亡的最多只有 (delist - start) 个交易日
    eligible["expected_obs"] = eligible.apply(
        lambda r: n_days_in_period if not r["is_delisted"] or r["delist_date"] > end
        else len(pd.bdate_range(start, r["delist_date"])),
        axis=1,
    )
    would_pass_filter = eligible["expected_obs"] >= min_obs

    result = {
        "start": str(start.date()),
        "end": str(end.date()),
        "period_trading_days": n_days_in_period,
        "min_obs_filter": min_obs,
        "eligible_total": int(len(eligible)),
        "eligible_with_data": int(eligible["has_data"].sum()),
        "died_in_period": int(died_in_period.sum()),
        "died_and_kept_by_filter": int(
            (died_in_period & would_pass_filter).sum()
        ),
        "died_and_dropped_by_filter": int(
            (died_in_period & ~would_pass_filter).sum()
        ),
        "survivors_kept": int(
            (~died_in_period & would_pass_filter).sum()
        ),
    }
    result["survivor_bias_pct"] = (
        result["died_and_dropped_by_filter"]
        / max(result["eligible_total"], 1)
        * 100
    )
    result["meta_quality_warning"] = meta_quality_warning
    return result


def main():
    if len(sys.argv) < 3:
        print("用法: python audit_survivorship_bias.py <start YYYY-MM-DD> <end YYYY-MM-DD> [min_obs]")
        sys.exit(2)

    start = _parse_date(sys.argv[1])
    end = _parse_date(sys.argv[2])
    min_obs = int(sys.argv[3]) if len(sys.argv) > 3 else 500

    if start >= end:
        print(f"错误: start ({start}) 应早于 end ({end})")
        sys.exit(2)

    r = audit(start, end, min_obs=min_obs)

    print(f"\n=== 幸存者偏差审计 {r['start']} ~ {r['end']} ===")
    print(f"期内交易日: {r['period_trading_days']}")
    print(f"过滤门槛: notna >= {r['min_obs_filter']} 个交易日")
    print()
    print(f"期初可投资 universe: {r['eligible_total']} 只")
    print(f"  其中本地有数据: {r['eligible_with_data']}")
    print(f"  期内死亡: {r['died_in_period']}")
    print()
    print("过滤后的偏差:")
    print(f"  存活并通过过滤 (回测实际使用): {r['survivors_kept']}")
    print(f"  期内死亡但通过过滤 (≥{r['min_obs_filter']} 天): {r['died_and_kept_by_filter']}")
    print(f"  期内死亡被过滤掉 (<{r['min_obs_filter']} 天): {r['died_and_dropped_by_filter']}")
    print(f"  **隐性幸存者偏差: {r['survivor_bias_pct']:.2f}% 的 universe 被丢弃**")
    print()
    if r["died_and_dropped_by_filter"] > 0:
        print("警告: 回测结果高估了真实可投资性。建议降低 min_obs 门槛或单独统计死亡股贡献。")
    else:
        print("本区间无隐性幸存者偏差 (按当前元数据).")

    if r["meta_quality_warning"]:
        print()
        print(f"⚠️  元数据警告: {r['meta_quality_warning']}")

    sys.exit(0)


if __name__ == "__main__":
    main()
