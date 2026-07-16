"""SQLite persistence for users, settings, positions, trades, journals, and credits."""

from __future__ import annotations

import json
import os
import sqlite3
import threading
import uuid
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterator, Mapping


LOCAL_OPENID = "local-web"
LOCAL_USER_ID = 1


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _parse_utc(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


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
                CREATE TABLE IF NOT EXISTS users (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    openid TEXT NOT NULL UNIQUE,
                    unionid TEXT,
                    session_key TEXT NOT NULL DEFAULT '',
                    mock INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS sessions (
                    token_hash TEXT PRIMARY KEY,
                    user_id INTEGER NOT NULL,
                    expires_at TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
                );

                CREATE TABLE IF NOT EXISTS credit_accounts (
                    user_id INTEGER PRIMARY KEY,
                    balance INTEGER NOT NULL DEFAULT 0 CHECK (balance >= 0),
                    updated_at TEXT NOT NULL,
                    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
                );

                CREATE TABLE IF NOT EXISTS credit_ledger (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL,
                    delta INTEGER NOT NULL,
                    balance_after INTEGER NOT NULL,
                    reason TEXT NOT NULL,
                    ref_type TEXT NOT NULL DEFAULT '',
                    ref_id TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL,
                    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
                    UNIQUE(user_id, ref_type, ref_id)
                );

                CREATE TABLE IF NOT EXISTS orders (
                    id TEXT PRIMARY KEY,
                    user_id INTEGER NOT NULL,
                    sku TEXT NOT NULL,
                    title TEXT NOT NULL,
                    credits INTEGER NOT NULL CHECK (credits > 0),
                    amount_fen INTEGER NOT NULL CHECK (amount_fen > 0),
                    status TEXT NOT NULL CHECK (status IN ('pending', 'paid', 'cancelled', 'failed')),
                    provider TEXT NOT NULL,
                    provider_ref TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    paid_at TEXT,
                    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
                );

                CREATE TABLE IF NOT EXISTS settings (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS user_settings (
                    user_id INTEGER NOT NULL,
                    key TEXT NOT NULL,
                    value TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY (user_id, key),
                    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
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

                CREATE INDEX IF NOT EXISTS idx_trades_code_time ON trades(code, traded_at);
                CREATE INDEX IF NOT EXISTS idx_journal_created ON journal(created_at);
                CREATE INDEX IF NOT EXISTS idx_sessions_user ON sessions(user_id);
                CREATE INDEX IF NOT EXISTS idx_ledger_user ON credit_ledger(user_id, created_at);
                CREATE INDEX IF NOT EXISTS idx_orders_user ON orders(user_id, created_at);
                """
            )
            self._ensure_local_user(connection)
            self._migrate_user_id_columns(connection)
            # Legacy columns must exist before positions PK migration SELECTs them.
            self._ensure_legacy_columns(connection)
            self._migrate_positions_pk(connection)
            self._migrate_settings_to_user(connection)
            now = utc_now()
            defaults = {
                "total_capital": 100000.0,
                "max_position_ratio": 0.30,
                "max_invested_ratio": 0.60,
            }
            for key, value in defaults.items():
                connection.execute(
                    """
                    INSERT OR IGNORE INTO user_settings(user_id, key, value, updated_at)
                    VALUES (?, ?, ?, ?)
                    """,
                    (LOCAL_USER_ID, key, json.dumps(value), now),
                )
                connection.execute(
                    "INSERT OR IGNORE INTO settings(key, value, updated_at) VALUES (?, ?, ?)",
                    (key, json.dumps(value), now),
                )
            connection.execute(
                """
                INSERT OR IGNORE INTO credit_accounts(user_id, balance, updated_at)
                VALUES (?, 0, ?)
                """,
                (LOCAL_USER_ID, now),
            )

    def _ensure_local_user(self, connection: sqlite3.Connection) -> None:
        now = utc_now()
        row = connection.execute(
            "SELECT id FROM users WHERE openid = ?", (LOCAL_OPENID,)
        ).fetchone()
        if row:
            return
        # Keep id=1 stable for migrated legacy rows.
        connection.execute(
            """
            INSERT INTO users(id, openid, unionid, session_key, mock, created_at, updated_at)
            VALUES (?, ?, NULL, '', 1, ?, ?)
            """,
            (LOCAL_USER_ID, LOCAL_OPENID, now, now),
        )

    def _migrate_user_id_columns(self, connection: sqlite3.Connection) -> None:
        for table in ("trades", "journal"):
            columns = {
                row["name"]
                for row in connection.execute(f"PRAGMA table_info({table})").fetchall()
            }
            if "user_id" not in columns:
                connection.execute(
                    f"ALTER TABLE {table} ADD COLUMN user_id INTEGER NOT NULL DEFAULT {LOCAL_USER_ID}"
                )

    def _migrate_positions_pk(self, connection: sqlite3.Connection) -> None:
        columns = {
            row["name"]
            for row in connection.execute("PRAGMA table_info(positions)").fetchall()
        }
        if not columns or "user_id" in columns:
            return
        # Use execute (not executescript): executescript implicitly COMMITs first
        # and would break the outer BEGIN IMMEDIATE from self.transaction().
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS positions_v2 (
                user_id INTEGER NOT NULL,
                code TEXT NOT NULL,
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
                updated_at TEXT NOT NULL,
                PRIMARY KEY (user_id, code),
                FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
            )
            """
        )
        tier = "tier" if "tier" in columns else "1"
        thesis = "thesis" if "thesis" in columns else "''"
        market = "market" if "market" in columns else "'A'"
        currency = "currency" if "currency" in columns else "'CNY'"
        fx_rate = "fx_rate" if "fx_rate" in columns else "1"
        connection.execute(
            f"""
            INSERT INTO positions_v2(
                user_id, code, name, quantity, avg_price, stop_loss, tier, thesis,
                market, currency, fx_rate, created_at, updated_at
            )
            SELECT {LOCAL_USER_ID}, code, name, quantity, avg_price, stop_loss,
                   {tier}, {thesis}, {market}, {currency}, {fx_rate},
                   created_at, updated_at
            FROM positions
            """
        )
        connection.execute("DROP TABLE positions")
        connection.execute("ALTER TABLE positions_v2 RENAME TO positions")

    def _migrate_settings_to_user(self, connection: sqlite3.Connection) -> None:
        legacy = connection.execute("SELECT key, value, updated_at FROM settings").fetchall()
        for row in legacy:
            connection.execute(
                """
                INSERT OR IGNORE INTO user_settings(user_id, key, value, updated_at)
                VALUES (?, ?, ?, ?)
                """,
                (LOCAL_USER_ID, row["key"], row["value"], row["updated_at"]),
            )

    def _ensure_legacy_columns(self, connection: sqlite3.Connection) -> None:
        position_columns = {
            row["name"]
            for row in connection.execute("PRAGMA table_info(positions)").fetchall()
        }
        for name, definition in (
            ("tier", "INTEGER NOT NULL DEFAULT 1"),
            ("market", "TEXT NOT NULL DEFAULT 'A'"),
            ("currency", "TEXT NOT NULL DEFAULT 'CNY'"),
            ("fx_rate", "REAL NOT NULL DEFAULT 1"),
        ):
            if name not in position_columns:
                connection.execute(f"ALTER TABLE positions ADD COLUMN {name} {definition}")
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
                connection.execute(f"ALTER TABLE trades ADD COLUMN {name} {definition}")

    def healthcheck(self) -> bool:
        try:
            with self.connect() as connection:
                return connection.execute("SELECT 1").fetchone()[0] == 1
        except sqlite3.Error:
            return False

    # --- users / sessions -------------------------------------------------

    def get_or_create_local_user(self) -> dict[str, Any]:
        return self.upsert_user(LOCAL_OPENID, session_key="", mock=True)

    def upsert_user(
        self, openid: str, *, session_key: str = "", mock: bool = False
    ) -> dict[str, Any]:
        now = utc_now()
        with self.transaction() as connection:
            row = connection.execute(
                "SELECT * FROM users WHERE openid = ?", (openid,)
            ).fetchone()
            if row:
                connection.execute(
                    """
                    UPDATE users SET session_key = ?, mock = ?, updated_at = ?
                    WHERE id = ?
                    """,
                    (session_key, int(mock), now, row["id"]),
                )
                user_id = int(row["id"])
            else:
                cursor = connection.execute(
                    """
                    INSERT INTO users(openid, unionid, session_key, mock, created_at, updated_at)
                    VALUES (?, NULL, ?, ?, ?, ?)
                    """,
                    (openid, session_key, int(mock), now, now),
                )
                user_id = int(cursor.lastrowid)
            connection.execute(
                """
                INSERT OR IGNORE INTO credit_accounts(user_id, balance, updated_at)
                VALUES (?, 0, ?)
                """,
                (user_id, now),
            )
            for key, value in (
                ("total_capital", 100000.0),
                ("max_position_ratio", 0.30),
                ("max_invested_ratio", 0.60),
            ):
                connection.execute(
                    """
                    INSERT OR IGNORE INTO user_settings(user_id, key, value, updated_at)
                    VALUES (?, ?, ?, ?)
                    """,
                    (user_id, key, json.dumps(value), now),
                )
            user = connection.execute(
                "SELECT * FROM users WHERE id = ?", (user_id,)
            ).fetchone()
        return dict(user)

    def create_session(self, user_id: int, *, token_hash: str, ttl_seconds: int) -> None:
        now = datetime.now(timezone.utc)
        expires = (now + timedelta(seconds=ttl_seconds)).isoformat(timespec="seconds")
        with self.transaction() as connection:
            connection.execute(
                """
                INSERT INTO sessions(token_hash, user_id, expires_at, created_at)
                VALUES (?, ?, ?, ?)
                """,
                (token_hash, user_id, expires, now.isoformat(timespec="seconds")),
            )

    def get_user_by_token(self, token_hash: str) -> dict[str, Any] | None:
        with self.connect() as connection:
            row = connection.execute(
                """
                SELECT u.* FROM sessions s
                JOIN users u ON u.id = s.user_id
                WHERE s.token_hash = ?
                """,
                (token_hash,),
            ).fetchone()
            if not row:
                return None
            expires = connection.execute(
                "SELECT expires_at FROM sessions WHERE token_hash = ?",
                (token_hash,),
            ).fetchone()
        if expires and _parse_utc(expires["expires_at"]) < datetime.now(timezone.utc):
            with self.transaction() as connection:
                connection.execute(
                    "DELETE FROM sessions WHERE token_hash = ?", (token_hash,)
                )
            return None
        data = dict(row)
        data["mock"] = bool(data.get("mock"))
        return data

    def delete_session(self, token_hash: str) -> None:
        with self.transaction() as connection:
            connection.execute("DELETE FROM sessions WHERE token_hash = ?", (token_hash,))

    # --- settings ---------------------------------------------------------

    def get_settings(self, user_id: int = LOCAL_USER_ID) -> dict[str, Any]:
        with self.connect() as connection:
            rows = connection.execute(
                "SELECT key, value FROM user_settings WHERE user_id = ?",
                (user_id,),
            ).fetchall()
        if not rows:
            with self.connect() as connection:
                rows = connection.execute("SELECT key, value FROM settings").fetchall()
        return {row["key"]: json.loads(row["value"]) for row in rows}

    def set_settings(
        self, values: Mapping[str, Any], user_id: int = LOCAL_USER_ID
    ) -> dict[str, Any]:
        now = utc_now()
        with self.transaction() as connection:
            for key, value in values.items():
                connection.execute(
                    """
                    INSERT INTO user_settings(user_id, key, value, updated_at)
                    VALUES (?, ?, ?, ?)
                    ON CONFLICT(user_id, key) DO UPDATE SET
                        value = excluded.value,
                        updated_at = excluded.updated_at
                    """,
                    (user_id, key, json.dumps(value), now),
                )
                if user_id == LOCAL_USER_ID:
                    connection.execute(
                        """
                        INSERT INTO settings(key, value, updated_at) VALUES (?, ?, ?)
                        ON CONFLICT(key) DO UPDATE SET value = excluded.value,
                            updated_at = excluded.updated_at
                        """,
                        (key, json.dumps(value), now),
                    )
        return self.get_settings(user_id)

    # --- positions / portfolio --------------------------------------------

    def list_positions(self, user_id: int = LOCAL_USER_ID) -> list[dict[str, Any]]:
        with self.connect() as connection:
            rows = connection.execute(
                "SELECT * FROM positions WHERE user_id = ? ORDER BY created_at",
                (user_id,),
            ).fetchall()
        return [dict(row) for row in rows]

    def get_position(
        self, code: str, user_id: int = LOCAL_USER_ID
    ) -> dict[str, Any] | None:
        with self.connect() as connection:
            row = connection.execute(
                "SELECT * FROM positions WHERE user_id = ? AND code = ?",
                (user_id, code),
            ).fetchone()
        return dict(row) if row else None

    def create_position(
        self, values: Mapping[str, Any], user_id: int = LOCAL_USER_ID
    ) -> dict[str, Any]:
        now = utc_now()
        with self.transaction() as connection:
            connection.execute(
                """
                INSERT INTO positions(
                    user_id, code, name, quantity, avg_price, stop_loss, tier, thesis,
                    market, currency, fx_rate, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    user_id,
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
        return self.get_position(str(values["code"]), user_id) or {}

    def update_position(
        self, code: str, values: Mapping[str, Any], user_id: int = LOCAL_USER_ID
    ) -> dict[str, Any] | None:
        allowed = {
            "name", "quantity", "avg_price", "stop_loss", "tier", "thesis",
            "market", "currency", "fx_rate",
        }
        updates = {key: value for key, value in values.items() if key in allowed}
        if not updates:
            return self.get_position(code, user_id)
        clauses = [f"{key} = ?" for key in updates]
        params = list(updates.values())
        clauses.append("updated_at = ?")
        params.extend([utc_now(), user_id, code])
        with self.transaction() as connection:
            cursor = connection.execute(
                f"UPDATE positions SET {', '.join(clauses)} WHERE user_id = ? AND code = ?",
                params,
            )
            if cursor.rowcount == 0:
                return None
        return self.get_position(code, user_id)

    def delete_position(self, code: str, user_id: int = LOCAL_USER_ID) -> bool:
        with self.transaction() as connection:
            cursor = connection.execute(
                "DELETE FROM positions WHERE user_id = ? AND code = ?",
                (user_id, code),
            )
            return cursor.rowcount > 0

    def list_trades(
        self, limit: int = 200, user_id: int = LOCAL_USER_ID
    ) -> list[dict[str, Any]]:
        with self.connect() as connection:
            rows = connection.execute(
                """
                SELECT * FROM trades WHERE user_id = ?
                ORDER BY traded_at DESC, id DESC LIMIT ?
                """,
                (user_id, limit),
            ).fetchall()
        return [self._normalize_trade(dict(row)) for row in rows]

    def portfolio_snapshot(self, user_id: int = LOCAL_USER_ID) -> dict[str, float]:
        settings = self.get_settings(user_id)
        total_capital = float(settings.get("total_capital", 100000.0))
        with self.connect() as connection:
            invested = float(
                connection.execute(
                    """
                    SELECT COALESCE(SUM(quantity * avg_price * fx_rate), 0)
                    FROM positions WHERE user_id = ?
                    """,
                    (user_id,),
                ).fetchone()[0]
            )
            realized = float(
                connection.execute(
                    """
                    SELECT COALESCE(SUM(realized_pnl), 0)
                    FROM trades WHERE user_id = ? AND side = 'sell'
                    """,
                    (user_id,),
                ).fetchone()[0]
            )
        return {
            "total_capital": total_capital,
            "invested_cost": round(invested, 2),
            "realized_pnl": round(realized, 2),
            "available_funds": round(total_capital + realized - invested, 2),
        }

    def execute_trade(
        self, values: Mapping[str, Any], user_id: int = LOCAL_USER_ID
    ) -> dict[str, Any]:
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
                "SELECT key, value FROM user_settings WHERE user_id = ?",
                (user_id,),
            ).fetchall()
            settings = {row["key"]: json.loads(row["value"]) for row in settings_rows}
            total_capital = float(settings.get("total_capital", 100000.0))
            max_ratio = float(settings.get("max_position_ratio", 0.30))
            max_invested_ratio = float(settings.get("max_invested_ratio", 0.60))
            position_row = connection.execute(
                "SELECT * FROM positions WHERE user_id = ? AND code = ?",
                (user_id, code),
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
                    user_id,
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
                        user_id, code, name, quantity, avg_price, stop_loss, tier, thesis,
                        market, currency, fx_rate, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(user_id, code) DO UPDATE SET
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
                        user_id,
                        code,
                        name,
                        new_quantity,
                        avg_price,
                        stop_loss,
                        int(values.get("tier") or (position and position.get("tier")) or 1),
                        thesis,
                        values.get("market", position.get("market") if position else "A"),
                        values.get(
                            "currency", position.get("currency") if position else "CNY"
                        ),
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
                        """
                        UPDATE positions SET quantity = ?, updated_at = ?
                        WHERE user_id = ? AND code = ?
                        """,
                        (remaining, now, user_id, code),
                    )
                else:
                    connection.execute(
                        "DELETE FROM positions WHERE user_id = ? AND code = ?",
                        (user_id, code),
                    )
            else:
                raise ValueError("side must be buy or sell")

            cursor = connection.execute(
                """
                INSERT INTO trades(
                    user_id, code, name, side, quantity, price, amount, logic,
                    funds_confirmed, space_confirmed, stop_loss, realized_pnl,
                    violated, note, market, currency, fx_rate, traded_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    user_id,
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
                    0,
                    str(values.get("note") or ""),
                    values.get("market", position.get("market") if position else "A"),
                    values.get(
                        "currency", position.get("currency") if position else "CNY"
                    ),
                    fx_rate,
                    now,
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
        user_id: int,
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
                """
                SELECT COALESCE(SUM(quantity * avg_price * fx_rate), 0)
                FROM positions WHERE user_id = ?
                """,
                (user_id,),
            ).fetchone()[0]
        )
        realized = float(
            connection.execute(
                """
                SELECT COALESCE(SUM(realized_pnl), 0)
                FROM trades WHERE user_id = ? AND side = 'sell'
                """,
                (user_id,),
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

    # --- journal ----------------------------------------------------------

    def list_journals(
        self, limit: int = 200, user_id: int = LOCAL_USER_ID
    ) -> list[dict[str, Any]]:
        with self.connect() as connection:
            rows = connection.execute(
                """
                SELECT * FROM journal WHERE user_id = ?
                ORDER BY created_at DESC, id DESC LIMIT ?
                """,
                (user_id, limit),
            ).fetchall()
        return [self._normalize_journal(dict(row)) for row in rows]

    def get_journal(
        self, journal_id: int, user_id: int = LOCAL_USER_ID
    ) -> dict[str, Any] | None:
        with self.connect() as connection:
            row = connection.execute(
                "SELECT * FROM journal WHERE id = ? AND user_id = ?",
                (journal_id, user_id),
            ).fetchone()
        return self._normalize_journal(dict(row)) if row else None

    def create_journal(
        self, values: Mapping[str, Any], user_id: int = LOCAL_USER_ID
    ) -> dict[str, Any]:
        now = utc_now()
        with self.transaction() as connection:
            cursor = connection.execute(
                """
                INSERT INTO journal(
                    user_id, title, content, mood, tags, trade_id, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    user_id,
                    values["title"],
                    values["content"],
                    values.get("mood", ""),
                    json.dumps(values.get("tags", []), ensure_ascii=False),
                    values.get("trade_id"),
                    now,
                    now,
                ),
            )
            journal_id = int(cursor.lastrowid)
        return self.get_journal(journal_id, user_id) or {}

    def update_journal(
        self,
        journal_id: int,
        values: Mapping[str, Any],
        user_id: int = LOCAL_USER_ID,
    ) -> dict[str, Any] | None:
        allowed = {"title", "content", "mood", "tags", "trade_id"}
        updates = {key: value for key, value in values.items() if key in allowed}
        if "tags" in updates:
            updates["tags"] = json.dumps(updates["tags"], ensure_ascii=False)
        if not updates:
            return self.get_journal(journal_id, user_id)
        clauses = [f"{key} = ?" for key in updates]
        params = list(updates.values())
        clauses.append("updated_at = ?")
        params.extend([utc_now(), journal_id, user_id])
        with self.transaction() as connection:
            cursor = connection.execute(
                f"UPDATE journal SET {', '.join(clauses)} WHERE id = ? AND user_id = ?",
                params,
            )
            if cursor.rowcount == 0:
                return None
        return self.get_journal(journal_id, user_id)

    def delete_journal(self, journal_id: int, user_id: int = LOCAL_USER_ID) -> bool:
        with self.transaction() as connection:
            cursor = connection.execute(
                "DELETE FROM journal WHERE id = ? AND user_id = ?",
                (journal_id, user_id),
            )
            return cursor.rowcount > 0

    # --- credits / orders -------------------------------------------------

    def get_credit_balance(self, user_id: int) -> dict[str, Any]:
        with self.connect() as connection:
            row = connection.execute(
                "SELECT balance, updated_at FROM credit_accounts WHERE user_id = ?",
                (user_id,),
            ).fetchone()
        if not row:
            return {"balance": 0, "updated_at": utc_now()}
        return {"balance": int(row["balance"]), "updated_at": row["updated_at"]}

    def list_credit_ledger(
        self, user_id: int, limit: int = 50
    ) -> list[dict[str, Any]]:
        with self.connect() as connection:
            rows = connection.execute(
                """
                SELECT * FROM credit_ledger WHERE user_id = ?
                ORDER BY id DESC LIMIT ?
                """,
                (user_id, limit),
            ).fetchall()
        return [dict(row) for row in rows]

    def reserve_credits(
        self,
        user_id: int,
        amount: int,
        *,
        reason: str,
        ref_type: str,
        ref_id: str,
    ) -> dict[str, Any]:
        """Atomically debit credits with idempotent ref key. Raises ValueError if short.

        A prior debit for the same ref is only reused when it has not been reversed.
        If a matching positive ledger row already restored the balance, the old
        attempt is archived and a fresh debit is taken so retries are not free.
        """
        if amount <= 0:
            raise ValueError("debit amount must be positive")
        now = utc_now()
        with self.transaction() as connection:
            existing = connection.execute(
                """
                SELECT * FROM credit_ledger
                WHERE user_id = ? AND ref_type = ? AND ref_id = ?
                """,
                (user_id, ref_type, ref_id),
            ).fetchone()
            if existing:
                reversal = connection.execute(
                    """
                    SELECT id FROM credit_ledger
                    WHERE user_id = ? AND ref_id = ? AND ref_type != ?
                      AND delta = ?
                    """,
                    (user_id, ref_id, ref_type, -int(existing["delta"])),
                ).fetchone()
                if not reversal:
                    reused = dict(existing)
                    reused["created"] = False
                    return reused
                # Prior attempt was refunded — free the unique key and charge again.
                archive_ref = f"{ref_id}#closed-{existing['id']}"
                connection.execute(
                    """
                    UPDATE credit_ledger SET ref_id = ?
                    WHERE user_id = ? AND ref_id = ?
                    """,
                    (archive_ref, user_id, ref_id),
                )
            account = connection.execute(
                "SELECT balance FROM credit_accounts WHERE user_id = ?",
                (user_id,),
            ).fetchone()
            balance = int(account["balance"]) if account else 0
            if balance < amount:
                raise ValueError("insufficient credits")
            new_balance = balance - amount
            connection.execute(
                """
                INSERT INTO credit_accounts(user_id, balance, updated_at)
                VALUES (?, ?, ?)
                ON CONFLICT(user_id) DO UPDATE SET
                    balance = excluded.balance,
                    updated_at = excluded.updated_at
                """,
                (user_id, new_balance, now),
            )
            cursor = connection.execute(
                """
                INSERT INTO credit_ledger(
                    user_id, delta, balance_after, reason, ref_type, ref_id, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (user_id, -amount, new_balance, reason, ref_type, ref_id, now),
            )
            row = connection.execute(
                "SELECT * FROM credit_ledger WHERE id = ?", (cursor.lastrowid,)
            ).fetchone()
        created = dict(row)
        created["created"] = True
        return created

    def refund_credits(
        self,
        user_id: int,
        amount: int,
        *,
        reason: str,
        ref_type: str,
        ref_id: str,
    ) -> dict[str, Any]:
        now = utc_now()
        with self.transaction() as connection:
            existing = connection.execute(
                """
                SELECT * FROM credit_ledger
                WHERE user_id = ? AND ref_type = ? AND ref_id = ?
                """,
                (user_id, ref_type, ref_id),
            ).fetchone()
            if existing:
                return dict(existing)
            account = connection.execute(
                "SELECT balance FROM credit_accounts WHERE user_id = ?",
                (user_id,),
            ).fetchone()
            balance = int(account["balance"]) if account else 0
            new_balance = balance + amount
            connection.execute(
                """
                INSERT INTO credit_accounts(user_id, balance, updated_at)
                VALUES (?, ?, ?)
                ON CONFLICT(user_id) DO UPDATE SET
                    balance = excluded.balance,
                    updated_at = excluded.updated_at
                """,
                (user_id, new_balance, now),
            )
            cursor = connection.execute(
                """
                INSERT INTO credit_ledger(
                    user_id, delta, balance_after, reason, ref_type, ref_id, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (user_id, amount, new_balance, reason, ref_type, ref_id, now),
            )
            row = connection.execute(
                "SELECT * FROM credit_ledger WHERE id = ?", (cursor.lastrowid,)
            ).fetchone()
        return dict(row)

    def create_order(
        self,
        *,
        user_id: int,
        sku: str,
        title: str,
        credits: int,
        amount_fen: int,
        provider: str,
    ) -> dict[str, Any]:
        now = utc_now()
        order_id = uuid.uuid4().hex
        with self.transaction() as connection:
            connection.execute(
                """
                INSERT INTO orders(
                    id, user_id, sku, title, credits, amount_fen, status, provider,
                    provider_ref, created_at, updated_at, paid_at
                ) VALUES (?, ?, ?, ?, ?, ?, 'pending', ?, '', ?, ?, NULL)
                """,
                (
                    order_id,
                    user_id,
                    sku,
                    title,
                    credits,
                    amount_fen,
                    provider,
                    now,
                    now,
                ),
            )
        return self.get_order(order_id) or {}

    def get_order(self, order_id: str) -> dict[str, Any] | None:
        with self.connect() as connection:
            row = connection.execute(
                "SELECT * FROM orders WHERE id = ?", (order_id,)
            ).fetchone()
        return dict(row) if row else None

    def mark_order_paid(
        self, order_id: str, *, provider_ref: str
    ) -> dict[str, Any]:
        now = utc_now()
        with self.transaction() as connection:
            order = connection.execute(
                "SELECT * FROM orders WHERE id = ?", (order_id,)
            ).fetchone()
            if order is None:
                raise ValueError("order not found")
            if order["status"] == "paid":
                return dict(order)
            if order["status"] != "pending":
                raise ValueError(
                    f"order status must be pending to mark paid, got {order['status']}"
                )
            connection.execute(
                """
                UPDATE orders SET status = 'paid', provider_ref = ?, updated_at = ?, paid_at = ?
                WHERE id = ? AND status = 'pending'
                """,
                (provider_ref, now, now, order_id),
            )
            user_id = int(order["user_id"])
            credits = int(order["credits"])
            account = connection.execute(
                "SELECT balance FROM credit_accounts WHERE user_id = ?",
                (user_id,),
            ).fetchone()
            balance = int(account["balance"]) if account else 0
            new_balance = balance + credits
            connection.execute(
                """
                INSERT INTO credit_accounts(user_id, balance, updated_at)
                VALUES (?, ?, ?)
                ON CONFLICT(user_id) DO UPDATE SET
                    balance = excluded.balance,
                    updated_at = excluded.updated_at
                """,
                (user_id, new_balance, now),
            )
            connection.execute(
                """
                INSERT OR IGNORE INTO credit_ledger(
                    user_id, delta, balance_after, reason, ref_type, ref_id, created_at
                ) VALUES (?, ?, ?, ?, 'order', ?, ?)
                """,
                (
                    user_id,
                    credits,
                    new_balance,
                    f"充值 {order['title']}",
                    order_id,
                    now,
                ),
            )
            row = connection.execute(
                "SELECT * FROM orders WHERE id = ?", (order_id,)
            ).fetchone()
        return dict(row)

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
