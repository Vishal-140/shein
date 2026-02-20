"""
Shein Dynamic Stock Monitor
---------------------------
Monitors Shein India for new/restocked products in Men and Women categories.
Features:
- Dynamic discovery via 'sverse' API endpoint (Parallelized).
- Robust verification of stock using product detail pages (Parallelized).
- Telegram alerts with images and direct links (HTML Format).
- State persistence to prevent duplicate alerts.

Author: Antigravity
"""

import sys
import json
import time
import random
import os
import signal
import logging
import re
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed
from curl_cffi import requests
import requests as standard_requests
import urllib3
from dotenv import load_dotenv
import pytz
from datetime import datetime

# Load environment variables from .env file if present
load_dotenv()

# Suppress SSL Warnings
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# --- Configuration ---

# Credentials (Environment Variables)
# Men channel
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
# Women channel
TELEGRAM_BOT_TOKEN_WOMEN = os.getenv("TELEGRAM_BOT_TOKEN_WOMEN")
TELEGRAM_CHAT_ID_WOMEN = os.getenv("TELEGRAM_CHAT_ID_WOMEN")

if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
    logger = logging.getLogger("SheinMonitor")
    logger.error("❌ Critical: TELEGRAM_BOT_TOKEN or TELEGRAM_CHAT_ID not found in environment variables.")
if not TELEGRAM_BOT_TOKEN_WOMEN or not TELEGRAM_CHAT_ID_WOMEN:
    logger = logging.getLogger("SheinMonitor")
    logger.error("❌ Critical: TELEGRAM_BOT_TOKEN_WOMEN or TELEGRAM_CHAT_ID_WOMEN not found in environment variables.")

# API Configuration
SHEIN_BASE_URL = "https://www.sheinindia.in"
CATEGORY_API_URL = "https://www.sheinindia.in/api/category/sverse-5939-37961"

# Categories to Monitor
MONITORED_GENDERS = ["Men", "Women"]

# System Settings
STOCK_STATE_FILE = "stock_state.json"
LOG_FILE = "monitor.log"
MAX_THREADS = 5  # Reduced for stability to prevent 403s
CYCLE_DELAY_RANGE = (45, 90) # Increased delay between cycles
PAGE_DELAY = (1, 2) # Reduced delay since we are parallel
TIMEOUT_SECONDS = 60
MAX_RETRIES = 3

# --- Logging Setup ---
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout) # Output to console for Render logs
    ]
)
logger = logging.getLogger("SheinMonitor")

class SheinMonitor:
    def __init__(self):
        self.session = None
        self.stock_state_file = STOCK_STATE_FILE
        self.stock_state = self.load_state()
        self.running = False # Start false, let run() set it or controls
        self.init_session()
        
        # Graceful Shutdown
        signal.signal(signal.SIGINT, self.shutdown)
        signal.signal(signal.SIGTERM, self.shutdown)

    def start(self):
        """Start the monitor loop."""
        self.running = True
        self.run()

    def stop(self):
        """Stop the monitor loop."""
        self.running = False

    def load_state(self):
        """Load state from JSON file."""
        if os.path.exists(self.stock_state_file):
            try:
                with open(self.stock_state_file, 'r') as f:
                    return json.load(f)
            except Exception as e:
                logger.error(f"Failed to load state: {e}")
        return {}

    def save_state(self):
        """Save state to JSON file."""
        try:
            with open(self.stock_state_file, 'w') as f:
                json.dump(self.stock_state, f, indent=4)
        except Exception as e:
            logger.error(f"Failed to save state: {e}")

    def shutdown(self, signum, frame):
        logger.info("Shutdown signal received. Exiting...")
        self.send_telegram_message("🛑 Monitor Stopped")
        self.send_telegram_message("🛑 Monitor Stopped", gender="Women")
        self.running = False
        sys.exit(0)

    def init_session(self):
        """Initialize curl_cffi session with browser impersonation and retries."""
        max_attempts = 10
        for attempt in range(max_attempts):
            try:
                self.session = requests.Session()
                self.impersonation = random.choice(["chrome110", "safari15_3"])
                logger.info(f"Trying session with impersonation: {self.impersonation}") 
                
                # Test connection to base URL to warm up
                resp = self.session.get(SHEIN_BASE_URL, timeout=15, impersonate=self.impersonation)
                if resp.status_code == 200:
                    logger.info("✅ Session initialized successfully")
                    return
                elif resp.status_code == 403:
                    logger.warning(f"Session init 403 (Attempt {attempt+1}/{max_attempts}). Retrying...")
                    time.sleep(random.uniform(5, 10))
                else:
                    logger.warning(f"Session init {resp.status_code}. Retrying...")
                    time.sleep(2)

            except Exception as e:
                logger.error(f"Session init failed: {e}")
                time.sleep(2)
        
        logger.error("❌ Critical: Could not initialize valid session after retries.")

    def send_telegram_message(self, text, photo_url=None, gender=None):
        """Send a message to Telegram using standard requests with retries.
        
        Routes to the Women channel when gender=='Women', otherwise uses the Men channel.
        """
        # Pick credentials based on gender
        if gender == "Women":
            bot_token = TELEGRAM_BOT_TOKEN_WOMEN
            chat_id = TELEGRAM_CHAT_ID_WOMEN
        else:
            bot_token = TELEGRAM_BOT_TOKEN
            chat_id = TELEGRAM_CHAT_ID

        for attempt in range(3):
            try:
                if photo_url:
                    url = f"https://api.telegram.org/bot{bot_token}/sendPhoto"
                    payload = {
                        "chat_id": chat_id,
                        "photo": photo_url,
                        "caption": text[:1024], # Caption limit
                        "parse_mode": "HTML" # Use HTML for safety
                    }
                else:
                    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
                    payload = {
                        "chat_id": chat_id,
                        "text": text,
                        "disable_web_page_preview": False,
                        "parse_mode": "HTML"
                    }
                
                # Use standard_requests here for reliability
                resp = standard_requests.post(url, json=payload, timeout=30)
                
                if resp.status_code == 200:
                    return True
                elif resp.status_code == 429:
                    retry_after = int(resp.headers.get("Retry-After", 5))
                    logger.warning(f"Telegram Rate Limit. Waiting {retry_after}s...")
                    time.sleep(retry_after)
                else:
                    logger.error(f"Telegram failed ({resp.status_code}): {resp.text[:200]}...")
                    # Retry once for text only if photo failed
                    if photo_url and attempt == 0:
                        logger.info("Retrying as text-only...")
                        return self.send_telegram_message(text, gender=gender)
            
            except standard_requests.exceptions.ReadTimeout:
                logger.warning(f"Telegram ReadTimeout (Attempt {attempt+1}/3). Assuming delivered to prevent duplicate spam.")
                return True # Assume success to prevent spam
            except Exception as e:
                logger.error(f"Failed to send Telegram alert (Attempt {attempt+1}/3): {e}")
                time.sleep(2)
        
        return False

    def fetch_page(self, page, gender):
        """Helper to fetch a single page."""
        params = {
            'fields': 'SITE',
            'currentPage': page,
            'pageSize': 40,
            'format': 'json',
            'query': f':relevance:genderfilter:{gender}',
            'facets': f'genderfilter:{gender}',
            'advfilter': 'true',
            'platform': 'Desktop', 
            'is_ads_enable_plp': 'true'
        }
        
        for attempt in range(MAX_RETRIES):
            try:
                # strict impersonation for every call
                resp = self.session.get(CATEGORY_API_URL, params=params, timeout=TIMEOUT_SECONDS, impersonate=self.impersonation)
                if resp.status_code == 200:
                    return resp.json()
                elif resp.status_code == 403:
                     time.sleep(random.uniform(2, 5)) # Backoff
                else:
                    time.sleep(1)
            except Exception as e:
                logger.error(f"Error fetching page {page}: {e}")
                time.sleep(1)
        return None

    def _parse_product(self, p, products_dict, gender):
        """Helper to parse raw product json and add to dict."""
        code = p.get('code')
        if not code: return
        
        # Extract Price/MRP
        mrp = "N/A"
        if 'retailPrice' in p and 'displayformattedValue' in p['retailPrice']:
            mrp = p['retailPrice']['displayformattedValue']
        elif 'offerPrice' in p and 'displayformattedValue' in p['offerPrice']:
                mrp = p['offerPrice']['displayformattedValue']
        
        price = mrp
        
        # Extract Image
        image = ""
        if 'fnlColorVariantData' in p and 'outfitPictureURL' in p['fnlColorVariantData']:
            image = p['fnlColorVariantData']['outfitPictureURL']
        elif 'images' in p and len(p['images']) > 0:
            image = p['images'][0].get('url', "")
        
        products_dict[code] = {
            'code': code,
            'name': p.get('name', 'Unknown Product'),
            'price': price,
            'image': image,
            'url': SHEIN_BASE_URL + p.get('url', f"/p/{code}"),
            'category': gender
        }

    def fetch_products_for_gender(self, gender):
        """Fetch all products for a given gender using Parallel Requests."""
        products = {}
        
        logger.info(f"Started fetching products for: {gender}")
        
        # 1. Fetch Page 1 to get metadata (Total Pages)
        first_page_data = self.fetch_page(1, gender)
        if not first_page_data:
            logger.error(f"Failed to fetch Page 1 for {gender}")
            return {}

        total_pages = 1
        if 'pagination' in first_page_data:
            total_pages = first_page_data['pagination'].get('totalPages', 1)
        
        logger.info(f"Gender {gender}: Found {total_pages} total pages.")
        
        # Process Page 1
        if 'products' in first_page_data:
            for p in first_page_data['products']:
                self._parse_product(p, products, gender)

        # 2. Parallel Fetch for remaining pages
        if total_pages > 1:
            pages_to_fetch = list(range(2, total_pages + 1))
            
            # 5 threads for pages is safe
            with ThreadPoolExecutor(max_workers=5) as executor: 
                future_to_page = {executor.submit(self.fetch_page, p, gender): p for p in pages_to_fetch}
                
                for future in as_completed(future_to_page):
                    page_num = future_to_page[future]
                    data = future.result()
                    
                    if data and 'products' in data:
                        count = len(data['products'])
                        logger.info(f"  Page {page_num}: Found {count} products.")
                        for p in data['products']:
                            self._parse_product(p, products, gender)
                    else:
                        # If we failed (likely 403 inside fetch_page), we should probably slow down global execution
                        # but inside threads it's hard. We just log and continue.
                        pass # Ignore empty/failed pages
        
        return products

    def verify_stock(self, product_code):
        """
        Verify stock status by fetching the product detail page.
        """
        url = f"{SHEIN_BASE_URL}/p/{product_code}"
        try:
            resp = self.session.get(url, timeout=TIMEOUT_SECONDS, impersonate=self.impersonation)
            
            if resp.status_code == 200:
                # Regex to find the JSON state
                match = re.search(r'window\.__PRELOADED_STATE__\s*=\s*(\{.*?\});', resp.text, re.DOTALL)
                if match:
                    try:
                        state = json.loads(match.group(1))
                        if 'product' in state and 'productDetails' in state['product']:
                            details = state['product']['productDetails']
                            variants = details.get('variantOptions', [])
                            
                            in_stock_sizes = []
                            for v in variants:
                                qty = v.get('stock', {}).get('stockLevel', 0)
                                status = v.get('stock', {}).get('stockLevelStatus', 'outOfStock')
                                
                                # Get Size Label
                                size_label = "Unknown"
                                for q in v.get('variantOptionQualifiers', []):
                                    if q.get('qualifier') == 'size':
                                        size_label = q.get('value')
                                        break
                                
                                # Check for In Stock status OR quantity
                                if qty > 0:
                                    in_stock_sizes.append(f"{size_label} ({qty})")
                                elif status == 'inStock':
                                    in_stock_sizes.append(f"{size_label} (In Stock)")
                            
                            if in_stock_sizes:
                                return True, ", ".join(in_stock_sizes)
                            else:
                                return False, "Out of Stock"
                        else:
                            # Fallback if structure is different
                            if '"stockLevelStatus":"inStock"' in resp.text:
                                return False, "Structure Mismatch (OOS Safety)"
                            return False, "Structure Mismatch"
                    except json.JSONDecodeError:
                        logger.error(f"JSON Parse Error for {product_code}")
                # Regex failed
                return False, "No Data"
            
            elif resp.status_code == 403:
                logger.warning(f"403 Forbidden checking stock for {product_code}")
                return None, "403" # Special value to indicate retry/backoff
            
            else:
                return False, f"HTTP {resp.status_code}"
                
        except Exception as e:
            logger.error(f"Exception checking stock {product_code}: {e}")
            return False, "Error"

    def run(self):
        """Main Loop."""
        logger.info("🚀 Starting Shein Dynamic Monitor (Optimized + HTML)")
        self.running = True # Ensure running is True when called explicitly
        self.send_telegram_message("🚀 Monitor Started (Optimized + HTML) - Men Channel")
        self.send_telegram_message("🚀 Monitor Started (Optimized + HTML) - Women Channel", gender="Women")
        
        cycle = 0
        last_reset_date = None
        
        while self.running:
            # --- Daily 7 AM Reset Logic ---
            try:
                ist_tz = pytz.timezone('Asia/Kolkata')
                now_ist = datetime.now(ist_tz)
                
                # Check if it is 7 AM (or slightly after) and we haven't reset today
                if now_ist.hour == 7 and now_ist.date() != last_reset_date:
                    logger.info("🌅 7 AM Detected! Clearing state to force daily alerts...")
                    self.send_telegram_message("🌅 <b>Good Morning!</b>\nStarting daily stock check... You will receive alerts for ALL in-stock items now.")
                    self.send_telegram_message("🌅 <b>Good Morning!</b>\nStarting daily stock check... You will receive alerts for ALL in-stock items now.", gender="Women")
                    
                    self.stock_state = {} # Clear state
                    self.save_state()     # Save empty state
                    last_reset_date = now_ist.date()
            except Exception as e:
                logger.error(f"Error in daily reset check: {e}")
            
            cycle += 1
            start_time = time.time()
            logger.info(f"--- Cycle {cycle} ---")
            
            # 1. Discovery Phase (Parallel)
            all_found_products = {}
            for gender in MONITORED_GENDERS:
                prods = self.fetch_products_for_gender(gender)
                # Ensure unique codes and strip whitespace
                for k, v in prods.items():
                    clean_code = str(k).strip()
                    all_found_products[clean_code] = v
            
            logger.info(f"Discovery complete. Found {len(all_found_products)} total products.")
            
            if not all_found_products:
                logger.warning("No products found! Check API or Network.")
                time.sleep(60)
                continue

            # 2. Verification Phase (Parallel)
            with ThreadPoolExecutor(max_workers=MAX_THREADS) as executor:
                # Submit all checks
                future_to_code = {
                    executor.submit(self.verify_stock, p['code']): p['code'] 
                    for p in all_found_products.values()
                }
                
                processed_codes_this_cycle = set()

                for future in as_completed(future_to_code):
                    raw_code = future_to_code[future]
                    code = str(raw_code).strip()
                    
                    if code in processed_codes_this_cycle:
                        continue
                    processed_codes_this_cycle.add(code)

                    product = all_found_products[raw_code]
                    
                    try:
                        is_in_stock, stock_details = future.result()
                        
                        if is_in_stock is None: 
                            continue
                            
                        prev_state = self.stock_state.get(code, {}).get('in_stock', False)
                        
                        if is_in_stock:
                            if not prev_state:
                                logger.info(f"🎉 RESTOCK/NEW: {product['name']} - {stock_details}")
                                
                                # HTML Escaping for Text Fields
                                def escape_html(text):
                                    return str(text).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

                                safe_name = escape_html(product['name'])
                                safe_mrp = escape_html(product['price'])
                                safe_sizes = escape_html(stock_details)
                                
                                msg = (
                                    f"🎉 <b>IN STOCK</b>\n\n"
                                    f"📦 <b>{safe_name}</b>\n"
                                    f"💰 MRP: {safe_mrp}\n"
                                    f"📏 Sizes: {safe_sizes}\n"
                                    f"🔗 <a href='{product['url']}'>{product['url']}</a>"
                                )
                                # Send!
                                if self.send_telegram_message(msg, product['image'], gender=product.get('category')):
                                    self.stock_state[code] = {'in_stock': True, 'details': stock_details}
                                    self.save_state()
                            else:
                                pass
                        else:
                            if prev_state:
                                logger.info(f"❌ OOS: {product['name']}")
                                logger.info(f"❌ OOS: {product['name']}")
                                self.stock_state[code] = {'in_stock': False}
                                self.save_state()
                                
                    except Exception as e:
                        logger.error(f"Error processing future for {code}: {e}")

            elapsed = time.time() - start_time
            sleep_time = random.uniform(*CYCLE_DELAY_RANGE)
            logger.info(f"Cycle finished in {elapsed:.2f}s. Sleeping {sleep_time:.2f}s...")
            time.sleep(sleep_time)

if __name__ == "__main__":
    monitor = SheinMonitor()
    monitor.run()
