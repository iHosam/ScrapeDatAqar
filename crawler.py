"""
High-throughput crawler module for Aqar.fm using Next.js streaming deserialization.
"""

import os
import re
import csv
import json
import time
import random
import sqlite3
import signal
import threading
import urllib.parse
import urllib.request
from datetime import datetime
import concurrent.futures

from config import (
    BASE_CITY_URL, FLARESOLVERR_URL, DB_PATH, CSV_PATH,
    MAX_WORKERS, REQUEST_TIMEOUT, FLARE_TIMEOUT, CSV_HEADERS
)

class AqarCrawler:
    def __init__(self):
        self.lock = threading.Lock()
        self.running = True
        self.user_agent = None
        self.cookie_header = None
        signal.signal(signal.SIGINT, self._handle_exit)
        signal.signal(signal.SIGTERM, self._handle_exit)
        self._init_db()
        self._init_csv()

    def _handle_exit(self, signum, frame):
        print(f"\n[Signal] Gracefully terminating crawler loop...", flush=True)
        self.running = False

    def _init_db(self):
        conn = sqlite3.connect(DB_PATH)
        cur = conn.cursor()
        cur.execute("PRAGMA journal_mode = WAL;")
        cur.execute("PRAGMA synchronous = NORMAL;")
        cur.execute("""
            CREATE TABLE IF NOT EXISTS pages (
                page_num INTEGER PRIMARY KEY,
                status TEXT DEFAULT 'pending',
                scraped_at TEXT
            )
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS listings (
                id INTEGER PRIMARY KEY,
                page_num INTEGER,
                page_url TEXT,
                ad_url TEXT,
                data_json TEXT,
                scraped_at TEXT
            )
        """)
        cur.execute("CREATE INDEX IF NOT EXISTS idx_pages_status ON pages(status);")
        conn.commit()
        conn.close()

    def _init_csv(self):
        if not os.path.exists(CSV_PATH) or os.path.getsize(CSV_PATH) == 0:
            with open(CSV_PATH, 'w', newline='', encoding='utf-8-sig') as f:
                writer = csv.writer(f)
                writer.writerow(CSV_HEADERS)

    def refresh_clearance(self):
        with self.lock:
            print("[FlareSolverr] Requesting clearance token...", flush=True)
            payload = json.dumps({
                'cmd': 'request.get',
                'url': BASE_CITY_URL,
                'maxTimeout': FLARE_TIMEOUT
            }).encode('utf-8')
            req = urllib.request.Request(FLARESOLVERR_URL, data=payload, headers={'Content-Type': 'application/json'})
            for att in range(3):
                try:
                    with urllib.request.urlopen(req, timeout=50) as resp:
                        data = json.loads(resp.read().decode('utf-8'))
                        sol = data.get('solution', {})
                        self.user_agent = sol.get('userAgent')
                        cookies = sol.get('cookies', [])
                        self.cookie_header = "; ".join([f"{c['name']}={c['value']}" for c in cookies])
                        print(f"[FlareSolverr] Clearance OK! Cookies: {len(cookies)}, UA: {self.user_agent[:40]}...", flush=True)
                        return
                except Exception as e:
                    print(f"[FlareSolverr] Attempt {att+1} failed: {e}", flush=True)
                    time.sleep(2)

    def fetch_url(self, url):
        headers = {
            'User-Agent': self.user_agent or 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
            'Accept-Language': 'ar,en;q=0.9',
            'Referer': BASE_CITY_URL
        }
        if self.cookie_header:
            headers['Cookie'] = self.cookie_header

        path = url.replace('https://sa.aqar.fm', '')
        clean_path = urllib.parse.quote(urllib.parse.unquote(path))
        encoded_url = f'https://sa.aqar.fm{clean_path}'
        req = urllib.request.Request(encoded_url, headers=headers)

        for attempt in range(2):
            try:
                with urllib.request.urlopen(req, timeout=REQUEST_TIMEOUT) as resp:
                    return resp.read().decode('utf-8', errors='ignore')
            except urllib.error.HTTPError as he:
                if he.code in (403, 503):
                    self.refresh_clearance()
                elif he.code == 404:
                    return None
                time.sleep(0.5)
            except Exception:
                time.sleep(0.3)
        return ""

    def parse_page_listings(self, html):
        if not html:
            return []
        m = re.search(r'(?<!sov_)listings\\*":\s*(\[)', html)
        if not m:
            return []
        start = m.start(1)
        raw = html[start:]
        cleaned = raw.replace('\\"', '"')
        try:
            items, _ = json.JSONDecoder().raw_decode(cleaned)
            return items if isinstance(items, list) else []
        except Exception:
            return []

    def transform_to_row(self, item, page_num):
        loc = item.get('location') or {}
        user = item.get('user') or {}
        aid = item.get('id')
        imgs = item.get('imgs') or []
        img_urls = [f"https://images.aqar.fm/webp/750x0/props/{i}" if not i.startswith('http') else i for i in imgs]
        videos = item.get('videos') or []
        vid_url = f"https://videos.aqar.fm/{videos[0].get('video')}/master.m3u8" if videos and isinstance(videos[0], dict) and videos[0].get('video') else ""
        c_time = datetime.fromtimestamp(item['create_time']).strftime('%Y-%m-%d %H:%M') if item.get('create_time') else ""
        u_time = datetime.fromtimestamp(item['last_update']).strftime('%Y-%m-%d %H:%M') if item.get('last_update') else ""

        page_search_url = f"{BASE_CITY_URL}/{page_num}" if page_num > 1 else BASE_CITY_URL
        direct_path = item.get('path') or f"/ad/{aid}"
        full_ad_url = f"https://sa.aqar.fm{direct_path}"
        short_ad_url = f"https://sa.aqar.fm/ad/{aid}"

        return [
            aid, "عقارات الرياض", item.get('categoryName', ''), item.get('title', ''), item.get('price', ''),
            item.get('rent_period_text', ''), item.get('rega_total_price', ''), item.get('area', ''), item.get('deed_area', ''),
            "الرياض", loc.get('district', ''), item.get('address', ''), item.get('advertisement_number', ''),
            item.get('deed_number', ''), item.get('plan_number', ''), item.get('parcel_number', ''),
            f"{item.get('plan_number', '')} / {item.get('parcel_number', '')}".strip(" /"),
            "نعم" if item.get('licensed') else "لا", user.get('name', ''), user.get('iam_fal_license_number', ''),
            user.get('user_type_text', ''), user.get('phone', ''), item.get('beds', ''), item.get('livings', ''),
            item.get('wc', ''), item.get('floor', ''), item.get('age', ''), item.get('property_type', ''),
            item.get('street_width', ''), item.get('street_direction', ''),
            "نعم" if item.get('has_air_conditioner') else "لا", "نعم" if item.get('is_furnished') else "لا",
            "نعم" if item.get('has_car_entrance') else "لا", "نعم" if item.get('has_two_entrances') else "لا",
            "نعم" if item.get('has_special_entrance') else "لا", "نعم" if item.get('apartment_in_villa') else "لا",
            "نعم" if item.get('water_availability') else "لا", "نعم" if item.get('electrical_availability') else "لا",
            "نعم" if item.get('drainage_availability') else "لا", loc.get('lat', ''), loc.get('lng', ''),
            item.get('views', 0), item.get('likes_count', 0), item.get('favourites_count', 0),
            c_time, u_time, page_search_url, full_ad_url, short_ad_url,
            item.get('content', '') or item.get('description', ''), len(img_urls), ', '.join(img_urls[:5]), vid_url
        ]

    def run(self):
        print("Checking session tokens...", flush=True)
        self.refresh_clearance()

        p1 = self.fetch_url(BASE_CITY_URL)
        m_count = re.search(r'count\\*":\s*(\d+)', p1) if p1 else None
        total_ads = int(m_count.group(1)) if m_count else 86000
        total_pages = (total_ads // 20) + 1
        print(f"[Total Found] {total_ads:,} active ads across ~{total_pages:,} pages.", flush=True)

        conn = sqlite3.connect(DB_PATH)
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) FROM pages")
        existing_pages = cur.fetchone()[0]

        if existing_pages < total_pages:
            print(f"[Queue] Initializing {total_pages - existing_pages} pending pages...", flush=True)
            pages_data = [(p, 'pending', None) for p in range(1, total_pages + 1)]
            cur.executemany("INSERT OR IGNORE INTO pages (page_num, status, scraped_at) VALUES (?, ?, ?)", pages_data)
            conn.commit()
        else:
            cur.execute("SELECT COUNT(*) FROM pages WHERE status='done'")
            done_cnt = cur.fetchone()[0]
            print(f"[Queue] Resuming crawl: {done_cnt:,}/{existing_pages:,} already scraped.", flush=True)
        conn.close()

        while self.running:
            conn = sqlite3.connect(DB_PATH)
            cur = conn.cursor()
            cur.execute("SELECT page_num FROM pages WHERE status = 'pending' ORDER BY page_num ASC LIMIT 30")
            batch = [r[0] for r in cur.fetchall()]
            conn.close()

            if not batch:
                print("[Crawler] Finished! All pages processed.", flush=True)
                break

            def scrape_worker(p_num):
                if not self.running:
                    return p_num, []
                url = f"{BASE_CITY_URL}/{p_num}" if p_num > 1 else BASE_CITY_URL
                html = self.fetch_url(url)
                items = self.parse_page_listings(html)
                time.sleep(random.uniform(0.08, 0.15))
                return p_num, items

            with concurrent.futures.ThreadPoolExecutor(max_workers=MAX_WORKERS) as pool:
                results = list(pool.map(scrape_worker, batch))

            conn = sqlite3.connect(DB_PATH)
            c = conn.cursor()
            csv_rows = []
            for p_num, items in results:
                if items:
                    for it in items:
                        aid = it.get('id')
                        if aid:
                            row = self.transform_to_row(it, p_num)
                            csv_rows.append(row)
                            c.execute("INSERT OR REPLACE INTO listings (id, page_num, page_url, ad_url, data_json, scraped_at) VALUES (?, ?, ?, ?, ?, ?)",
                                      (aid, p_num, row[46], row[47], json.dumps(it, ensure_ascii=False), datetime.now().isoformat()))
                    c.execute("UPDATE pages SET status = 'done', scraped_at = ? WHERE page_num = ?", (datetime.now().isoformat(), p_num))
                else:
                    c.execute("UPDATE pages SET status = 'empty', scraped_at = ? WHERE page_num = ?", (datetime.now().isoformat(), p_num))
            conn.commit()
            conn.close()

            if csv_rows:
                with open(CSV_PATH, 'a', newline='', encoding='utf-8-sig') as f:
                    csv.writer(f).writerows(csv_rows)

if __name__ == '__main__':
    AqarCrawler().run()
