"""
test_live_data.py — 实时数据层测试

测试覆盖：
  1. Sina provider 返回结构
  2. 行情数据校验（价格 > 0，字段完整）
  3. control surface live.quote 走通
  4. 安全校验（非法 symbol 不崩溃）
"""
import sys
import unittest
from unittest.mock import MagicMock

for _pkg in ("akshare",):
    if _pkg not in sys.modules:
        sys.modules[_pkg] = MagicMock()


class TestSinaProvider(unittest.TestCase):
    """测试新浪实时行情 Provider"""

    def test_fetch_returns_dict(self):
        """fetch_realtime_quotes 返回 dict"""
        from providers.sina_provider import fetch_realtime_quotes
        result = fetch_realtime_quotes(["600000"])
        self.assertIsInstance(result, dict)

    def test_quote_has_required_fields(self):
        """每条行情包含必要字段"""
        from providers.sina_provider import fetch_realtime_quotes
        result = fetch_realtime_quotes(["600000"])
        if "600000" in result:
            q = result["600000"]
            for field in ["name", "price", "open", "high", "low", "volume", "amount"]:
                self.assertIn(field, q, f"缺少字段: {field}")
            self.assertGreater(q["price"], 0, "价格应 > 0")

    def test_batch_fetch(self):
        """批量获取不崩溃"""
        from providers.sina_provider import fetch_realtime_quotes
        symbols = ["600000", "000001", "600519"]
        result = fetch_realtime_quotes(symbols)
        self.assertGreater(len(result), 0)

    def test_invalid_symbol_no_crash(self):
        """非法 symbol 不应导致崩溃"""
        from providers.sina_provider import fetch_realtime_quotes
        # 空列表
        result = fetch_realtime_quotes([])
        self.assertEqual(len(result), 0)

    def test_symbol_injection_blocked(self):
        """symbol 注入攻击被阻止"""
        from providers.sina_provider import _to_sina_code
        with self.assertRaises(ValueError):
            _to_sina_code("600000;rm -rf /")
        with self.assertRaises(ValueError):
            _to_sina_code("<script>")

    def test_control_surface_live_quote(self):
        """control surface 的 live.quote 命令走通"""
        from pipeline.control_surface import execute
        result = execute("live.quote", symbols=["600000"])
        self.assertEqual(result["status"], "success")
        self.assertIsInstance(result["data"], dict)


class TestLiveDataService(unittest.TestCase):
    """测试实时数据服务"""

    def test_market_hours_detection(self):
        """交易时间判断不崩溃"""
        from pipeline.live_data_service import is_market_hours, is_after_close
        # 不测具体值（依赖当前时间），只确认不崩溃
        self.assertIsInstance(is_market_hours(), bool)
        self.assertIsInstance(is_after_close(), bool)


if __name__ == "__main__":
    unittest.main()
