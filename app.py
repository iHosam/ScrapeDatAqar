"""
ScrapeDatAqar Web Interface & Controller
Provides REST API and Dashboard for readiness checks, crawl control, and history log.
"""

import os
import shutil
import sqlite3
import threading
import time
from collections import deque
from datetime import datetime
from flask import Flask, jsonify, render_template, request, send_from_directory
import requests

from config import (
    BASE_SITE_URL, BASE_CITY_URL, FLARESOLVERR_URL, DB_PATH, CSV_PATH, EXCEL_PATH,
    PORT, DATA_DIR, SUPPORTED_CITIES, SUPPORTED_CATEGORIES
)
from crawler import AqarCrawler
from export_excel import export_to_excel
from init_db import init_database

app = Flask(__name__)

# Global state
crawler_instance = None
crawler_thread = None
is_running = False
log_buffer = deque(maxlen=200)

def add_log(msg):
    log_buffer.append(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}")

@app.route('/')
def index():
    return render_template(
        'index.html',
        port=PORT,
        cities=SUPPORTED_CITIES,
        categories=SUPPORTED_CATEGORIES
    )

@app.route('/api/readiness')
def check_readiness():
    checks = {
        'flaresolverr': {'status': False, 'message': 'Unreachable'},
        'database': {'status': False, 'message': 'Not initialized'},
        'disk': {'status': True, 'free_gb': 0},
        'ready': False
    }

    # 1. FlareSolverr Check
    urls_to_try = [FLARESOLVERR_URL, 'http://172.17.0.1:8191/v1', 'http://127.0.0.1:8191/v1', 'http://flaresolverr:8191/v1']
    for candidate in urls_to_try:
        try:
            t0 = time.time()
            resp = requests.post(candidate, json={'cmd': 'sessions.list'}, timeout=3)
            if resp.status_code == 200:
                checks['flaresolverr'] = {
                    'status': True,
                    'latency_ms': int((time.time() - t0) * 1000),
                    'message': f'Healthy'
                }
                break
        except Exception as e:
            checks['flaresolverr']['message'] = str(e)

    # 2. Database Check
    try:
        if os.path.exists(DB_PATH):
            conn = sqlite3.connect(DB_PATH)
            cur = conn.cursor()
            cur.execute("SELECT name FROM sqlite_master WHERE type='table'")
            tables = [r[0] for r in cur.fetchall()]
            conn.close()
            if 'pages' in tables and 'listings' in tables:
                checks['database'] = {'status': True, 'message': f'OK ({len(tables)} tables)'}
        else:
            init_database(DB_PATH)
            checks['database'] = {'status': True, 'message': 'Auto-initialized'}
    except Exception as e:
        checks['database']['message'] = str(e)

    # 3. Disk Space Check
    try:
        total, used, free = shutil.disk_usage(DATA_DIR)
        checks['disk']['free_gb'] = round(free / (1024**3), 2)
        if checks['disk']['free_gb'] < 1.0:
            checks['disk']['status'] = False
    except Exception:
        pass

    checks['ready'] = checks['flaresolverr']['status'] and checks['database']['status'] and checks['disk']['status']
    return jsonify(checks)

@app.route('/api/status')
def get_status():
    global is_running

    stats = {
        'is_running': is_running,
        'listings_count': 0,
        'pages_done': 0,
        'pages_empty': 0,
        'pages_pending': 0,
        'total_pages': 0,
        'progress_pct': 0.0,
        'csv_exists': os.path.exists(CSV_PATH),
        'csv_size_mb': round(os.path.getsize(CSV_PATH)/(1024**2), 2) if os.path.exists(CSV_PATH) else 0,
        'excel_exists': os.path.exists(EXCEL_PATH),
        'excel_size_mb': round(os.path.getsize(EXCEL_PATH)/(1024**2), 2) if os.path.exists(EXCEL_PATH) else 0,
        'db_size_mb': round(os.path.getsize(DB_PATH)/(1024**2), 2) if os.path.exists(DB_PATH) else 0,
    }

    if os.path.exists(DB_PATH):
        try:
            conn = sqlite3.connect(DB_PATH)
            cur = conn.cursor()
            cur.execute("SELECT status, count(*) FROM pages GROUP BY status")
            page_stats = dict(cur.fetchall())
            cur.execute("SELECT count(*) FROM listings")
            stats['listings_count'] = cur.fetchone()[0]
            conn.close()

            stats['pages_done'] = page_stats.get('done', 0)
            stats['pages_empty'] = page_stats.get('empty', 0)
            stats['pages_pending'] = page_stats.get('pending', 0)
            stats['total_pages'] = stats['pages_done'] + stats['pages_empty'] + stats['pages_pending']
            if stats['total_pages'] > 0:
                stats['progress_pct'] = round(((stats['pages_done'] + stats['pages_empty']) / stats['total_pages']) * 100, 1)
        except Exception:
            pass

    return jsonify(stats)

@app.route('/api/start', methods=['POST'])
def start_scrape():
    """Starts or resumes the crawler loop in a background thread with custom filters."""
    global crawler_instance, crawler_thread, is_running

    if is_running:
        return jsonify({'success': False, 'message': 'Crawler is already active.'})

    filters = request.get_json(silent=True) or {}

    def run_worker():
        global crawler_instance, is_running
        is_running = True
        try:
            add_log(f"Initializing crawl with filters: {filters}")
            crawler_instance = AqarCrawler(filters=filters, log_callback=add_log)
            crawler_instance.run()
        except Exception as e:
            add_log(f"Crawler encountered an error: {e}")
        finally:
            is_running = False
            add_log("Crawler execution completed or paused.")

    crawler_thread = threading.Thread(target=run_worker, daemon=True)
    crawler_thread.start()
    return jsonify({'success': True, 'message': 'Crawl initiated with custom filters.'})

@app.route('/api/stop', methods=['POST'])
def stop_scrape():
    global crawler_instance, is_running

    if not is_running or not crawler_instance:
        return jsonify({'success': False, 'message': 'Crawler is not running.'})

    crawler_instance.stop()
    add_log("Pause request issued to crawler.")
    return jsonify({'success': True, 'message': 'Pause signal sent to crawler.'})

@app.route('/api/export', methods=['POST'])
def run_export():
    def export_worker():
        add_log("Starting Excel export...")
        try:
            export_to_excel()
            add_log("Excel workbook generated successfully.")
            if os.path.exists(DB_PATH):
                conn = sqlite3.connect(DB_PATH)
                c = conn.cursor()
                c.execute("UPDATE runs SET excel_file = ? WHERE id = (SELECT max(id) FROM runs)", (os.path.basename(EXCEL_PATH),))
                conn.commit()
                conn.close()
        except Exception as e:
            add_log(f"Export failed: {e}")

    t = threading.Thread(target=export_worker, daemon=True)
    t.start()
    return jsonify({'success': True, 'message': 'Excel export initiated.'})

@app.route('/api/logs')
def get_logs():
    return jsonify({'logs': list(log_buffer)})

@app.route('/api/history')
def get_history():
    runs = []
    if os.path.exists(DB_PATH):
        try:
            conn = sqlite3.connect(DB_PATH)
            cur = conn.cursor()
            cur.execute("""
                SELECT id, started_at, finished_at, status, listings_count, pages_done, total_pages, filter_desc, csv_file, excel_file
                FROM runs ORDER BY id DESC LIMIT 20
            """)
            for r in cur.fetchall():
                runs.append({
                    'id': r[0],
                    'started_at': r[1],
                    'finished_at': r[2] or 'Active',
                    'status': r[3],
                    'listings_count': r[4],
                    'pages_done': r[5],
                    'total_pages': r[6],
                    'filter_desc': r[7] or 'Default Filters',
                    'csv_file': r[8],
                    'excel_file': r[9] or (os.path.basename(EXCEL_PATH) if os.path.exists(EXCEL_PATH) else None)
                })
            conn.close()
        except Exception:
            pass
    return jsonify({'runs': runs})

@app.route('/download/<path:filename>')
def download_file(filename):
    filename = os.path.basename(filename)
    return send_from_directory(DATA_DIR, filename, as_attachment=True)

if __name__ == '__main__':
    init_database(DB_PATH)
    add_log(f"ScrapeDatAqar Web Server started on port {PORT}.")
    app.run(host='0.0.0.0', port=PORT, threaded=True)
