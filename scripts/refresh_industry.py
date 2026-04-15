#!/usr/bin/env python3
"""
scripts/refresh_industry.py — 申万行业分类缓存刷新工具

使用方式
--------
  # 检查缓存状态（不刷新）
  python scripts/refresh_industry.py --status

  # 按 TTL 自动判断（30 天内不重拉）
  python scripts/refresh_industry.py

  # 强制重拉（忽略 TTL，适合月底手动更新）
  python scripts/refresh_industry.py --force

  # 集成到 daily_run.sh（加 --quiet 只在真正刷新时打印）
  python scripts/refresh_industry.py --quiet

设计原则
--------
- 30 天 TTL：申万行业调整频率低（季度），30 天足够
- 降级策略：akshare 失败 → 旧缓存（哪怕过期）→ legacy CSV → 报错
- 原子写：tmp + rename，拉取中断不污染缓存
- 幂等：每天在 daily_run.sh 里调用都安全，只有过期才真正打网络
"""

import argparse
import logging
import sys
from datetime import datetime
from pathlib import Path

# 把项目根目录加入 path，支持 `python scripts/xxx.py` 直接运行
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from utils.fundamental_loader import (
    _INDUSTRY_CACHE_PATH,
    _INDUSTRY_CACHE_TTL,
    refresh_industry_classification,
)


def _cache_status() -> dict:
    """返回当前缓存状态信息。"""
    if not _INDUSTRY_CACHE_PATH.exists():
        return {"exists": False, "age_days": None, "expired": True, "n_stocks": 0, "n_industries": 0}

    import pandas as pd
    mtime = datetime.fromtimestamp(_INDUSTRY_CACHE_PATH.stat().st_mtime)
    age = datetime.now() - mtime
    try:
        df = pd.read_parquet(_INDUSTRY_CACHE_PATH)
        n_stocks = len(df)
        n_industries = df["industry_code"].nunique() if "industry_code" in df.columns else 0
    except Exception:
        n_stocks = n_industries = -1

    return {
        "exists": True,
        "path": str(_INDUSTRY_CACHE_PATH),
        "mtime": mtime.strftime("%Y-%m-%d %H:%M"),
        "age_days": age.days + age.seconds / 86400,
        "ttl_days": _INDUSTRY_CACHE_TTL.days,
        "expired": age >= _INDUSTRY_CACHE_TTL,
        "n_stocks": n_stocks,
        "n_industries": n_industries,
    }


def main():
    parser = argparse.ArgumentParser(
        description="申万行业分类缓存刷新（30 天 TTL，可强制）"
    )
    parser.add_argument("--force", action="store_true", help="忽略 TTL，强制重拉")
    parser.add_argument("--status", action="store_true", help="只打印缓存状态，不刷新")
    parser.add_argument("--quiet", action="store_true",
                        help="静默模式：缓存有效时不打印，只在真正刷新时打印")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        datefmt="%H:%M:%S",
    )

    status = _cache_status()

    # ── 只看状态 ──
    if args.status:
        if not status["exists"]:
            print("❌ 缓存不存在", _INDUSTRY_CACHE_PATH)
        else:
            flag = "⚠ 已过期" if status["expired"] else "✅ 有效"
            print(f"{flag}  {status['mtime']}  ({status['age_days']:.1f}/{status['ttl_days']} 天)")
            print(f"   覆盖: {status['n_stocks']} 只股票 / {status['n_industries']} 个行业")
            print(f"   路径: {status['path']}")
        return 0

    # ── 静默模式：缓存有效则直接退出 ──
    if args.quiet and not args.force and status["exists"] and not status["expired"]:
        return 0

    # ── 执行刷新 ──
    need_refresh = args.force or not status["exists"] or status["expired"]
    if not need_refresh:
        print(f"✅ 申万行业缓存有效（{status['age_days']:.1f} 天），无需刷新")
        print(f"   {status['n_stocks']} 只股票 / {status['n_industries']} 个行业")
        return 0

    reason = "强制" if args.force else ("首次" if not status["exists"] else "已过期")
    print(f"🔄 刷新申万行业分类（{reason}）...")

    try:
        df = refresh_industry_classification(force=True)
        n_stocks = len(df)
        n_industries = df["industry_code"].nunique()
        new_mtime = datetime.fromtimestamp(_INDUSTRY_CACHE_PATH.stat().st_mtime)
        print(f"✅ 完成  {new_mtime.strftime('%Y-%m-%d %H:%M')}")
        print(f"   {n_stocks} 只股票 / {n_industries} 个行业")
        print(f"   缓存: {_INDUSTRY_CACHE_PATH}")
        return 0
    except Exception as exc:
        print(f"❌ 刷新失败: {exc}", file=sys.stderr)
        # 检查是否还有可用的旧缓存
        if status["exists"]:
            print(f"   使用旧缓存（{status['age_days']:.1f} 天前）", file=sys.stderr)
            return 0  # 不致命，旧缓存仍可用
        return 1


if __name__ == "__main__":
    sys.exit(main())
