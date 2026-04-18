"""
从 Tushare 重建 data/raw/listing_metadata.parquet — 修复幸存者偏差基础。

背景 (2026-04-17 cycle 13 发现):
  原 listing_metadata.parquet 中 289 条 is_delisted=True 记录的 delist_date
  全部集中在 2026-03-26 ~ 2026-04-10 (15 天, scraper 最后抓取失败的快照,
  不是真实历史退市日期)。导致: 长历史回测无法校正幸存者偏差。

Tushare 限流 (2026-04-17 实测):
  免费 120 积分的 stock_basic 是 **每天最多 5 次** (不是 1 次/小时;
  原文档错了, 实际错误信息: "您每天最多访问该接口5次")。失败调用也
  消耗配额。推荐做法: 一天内顺序跑 D → L → P (间隔建议 ≥ 60 分钟避免
  其他接口联动限流), 全部失败则次日重试。"增量落盘"机制:
  - 第 1 次跑 --status=D: 保存 data/raw/_listing_D.parquet
  - 第 2 次跑 --status=L: 保存 _listing_L.parquet
  - 第 3 次跑 --status=P: 保存 _listing_P.parquet (非关键)
  - 最后 --merge-apply: 读 stage 文件合并, 写 listing_metadata.parquet
  - P 可选: D + L 足以覆盖幸存者偏差分析 (P = 暂停上市, 非退市)

紧急 "立即" 修复 (无需 API):
  --patch-nat: 把原 parquet 里 289 条伪造的 delist_date 清成 NaT。
  这样审计工具不再被 fake 2026-03-26 日期误导。真值晚点从 tushare 拉。

schema (对齐原 parquet):
  symbol, name, list_date, exchange, board, is_delisted, delist_date
"""
from __future__ import annotations

import os
import shutil
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import pandas as pd
from dotenv import load_dotenv

META_PATH = Path("data/raw/listing_metadata.parquet")
BACKUP_PATH = Path("data/raw/listing_metadata.bak.parquet")
STAGE_DIR = Path("data/raw")
STAGE_FILES = {
    "L": STAGE_DIR / "_listing_L.parquet",
    "D": STAGE_DIR / "_listing_D.parquet",
    "P": STAGE_DIR / "_listing_P.parquet",
}


def _market_to_board(market: str | None) -> str:
    m = {
        "主板": "主板",
        "中小板": "主板A股",
        "创业板": "创业板",
        "科创板": "科创板",
        "北交所": "北交所",
        "CDR": "主板",
    }
    return m.get(market or "", market or "")


def _exchange_from_ts_code(ts_code: str) -> str:
    if ts_code.endswith(".SZ"):
        return "SZ"
    if ts_code.endswith(".SH"):
        return "SH"
    if ts_code.endswith(".BJ"):
        return "BJ"
    return ""


def fetch_one_status(status: str) -> pd.DataFrame:
    """拉单个 list_status, 保存到 stage file."""
    load_dotenv()
    token = os.getenv("TUSHARE_TOKEN")
    if not token:
        raise RuntimeError("TUSHARE_TOKEN 未配置在 .env")

    import tushare as ts
    pro = ts.pro_api(token)

    fields = "ts_code,symbol,name,list_date,delist_date,market"
    df = pro.stock_basic(exchange="", list_status=status, fields=fields)
    if df is None or df.empty:
        # 2026-04-18 实测: 免费层 list_status=P 稳定返回空 (推测 VIP-only 数据).
        # D + L 是必需, P 非关键 (暂停上市 ≠ 退市, 不影响幸存者偏差).
        if status == "P":
            print(f"  list_status={status}: 免费层返回空 (已知限制, P 非关键可跳过)")
            return pd.DataFrame()
        raise RuntimeError(f"list_status={status} 返回空")

    df["is_delisted"] = (status == "D")
    df["status_code"] = status
    df["list_date"] = pd.to_datetime(df["list_date"], format="%Y%m%d", errors="coerce")
    df["delist_date"] = pd.to_datetime(df["delist_date"], format="%Y%m%d", errors="coerce")
    df["exchange"] = df["ts_code"].map(_exchange_from_ts_code)
    df["board"] = df["market"].map(_market_to_board)

    out = df[[
        "symbol", "name", "list_date", "exchange", "board",
        "is_delisted", "delist_date", "status_code",
    ]].copy()
    out["list_date"] = out["list_date"].astype("datetime64[us]")

    path = STAGE_FILES[status]
    out.to_parquet(path, index=False)
    print(f"  list_status={status}: {len(out)} 条 → {path}")
    return out


def merge_stages(require_all: bool = False) -> pd.DataFrame:
    """读 stage files, 按 D > P > L 优先合并. D 和 L 是必需, P 可选."""
    frames = []
    missing = []
    for status, path in STAGE_FILES.items():
        if not path.exists():
            missing.append(status)
            if require_all or status in ("D", "L"):
                raise RuntimeError(f"缺少 stage file {path}, 先跑 --status {status}")
            continue
        frames.append(pd.read_parquet(path))
    if missing:
        print(f"  注意: 缺 stage {missing} (P 非关键, 跳过; 暂停上市股本地元数据保留)")

    combined = pd.concat(frames, ignore_index=True)
    priority = {"D": 0, "P": 1, "L": 2}
    combined["_pri"] = combined["status_code"].map(priority)
    combined = combined.sort_values("_pri").drop_duplicates("symbol", keep="first")
    combined = combined.drop(columns=["_pri", "status_code"])
    combined = combined.sort_values("symbol").reset_index(drop=True)
    return combined


def patch_nat_into_current() -> None:
    """立即修复: 把原 parquet 里 289 条伪造 delist_date 清成 NaT."""
    if BACKUP_PATH.exists():
        print(f"  备份已存在, 跳过: {BACKUP_PATH}")
    else:
        shutil.copy(META_PATH, BACKUP_PATH)
        print(f"  备份: {META_PATH} → {BACKUP_PATH}")

    meta = pd.read_parquet(META_PATH)
    # scraper 伪造日期特征: 全部集中在 2026-03-26 ~ 2026-04-10
    fake_mask = (
        meta["is_delisted"]
        & meta["delist_date"].notna()
        & (meta["delist_date"] >= pd.Timestamp("2026-03-01"))
        & (meta["delist_date"] <= pd.Timestamp("2026-04-30"))
    )
    n = int(fake_mask.sum())
    print(f"  识别 {n} 条伪造 delist_date (scraper 快照)")
    meta.loc[fake_mask, "delist_date"] = pd.NaT
    meta.to_parquet(META_PATH, index=False)
    print(f"  写入完成: 这些记录仍标 is_delisted=True, 但 delist_date=NaT (真值未知)")


def summarize_diff(old: pd.DataFrame, new: pd.DataFrame) -> None:
    old_syms = set(old["symbol"])
    new_syms = set(new["symbol"])
    print("\n=== Symbol-level diff ===")
    print(f"  原有: {len(old_syms)}, 新: {len(new_syms)}")
    print(f"  新增 (tushare 有 / 本地无): {len(new_syms - old_syms)}")
    print(f"  丢失 (本地有 / tushare 无): {len(old_syms - new_syms)}")

    old_del = old[old["is_delisted"]]
    new_del = new[new["is_delisted"]]
    print("\n=== is_delisted 记录 ===")
    if len(old_del) and old_del["delist_date"].notna().any():
        print(f"  原: {len(old_del)} (delist_date 跨度 "
              f"{old_del['delist_date'].min()} ~ {old_del['delist_date'].max()})")
    else:
        print(f"  原: {len(old_del)} (delist_date 无值或已被 patch 清空)")
    print(f"  新: {len(new_del)} (delist_date 跨度 "
          f"{new_del['delist_date'].min()} ~ {new_del['delist_date'].max()})")

    print("\n=== 新 delist_date 按年份 ===")
    years = new_del["delist_date"].dt.year.value_counts().sort_index()
    for y, c in years.items():
        print(f"  {int(y)}: {c}")


def main():
    args = sys.argv[1:]

    if "--patch-nat" in args:
        print("[patch-nat] 立即清除原 parquet 的伪造 delist_date...")
        patch_nat_into_current()
        sys.exit(0)

    if "--status" in args:
        i = args.index("--status")
        status = args[i + 1].upper()
        if status not in STAGE_FILES:
            print(f"错误: --status 只能是 L/D/P, 不是 {status}")
            sys.exit(2)
        print(f"[fetch] 拉 list_status={status} (免费限流 5 次/天, 失败也扣配额)...")
        fetch_one_status(status)
        remaining = [s for s, p in STAGE_FILES.items() if not p.exists()]
        if remaining:
            print(f"\n还需拉: {remaining}. 当日配额不足需次日重试 (P 非关键可跳过)。")
            print("全部拉完后: python scripts/refresh_listing_metadata.py --merge-apply")
        else:
            print("\n✅ 三份 stage file 齐全, 可以 --merge-apply 了。")
        sys.exit(0)

    if "--merge-apply" in args:
        print("[merge] 合并 stage files...")
        new_meta = merge_stages()
        print(f"  合并后 {len(new_meta)} 条 (D > P > L 优先)")

        print(f"\n[diff] 对比本地 {META_PATH}")
        old_meta = pd.read_parquet(META_PATH)
        summarize_diff(old_meta, new_meta)

        print(f"\n[apply] 写入 {META_PATH}")
        if META_PATH.exists() and not BACKUP_PATH.exists():
            shutil.copy(META_PATH, BACKUP_PATH)
            print(f"  备份: {BACKUP_PATH}")
        new_meta.to_parquet(META_PATH, index=False)
        print(f"  ✅ 写入完成: {len(new_meta)} 条, is_delisted={new_meta['is_delisted'].sum()}")
        print("\n  下一步: python scripts/audit_survivorship_bias.py 2005-2020-12-31")
        sys.exit(0)

    # 无参数: 打印帮助
    print(__doc__)
    print("\n可用命令:")
    print("  --patch-nat                立即清除 289 条伪造 delist_date (无需 API)")
    print("  --status {L|D|P}           拉一种 status 到 stage file (1 次/小时)")
    print("  --merge-apply              合并三份 stage file 写 listing_metadata.parquet")
    sys.exit(0)


if __name__ == "__main__":
    main()
