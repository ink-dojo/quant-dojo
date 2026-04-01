from pathlib import Path

import pandas as pd

from utils import data_loader


def test_get_index_history_prefers_local_cache(monkeypatch, tmp_path):
    cache_dir = tmp_path / "indices"
    cache_dir.mkdir(parents=True, exist_ok=True)
    cache_path = cache_dir / "sh000300.parquet"
    cached = pd.DataFrame(
        {
            "open": [1.0, 2.0, 3.0],
            "high": [1.1, 2.1, 3.1],
            "low": [0.9, 1.9, 2.9],
            "close": [1.0, 2.0, 3.0],
            "volume": [10, 20, 30],
            "amount": [100, 200, 300],
        },
        index=pd.to_datetime(["2026-01-01", "2026-01-02", "2026-01-03"]),
    )
    cached.to_parquet(cache_path)

    monkeypatch.setattr(data_loader, "INDEX_CACHE_DIR", cache_dir)
    monkeypatch.setattr(
        data_loader,
        "_fetch_index_history_akshare",
        lambda symbol: (_ for _ in ()).throw(AssertionError("should not fetch akshare")),
    )
    monkeypatch.setattr(
        data_loader,
        "_fetch_index_history_baostock",
        lambda symbol: (_ for _ in ()).throw(AssertionError("should not fetch baostock")),
    )

    result = data_loader.get_index_history("sh000300", "2026-01-01", "2026-01-03")

    assert list(result.index) == list(cached.index)
    assert result.loc[pd.Timestamp("2026-01-02"), "close"] == 2.0


def test_get_index_history_writes_cache_after_provider_fetch(monkeypatch, tmp_path):
    cache_dir = tmp_path / "indices"
    monkeypatch.setattr(data_loader, "INDEX_CACHE_DIR", cache_dir)

    fetched = pd.DataFrame(
        {
            "date": pd.to_datetime(["2026-01-01", "2026-01-02", "2026-01-03"]),
            "open": [1.0, 2.0, 3.0],
            "high": [1.1, 2.1, 3.1],
            "low": [0.9, 1.9, 2.9],
            "close": [1.0, 2.0, 3.0],
            "volume": [10, 20, 30],
            "amount": [100, 200, 300],
        }
    )

    monkeypatch.setattr(data_loader, "_fetch_index_history_akshare", lambda symbol: fetched)
    monkeypatch.setattr(
        data_loader,
        "_fetch_index_history_baostock",
        lambda symbol: (_ for _ in ()).throw(AssertionError("should not fetch baostock")),
    )

    result = data_loader.get_index_history("sh000300", "2026-01-02", "2026-01-03", use_cache=True)

    assert list(result.index) == list(pd.to_datetime(["2026-01-02", "2026-01-03"]))
    cache_path = cache_dir / "sh000300.parquet"
    assert cache_path.exists()
    cached = pd.read_parquet(cache_path)
    assert pd.Timestamp("2026-01-01") in cached.index
