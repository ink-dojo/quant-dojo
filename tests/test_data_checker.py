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


    def test_freshness_reads_english_date_column(self):
        """checker 能正确读取 data_update 写出的英文 date 列 CSV。"""
        import pandas as pd
        from pipeline.data_checker import check_data_freshness

        with tempfile.TemporaryDirectory() as tmp:
            # 模拟 data_update 写出的文件格式
            csv_path = Path(tmp) / "sh.600000.csv"
            pd.DataFrame({
                "date": ["2026-03-20", "2026-03-21"],
                "open": [10.0, 10.5],
                "high": [11.0, 11.2],
                "low": [9.5, 9.8],
                "close": [10.5, 10.8],
                "volume": [1000, 1200],
                "amount": [10000.0, 12000.0],
            }).to_csv(csv_path, index=False)

            result = check_data_freshness(data_dir=tmp)

        self.assertEqual(result["latest_date"], "2026-03-21")
        self.assertIsInstance(result["days_stale"], int)
        self.assertIn(result["status"], {"ok", "stale"})

    def test_freshness_reads_chinese_date_column(self):
        """checker 也能读取旧格式的中文日期列。"""
        import pandas as pd
        from pipeline.data_checker import check_data_freshness

        with tempfile.TemporaryDirectory() as tmp:
            csv_path = Path(tmp) / "sz.000001.csv"
            pd.DataFrame({
                "交易所行情日期": ["2026-03-18", "2026-03-19"],
                "开盘价": [10.0, 10.5],
            }).to_csv(csv_path, index=False)

            result = check_data_freshness(data_dir=tmp)

        self.assertEqual(result["latest_date"], "2026-03-19")
        self.assertIsInstance(result["days_stale"], int)


    def test_freshness_changes_after_file_write(self):
        """写入更新日期的 CSV 后，freshness 应反映最新日期。"""
        import pandas as pd
        from datetime import datetime
        from pipeline.data_checker import check_data_freshness

        with tempfile.TemporaryDirectory() as tmp:
            # 先写一个旧文件
            old_csv = Path(tmp) / "sh.600000.csv"
            pd.DataFrame({
                "date": ["2025-01-01"],
                "close": [10.0],
            }).to_csv(old_csv, index=False)

            result_old = check_data_freshness(data_dir=tmp)
            self.assertEqual(result_old["latest_date"], "2025-01-01")

            # 再写一个更新的文件
            today = datetime.now().strftime("%Y-%m-%d")
            new_csv = Path(tmp) / "sz.000001.csv"
            pd.DataFrame({
                "date": [today],
                "close": [11.0],
            }).to_csv(new_csv, index=False)

            result_new = check_data_freshness(data_dir=tmp)
            self.assertEqual(result_new["latest_date"], today)
            self.assertLessEqual(result_new["days_stale"], 1)

    def test_control_surface_freshness_matches_direct_call(self):
        """control_surface.execute('data.freshness') 应返回和直接调用一样的结果。"""
        from pipeline.data_checker import check_data_freshness
        from pipeline.control_surface import execute

        direct = check_data_freshness()
        via_cs = execute("data.freshness")

        self.assertEqual(via_cs["status"], "success")
        cs_data = via_cs["data"]

        # 两者的核心字段必须一致
        self.assertEqual(cs_data["latest_date"], direct["latest_date"])
        self.assertEqual(cs_data["status"], direct["status"])
        self.assertEqual(cs_data["days_stale"], direct["days_stale"])


class TestDataCLISmoke(unittest.TestCase):
    """CLI data 子命令 smoke test。"""

    def test_cli_data_status(self):
        """data status 应能成功运行。"""
        import subprocess
        result = subprocess.run(
            [sys.executable, "-m", "pipeline.cli", "data", "status"],
            capture_output=True, text=True, timeout=30,
        )
        # 允许 exit 1（数据缺失时），但不允许 argparse 报错
        self.assertNotIn("unrecognized arguments", result.stderr)
        self.assertNotIn("error: the following arguments are required", result.stderr)

    def test_cli_data_update_help(self):
        """data update --help 应成功输出帮助信息。"""
        import subprocess
        result = subprocess.run(
            [sys.executable, "-m", "pipeline.cli", "data", "update", "--help"],
            capture_output=True, text=True, timeout=15,
        )
        self.assertEqual(result.returncode, 0)
        self.assertIn("end-date", result.stdout)


if __name__ == "__main__":
    unittest.main()
