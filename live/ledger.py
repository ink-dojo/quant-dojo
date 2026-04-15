"""
live/ledger.py — SQLite 账本（ACID 持仓/交易/净值）

动机
----
原先 paper_trader 用 positions.json + trades.json + nav.csv 做状态存储。
问题：
  - json.dump 不是原子写（覆盖式写盘，中断即损坏）
  - 多进程并发调仓 threading.Lock 管不了
  - trades.json 追加时要先整表 load 再整表 dump，崩溃会丢失整段历史
  - 无事务：写 positions 成功但 nav.csv 失败，状态漂移

本模块：
  - SQLite WAL 模式，支持并发读 + 独占写
  - 三张表：trades（append-only）、nav_history、positions
  - 每个 rebalance 包在一个事务里，要么全成功要么回滚
  - 提供 `Ledger` 类，API 形态贴近 PaperTrader 的内部写法
  - 可从 legacy JSON 一次性迁移

放在哪里
--------
- 存盘：live/portfolio/ledger.db
- 和 JSON 并存：PaperTrader 内部写两份（SQLite 主，JSON 作为 dashboard/tests 的读缓存）
- JSON 损坏或缺失时，Ledger.rehydrate_to_json() 从 SQLite 重建
"""

from __future__ import annotations

import json
import logging
import sqlite3
import threading
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger(__name__)


_SCHEMA = """
CREATE TABLE IF NOT EXISTS trades (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    trade_date TEXT NOT NULL,
    symbol TEXT NOT NULL,
    action TEXT NOT NULL CHECK(action IN ('buy', 'sell')),
    shares INTEGER NOT NULL CHECK(shares > 0),
    price REAL NOT NULL CHECK(price > 0),
    cost REAL NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_trades_date ON trades(trade_date);
CREATE INDEX IF NOT EXISTS idx_trades_symbol ON trades(symbol);

CREATE TABLE IF NOT EXISTS nav_history (
    trade_date TEXT PRIMARY KEY,
    nav REAL NOT NULL,
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS positions (
    symbol TEXT PRIMARY KEY,
    shares INTEGER NOT NULL,
    cost_price REAL NOT NULL,
    current_price REAL NOT NULL,
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS meta (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL,
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);
"""


class Ledger:
    """SQLite 账本。线程/进程安全（WAL + explicit transactions）。"""

    # 进程内共享一把锁，避免同一连接被两个线程同时 BEGIN
    _proc_lock = threading.Lock()

    def __init__(self, db_path: Path, initial_capital: Optional[float] = None):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(
            str(self.db_path),
            check_same_thread=False,
            isolation_level=None,  # autocommit off via manual transaction
            timeout=30.0,
        )
        self._conn.row_factory = sqlite3.Row
        # WAL: 多进程可读、单进程可写；断电后能恢复到最后一个 checkpoint
        self._conn.execute("PRAGMA journal_mode=WAL;")
        self._conn.execute("PRAGMA synchronous=NORMAL;")
        self._conn.execute("PRAGMA foreign_keys=ON;")
        self._conn.executescript(_SCHEMA)

        if initial_capital is not None:
            self.set_meta("initial_capital", str(initial_capital), overwrite=False)

    def close(self) -> None:
        try:
            self._conn.close()
        except sqlite3.Error:
            pass

    # ------------------------------------------------------------------
    # 事务
    # ------------------------------------------------------------------
    @contextmanager
    def transaction(self):
        """独占事务。用法：with ledger.transaction(): ..."""
        with self._proc_lock:
            self._conn.execute("BEGIN IMMEDIATE;")
            try:
                yield self._conn
                self._conn.execute("COMMIT;")
            except Exception:
                self._conn.execute("ROLLBACK;")
                raise

    # ------------------------------------------------------------------
    # 写
    # ------------------------------------------------------------------
    def append_trade(self, trade: dict) -> int:
        """追加一笔交易，返回 rowid。"""
        with self.transaction() as conn:
            cur = conn.execute(
                """INSERT INTO trades (trade_date, symbol, action, shares, price, cost)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (
                    trade["date"],
                    trade["symbol"],
                    trade["action"],
                    int(trade["shares"]),
                    float(trade["price"]),
                    float(trade.get("cost", 0.0)),
                ),
            )
            return cur.lastrowid

    def upsert_nav(self, trade_date: str, nav: float) -> None:
        """写入/覆盖一日净值。"""
        with self.transaction() as conn:
            conn.execute(
                """INSERT INTO nav_history (trade_date, nav) VALUES (?, ?)
                   ON CONFLICT(trade_date) DO UPDATE SET
                     nav=excluded.nav,
                     updated_at=datetime('now')""",
                (trade_date, float(nav)),
            )

    def replace_positions(self, positions: dict) -> None:
        """
        用 positions 字典整体替换仓位表（不包括 __cash__）。
        现金通过 meta 表独立存储。
        """
        with self.transaction() as conn:
            conn.execute("DELETE FROM positions;")
            for sym, info in positions.items():
                if sym == "__cash__":
                    conn.execute(
                        """INSERT INTO meta (key, value, updated_at)
                           VALUES ('cash', ?, datetime('now'))
                           ON CONFLICT(key) DO UPDATE SET
                             value=excluded.value,
                             updated_at=datetime('now')""",
                        (str(float(info)),),
                    )
                    continue
                conn.execute(
                    """INSERT INTO positions (symbol, shares, cost_price, current_price)
                       VALUES (?, ?, ?, ?)""",
                    (
                        sym,
                        int(info["shares"]),
                        float(info["cost_price"]),
                        float(info["current_price"]),
                    ),
                )

    def set_meta(self, key: str, value: str, overwrite: bool = True) -> None:
        with self.transaction() as conn:
            if overwrite:
                conn.execute(
                    """INSERT INTO meta (key, value) VALUES (?, ?)
                       ON CONFLICT(key) DO UPDATE SET
                         value=excluded.value,
                         updated_at=datetime('now')""",
                    (key, value),
                )
            else:
                conn.execute(
                    "INSERT OR IGNORE INTO meta (key, value) VALUES (?, ?)",
                    (key, value),
                )

    # ------------------------------------------------------------------
    # 读
    # ------------------------------------------------------------------
    def read_trades(self) -> list[dict]:
        rows = self._conn.execute(
            "SELECT trade_date, symbol, action, shares, price, cost "
            "FROM trades ORDER BY id ASC"
        ).fetchall()
        return [
            {
                "date": r["trade_date"],
                "symbol": r["symbol"],
                "action": r["action"],
                "shares": r["shares"],
                "price": r["price"],
                "cost": r["cost"],
            }
            for r in rows
        ]

    def read_positions(self) -> dict:
        rows = self._conn.execute(
            "SELECT symbol, shares, cost_price, current_price FROM positions"
        ).fetchall()
        positions: dict = {}
        for r in rows:
            positions[r["symbol"]] = {
                "shares": r["shares"],
                "cost_price": r["cost_price"],
                "current_price": r["current_price"],
            }
        # 把现金读回
        cash_row = self._conn.execute(
            "SELECT value FROM meta WHERE key='cash'"
        ).fetchone()
        if cash_row is not None:
            positions["__cash__"] = float(cash_row["value"])
        return positions

    def read_nav(self) -> list[tuple[str, float]]:
        rows = self._conn.execute(
            "SELECT trade_date, nav FROM nav_history ORDER BY trade_date ASC"
        ).fetchall()
        return [(r["trade_date"], r["nav"]) for r in rows]

    def get_meta(self, key: str) -> Optional[str]:
        row = self._conn.execute(
            "SELECT value FROM meta WHERE key=?", (key,)
        ).fetchone()
        return row["value"] if row else None

    # ------------------------------------------------------------------
    # 迁移 / 重建
    # ------------------------------------------------------------------
    def migrate_from_json(
        self,
        positions_file: Path,
        trades_file: Path,
        nav_file: Path,
    ) -> dict:
        """
        首次从 JSON/CSV 导入数据。只在 SQLite 空时执行。
        返回 {imported_trades, imported_nav_rows, had_positions}。
        """
        if self.read_trades() or self.read_nav():
            return {"imported_trades": 0, "imported_nav_rows": 0, "had_positions": False,
                    "note": "SQLite 已有数据，跳过迁移"}

        imported_trades = 0
        imported_nav = 0
        had_positions = False

        with self.transaction() as conn:
            if trades_file.exists():
                try:
                    with open(trades_file, "r", encoding="utf-8") as f:
                        trades = json.load(f)
                    for t in trades:
                        if not all(k in t for k in ("date", "symbol", "action", "shares", "price")):
                            continue
                        conn.execute(
                            """INSERT INTO trades (trade_date, symbol, action, shares, price, cost)
                               VALUES (?, ?, ?, ?, ?, ?)""",
                            (t["date"], t["symbol"], t["action"],
                             int(t["shares"]), float(t["price"]),
                             float(t.get("cost", 0.0))),
                        )
                        imported_trades += 1
                except (json.JSONDecodeError, OSError) as exc:
                    logger.warning("trades.json 迁移失败: %s", exc)

            if nav_file.exists():
                try:
                    import pandas as pd
                    nav_df = pd.read_csv(nav_file)
                    for _, row in nav_df.iterrows():
                        conn.execute(
                            """INSERT INTO nav_history (trade_date, nav) VALUES (?, ?)
                               ON CONFLICT(trade_date) DO UPDATE SET nav=excluded.nav""",
                            (str(row["date"]), float(row["nav"])),
                        )
                        imported_nav += 1
                except Exception as exc:
                    logger.warning("nav.csv 迁移失败: %s", exc)

            if positions_file.exists():
                try:
                    with open(positions_file, "r", encoding="utf-8") as f:
                        positions = json.load(f)
                    for sym, info in positions.items():
                        if sym == "__cash__":
                            conn.execute(
                                """INSERT INTO meta (key, value) VALUES ('cash', ?)
                                   ON CONFLICT(key) DO UPDATE SET
                                     value=excluded.value,
                                     updated_at=datetime('now')""",
                                (str(float(info)),),
                            )
                            had_positions = True
                            continue
                        if not isinstance(info, dict) or "shares" not in info:
                            continue
                        conn.execute(
                            """INSERT INTO positions (symbol, shares, cost_price, current_price)
                               VALUES (?, ?, ?, ?)""",
                            (sym, int(info["shares"]),
                             float(info.get("cost_price", 0.0)),
                             float(info.get("current_price", 0.0))),
                        )
                    had_positions = True
                except (json.JSONDecodeError, OSError) as exc:
                    logger.warning("positions.json 迁移失败: %s", exc)

        return {
            "imported_trades": imported_trades,
            "imported_nav_rows": imported_nav,
            "had_positions": had_positions,
        }

    def rehydrate_to_json(
        self,
        positions_file: Path,
        trades_file: Path,
        nav_file: Path,
    ) -> None:
        """从 SQLite 把 JSON/CSV 重建一遍，供 dashboard/tests 读取。"""
        trades = self.read_trades()
        positions = self.read_positions()
        nav = self.read_nav()

        # 原子写 JSON：先写 tmp 再 rename
        def _atomic_write_json(path: Path, data: Any) -> None:
            path.parent.mkdir(parents=True, exist_ok=True)
            tmp = path.with_suffix(path.suffix + ".tmp")
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            tmp.replace(path)

        _atomic_write_json(trades_file, trades)
        _atomic_write_json(positions_file, positions)

        nav_file.parent.mkdir(parents=True, exist_ok=True)
        tmp = nav_file.with_suffix(nav_file.suffix + ".tmp")
        with open(tmp, "w", encoding="utf-8") as f:
            f.write("date,nav\n")
            for d, v in nav:
                f.write(f"{d},{v}\n")
        tmp.replace(nav_file)


if __name__ == "__main__":
    import tempfile
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    with tempfile.TemporaryDirectory() as tmp:
        db = Ledger(Path(tmp) / "test.db", initial_capital=1_000_000)
        db.set_meta("cash", "1000000")
        tid = db.append_trade({
            "date": "2026-04-14", "symbol": "600000",
            "action": "buy", "shares": 100, "price": 10.5, "cost": 3.15,
        })
        print(f"插入交易 id={tid}")
        db.upsert_nav("2026-04-14", 1_000_000)
        db.replace_positions({
            "__cash__": 998946.85,
            "600000": {"shares": 100, "cost_price": 10.5, "current_price": 10.5},
        })
        print("交易:", db.read_trades())
        print("净值:", db.read_nav())
        print("持仓:", db.read_positions())
        print("initial_capital:", db.get_meta("initial_capital"))
        print("✅ Ledger smoke test ok")
        db.close()
