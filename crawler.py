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
from init_db import init_database

class AqarCrawler:
    def __init__(self, log_callback=None):
        self.lock = threading.Lock()
        self.running = True
        self.user_agent = None
        self.cookie_header = None
        self.log_callback = log_callback or print
        self.current_run_id = None
        
        try:
            signal.signal(signal.SIGINT, self._handle_exit)
            signal.signal(signal.SIGTERM, self._handle_exit)
        except Exception:
            pass  # When running in subthread

        self._init_db()
        self._init_csv()

    def _log(self, msg):
        self.log_callback(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}")

    def _handle_exit(self, signum, frame):
        self._log(f"Received exit signal {signum}. Stopping crawler loop...")
        self.running = False

    def stop(self):
        self._log("Stop requested. Gracefully halting crawler...")
        self.running = False

    def _init_db(self):
        init_database(DB_PATH)

    def _init_csv(self):
        if not os.path.exists(CSV_PATH) or os.path.getsize(CSV_PATH) == 0:
            with open(CSV_PATH, 'w', newline='', encoding='utf-8-sig') as f:
                writer = csv.writer(f)
                writer.writerow(CSV_HEADERS)

    def refresh_clearance(self):
        with self.lock:
            self._log("[FlareSolverr] Requesting clearance token...")
            payload = json.dumps({
                'cmd': 'request.get',
                'url': BASE_CITY_URL,
                'maxTimeout': FLARE_TIMEOUT
            }).encode('utf-8')

            endpoints = [FLARESOLVERR_URL, 'http://172.17.0.1:8191/v1', 'http://127.0.0.1:8191/v1', 'http://flaresolverr:8191/v1']
            # Deduplicate endpoints while preserving order
            seen = set()
            valid_endpoints = []
            for ep in endpoints:
                if ep not in seen:
                    seen.add(ep)
                    valid_endpoints.append(ep)

            for target_url in valid_endpoints:
                req = urllib.request.Request(target_url, data=payload, headers={'Content-Type': 'application/json'})
                for att in range(2):
                    try:
                        with urllib.request.urlopen(req, timeout=50) as resp:
                            data = json.loads(resp.read().decode('utf-8'))
                            sol = data.get('solution', {})
                            self.user_agent = sol.get('userAgent')
                            cookies = sol.get('cookies', [])
                            self.cookie_header = "; ".join([f"{c['name']}={c['value']}" for c in cookies])
                            self._log(f"[FlareSolverr] Clearance OK via {target_url}! Cookies: {len(cookies)}, UA: {self.user_agent[:40]}...")
                            return True
                    except Exception as e:
                        self._log(f"[FlareSolverr] Attempt {att+1} failed on {target_url}: {e}")
                        time.sleep(1)
            return False

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
        self._log("Starting crawler session...")
        self.refresh_clearance()

        p1 = self.fetch_url(BASE_CITY_URL)
        m_count = re.search(r'count\\*":\s*(\d+)', p1) if p1 else None
        total_ads = int(m_count.group(1)) if m_count else 86000
        total_pages = (total_ads // 20) + 1
        self._log(f"[Total Found] {total_ads:,} active ads across ~{total_pages:,} pages.")

        conn = sqlite3.connect(DB_PATH)
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) FROM pages")
        existing_pages = cur.fetchone()[0]

        if existing_pages < total_pages:
            self._log(f"[Queue] Initializing {total_pages - existing_pages} pages into queue...")
            pages_data = [(p, 'pending', None) for p in range(1, total_pages + 1)]
            cur.executemany("INSERT OR IGNORE INTO pages (page_num, status, scraped_at) VALUES (?, ?, ?)", pages_data)
            conn.commit()
        else:
            cur.execute("SELECT COUNT(*) FROM pages WHERE status='done'")
            done_cnt = cur.fetchone()[0]
            self._log(f"[Queue] Resuming crawl: {done_cnt:,}/{existing_pages:,} already scraped.")

        # Record run start
        cur.execute("INSERT INTO runs (started_at, status, total_pages, csv_file) VALUES (?, 'RUNNING', ?, ?)",
                    (datetime.now().isoformat(), total_pages, os.path.basename(CSV_PATH)))
        self.current_run_id = cur.lastrowid
        conn.commit()
        conn.close()

        scraped_this_session = 0
        t_start = time.time()

        while self.running:
            conn = sqlite3.connect(DB_PATH)
            cur = conn.cursor()
            cur.execute("SELECT page_num FROM pages WHERE status = 'pending' ORDER BY page_num ASC LIMIT 30")
            batch = [r[0] for r in cur.fetchall()]
            conn.close()

            if not batch:
                self._log("[Crawler] Finished! All pages processed.")
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
                    scraped_this_session += len(items)
                else:
                    c.execute("UPDATE pages SET status = 'empty', scraped_at = ? WHERE page_num = ?", (datetime.now().isoformat(), p_num))
            conn.commit()

            # Update runs record
            c.execute("SELECT COUNT(*) FROM listings")
            total_listings = c.fetchone()[0]
            c.execute("SELECT COUNT(*) FROM pages WHERE status='done'")
            pages_done = c.fetchone()[0]

            if self.current_run_id:
                c.execute("UPDATE runs SET listings_count = ?, pages_done = ? WHERE id = ?",
                          (total_listings, pages_done, self.current_run_id))
                conn.commit()
            conn.close()

            if csv_rows:
                with open(CSV_PATH, 'a', newline='', encoding='utf-8-sig') as f:
                    csv.writer(f).writerows(csv_rows)

            el = time.time() - t_start
            spd = scraped_this_session / el if el > 0 else 0
            self._log(f"Progress: {total_listings:,} ads ({pages_done:,} pages done) | {spd:.1f} ads/sec")

        # Finalize run status
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        final_status = 'COMPLETED' if self.running else 'PAUSED'
        if self.current_run_id:
            c.execute("UPDATE runs SET finished_at = ?, status = ? WHERE id = ?",
                      (datetime.now().isoformat(), final_status, self.current_run_id))
            conn.commit()
        conn.close()
        self._log(f"Crawler loop ended with status: {final_status}")

if __name__ == '__main__':
    AqarCrawler().run()
