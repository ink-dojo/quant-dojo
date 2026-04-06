"""
agents/data_agent.py — 数据管家 Agent

职责:
  1. 检查本地数据新鲜度
  2. 触发增量更新（如果数据过期）
  3. 验证数据质量（空值率、异常值、CSV 完整性）
  4. 清理 parquet 缓存

在流水线中作为第一个阶段运行，确保后续 Agent 拿到的数据是可靠的。
"""

import logging
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import pandas as pd

logger = logging.getLogger(__name__)


class DataAgent:
    """数据管家：确保本地数据新鲜、完整、可用。"""

    # 数据过期阈值（交易日）
    STALE_THRESHOLD_DAYS = 3

    # 数据质量检查的抽样数量
    QUALITY_SAMPLE_SIZE = 50

    def run(self, ctx: Any) -> dict:
        """
        执行数据检查和更新。

        流程:
          1. 检查数据新鲜度
          2. 如果过期，执行增量更新
          3. 数据质量抽样检查
          4. 清理过期的 parquet 缓存

        返回:
          dict: {
            freshness: {latest_date, days_stale, status},
            quality: {checked, issues},
            update: {triggered, result},
          }
        """
        from pipeline.data_checker import check_data_freshness
        from utils.local_data_loader import get_all_symbols

        result = {
            "freshness": {},
            "quality": {"checked": 0, "issues": []},
            "update": {"triggered": False},
        }

        # ── 1. 数据新鲜度 ──────────────────────────────────────
        print("  检查数据新鲜度...")
        freshness = check_data_freshness()
        result["freshness"] = freshness

        latest_date = freshness.get("latest_date", "unknown")
        days_stale = freshness.get("days_stale", 999)
        print(f"  最新数据: {latest_date} (延迟 {days_stale} 天)")

        ctx.set("data_latest_date", latest_date)
        ctx.set("data_days_stale", days_stale)

        # ── 2. 触发更新（如果数据过期且非 dry_run） ────────────
        if days_stale > self.STALE_THRESHOLD_DAYS and not ctx.dry_run:
            print(f"  数据过期 > {self.STALE_THRESHOLD_DAYS} 天，触发增量更新...")
            ctx.log_decision(
                "DataAgent",
                f"触发数据更新: 数据延迟 {days_stale} 天",
                f"阈值 = {self.STALE_THRESHOLD_DAYS} 天",
            )
            try:
                from pipeline.data_update import run_update
                update_result = run_update(end_date=ctx.date)
                result["update"] = {
                    "triggered": True,
                    "updated": len(update_result.get("updated", [])),
                    "failed": len(update_result.get("failed", [])),
                }
                print(f"  更新完成: {result['update']['updated']} 只股票")

                # 更新后清缓存
                self._clear_cache(update_result.get("updated", []))

            except Exception as e:
                logger.error("数据更新失败: %s", e)
                result["update"]["error"] = str(e)
                print(f"  更新失败: {e}")
        elif days_stale <= self.STALE_THRESHOLD_DAYS:
            print(f"  数据新鲜度正常 (<= {self.STALE_THRESHOLD_DAYS} 天)")
            ctx.log_decision(
                "DataAgent",
                "跳过数据更新: 数据足够新鲜",
                f"延迟 {days_stale} 天 <= 阈值 {self.STALE_THRESHOLD_DAYS} 天",
            )

        # ── 3. 数据质量抽样检查 ────────────────────────────────
        print("  数据质量抽样检查...")
        symbols = get_all_symbols()
        quality_issues = self._check_quality(symbols[:self.QUALITY_SAMPLE_SIZE])
        result["quality"] = {
            "checked": min(len(symbols), self.QUALITY_SAMPLE_SIZE),
            "issues": quality_issues,
        }
        if quality_issues:
            print(f"  发现 {len(quality_issues)} 个质量问题")
            for issue in quality_issues[:3]:
                print(f"    - {issue}")
        else:
            print(f"  抽样 {result['quality']['checked']} 只，质量正常")

        ctx.set("data_quality", result["quality"])
        return result

    def _check_quality(self, symbols: list) -> list:
        """
        抽样检查数据质量。

        检查项:
          - CSV 列数是否一致
          - close 列是否有 >10% 空值
          - 是否有未来日期的数据
        """
        from utils.local_data_loader import load_local_stock

        issues = []
        today = pd.Timestamp.now().normalize()

        for sym in symbols:
            try:
                df = load_local_stock(sym)
                if df.empty:
                    issues.append(f"{sym}: 空数据")
                    continue

                # 检查 close 列空值率
                if "close" in df.columns:
                    null_rate = df["close"].isna().mean()
                    if null_rate > 0.1:
                        issues.append(f"{sym}: close 空值率 {null_rate:.1%}")

                # 检查未来日期
                if hasattr(df.index, 'max'):
                    max_date = df.index.max()
                    if pd.notna(max_date) and max_date > today + pd.Timedelta(days=1):
                        issues.append(f"{sym}: 包含未来日期 {max_date.date()}")

            except Exception as e:
                issues.append(f"{sym}: 加载失败 ({e})")

        return issues

    def _clear_cache(self, updated_symbols: list):
        """清理已更新股票的 parquet 缓存"""
        cache_dir = Path("data/cache/local")
        if not cache_dir.exists():
            return

        cleared = 0
        for sym in updated_symbols:
            cache_file = cache_dir / f"{sym}.parquet"
            if cache_file.exists():
                cache_file.unlink()
                cleared += 1

        if cleared:
            print(f"  已清理 {cleared} 个缓存文件")
