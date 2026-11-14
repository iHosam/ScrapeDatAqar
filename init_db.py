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

CREATE TABLE IF NOT EXISTS runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    started_at TEXT,
    finished_at TEXT,
    status TEXT, -- 'RUNNING', 'COMPLETED', 'PAUSED', 'FAILED'
    listings_count INTEGER DEFAULT 0,
    pages_done INTEGER DEFAULT 0,
    total_pages INTEGER DEFAULT 0,
    filter_desc TEXT DEFAULT 'All Filters (Default)',
    csv_file TEXT,
    excel_file TEXT
);

CREATE INDEX IF NOT EXISTS idx_pages_status ON pages(status);
CREATE INDEX IF NOT EXISTS idx_listings_page ON listings(page_num);
"""

def init_database(db_path=DB_PATH):
    db_dir = os.path.dirname(db_path)
    if db_dir:
        os.makedirs(db_dir, exist_ok=True)

    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    cur.executescript(SCHEMA_SQL)

    # Safe migration: add filter_desc if missing
    cur.execute("PRAGMA table_info(runs)")
    cols = [col[1] for col in cur.fetchall()]
    if 'filter_desc' not in cols:
        try:
            cur.execute("ALTER TABLE runs ADD COLUMN filter_desc TEXT DEFAULT 'All Filters (Default)'")
        except Exception:
            pass

    conn.commit()

    cur.execute("SELECT name FROM sqlite_master WHERE type='table';")
    tables = [row[0] for row in cur.fetchall()]

    cur.execute("PRAGMA journal_mode;")
    mode = cur.fetchone()[0]
    conn.close()
    return tables, mode

if __name__ == '__main__':
    tables, mode = init_database()
    print(f"[Database] Active tables: {', '.join(tables)}")
    print(f"[Database] WAL mode: {mode.upper()}")
