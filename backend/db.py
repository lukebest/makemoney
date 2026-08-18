"""SQLite persistence for settings, positions, trades, and journals."""

from __future__ import annotations

import json
import os
import sqlite3
import threading
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator, Mapping


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class Database:
    """Small thread-safe SQLite repository with explicit transactions."""

    def __init__(self, path: str | os.PathLike[str] | None = None) -> None:
        default = Path(__file__).resolve().parent / "data" / "makemoney.db"
        self.path = str(path or os.getenv("APP_DB_PATH") or default)
        Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()

    def connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=10, check_same_thread=False)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA busy_timeout = 10000")
        return connection

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        with self._lock:
            connection = self.connect()
            try:
                connection.execute("BEGIN IMMEDIATE")
                yield connection
                connection.commit()
            except Exception:
                connection.rollback()
                raise
            finally:
                connection.close()

    def initialize(self) -> None:
        with self.transaction() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS settings (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS positions (
                    code TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    quantity INTEGER NOT NULL CHECK (quantity > 0),
                    avg_price REAL NOT NULL CHECK (avg_price > 0),
                    stop_loss REAL NOT NULL CHECK (stop_loss > 0),
                    tier INTEGER NOT NULL DEFAULT 1 CHECK (tier BETWEEN 1 AND 3),
                    thesis TEXT NOT NULL DEFAULT '',
                    market TEXT NOT NULL DEFAULT 'A',
                    currency TEXT NOT NULL DEFAULT 'CNY',
                    fx_rate REAL NOT NULL DEFAULT 1,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS trades (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    code TEXT NOT NULL,
                    name TEXT NOT NULL,
                    side TEXT NOT NULL CHECK (side IN ('buy', 'sell')),
                    quantity INTEGER NOT NULL CHECK (quantity > 0),
                    price REAL NOT NULL CHECK (price > 0),
                    amount REAL NOT NULL,
                    logic TEXT NOT NULL DEFAULT '',
                    funds_confirmed INTEGER NOT NULL DEFAULT 0,
                    space_confirmed INTEGER NOT NULL DEFAULT 0,
                    stop_loss REAL,
                    realized_pnl REAL,
                    violated INTEGER NOT NULL DEFAULT 0,
                    note TEXT NOT NULL DEFAULT '',
                    market TEXT NOT NULL DEFAULT 'A',
                    currency TEXT NOT NULL DEFAULT 'CNY',
                    fx_rate REAL NOT NULL DEFAULT 1,
                    traded_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS journal (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    title TEXT NOT NULL,
                    content TEXT NOT NULL,
                    mood TEXT NOT NULL DEFAULT '',
                    tags TEXT NOT NULL DEFAULT '[]',
                    trade_id INTEGER,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    FOREIGN KEY (trade_id) REFERENCES trades(id) ON DELETE SET NULL
                );

                CREATE INDEX IF NOT EXISTS idx_trades_code_time
                    ON trades(code, traded_at);
                CREATE INDEX IF NOT EXISTS idx_journal_created
                    ON journal(created_at);

                CREATE TABLE IF NOT EXISTS close_screens (
                    as_of_date TEXT PRIMARY KEY,
                    for_date TEXT NOT NULL,
                    payload TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_close_screens_for_date
                    ON close_screens(for_date);

                CREATE TABLE IF NOT EXISTS snapshots (
                    key TEXT PRIMARY KEY,
                    payload TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                """
            )
            position_columns = {
                row["name"]
                for row in connection.execute("PRAGMA table_info(positions)").fetchall()
            }
            if "tier" not in position_columns:
                connection.execute(
                    "ALTER TABLE positions ADD COLUMN tier INTEGER NOT NULL DEFAULT 1"
                )
            for name, definition in (
                ("market", "TEXT NOT NULL DEFAULT 'A'"),
                ("currency", "TEXT NOT NULL DEFAULT 'CNY'"),
                ("fx_rate", "REAL NOT NULL DEFAULT 1"),
            ):
                if name not in position_columns:
                    connection.execute(
                        f"ALTER TABLE positions ADD COLUMN {name} {definition}"
                    )
            trade_columns = {
                row["name"]
                for row in connection.execute("PRAGMA table_info(trades)").fetchall()
            }
            for name, definition in (
                ("market", "TEXT NOT NULL DEFAULT 'A'"),
                ("currency", "TEXT NOT NULL DEFAULT 'CNY'"),
                ("fx_rate", "REAL NOT NULL DEFAULT 1"),
            ):
                if name not in trade_columns:
                    connection.execute(
                        f"ALTER TABLE trades ADD COLUMN {name} {definition}"
                    )
            now = utc_now()
            defaults = {
                "total_capital": 100000.0,
                "max_position_ratio": 0.30,
                "max_invested_ratio": 0.60,
            }
            for key, value in defaults.items():
                connection.execute(
                    "INSERT OR IGNORE INTO settings(key, value, updated_at) VALUES (?, ?, ?)",
                    (key, json.dumps(value), now),
                )

    def healthcheck(self) -> bool:
        try:
            with self.connect() as connection:
                return connection.execute("SELECT 1").fetchone()[0] == 1
        except sqlite3.Error:
            return False

    def get_settings(self) -> dict[str, Any]:
        with self.connect() as connection:
            rows = connection.execute("SELECT key, value FROM settings").fetchall()
        return {row["key"]: json.loads(row["value"]) for row in rows}

    def set_settings(self, values: Mapping[str, Any]) -> dict[str, Any]:
        now = utc_now()
        with self.transaction() as connection:
            for key, value in values.items():
                connection.execute(
                    """
                    INSERT INTO settings(key, value, updated_at) VALUES (?, ?, ?)
                    ON CONFLICT(key) DO UPDATE SET value = excluded.value,
                        updated_at = excluded.updated_at
                    """,
                    (key, json.dumps(value), now),
                )
        return self.get_settings()

    def list_positions(self) -> list[dict[str, Any]]:
        with self.connect() as connection:
            rows = connection.execute(
                "SELECT * FROM positions ORDER BY created_at"
            ).fetchall()
        return [dict(row) for row in rows]

    def get_position(self, code: str) -> dict[str, Any] | None:
        with self.connect() as connection:
            row = connection.execute(
                "SELECT * FROM positions WHERE code = ?", (code,)
            ).fetchone()
        return dict(row) if row else None

    def create_position(self, values: Mapping[str, Any]) -> dict[str, Any]:
        now = utc_now()
        with self.transaction() as connection:
            connection.execute(
                """
                INSERT INTO positions(
                    code, name, quantity, avg_price, stop_loss, tier, thesis,
                    market, currency, fx_rate, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    values["code"],
                    values["name"],
                    values["quantity"],
                    values["avg_price"],
                    values["stop_loss"],
                    values.get("tier", 1),
                    values.get("thesis", ""),
                    values.get("market", "A"),
                    values.get("currency", "CNY"),
                    values.get("fx_rate", 1.0),
                    now,
                    now,
                ),
            )
        return self.get_position(str(values["code"])) or {}

    def update_position(self, code: str, values: Mapping[str, Any]) -> dict[str, Any] | None:
        allowed = {
            "name", "quantity", "avg_price", "stop_loss", "tier", "thesis",
            "market", "currency", "fx_rate",
        }
        updates = {key: value for key, value in values.items() if key in allowed}
        if not updates:
            return self.get_position(code)
        clauses = [f"{key} = ?" for key in updates]
        params = list(updates.values())
        clauses.append("updated_at = ?")
        params.extend([utc_now(), code])
        with self.transaction() as connection:
            cursor = connection.execute(
                f"UPDATE positions SET {', '.join(clauses)} WHERE code = ?", params
            )
            if cursor.rowcount == 0:
                return None
        return self.get_position(code)

    def delete_position(self, code: str) -> bool:
        with self.transaction() as connection:
            cursor = connection.execute("DELETE FROM positions WHERE code = ?", (code,))
            return cursor.rowcount > 0

    def list_trades(self, limit: int = 200) -> list[dict[str, Any]]:
        with self.connect() as connection:
            rows = connection.execute(
                "SELECT * FROM trades ORDER BY traded_at DESC, id DESC LIMIT ?", (limit,)
            ).fetchall()
        return [self._normalize_trade(dict(row)) for row in rows]

    def portfolio_snapshot(self) -> dict[str, float]:
        settings = self.get_settings()
        total_capital = float(settings.get("total_capital", 100000.0))
        with self.connect() as connection:
            invested = float(
                connection.execute(
                    "SELECT COALESCE(SUM(quantity * avg_price * fx_rate), 0) FROM positions"
                ).fetchone()[0]
            )
            realized = float(
                connection.execute(
                    "SELECT COALESCE(SUM(realized_pnl), 0) FROM trades WHERE side = 'sell'"
                ).fetchone()[0]
            )
        return {
            "total_capital": total_capital,
            "invested_cost": round(invested, 2),
            "realized_pnl": round(realized, 2),
            "available_funds": round(total_capital + realized - invested, 2),
        }

    def execute_trade(self, values: Mapping[str, Any]) -> dict[str, Any]:
        """Validate and atomically persist a buy or sell and its position."""
        code = str(values["code"])
        side = str(values["side"]).lower()
        quantity = int(values["quantity"])
        price = float(values["price"])
        fx_rate = float(values.get("fx_rate", 1.0))
        amount = round(quantity * price * fx_rate, 2)
        now = utc_now()
        with self.transaction() as connection:
            settings_rows = connection.execute(
                "SELECT key, value FROM settings"
            ).fetchall()
            settings = {row["key"]: json.loads(row["value"]) for row in settings_rows}
            total_capital = float(settings.get("total_capital", 100000.0))
            max_ratio = float(settings.get("max_position_ratio", 0.30))
            max_invested_ratio = float(settings.get("max_invested_ratio", 0.60))
            position_row = connection.execute(
                "SELECT * FROM positions WHERE code = ?", (code,)
            ).fetchone()
            position = dict(position_row) if position_row else None
            realized_pnl: float | None = None

            if side == "buy":
                self._validate_buy(
                    connection,
                    values,
                    position,
                    amount,
                    total_capital,
                    max_ratio,
                    max_invested_ratio,
                )
                old_quantity = int(position["quantity"]) if position else 0
                old_cost = old_quantity * float(position["avg_price"]) if position else 0.0
                new_quantity = old_quantity + quantity
                avg_price = (old_cost + quantity * price) / new_quantity
                stop_loss = float(values["stop_loss"])
                name = str(values.get("name") or (position and position["name"]) or code)
                thesis = str(values.get("logic") or "")
                connection.execute(
                    """
                    INSERT INTO positions(
                        code, name, quantity, avg_price, stop_loss, tier, thesis,
                        market, currency, fx_rate, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(code) DO UPDATE SET
                        name = excluded.name,
                        quantity = excluded.quantity,
                        avg_price = excluded.avg_price,
                        stop_loss = excluded.stop_loss,
                        tier = excluded.tier,
                        thesis = excluded.thesis,
                        market = excluded.market,
                        currency = excluded.currency,
                        fx_rate = excluded.fx_rate,
                        updated_at = excluded.updated_at
                    """,
                    (
                        code,
                        name,
                        new_quantity,
                        avg_price,
                        stop_loss,
                        int(values.get("tier") or (position and position.get("tier")) or 1),
                        thesis,
                        values.get("market", position.get("market") if position else "A"),
                        values.get("currency", position.get("currency") if position else "CNY"),
                        fx_rate,
                        position["created_at"] if position else now,
                        now,
                    ),
                )
            elif side == "sell":
                if not position:
                    raise ValueError("cannot sell a stock without an open position")
                if quantity > int(position["quantity"]):
                    raise ValueError("sell quantity exceeds the open position")
                realized_pnl = round(
                    (price - float(position["avg_price"])) * quantity * fx_rate, 2
                )
                remaining = int(position["quantity"]) - quantity
                if remaining:
                    connection.execute(
                        "UPDATE positions SET quantity = ?, updated_at = ? WHERE code = ?",
                        (remaining, now, code),
                    )
                else:
                    connection.execute("DELETE FROM positions WHERE code = ?", (code,))
            else:
                raise ValueError("side must be buy or sell")

            cursor = connection.execute(
                """
                INSERT INTO trades(
                    code, name, side, quantity, price, amount, logic,
                    funds_confirmed, space_confirmed, stop_loss, realized_pnl,
                    violated, note, market, currency, fx_rate, traded_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    code,
                    str(values.get("name") or (position and position["name"]) or code),
                    side,
                    quantity,
                    price,
                    amount,
                    str(values.get("logic") or ""),
                    int(bool(values.get("funds_confirmed"))),
                    int(bool(values.get("space_confirmed"))),
                    values.get("stop_loss"),
                    realized_pnl,
                    int(bool(values.get("violated"))),
                    str(values.get("note") or ""),
                    values.get("market", position.get("market") if position else "A"),
                    values.get("currency", position.get("currency") if position else "CNY"),
                    fx_rate,
                    values.get("traded_at") or now,
                ),
            )
            row = connection.execute(
                "SELECT * FROM trades WHERE id = ?", (cursor.lastrowid,)
            ).fetchone()
        return self._normalize_trade(dict(row))

    def _validate_buy(
        self,
        connection: sqlite3.Connection,
        values: Mapping[str, Any],
        position: Mapping[str, Any] | None,
        amount: float,
        total_capital: float,
        max_ratio: float,
        max_invested_ratio: float,
    ) -> None:
        if not str(values.get("logic") or "").strip():
            raise ValueError("buy requires a written investment logic")
        if not bool(values.get("funds_confirmed")):
            raise ValueError("buy requires funds confirmation")
        if not bool(values.get("space_confirmed")):
            raise ValueError("buy requires upside-space confirmation")
        stop_loss = values.get("stop_loss")
        if stop_loss is None or float(stop_loss) <= 0:
            raise ValueError("buy requires a positive stop_loss")
        if float(stop_loss) >= float(values["price"]):
            raise ValueError("stop_loss must be below the buy price")

        invested = float(
            connection.execute(
                "SELECT COALESCE(SUM(quantity * avg_price * fx_rate), 0) FROM positions"
            ).fetchone()[0]
        )
        realized = float(
            connection.execute(
                "SELECT COALESCE(SUM(realized_pnl), 0) FROM trades WHERE side = 'sell'"
            ).fetchone()[0]
        )
        available = total_capital + realized - invested
        if amount > available + 1e-6:
            raise ValueError("insufficient available funds")
        if invested + amount > total_capital * max_invested_ratio + 1e-6:
            raise ValueError(
                f"total position would exceed the {max_invested_ratio:.0%} invested limit"
            )
        existing_cost = (
            int(position["quantity"])
            * float(position["avg_price"])
            * float(position.get("fx_rate", 1.0))
            if position
            else 0.0
        )
        if existing_cost + amount > total_capital * max_ratio + 1e-6:
            raise ValueError(
                f"position would exceed the {max_ratio:.0%} single-stock limit"
            )

    def list_journals(self, limit: int = 200) -> list[dict[str, Any]]:
        with self.connect() as connection:
            rows = connection.execute(
                "SELECT * FROM journal ORDER BY created_at DESC, id DESC LIMIT ?", (limit,)
            ).fetchall()
        return [self._normalize_journal(dict(row)) for row in rows]

    def get_journal(self, journal_id: int) -> dict[str, Any] | None:
        with self.connect() as connection:
            row = connection.execute(
                "SELECT * FROM journal WHERE id = ?", (journal_id,)
            ).fetchone()
        return self._normalize_journal(dict(row)) if row else None

    def create_journal(self, values: Mapping[str, Any]) -> dict[str, Any]:
        now = utc_now()
        with self.transaction() as connection:
            cursor = connection.execute(
                """
                INSERT INTO journal(
                    title, content, mood, tags, trade_id, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    values["title"],
                    values["content"],
                    values.get("mood", ""),
                    json.dumps(values.get("tags", []), ensure_ascii=False),
                    values.get("trade_id"),
                    values.get("created_at") or now,
                    now,
                ),
            )
            journal_id = int(cursor.lastrowid)
        return self.get_journal(journal_id) or {}

    def update_journal(
        self, journal_id: int, values: Mapping[str, Any]
    ) -> dict[str, Any] | None:
        allowed = {"title", "content", "mood", "tags", "trade_id"}
        updates = {key: value for key, value in values.items() if key in allowed}
        if "tags" in updates:
            updates["tags"] = json.dumps(updates["tags"], ensure_ascii=False)
        if not updates:
            return self.get_journal(journal_id)
        clauses = [f"{key} = ?" for key in updates]
        params = list(updates.values())
        clauses.append("updated_at = ?")
        params.extend([utc_now(), journal_id])
        with self.transaction() as connection:
            cursor = connection.execute(
                f"UPDATE journal SET {', '.join(clauses)} WHERE id = ?", params
            )
            if cursor.rowcount == 0:
                return None
        return self.get_journal(journal_id)

    def delete_journal(self, journal_id: int) -> bool:
        with self.transaction() as connection:
            cursor = connection.execute("DELETE FROM journal WHERE id = ?", (journal_id,))
            return cursor.rowcount > 0

    def save_close_screen(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        as_of_date = str(payload["as_of_date"])
        for_date = str(payload["for_date"])
        now = utc_now()
        body = json.dumps(payload, ensure_ascii=False)
        with self.transaction() as connection:
            connection.execute(
                """
                INSERT INTO close_screens(as_of_date, for_date, payload, created_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(as_of_date) DO UPDATE SET
                    for_date = excluded.for_date,
                    payload = excluded.payload,
                    created_at = excluded.created_at
                """,
                (as_of_date, for_date, body, now),
            )
        return self.get_close_screen(as_of_date=as_of_date) or dict(payload)

    def get_close_screen(
        self,
        *,
        as_of_date: str | None = None,
        for_date: str | None = None,
    ) -> dict[str, Any] | None:
        with self.connect() as connection:
            if as_of_date:
                row = connection.execute(
                    "SELECT payload FROM close_screens WHERE as_of_date = ?",
                    (as_of_date,),
                ).fetchone()
            elif for_date:
                row = connection.execute(
                    """
                    SELECT payload FROM close_screens
                    WHERE for_date = ?
                    ORDER BY as_of_date DESC
                    LIMIT 1
                    """,
                    (for_date,),
                ).fetchone()
            else:
                row = connection.execute(
                    """
                    SELECT payload FROM close_screens
                    ORDER BY as_of_date DESC
                    LIMIT 1
                    """
                ).fetchone()
        if row is None:
            return None
        try:
            data = json.loads(row["payload"])
        except (TypeError, json.JSONDecodeError):
            return None
        return data if isinstance(data, dict) else None

    def save_snapshot(self, key: str, payload: Mapping[str, Any]) -> None:
        now = utc_now()
        with self.transaction() as connection:
            connection.execute(
                """
                INSERT INTO snapshots(key, payload, updated_at)
                VALUES (?, ?, ?)
                ON CONFLICT(key) DO UPDATE SET
                    payload = excluded.payload,
                    updated_at = excluded.updated_at
                """,
                (key, json.dumps(payload, ensure_ascii=False), now),
            )

    def get_snapshot(self, key: str) -> dict[str, Any] | None:
        with self.connect() as connection:
            row = connection.execute(
                "SELECT payload FROM snapshots WHERE key = ?", (key,)
            ).fetchone()
        if row is None:
            return None
        try:
            data = json.loads(row["payload"])
        except (TypeError, json.JSONDecodeError):
            return None
        return data if isinstance(data, dict) else None

    @staticmethod
    def _normalize_trade(row: dict[str, Any]) -> dict[str, Any]:
        row["funds_confirmed"] = bool(row["funds_confirmed"])
        row["space_confirmed"] = bool(row["space_confirmed"])
        row["violated"] = bool(row["violated"])
        return row

    @staticmethod
    def _normalize_journal(row: dict[str, Any]) -> dict[str, Any]:
        try:
            row["tags"] = json.loads(row["tags"])
        except (TypeError, json.JSONDecodeError):
            row["tags"] = []
        return row
