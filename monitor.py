"""
Real-time crawler queue and metrics monitoring tool.
"""

import sqlite3
import os
from config import DB_PATH

def check_progress():
    if not os.path.exists(DB_PATH):
        print(f"Database {DB_PATH} not initialized yet.")
        return

    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("SELECT status, count(*) FROM pages GROUP BY status")
    stats = dict(cur.fetchall())
    cur.execute("SELECT count(*) FROM listings")
    total_listings = cur.fetchone()[0]
    conn.close()

    done = stats.get("done", 0)
    empty = stats.get("empty", 0)
    pending = stats.get("pending", 0)
    total_pages = done + empty + pending
    pct = (done + empty) / total_pages * 100 if total_pages > 0 else 0

    print("=" * 45)
    print(f"  Live Crawler Progress: {pct:.1f}%")
    print("=" * 45)
    print(f"  Total Listings Scraped : {total_listings:,}")
    print(f"  Pages Done (Active)    : {done:,}")
    print(f"  Pages Completed (Empty): {empty:,}")
    print(f"  Pages Pending          : {pending:,}")
    print(f"  Total Pages Queued     : {total_pages:,}")
    print("=" * 45)

if __name__ == '__main__':
    check_progress()
