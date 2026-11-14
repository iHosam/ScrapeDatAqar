"""
High-throughput crawler module for Aqar.fm using Next.js streaming deserialization.
Version 2.1: Multi-city, persistent filters, isolated runs, and automatic Excel exports.
"""

import os
import re
import csv
import json
import time
import random
import shutil
import sqlite3
import signal
import threading
import urllib.parse
import urllib.request
from datetime import datetime
import concurrent.futures

from config import (
    BASE_SITE_URL, FLARESOLVERR_URL, DB_PATH, DATA_DIR,
    MAX_WORKERS, REQUEST_TIMEOUT, FLARE_TIMEOUT, CSV_HEADERS
)
from init_db import init_database
from export_excel import export_to_excel

CATEGORY_SLUG_MAP = {
    'شقق للإيجار': 'شقق-للإيجار',
    'شقق للبيع': 'شقق-للبيع',
    'فلل للبيع': 'فلل-للبيع',
    'فلل للإيجار': 'فلل-للإيجار',
    'أراضي للبيع': 'أراضي-للبيع',
    'دور للإيجار': 'دور-للإيجار',
    'دور للبيع': 'دور-للبيع',
    'عمارة للبيع': 'عمارة-للبيع',
    'استراحة للإيجار': 'استراحة-للإيجار',
    'استراحة للبيع': 'استراحة-للبيع',
    'محلات للإيجار': 'محلات-للإيجار',
    'محلات للبيع': 'محلات-للبيع',
    'مكاتب للإيجار': 'مكاتب-للإيجار',
    'مستودع للإيجار': 'مستودع-للإيجار'
}

class AqarCrawler:
    def __init__(self, filters=None, log_callback=None):
        self.lock = threading.Lock()
        self.running = True
        self.user_agent = None
        self.cookie_header = None
        self.filters = filters or {}
        self.log_callback = log_callback or print
        self.current_run_id = None
        
        try:
            signal.signal(signal.SIGINT, self._handle_exit)
            signal.signal(signal.SIGTERM, self._handle_exit)
        except Exception:
            pass

        self._init_db()
        self._init_paths_and_urls()

    def _log(self, msg):
        self.log_callback(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}")

    def _handle_exit(self, signum, frame):
        self._log(f"Received exit signal {signum}. Halting crawler...")
        self.running = False

    def stop(self):
        self._log("Stop requested. Halting crawler...")
        self.running = False

    def _init_db(self):
        init_database(DB_PATH)

    def _init_paths_and_urls(self):
        """Builds unique run files and search URLs based on filter selections."""
        # 1. City selection (Default: ALL CITIES across the kingdom)
        city_raw = self.filters.get('city') or ''
        if not city_raw or 'الكل' in city_raw or city_raw.strip() in ('', 'all', 'الكل (جميع مدن المملكة)'):
            self.is_all_cities = True
            self.target_city = 'جميع المدن'
        else:
            self.is_all_cities = False
            self.target_city = city_raw.strip()

        # 2. Categories selection
        cats = self.filters.get('categories') or ['الكل']
        if isinstance(cats, str):
            cats = [c.strip() for c in cats.split(',') if c.strip()]
        self.target_categories = cats
        single_cat = len(cats) == 1 and cats[0] in CATEGORY_SLUG_MAP

        # 3. Districts filter
        dists = self.filters.get('districts') or ['الكل']
        if isinstance(dists, str):
            dists = [d.strip() for d in dists.split(',') if d.strip()]
        self.target_districts = dists
        has_single_district = len(self.target_districts) == 1 and self.target_districts[0] not in ('الكل', '', 'all')
        dist_slug = ''
        if has_single_district:
            d_raw = self.target_districts[0].strip().replace(' ', '-')
            if not d_raw.startswith('حي-'):
                dist_slug = f"حي-{d_raw}"
            else:
                dist_slug = d_raw

        # 4. Construct Base Search URL
        if self.is_all_cities:
            if single_cat:
                cat_slug = CATEGORY_SLUG_MAP[cats[0]]
                self.base_search_url = f"{BASE_SITE_URL}/{urllib.parse.quote(cat_slug)}"
            else:
                self.base_search_url = f"{BASE_SITE_URL}/عقارات"
        else:
            cat_part = CATEGORY_SLUG_MAP[cats[0]] if single_cat else 'عقارات'
            if dist_slug:
                self.base_search_url = f"{BASE_SITE_URL}/{urllib.parse.quote(cat_part)}/{urllib.parse.quote(self.target_city)}/{urllib.parse.quote(dist_slug)}"
            else:
                self.base_search_url = f"{BASE_SITE_URL}/{urllib.parse.quote(cat_part)}/{urllib.parse.quote(self.target_city)}"

        # 5. Numeric & Range Filters
        self.min_price = float(self.filters.get('min_price') or 0)
        self.max_price = float(self.filters.get('max_price') or 0)
        self.min_area = float(self.filters.get('min_area') or 0)
        self.max_area = float(self.filters.get('max_area') or 0)
        self.beds = str(self.filters.get('beds') or '').strip()

        # Build query parameters
        params = []
        if self.min_price > 0: params.append(f"min_price={int(self.min_price)}")
        if self.max_price > 0: params.append(f"max_price={int(self.max_price)}")
        if self.min_area > 0: params.append(f"min_area={int(self.min_area)}")
        if self.max_area > 0: params.append(f"max_area={int(self.max_area)}")
        if self.beds and self.beds not in ('الكل', '', '0'): params.append(f"beds={self.beds}")

        self.query_string = ("?" + "&".join(params)) if params else ""
        self.target_full_url = f"{self.base_search_url}{self.query_string}"
        self._log(f"Constructed Search Target: {self.target_full_url}")

        # Unique Output Files for this Run
        ts = datetime.now().strftime('%Y%m%d_%H%M%S')
        safe_city = re.sub(r'[^\w\-]', '_', self.target_city)
        self.csv_filename = f"aqar_{safe_city}_{ts}_53cols.csv"
        self.excel_filename = f"aqar_{safe_city}_{ts}_53cols.xlsx"
        self.csv_path = os.path.join(DATA_DIR, self.csv_filename)
        self.excel_path = os.path.join(DATA_DIR, self.excel_filename)

        # Initialize fresh CSV file for this run
        with open(self.csv_path, 'w', newline='', encoding='utf-8-sig') as f:
            csv.writer(f).writerow(CSV_HEADERS)

    def refresh_clearance(self):
        with self.lock:
            self._log("[FlareSolverr] Requesting clearance token...")
            payload = json.dumps({
                'cmd': 'request.get',
                'url': self.base_search_url,
                'maxTimeout': FLARE_TIMEOUT
            }).encode('utf-8')

            endpoints = [FLARESOLVERR_URL, 'http://172.17.0.1:8191/v1', 'http://127.0.0.1:8191/v1', 'http://flaresolverr:8191/v1']
            seen = set()
            valid_endpoints = [ep for ep in endpoints if ep not in seen and not seen.add(ep)]

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
            'Referer': self.base_search_url
        }
        if self.cookie_header:
            headers['Cookie'] = self.cookie_header

        parsed = urllib.parse.urlparse(url)
        clean_path = urllib.parse.quote(urllib.parse.unquote(parsed.path))
        full_url = f"{parsed.scheme}://{parsed.netloc}{clean_path}"
        if parsed.query:
            full_url += f"?{parsed.query}"

        req = urllib.request.Request(full_url, headers=headers)

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

        # Two-stage Next.js flight streaming JSON unescape:
        # Protects double-escaped backslashes so embedded quotes inside ad descriptions
        # (e.g. \\"مجدد\\") do not corrupt outer JSON string boundaries into unescaped quotes.
        MARKER = '@@ESCAPED_SLASH@@'
        cleaned = raw.replace('\\\\', MARKER).replace('\\"', '"').replace(MARKER, '\\')
        try:
            items, _ = json.JSONDecoder().raw_decode(cleaned)
            return items if isinstance(items, list) else []
        except Exception:
            try:
                # Fallback for simpler single-escaped formats
                fallback_cleaned = raw.replace('\\"', '"')
                items, _ = json.JSONDecoder().raw_decode(fallback_cleaned)
                return items if isinstance(items, list) else []
            except Exception:
                return []

    def matches_filters(self, item):
        """Dual-layer client side validation against active filters."""
        loc = item.get('location') or {}

        # 1. City check (if specific city targeted)
        if not self.is_all_cities:
            item_city = (item.get('city') or loc.get('city') or '').strip()
            item_addr = item.get('address') or ''
            if (self.target_city not in item_city and item_city not in self.target_city) and (self.target_city not in item_addr):
                return False

        # 2. Price check
        if self.min_price > 0 or self.max_price > 0:
            price = float(item.get('price') or 0)
            if self.min_price > 0 and price < self.min_price: return False
            if self.max_price > 0 and price > self.max_price: return False

        # 3. Area check
        if self.min_area > 0 or self.max_area > 0:
            area = float(item.get('area') or 0)
            if self.min_area > 0 and area < self.min_area: return False
            if self.max_area > 0 and area > self.max_area: return False

        # 4. Beds check
        if self.beds and self.beds not in ('الكل', '', '0'):
            item_beds = str(item.get('beds') or '')
            if self.beds.endswith('+'):
                min_b = int(self.beds.replace('+', ''))
                if not (item_beds.isdigit() and int(item_beds) >= min_b): return False
            else:
                if item_beds != self.beds: return False

        # 5. Category check
        if self.target_categories and not any('الكل' in c for c in self.target_categories):
            cat_name = item.get('categoryName', '')
            if not any(target in cat_name for target in self.target_categories):
                return False

        # 6. District check (robust matching against district property, address, and title)
        if self.target_districts and not any('الكل' in d for d in self.target_districts):
            item_dist = (item.get('district') or loc.get('district') or '').strip()
            item_addr = (item.get('address') or '').strip()
            item_title = (item.get('title') or '').strip()
            full_loc_text = f"{item_dist} {item_addr} {item_title}"

            matched = False
            for d in self.target_districts:
                d_clean = d.replace('حي ', '').replace('حي-', '').strip()
                if not d_clean:
                    continue
                if d in full_loc_text or d_clean in full_loc_text:
                    matched = True
                    break
            if not matched:
                return False

        return True

    def transform_to_row(self, item, page_num):
        loc = item.get('location') or {}
        user = item.get('user') or {}
        aid = item.get('id')
        item_city = item.get('city') or loc.get('city') or self.target_city
        item_district = item.get('district') or loc.get('district') or ''
        imgs = item.get('imgs') or []
        img_urls = [f"https://images.aqar.fm/webp/750x0/props/{i}" if not i.startswith('http') else i for i in imgs]
        videos = item.get('videos') or []
        vid_url = f"https://videos.aqar.fm/{videos[0].get('video')}/master.m3u8" if videos and isinstance(videos[0], dict) and videos[0].get('video') else ""
        c_time = datetime.fromtimestamp(item['create_time']).strftime('%Y-%m-%d %H:%M') if item.get('create_time') else ""
        u_time = datetime.fromtimestamp(item['last_update']).strftime('%Y-%m-%d %H:%M') if item.get('last_update') else ""

        page_search_url = f"{self.base_search_url}/{page_num}{self.query_string}" if page_num > 1 else self.target_full_url
        direct_path = item.get('path') or f"/ad/{aid}"
        full_ad_url = f"{BASE_SITE_URL}{direct_path}"
        short_ad_url = f"{BASE_SITE_URL}/ad/{aid}"

        return [
            aid, f"عقارات {item_city}", item.get('categoryName', ''), item.get('title', ''), item.get('price', ''),
            item.get('rent_period_text', ''), item.get('rega_total_price', ''), item.get('area', ''), item.get('deed_area', ''),
            item_city, item_district, item.get('address', ''), item.get('advertisement_number', ''),
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
        self._log(f"Starting crawl for: {self.target_city} | Target URL: {self.target_full_url}")
        self.refresh_clearance()

        # Fetch Page 1
        p1 = self.fetch_url(self.target_full_url)

        m_count = re.search(r'count\\*":\s*(\d+)', p1) if p1 else None
        if not m_count and p1:
            m_count = re.search(r'count="(\d+)"', p1)

        total_ads = int(m_count.group(1)) if m_count else 2000
        total_pages = max(1, (total_ads // 20) + 1)
        self._log(f"[Total Found] {total_ads:,} active ads across ~{total_pages:,} pages.")

        # Filter summary
        filter_summary = f"المدينة: {self.target_city}"
        if not any('الكل' in c for c in self.target_categories):
            filter_summary += f" | القسم: {','.join(self.target_categories)}"
        if self.min_price > 0 or self.max_price > 0:
            filter_summary += f" | السعر: {int(self.min_price):,}-{int(self.max_price):,}"
        if self.min_area > 0 or self.max_area > 0:
            filter_summary += f" | المساحة: {int(self.min_area):,}-{int(self.max_area):,}"
        if self.beds and self.beds != 'الكل':
            filter_summary += f" | غرف: {self.beds}"

        # CRITICAL FIX FOR ISSUE 3: Always initialize a clean queue for the new crawl!
        conn = sqlite3.connect(DB_PATH)
        cur = conn.cursor()
        cur.execute("DELETE FROM pages")
        cur.execute("DELETE FROM listings")

        pages_data = [(p, 'pending', None) for p in range(1, total_pages + 1)]
        cur.executemany("INSERT INTO pages (page_num, status, scraped_at) VALUES (?, ?, ?)", pages_data)

        cur.execute("""
            INSERT INTO runs (started_at, status, total_pages, filter_desc, csv_file, excel_file)
            VALUES (?, 'RUNNING', ?, ?, ?, ?)
        """, (datetime.now().isoformat(), total_pages, filter_summary, self.csv_filename, self.excel_filename))
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
                self._log("[Crawler] All pages processed! Completing crawl.")
                break

            def scrape_worker(p_num):
                if not self.running:
                    return p_num, []
                url = f"{self.base_search_url}/{p_num}{self.query_string}" if p_num > 1 else self.target_full_url
                html = self.fetch_url(url)
                items = self.parse_page_listings(html)
                filtered_items = [it for it in items if self.matches_filters(it)]
                time.sleep(random.uniform(0.08, 0.15))
                return p_num, filtered_items

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

            c.execute("SELECT COUNT(*) FROM listings")
            total_listings = c.fetchone()[0]
            c.execute("SELECT COUNT(*) FROM pages WHERE status IN ('done', 'empty')")
            pages_done = c.fetchone()[0]

            if self.current_run_id:
                c.execute("UPDATE runs SET listings_count = ?, pages_done = ? WHERE id = ?",
                          (total_listings, pages_done, self.current_run_id))
                conn.commit()
            conn.close()

            if csv_rows:
                with open(self.csv_path, 'a', newline='', encoding='utf-8-sig') as f:
                    csv.writer(f).writerows(csv_rows)

            el = time.time() - t_start
            spd = scraped_this_session / el if el > 0 else 0
            self._log(f"Progress ({self.target_city}): {total_listings:,} ads ({pages_done:,} pages done) | {spd:.1f} ads/sec")

        # Automatically generate Excel for this run upon completion
        final_status = 'COMPLETED' if self.running else 'PAUSED'
        self._log(f"Crawl {final_status}. Automatically compiling Excel workbook...")
        try:
            export_to_excel(self.csv_path, self.excel_path)
            self._log(f"Excel workbook generated: {self.excel_filename}")
        except Exception as e:
            self._log(f"Auto Excel generation error: {e}")

        # Update latest pointers
        latest_csv = os.path.join(DATA_DIR, 'aqar_latest_53cols.csv')
        latest_xlsx = os.path.join(DATA_DIR, 'aqar_latest_53cols.xlsx')
        try:
            shutil.copyfile(self.csv_path, latest_csv)
            if os.path.exists(self.excel_path):
                shutil.copyfile(self.excel_path, latest_xlsx)
        except Exception:
            pass

        # Finalize run record in SQLite
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        if self.current_run_id:
            c.execute("""
                UPDATE runs SET finished_at = ?, status = ?, excel_file = ?, csv_file = ?
                WHERE id = ?
            """, (datetime.now().isoformat(), final_status, self.excel_filename, self.csv_filename, self.current_run_id))
            conn.commit()
        conn.close()
        self._log(f"Run #{self.current_run_id} finished successfully ({final_status}) with files {self.excel_filename} & {self.csv_filename}.")

if __name__ == '__main__':
    AqarCrawler().run()
