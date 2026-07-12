import sqlite3
import os
import re
from werkzeug.security import generate_password_hash

DATABASE_URL = os.environ.get("DATABASE_URL", "")
DB_PATH = os.path.join(os.path.dirname(__file__), "orders.db")

DEFAULT_ADMIN_USERNAME = os.environ.get("INITIAL_ADMIN_USERNAME", "admin")
DEFAULT_ADMIN_PASSWORD = os.environ.get("INITIAL_ADMIN_PASSWORD", "changeme123")

USE_POSTGRES = bool(DATABASE_URL)


# ─────────────────────────────────────────────
# PostgreSQL サポート
# ─────────────────────────────────────────────
if USE_POSTGRES:
    import psycopg2
    import psycopg2.extras

    def _to_pg(sql, params=None):
        """SQLite 構文を PostgreSQL 構文に変換する。

        パラメータの型に応じて置換を切り替える。無条件に置換すると
        TO_CHAR(..., 'HH24:MI:SS') のようなリテラル内の「:xx」まで
        壊してしまうため、パラメータ無しのSQLには手を付けない。
        """
        if sql.strip().upper().startswith("PRAGMA"):
            return None, None
        sql = sql.replace("SELECT last_insert_rowid()", "SELECT lastval()")
        if isinstance(params, dict):
            # 名前付きパラメータ :name → %(name)s
            sql = re.sub(r":(\w+)", r"%(\1)s", sql)
        elif params is not None:
            # 位置パラメータ ? → %s
            sql = sql.replace("?", "%s")
        return sql, params

    class _PgResult:
        def __init__(self, rows):
            self._rows = rows or []

        def fetchone(self):
            return self._rows[0] if self._rows else None

        def fetchall(self):
            return self._rows

        def __iter__(self):
            return iter(self._rows)

    class _NullResult:
        def fetchone(self): return None
        def fetchall(self): return []

    class PgConnection:
        def __init__(self):
            url = DATABASE_URL
            if url.startswith("postgres://"):
                url = "postgresql://" + url[len("postgres://"):]
            self._conn = psycopg2.connect(
                url, cursor_factory=psycopg2.extras.DictCursor
            )

        def execute(self, sql, params=None):
            pg_sql, pg_params = _to_pg(sql, params)
            if pg_sql is None:
                return _NullResult()
            cur = self._conn.cursor()
            cur.execute(pg_sql, pg_params)
            if cur.description:
                return _PgResult(cur.fetchall())
            return _NullResult()

        def commit(self):
            self._conn.commit()

        def close(self):
            self._conn.close()

    def get_db():
        return PgConnection()

    def init_db():
        conn = get_db()
        for stmt in [
            """CREATE TABLE IF NOT EXISTS products (
                id SERIAL PRIMARY KEY,
                name TEXT NOT NULL,
                base_material TEXT
            )""",
            """CREATE TABLE IF NOT EXISTS colors (
                id SERIAL PRIMARY KEY,
                color_code TEXT NOT NULL UNIQUE
            )""",
            """CREATE TABLE IF NOT EXISTS orders (
                id SERIAL PRIMARY KEY,
                control_no TEXT,
                order_date TEXT,
                order_number TEXT,
                product_name TEXT NOT NULL,
                base_material TEXT,
                color_code TEXT,
                material_delivery_memo TEXT,
                desired_delivery TEXT,
                order_quantity INTEGER NOT NULL DEFAULT 0,
                status TEXT NOT NULL DEFAULT '進行中'
            )""",
            """CREATE TABLE IF NOT EXISTS delivery_plans (
                id SERIAL PRIMARY KEY,
                order_id INTEGER NOT NULL REFERENCES orders(id) ON DELETE CASCADE,
                reply_date TEXT,
                reply_quantity INTEGER NOT NULL DEFAULT 0
            )""",
            """CREATE TABLE IF NOT EXISTS delivery_records (
                id SERIAL PRIMARY KEY,
                order_id INTEGER NOT NULL REFERENCES orders(id) ON DELETE CASCADE,
                mold_number TEXT,
                actual_date TEXT,
                actual_quantity INTEGER NOT NULL DEFAULT 0,
                registered_at TEXT DEFAULT TO_CHAR(NOW(), 'YYYY-MM-DD HH24:MI:SS')
            )""",
            """CREATE TABLE IF NOT EXISTS change_logs (
                id SERIAL PRIMARY KEY,
                order_id INTEGER NOT NULL REFERENCES orders(id) ON DELETE CASCADE,
                changed_at TEXT DEFAULT TO_CHAR(NOW(), 'YYYY-MM-DD HH24:MI:SS'),
                change_type TEXT,
                change_detail TEXT,
                operator TEXT
            )""",
            """CREATE TABLE IF NOT EXISTS users (
                id SERIAL PRIMARY KEY,
                username TEXT NOT NULL UNIQUE,
                password_hash TEXT NOT NULL,
                created_at TEXT DEFAULT TO_CHAR(NOW(), 'YYYY-MM-DD HH24:MI:SS')
            )""",
        ]:
            conn.execute(stmt)
        conn.commit()

        count = conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]
        if count == 0:
            conn.execute(
                "INSERT INTO users (username, password_hash) VALUES (?, ?)",
                (DEFAULT_ADMIN_USERNAME, generate_password_hash(DEFAULT_ADMIN_PASSWORD)),
            )
            conn.commit()
            print(f"[init_db] 初期管理者ユーザーを作成しました: username='{DEFAULT_ADMIN_USERNAME}'")
        conn.close()


# ─────────────────────────────────────────────
# SQLite サポート（ローカル開発用）
# ─────────────────────────────────────────────
else:
    def get_db():
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        return conn

    def init_db():
        conn = get_db()
        c = conn.cursor()

        c.executescript("""
            CREATE TABLE IF NOT EXISTS products (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                base_material TEXT
            );

            CREATE TABLE IF NOT EXISTS colors (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                color_code TEXT NOT NULL UNIQUE
            );

            CREATE TABLE IF NOT EXISTS orders (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                control_no TEXT,
                order_date TEXT,
                order_number TEXT,
                product_name TEXT NOT NULL,
                base_material TEXT,
                color_code TEXT,
                material_delivery_memo TEXT,
                desired_delivery TEXT,
                order_quantity INTEGER NOT NULL DEFAULT 0,
                status TEXT NOT NULL DEFAULT '進行中'
            );

            CREATE TABLE IF NOT EXISTS delivery_plans (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                order_id INTEGER NOT NULL,
                reply_date TEXT,
                reply_quantity INTEGER NOT NULL DEFAULT 0,
                FOREIGN KEY (order_id) REFERENCES orders(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS delivery_records (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                order_id INTEGER NOT NULL,
                mold_number TEXT,
                actual_date TEXT,
                actual_quantity INTEGER NOT NULL DEFAULT 0,
                registered_at TEXT DEFAULT (datetime('now', 'localtime')),
                FOREIGN KEY (order_id) REFERENCES orders(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS change_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                order_id INTEGER NOT NULL,
                changed_at TEXT DEFAULT (datetime('now', 'localtime')),
                change_type TEXT,
                change_detail TEXT,
                operator TEXT,
                FOREIGN KEY (order_id) REFERENCES orders(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT NOT NULL UNIQUE,
                password_hash TEXT NOT NULL,
                created_at TEXT DEFAULT (datetime('now', 'localtime'))
            );
        """)
        conn.commit()

        # マイグレーション: delivery_records に mold_number が無ければ追加
        cols = [row[1] for row in c.execute("PRAGMA table_info(delivery_records)").fetchall()]
        if "mold_number" not in cols:
            c.execute("ALTER TABLE delivery_records ADD COLUMN mold_number TEXT")
            conn.commit()

        # マイグレーション: products から quantity_per_package / package_unit を削除
        prod_cols = [row[1] for row in c.execute("PRAGMA table_info(products)").fetchall()]
        if "quantity_per_package" in prod_cols or "package_unit" in prod_cols:
            c.executescript("""
                PRAGMA foreign_keys = OFF;
                CREATE TABLE products_new (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL,
                    base_material TEXT
                );
                INSERT INTO products_new (id, name, base_material)
                    SELECT id, name, base_material FROM products;
                DROP TABLE products;
                ALTER TABLE products_new RENAME TO products;
                PRAGMA foreign_keys = ON;
            """)
            conn.commit()

        # 初回起動時: ユーザーが0件なら初期管理者ユーザーを作成
        user_count = c.execute("SELECT COUNT(*) FROM users").fetchone()[0]
        if user_count == 0:
            c.execute(
                "INSERT INTO users (username, password_hash) VALUES (?, ?)",
                (DEFAULT_ADMIN_USERNAME, generate_password_hash(DEFAULT_ADMIN_PASSWORD)),
            )
            conn.commit()
            print(f"[init_db] 初期管理者ユーザーを作成しました: username='{DEFAULT_ADMIN_USERNAME}'")

        conn.close()
