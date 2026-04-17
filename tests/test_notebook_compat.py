import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import pandas as pd


class TestDataLoaderNotebookFallback(unittest.TestCase):
    def test_load_price_matrix_falls_back_to_local_csv(self):
        from utils import data_loader as dl

        dates = pd.date_range("2024-01-01", periods=3, freq="B")
        wide = pd.DataFrame(
            {
                "000001": [10.0, 10.2, 10.3],
                "000002": [20.0, 20.1, 20.4],
            },
            index=dates,
        )

        with tempfile.TemporaryDirectory() as tmp:
            processed_dir = Path(tmp)
            with patch.object(dl, "PROCESSED_DIR", processed_dir):
                with patch("utils.local_data_loader.get_all_symbols", return_value=["000001", "000002"]):
                    with patch("utils.local_data_loader.load_price_wide", return_value=wide):
                        result = dl.load_price_matrix(
                            start="2024-01-01",
                            end="2024-01-31",
                            n_stocks=2,
                        )

            self.assertIsInstance(result, pd.DataFrame)
            self.assertEqual(result.shape, (3, 2))
            self.assertTrue((processed_dir / "price_wide_close_2024-01-01_2024-01-31_qfq_2stocks.parquet").exists())


class TestWalkForwardNotebookCompatibility(unittest.TestCase):
    def test_walk_forward_accepts_legacy_four_arg_strategy_fn(self):
        from utils.walk_forward import walk_forward_test

        dates = pd.bdate_range("2020-01-01", periods=900)
        price_wide = pd.DataFrame(
            {
                "000001": 10 + pd.Series(range(len(dates)), index=dates) * 0.01,
                "000002": 20 + pd.Series(range(len(dates)), index=dates) * 0.02,
            },
            index=dates,
        )
        factor_data = {"dummy": ("ignored", 1)}

        def legacy_strategy_fn(price_slice, factor_slice, train_start, train_end):
            returns = price_slice["000001"].pct_change().dropna()
            return returns.iloc[-21:]

        result = walk_forward_test(
            strategy_fn=legacy_strategy_fn,
            price_wide=price_wide,
            factor_data=factor_data,
            train_years=2,
            test_months=3,
        )

        self.assertFalse(result.empty)
        self.assertIn("sharpe", result.columns)
        self.assertTrue(result["n_periods"].notna().all())


class TestWalkForwardEmbargo(unittest.TestCase):
    """验证 embargo_days 参数正确把训练期末截到 train_end - embargo_days 日。"""

    def _make_fixtures(self):
        dates = pd.bdate_range("2020-01-01", periods=900)
        price_wide = pd.DataFrame(
            {
                "000001": 10 + pd.Series(range(len(dates)), index=dates) * 0.01,
            },
            index=dates,
        )
        return dates, price_wide

    def test_embargo_shortens_train_end(self):
        from utils.walk_forward import walk_forward_test

        _dates, price_wide = self._make_fixtures()
        observed_train_ends = []

        def probe_fn(price_slice, factor_slice, train_start, train_end):
            observed_train_ends.append((train_start, train_end))
            return price_slice["000001"].pct_change().dropna().iloc[-21:]

        result_no_emb = walk_forward_test(
            strategy_fn=probe_fn,
            price_wide=price_wide,
            factor_data={},
            train_years=2,
            test_months=3,
            embargo_days=0,
        )
        no_emb_train_end_0 = result_no_emb.iloc[0]["train_end"]

        observed_train_ends.clear()
        result_emb = walk_forward_test(
            strategy_fn=probe_fn,
            price_wide=price_wide,
            factor_data={},
            train_years=2,
            test_months=3,
            embargo_days=10,
        )
        emb_train_end_0 = result_emb.iloc[0]["train_end"]
        test_start_0 = result_emb.iloc[0]["test_start"]

        # Embargo 应把训练期末提前
        self.assertLess(emb_train_end_0, no_emb_train_end_0)
        # test_start 不应变（embargo 只缩训练, 不挪测试）
        self.assertEqual(test_start_0, result_no_emb.iloc[0]["test_start"])
        # train_end 与 test_start 之间至少有 embargo_days 个交易日 gap
        gap = len(pd.bdate_range(emb_train_end_0, test_start_0)) - 2
        self.assertGreaterEqual(gap, 9)  # 10d embargo - 1 边界 = 9 实际 gap

    def test_embargo_rejects_negative(self):
        from utils.walk_forward import walk_forward_test

        _dates, price_wide = self._make_fixtures()
        with self.assertRaises(ValueError):
            walk_forward_test(
                strategy_fn=lambda *a: pd.Series(),
                price_wide=price_wide,
                factor_data={},
                train_years=2,
                test_months=3,
                embargo_days=-1,
            )


if __name__ == "__main__":
    unittest.main()
