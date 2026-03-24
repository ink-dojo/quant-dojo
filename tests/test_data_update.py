"""
test_data_update.py — providers 和 pipeline.data_update 模块的集成测试

这些模块可能在并行任务中创建，所以使用 pytest.importorskip 确保测试不会硬失败。
"""

import sys
import inspect
import unittest
from unittest.mock import MagicMock

# 预注入缺失的第三方依赖 stub
for _pkg in ("akshare",):
    if _pkg not in sys.modules:
        sys.modules[_pkg] = MagicMock()


class TestDataUpdateModules(unittest.TestCase):
    """测试 providers 和 data_update 模块的接口和结构。"""

    def test_provider_base_has_abstract_methods(self):
        """BaseDataProvider 应该定义核心的抽象方法。"""
        try:
            from providers.base import BaseDataProvider
        except ImportError:
            self.skipTest("providers.base 模块不存在，跳过此测试")
            return

        # 检查 BaseDataProvider 是否有预期的方法
        required_methods = {"get_stock_list", "fetch_daily_history", "incremental_update"}
        for method_name in required_methods:
            self.assertTrue(
                hasattr(BaseDataProvider, method_name),
                f"BaseDataProvider 缺少方法: {method_name}"
            )

    def test_akshare_provider_import(self):
        """AkShareProvider 应该能够被导入。"""
        try:
            from providers.akshare_provider import AkShareProvider
        except ImportError:
            self.skipTest("providers.akshare_provider 模块不存在，跳过此测试")
            return

        # 如果导入成功，确保 AkShareProvider 是一个类
        self.assertTrue(
            inspect.isclass(AkShareProvider),
            "AkShareProvider 应该是一个类"
        )

    def test_akshare_provider_is_subclass(self):
        """AkShareProvider 应该是 BaseDataProvider 的子类。"""
        try:
            from providers.base import BaseDataProvider
            from providers.akshare_provider import AkShareProvider
        except ImportError:
            self.skipTest("providers 模块不完整，跳过此测试")
            return

        self.assertTrue(
            issubclass(AkShareProvider, BaseDataProvider),
            "AkShareProvider 应该继承自 BaseDataProvider"
        )

    def test_run_update_signature(self):
        """run_update() 函数应该有正确的参数签名。"""
        try:
            from pipeline.data_update import run_update
        except ImportError:
            self.skipTest("pipeline.data_update 模块不存在，跳过此测试")
            return

        # 检查函数签名
        sig = inspect.signature(run_update)
        params = set(sig.parameters.keys())

        required_params = {"symbols", "end_date", "dry_run"}
        missing_params = required_params - params

        self.assertEqual(
            len(missing_params),
            0,
            f"run_update() 缺少参数: {missing_params}"
        )

    def test_run_update_dry_run(self):
        """run_update(dry_run=True) 应该不抛异常并返回合法的结果结构。"""
        try:
            from pipeline.data_update import run_update
        except ImportError:
            self.skipTest("pipeline.data_update 模块不存在，跳过此测试")
            return

        try:
            # 使用 dry_run=True 执行，不应该修改真实数据
            result = run_update(
                symbols=["000001"],
                end_date="2026-01-10",
                dry_run=True
            )

            # 返回值应该是 dict，包含 updated, skipped, failed 等 key
            self.assertIsInstance(
                result,
                dict,
                f"run_update() 应返回 dict，实际返回 {type(result)}"
            )

            # 检查返回结构中是否有预期的 key
            expected_keys = {"updated", "skipped", "failed"}
            for key in expected_keys:
                self.assertIn(
                    key,
                    result,
                    f"run_update() 返回的 dict 缺少 key: {key}"
                )

        except Exception as e:
            self.fail(f"run_update(dry_run=True) 抛异常: {e}")


if __name__ == "__main__":
    unittest.main()
