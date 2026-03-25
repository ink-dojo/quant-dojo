"""
data_loader.py — 底层文件读取工具函数

从 live/ 目录读取持仓、净值和信号文件，所有函数捕获异常并返回空值，不抛出。
"""

import json
from pathlib import Path

# live/ 目录根路径（相对于本文件向上两级）
_LIVE_DIR = Path(__file__).parent.parent.parent / "live"
_PORTFOLIO_DIR = _LIVE_DIR / "portfolio"
_SIGNALS_DIR = _LIVE_DIR / "signals"


def load_nav_csv() -> list[dict]:
    """
    读取 live/portfolio/nav.csv，返回净值历史列表。

    返回:
        list[dict]，格式为 [{"date": "2026-03-20", "nav": 1050000.0}, ...]
        文件不存在或读取失败时返回 []
    """
    try:
        import csv
        nav_file = _PORTFOLIO_DIR / "nav.csv"
        if not nav_file.exists():
            return []
        with open(nav_file, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            result = []
            for row in reader:
                try:
                    result.append({"date": row["date"], "nav": float(row["nav"])})
                except (KeyError, ValueError):
                    continue
        return result
    except Exception:
        return []


def load_positions_json() -> dict:
    """
    读取 live/portfolio/positions.json，返回持仓字典。

    返回:
        dict，格式为 {"600000.SH": {"shares": 100, "cost_price": 10.0, "current_price": 11.0}, ...}
        文件不存在或读取失败时返回 {}
    """
    try:
        positions_file = _PORTFOLIO_DIR / "positions.json"
        if not positions_file.exists():
            return {}
        with open(positions_file, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def load_latest_signal() -> dict:
    """
    扫描 live/signals/ 下最新日期的 json 文件，返回信号内容。

    文件命名约定：signals_YYYY-MM-DD.json 或 YYYY-MM-DD.json
    取文件名中日期最大的那个。

    返回:
        dict，包含信号内容；无文件或读取失败时返回 {}
    """
    try:
        if not _SIGNALS_DIR.exists():
            return {}
        signal_files = sorted(_SIGNALS_DIR.glob("*.json"))
        if not signal_files:
            return {}
        latest_file = signal_files[-1]
        with open(latest_file, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def load_signal_history(n: int = 10) -> list[dict]:
    """
    返回最近 n 个信号文件的日期和当期持仓数。

    参数:
        n: 返回最近几期，默认 10

    返回:
        list[dict]，格式为 [{"date": "2026-03-20", "n_picks": 5}, ...]
        按日期升序排列；无文件或读取失败时返回 []
    """
    try:
        if not _SIGNALS_DIR.exists():
            return []
        signal_files = sorted(_SIGNALS_DIR.glob("*.json"))[-n:]
        result = []
        for f in signal_files:
            try:
                with open(f, "r", encoding="utf-8") as fh:
                    data = json.load(fh)
                # 从文件名提取日期（取最后 10 个字符去掉 .json）
                date_str = f.stem[-10:] if len(f.stem) >= 10 else f.stem
                picks = data.get("picks", data.get("selected_stocks", []))
                n_picks = len(picks) if isinstance(picks, list) else 0
                result.append({"date": date_str, "n_picks": n_picks})
            except Exception:
                continue
        return result
    except Exception:
        return []


if __name__ == "__main__":
    print("=== nav.csv ===")
    nav = load_nav_csv()
    print(f"共 {len(nav)} 条记录，最新: {nav[-1] if nav else '无'}")

    print("\n=== positions.json ===")
    pos = load_positions_json()
    print(f"持仓股票数: {sum(1 for k in pos if k != '__cash__')}")
    print(f"现金: {pos.get('__cash__', '无')}")

    print("\n=== latest signal ===")
    sig = load_latest_signal()
    print(sig if sig else "无信号文件")

    print("\n=== signal history (last 5) ===")
    hist = load_signal_history(n=5)
    print(hist if hist else "无历史信号")

    print("\n✅ data_loader 检查完毕")
