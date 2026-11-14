"""
Database initialization and schema migration script for ScrapeDatAqar.
Configures SQLite in Write-Ahead Logging (WAL) mode and creates all required tables and indexes.
"""

import sqlite3
import os
from config import DB_PATH

SCHEMA_SQL = """
PRAGMA journal_mode = WAL;
PRAGMA synchronous = NORMAL;

CREATE TABLE IF NOT EXISTS pages (
    page_num INTEGER PRIMARY KEY,
    status TEXT DEFAULT 'pending', -- 'pending', 'done', 'empty'
    scraped_at TEXT
);

CREATE TABLE IF NOT EXISTS listings (
    id INTEGER PRIMARY KEY,
    page_num INTEGER,
    page_url TEXT,
    ad_url TEXT,
    data_json TEXT,
    scraped_at TEXT
);

CREATE INDEX IF NOT EXISTS idx_pages_status ON pages(status);
CREATE INDEX IF NOT EXISTS idx_listings_page ON listings(page_num);
"""

def init_database(db_path=DB_PATH):
    print(f"[Database] Initializing schema at '{db_path}'...")
    db_dir = os.path.dirname(db_path)
    if db_dir:
        os.makedirs(db_dir, exist_ok=True)

    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    cur.executescript(SCHEMA_SQL)
    conn.commit()

    # Verify tables
    cur.execute("SELECT name FROM sqlite_master WHERE type='table';")
    tables = [row[0] for row in cur.fetchall()]
    print(f"[Database] OK! Active tables: {', '.join(tables)}")

    cur.execute("PRAGMA journal_mode;")
    mode = cur.fetchone()[0]
    print(f"[Database] WAL mode enabled: {mode.upper()}")
    conn.close()

if __name__ == '__main__':
    init_database()
