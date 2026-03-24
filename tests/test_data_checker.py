"""
test_data_checker.py — pipeline.data_checker 模块的单元测试

测试 check_data_freshness() 函数的返回结构和数据有效性。
"""

import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch, MagicMock

# 预注入缺失的第三方依赖 stub（如果需要）
for _pkg in ("akshare",):
    if _pkg not in sys.modules:
        sys.modules[_pkg] = MagicMock()


class TestDataChecker(unittest.TestCase):
    """测试 pipeline.data_checker.check_data_freshness() 的返回结构。"""

    def test_freshness_returns_required_fields(self):
        """check_data_freshness() 返回的 dict 必须包含所有必要的 key。"""
        from pipeline.data_checker import check_data_freshness

        # 空目录会返回 'missing' 状态
        with tempfile.TemporaryDirectory() as tmp:
            result = check_data_freshness(data_dir=tmp)

        required_keys = {"latest_date", "days_stale", "missing_symbols", "status"}
        for key in required_keys:
            self.assertIn(
                key,
                result,
                f"返回字典缺少必要的 key: {key}"
            )

    def test_freshness_status_values(self):
        """status 字段必须是 'ok', 'stale', 或 'missing' 之一。"""
        from pipeline.data_checker import check_data_freshness

        with tempfile.TemporaryDirectory() as tmp:
            result = check_data_freshness(data_dir=tmp)

        valid_statuses = {"ok", "stale", "missing"}
        self.assertIn(
            result["status"],
            valid_statuses,
            f"status 值无效: {result['status']}, 应为 {valid_statuses}"
        )

    def test_missing_symbols_is_list(self):
        """missing_symbols 字段必须始终是一个 list（可能为空）。"""
        from pipeline.data_checker import check_data_freshness

        with tempfile.TemporaryDirectory() as tmp:
            result = check_data_freshness(data_dir=tmp)

        self.assertIsInstance(
            result["missing_symbols"],
            list,
            f"missing_symbols 应为 list，实际为 {type(result['missing_symbols'])}"
        )

    def test_days_stale_type(self):
        """如果 days_stale 不为 None，必须是 int 且 >= 0。"""
        from pipeline.data_checker import check_data_freshness

        with tempfile.TemporaryDirectory() as tmp:
            result = check_data_freshness(data_dir=tmp)

        days_stale = result["days_stale"]

        if days_stale is not None:
            self.assertIsInstance(
                days_stale,
                int,
                f"days_stale 应为 int 或 None，实际为 {type(days_stale)}"
            )
            self.assertGreaterEqual(
                days_stale,
                0,
                f"days_stale 应 >= 0，实际为 {days_stale}"
            )


if __name__ == "__main__":
    unittest.main()
