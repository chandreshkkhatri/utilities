import os
import csv
import time
import re
import requests
from datetime import datetime, timedelta
from playwright.sync_api import sync_playwright
from dotenv import load_dotenv

from telegram_bot import HouseHuntingBot, QuotaExceededError


class FacebookGroupScraper:
    def __init__(self):
        self.bot = HouseHuntingBot()
        self.playwright = None
        self.context = None
        self.page = None
        self.posts_processed = 0
        self.group_dir = 'results'

    def get_safe_group_dir_name(self, group_url_or_name: str) -> str:
        """Derive a safe directory name from a Facebook group URL or name."""
        url = group_url_or_name.rstrip('/')
        if 'facebook.com/groups/' in url:
            parts = url.split('facebook.com/groups/')
            if len(parts) > 1:
                group_name = parts[1].split('/')[0].split('?')[0]
                return ''.join(c for c in group_name if c.isalnum() or c in ['-', '_'])
        clean_name = re.sub(r'[^a-zA-Z0-9_\-]', '_', group_url_or_name.strip())
        return re.sub(r'_+', '_', clean_name).lower()

    def choose_group_dir_interactively(self) -> Optional[str]:
        """Find directories in results/ containing facebook_raw_posts.json and ask user to choose."""
        if not os.path.exists('results'):
            return None
            
        choices = []
        for entry in os.listdir('results'):
            full_path = os.path.join('results', entry)
            if os.path.isdir(full_path):
                raw_json = os.path.join(full_path, 'facebook_raw_posts.json')
                if os.path.exists(raw_json):
                    choices.append(entry)
                    
        if not choices:
            return None
            
        if len(choices) == 1:
            print(f"📁 Automatically selected only available group cache: '{choices[0]}'")
            return os.path.join('results', choices[0])
            
        print("\n📂 Select group cache directory to analyze:")
        for idx, choice in enumerate(choices):
            print(f"{idx+1}. {choice}")
            
        selected_idx = -1
        while selected_idx < 0 or selected_idx >= len(choices):
            try:
                ans = input(f"Enter choice (1-{len(choices)}): ").strip()
                selected_idx = int(ans) - 1
            except ValueError:
                pass
        return os.path.join('results', choices[selected_idx])

    def setup_playwright(self):
        """Setup Playwright Chrome instance with Facebook-optimized settings."""
        load_dotenv()

        self.playwright = sync_playwright().start()

        # Use existing Chrome profile if specified
        chrome_data_dir = os.getenv('CHROME_USER_DATA_DIR')
        user_data_path = chrome_data_dir if chrome_data_dir else "./results/profiles/facebook"

        try:
            self.context = self.playwright.chromium.launch_persistent_context(
                user_data_dir=user_data_path,
                headless=False,
                channel="chrome",
                args=["--disable-blink-features=AutomationControlled"],
                ignore_default_args=["--no-sandbox"]
            )
            self.page = self.context.pages[0] if self.context.pages else self.context.new_page()
        except Exception as e:
            print(f"⚠️ Could not launch Chrome with configured profile: {e}")
            print("Launching standard Chrome instance instead...")
            self.browser = self.playwright.chromium.launch(
                headless=False,
                channel="chrome",
                ignore_default_args=["--no-sandbox"]
            )
            self.context = self.browser.new_context()
            self.page = self.context.new_page()

    def login_to_facebook(self):
        """Navigate to Facebook and wait for manual login."""
        print("🌐 Opening Facebook...")
        self.page.goto("https://www.facebook.com")

        # Check if already logged in
        try:
            self.page.wait_for_selector("[data-testid='home-icon']", timeout=10000)
            print("✅ Already logged in to Facebook")
            return True
        except:
            pass

        print("🔐 Please log in to Facebook manually in the browser window")
        print("⏳ Waiting for login completion...")

        # Wait for login completion (home feed or profile icon)
        try:
            self.page.wait_for_selector("[data-testid='home-icon'], [aria-label='Facebook']", timeout=300000)
            print("✅ Successfully logged in to Facebook")
            return True
        except:
            print("❌ Login timeout. Please try again.")
            return False

    def navigate_to_group(self, group_url_or_name):
        """Navigate to the specified Facebook group."""
        if group_url_or_name.startswith('http'):
            self.page.goto(group_url_or_name)
        else:
            # Search for group by name
            search_url = f"https://www.facebook.com/search/groups/?q={group_url_or_name}"
            self.page.goto(search_url)

            # Wait for search results and click first group
            try:
                first_group_selector = "[role='article'] a"
                self.page.wait_for_selector(first_group_selector, timeout=15000)
                self.page.click(first_group_selector)
            except Exception as e:
                print(f"❌ Could not find group: {group_url_or_name}: {e}")
                return False

        # Wait for group page to load
        try:
            self.page.wait_for_selector("[role='main']", timeout=15000)
            print(f"✅ Successfully navigated to group")
            return True
        except:
            print("❌ Group page failed to load")
            return False

    def scroll_and_load_posts(self, max_posts=50, max_scroll_time=300):
        """Scroll through the group feed to load posts using fast locator count."""
        print(f"🔄 Loading posts (max {max_posts} posts, {max_scroll_time}s timeout)")

        start_time = time.time()
        post_selector = "div.x1a2a7pz[aria-posinset]"
        
        # Fast element counting
        posts_count = self.page.locator(post_selector).count()

        while posts_count < max_posts and (time.time() - start_time) < max_scroll_time:
            # Scroll down
            self.page.evaluate("window.scrollTo(0, document.body.scrollHeight)")

            # Wait for new content to load
            self.page.wait_for_timeout(2000)

            # Get new count
            posts_count = self.page.locator(post_selector).count()

        print(f"📊 Found {posts_count} posts loaded in DOM")
        return posts_count

    def extract_post_data(self, post_element):
        """Extract text and metadata from a Facebook post Locator."""
        try:
            # Expand 'See more' links within the post
            try:
                buttons_locator = post_element.locator("[role='button']:has-text('See more'), [role='button']:has-text('See More')")
                buttons_count = buttons_locator.count()
                for i in range(buttons_count):
                    try:
                        buttons_locator.nth(i).click(timeout=1000)
                    except:
                        pass
            except:
                pass

            # Extract post text - trying multiple selectors for different Facebook layouts
            text_selectors = [
                "[data-ad-preview='message']",
                "[data-testid='post_message']",
                ".userContent",
                "[data-ad-comet-preview='message']",
                "[data-testid='post-message']",
                "div[dir='auto'] span",
                ".x11i5rnm.xat24cr.x1mh8g0r"
            ]

            post_text = ""
            for selector in text_selectors:
                try:
                    locator = post_element.locator(selector)
                    count = locator.count()
                    for i in range(count):
                        text = locator.nth(i).inner_text().strip()
                        if text and len(text) > len(post_text):
                            post_text = text
                except:
                    continue

            if not post_text:
                return None

            # Try to extract timestamp
            timestamp = datetime.now()

            try:
                time_selectors = [
                    "[data-testid='story-subtitle'] a",
                    "time",
                    "a[role='link'][tabindex='0']",
                    ".x1i10hfl.xjbqb8w"
                ]

                for selector in time_selectors:
                    time_locator = post_element.locator(selector)
                    count = time_locator.count()
                    found = False
                    for i in range(count):
                        elem = time_locator.nth(i)
                        time_text = elem.get_attribute('title') or elem.get_attribute('aria-label') or elem.inner_text()
                        if time_text and any(word in time_text.lower() for word in ['ago', 'at', 'yesterday', 'hour', 'min']):
                            timestamp = self.parse_facebook_time(time_text)
                            found = True
                            break
                    if found:
                        break
            except Exception as e:
                print(f"⚠️ Error extracting timestamp: {e}")

            # Get post URL
            post_url = ''
            try:
                time_elem = post_element.locator('time')
                if time_elem.count() > 0:
                    parent_link = time_elem.locator("xpath=./ancestor::a")
                    if parent_link.count() > 0:
                        post_url = parent_link.first.get_attribute('href')
            except:
                pass
            if not post_url:
                try:
                    link_locator = post_element.locator("a[href*='/posts/'], a[href*='/permalink/'], a[href*='story.php']")
                    if link_locator.count() > 0:
                        post_url = link_locator.first.get_attribute('href')
                except:
                    pass
            post_url = self.normalize_post_url(post_url)

            # Get element HTML for raw storage
            raw_html = ""
            try:
                raw_html = post_element.inner_html()
            except:
                pass

            return {
                'text': post_text,
                'timestamp': timestamp,
                'raw_html': raw_html[:500],
                'post_url': post_url
            }

        except Exception as e:
            print(f"⚠️ Error extracting post data: {e}")
            return None

    def parse_facebook_time(self, time_text):
        """Parse Facebook's various time formats."""
        try:
            now = datetime.now()
            time_text = time_text.lower()

            if 'min' in time_text:
                minutes = int(re.search(r'(\d+)', time_text).group(1))
                return now - timedelta(minutes=minutes)
            elif 'hour' in time_text or 'hr' in time_text or time_text.endswith('h'):
                hours = int(re.search(r'(\d+)', time_text).group(1))
                return now - timedelta(hours=hours)
            elif 'yesterday' in time_text:
                return now - timedelta(days=1)
            elif 'day' in time_text:
                days = int(re.search(r'(\d+)', time_text).group(1))
                return now - timedelta(days=days)
            else:
                try:
                    return datetime.strptime(time_text, "%B %d at %I:%M %p")
                except:
                    return now
        except:
            return datetime.now()

    def skip_based_on_preference(self, text: str) -> bool:
        """Deprecated preference filter. We now extract structured enums instead of skipping."""
        return False

    def log_ingestion(self, message: str):
        """Append a message to facebook_ingestion_log.txt inside the group's directory."""
        os.makedirs(self.group_dir, exist_ok=True)
        log_path = os.path.join(self.group_dir, 'facebook_ingestion_log.txt')
        with open(log_path, 'a', encoding='utf-8') as f:
            f.write(message + '\n')

    def is_rental_post(self, text: str) -> bool:
        """Use LLM or keyword-based fallback to determine if post is about renting property."""
        try:
            prompt = (
                f"Determine if this Facebook post is about renting residential property. "
                f"Reply YES or NO.\nText: '''{text}'''"
            )
            response = self.bot.call_llm(
                prompt=prompt,
                system_instruction="Reply with only YES or NO. Do not add any introduction or explanations.",
                temperature=0.0,
                max_tokens=1024
            )
            if response:
                answer = response.strip().lower()
                return "yes" in answer
        except Exception:
            pass
        # Fallback to simple keyword check
        keywords = ['rent', 'for rent', 'room for rent',
                    'apartment for rent', 'flat for rent', 'house for rent']
        text_lower = text.lower()
        return any(k in text_lower for k in keywords)

    def process_group_posts_via_api(self, group_id: str, access_token: str, max_posts: int = 50) -> bool:
        """Fetch and process Facebook group posts directly using the Graph API."""
        print("🏠 Facebook Group House Hunting Started (Graph API Mode)")
        print(f"📍 Office Location: {self.bot.office_address}")
        print(f"👥 Target Group ID: {group_id}")
        print("-" * 50)

        # Load existing results to prevent duplicates
        self.bot.load_existing_results('facebook_results.json')
        processed_ids = {r.get('message_id') for r in self.bot.results if r.get('message_id')}
        processed_urls = {r.get('post_url') for r in self.bot.results if r.get('post_url')}

        # Initialize results files & directories
        os.makedirs('results', exist_ok=True)
        res_master = 'results/facebook_results.csv'
        file_exists = os.path.exists(res_master) and os.path.getsize(res_master) > 0
        if not file_exists:
            with open(res_master, 'w', newline='', encoding='utf-8') as rf:
                writer = csv.writer(rf)
                writer.writerow([
                    'message_id', 'date', 'location', 'city', 'rent', 'bhk',
                    'gender_preference', 'furnishing_status',
                    'additional_details', 'latitude', 'longitude',
                    'distance_from_office_km', 'driving_duration', 'post_url',
                    'source', 'group_name'
                ])

        api_url = f"https://graph.facebook.com/v25.0/{group_id}/feed"
        params = {
            'fields': 'id,message,created_time,permalink_url',
            'access_token': access_token,
            'limit': min(100, max_posts)
        }

        posts_fetched = 0
        found_properties = 0

        while api_url and posts_fetched < max_posts:
            try:
                if params:
                    response = requests.get(api_url, params=params, timeout=15)
                    params = {}
                else:
                    response = requests.get(api_url, timeout=15)

                if response.status_code != 200:
                    print(f"❌ Facebook Graph API returned error code {response.status_code}")
                    try:
                        err_detail = response.json()
                        print(f"Error detail: {err_detail}")
                    except Exception:
                        print(f"Response: {response.text}")
                    return False

                resp_data = response.json()
                data_list = resp_data.get('data', [])
                if not data_list:
                    print("📄 No more posts returned from the Graph API.")
                    break

                batch_results = []
                for post in data_list:
                    if posts_fetched >= max_posts:
                        break
                    
                    post_id = post.get('id')
                    post_url = post.get('permalink_url', f"https://www.facebook.com/groups/{group_id}/posts/{post_id}/")

                    # Skip already processed posts
                    if post_id in processed_ids or post_url in processed_urls:
                        print(f"⏭️ Skipping already processed post (API): {post_id}")
                        continue

                    posts_fetched += 1
                    message_text = post.get('message', '')
                    created_time = post.get('created_time')

                    if not message_text:
                        continue

                    is_rental = self.is_rental_post(message_text)
                    
                    log_entry = (
                        f"=== Post ID: {post_id} (API Mode) ===\n"
                        f"URL: {post_url}\n"
                        f"Text Preview: {message_text[:300]}...\n"
                        f"Is Rental Post: {is_rental}\n"
                    )

                    if not is_rental:
                        log_entry += "Result: SKIPPED (Not classified as rental post)\n\n"
                        self.log_ingestion(log_entry)
                        continue

                    timestamp = datetime.now()
                    if created_time:
                        try:
                            timestamp = datetime.strptime(created_time, "%Y-%m-%dT%H:%M:%S%z")
                        except Exception:
                            pass

                    raw_data = {
                        'message_id': post_id,
                        'text': message_text,
                        'timestamp': timestamp,
                        'post_url': post_url
                    }
                    
                    result = self.process_raw_data(raw_data)
                    if result:
                        log_entry += (
                            f"Result: PROCESSED\n"
                            f"  Location: {result.get('location')}\n"
                            f"  City: {result.get('city')}\n"
                            f"  Rent: {result.get('rent')}\n"
                            f"  BHK: {result.get('bhk')}\n"
                            f"  Gender Preference: {result.get('gender_preference')}\n"
                            f"  Furnishing Status: {result.get('furnishing_status')}\n"
                            f"  Distance: {result.get('distance_from_office_km')} km\n\n"
                        )
                        self.log_ingestion(log_entry)
                        
                        result.update({'group_name': group_id})
                        batch_results.append(result)
                        self.bot.results.append(result)
                        found_properties += 1
                        print(f"🏡 Found property #{found_properties}: {result['location']} - {result['distance_from_office_km']}km from office")
                    else:
                        log_entry += "Result: SKIPPED (AI extraction failed or empty location)\n\n"
                        self.log_ingestion(log_entry)

                if batch_results:
                    with open(res_master, 'a', newline='', encoding='utf-8') as rf:
                        writer = csv.writer(rf)
                        for result in batch_results:
                            writer.writerow([
                                result['message_id'], result['date'], result['location'],
                                result.get('city', ''), result.get('rent', ''),
                                result.get('bhk', ''), 
                                result.get('gender_preference', 'any'),
                                result.get('furnishing_status', 'unfurnished'),
                                result.get('additional_details', ''),
                                result['latitude'], result['longitude'],
                                result['distance_from_office_km'], result['driving_duration'],
                                result['post_url'], result['source'], result['group_name']
                            ])

                self.bot.save_results('facebook_results.json')
                api_url = resp_data.get('paging', {}).get('next')

            except QuotaExceededError as qe:
                print(f"\n🛑 LLM Quota Exceeded during Graph API processing: {qe}")
                return False
            except Exception as e:
                print(f"❌ Error during Facebook Graph API request: {e}")
                return False

        print(f"✅ API Ingestion done. Fetched {posts_fetched} posts, found {found_properties} properties.")
        return True

    def process_group_posts(self, group_url_or_name, max_posts=50, scrape_only=False):
        """Main method to scrape and process Facebook group posts in batches with aggregated CSV outputs."""
        safe_name = self.get_safe_group_dir_name(group_url_or_name)
        self.group_dir = os.path.join('results', safe_name)
        os.makedirs(os.path.join(self.group_dir, 'html'), exist_ok=True)
        
        print("🏠 Facebook Group House Hunting Started")
        print(f"📍 Office Location: {self.bot.office_address}")
        print(f"👥 Target Group: {group_url_or_name}")
        print(f"📁 Saving to directory: {self.group_dir}")
        print("-" * 50)

        # Load existing raw posts cache
        existing_raw_posts = self.load_raw_posts()
        raw_posts_dict = {p.get('post_url'): p for p in existing_raw_posts if p.get('post_url')}

        try:
            self.setup_playwright()
            if not self.login_to_facebook():
                return
            if not self.navigate_to_group(group_url_or_name):
                return

            # Switch to "New listings" feed
            try:
                sort_menu = self.page.locator("[aria-label='Sort group posts']")
                sort_menu.wait_for(timeout=10000)
                sort_menu.click()
                
                new_btn = self.page.locator("//span[text()='New listings']")
                new_btn.wait_for(timeout=5000)
                new_btn.click()
                print("🔄 Switched to New listings feed")
                self.page.wait_for_timeout(2000)
            except Exception as e:
                print(f"⚠️ Could not switch feed to New listings: {e}")

            # Load existing results to prevent duplicates
            self.bot.load_existing_results(f'{safe_name}/facebook_house_hunting_results.json')
            processed_urls = {r.get('post_url') for r in self.bot.results if r.get('post_url')}

            # Initialize aggregated results CSV
            res_master = os.path.join(self.group_dir, 'facebook_results.csv')
            file_exists = os.path.exists(res_master) and os.path.getsize(res_master) > 0
            if not file_exists:
                with open(res_master, 'w', newline='', encoding='utf-8') as rf:
                    writer = csv.writer(rf)
                    writer.writerow([
                        'message_id', 'date', 'location', 'city', 'rent', 'bhk',
                        'gender_preference', 'furnishing_status',
                        'additional_details', 'latitude', 'longitude',
                        'distance_from_office_km', 'driving_duration', 'post_url',
                        'source', 'group_name'
                    ])

            processed_in_run = set()
            start_time = time.time()
            max_scroll_time = 300
            post_selector = "div.x1a2a7pz[aria-posinset]:not([data-processed='true'])"
            scroll_retries = 0

            while self.posts_processed < max_posts and (time.time() - start_time) < max_scroll_time:
                # Count current posts in DOM
                post_locator = self.page.locator(post_selector)
                current_count = post_locator.count()

                # Scan the DOM for unprocessed posts
                new_elements_in_dom = []
                for idx in range(current_count):
                    post = post_locator.nth(idx)
                    try:
                        cls = post.get_attribute('class') or ''
                        if 'x1a2a7pz' not in cls:
                            continue
                    except:
                        continue

                    # Try to check post URL before scrolling to avoid unnecessary clicks/viewport resets
                    post_url = ""
                    try:
                        time_elem = post.locator('time')
                        if time_elem.count() > 0:
                            parent_link = time_elem.locator("xpath=./ancestor::a")
                            if parent_link.count() > 0:
                                post_url = parent_link.first.get_attribute('href')
                    except:
                        pass
                    if not post_url:
                        try:
                            link_locator = post.locator("a[href*='/posts/'], a[href*='/permalink/'], a[href*='story.php']")
                            if link_locator.count() > 0:
                                post_url = link_locator.first.get_attribute('href')
                        except:
                            pass
                    post_url = self.normalize_post_url(post_url)

                    # Skip if we already processed this URL in this run or historically
                    if post_url and (post_url in processed_urls or post_url in processed_in_run):
                        continue

                    new_elements_in_dom.append((idx, post, post_url))

                if not new_elements_in_dom:
                    # Scroll to trigger loading more posts
                    print("🔄 Scrolling down to load more posts...")
                    self.page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                    self.page.wait_for_timeout(3000)

                    new_count = post_locator.count()
                    if new_count <= current_count:
                        scroll_retries += 1
                        if scroll_retries >= 3:
                            print("📄 No new posts loaded after 3 scrolls. Ending scraper.")
                            break
                    else:
                        scroll_retries = 0
                    continue

                # Reset scroll retries as we found new elements
                scroll_retries = 0

                # Process in small batches of 10
                batch_limit = min(10, len(new_elements_in_dom))
                target_elements = new_elements_in_dom[:batch_limit]

                raw_file = os.path.join(self.group_dir, f"facebook_raw_{self.posts_processed+1}_{self.posts_processed + batch_limit}.csv")
                try:
                    with open(raw_file, 'w', newline='', encoding='utf-8') as rf:
                        writer = csv.writer(rf)
                        writer.writerow(
                            ['message_id', 'text', 'timestamp', 'post_url'])
                        raw_data_list = []
                        for idx_in_dom, post, post_url in target_elements:
                            try:
                                # Scroll this specific post into view to force rendering of DOM text structure
                                post.scroll_into_view_if_needed(timeout=2000)
                                self.page.wait_for_timeout(500)  # Brief pause to let rendering complete
                                post.evaluate("el => el.setAttribute('data-processed', 'true')")
                            except Exception as e:
                                print(f"⚠️ Error preparing element: {e}")
                                continue

                            html_path = os.path.join(self.group_dir, 'html', f"fb_post_{self.posts_processed + len(raw_data_list) + 1}.html")
                            self.save_post_html(post, html_path)

                            data = self.extract_post_data(post) or {}
                            data['message_id'] = f"fb_post_{self.posts_processed + len(raw_data_list) + 1}"
                            data['html_file'] = html_path
                            if not data.get('post_url') and post_url:
                                data['post_url'] = post_url

                            text = ' '.join(data.get('text', '').split())
                            raw_data_list.append(data)
                            writer.writerow([data['message_id'], text, data.get(
                                'timestamp', ''), data.get('post_url', '')])
                    print(f"🔖 Raw batch saved to {raw_file}")

                    batch_results = []
                    for data in raw_data_list:
                        post_url = data.get('post_url')
                        text = ' '.join(data.get('text', '').split())

                        # Unique signature matching: use URL if present, otherwise hash the alphanumeric text snippet
                        signature = post_url if post_url else f"hash_{hash(''.join(e for e in text if e.isalnum()).lower()[:100])}"

                        if signature in processed_in_run or (post_url and post_url in processed_urls):
                            print(f"⏭️ Skipping already processed post (signature): {signature}")
                            continue

                        processed_in_run.add(signature)

                        if not text:
                            # Log empty posts explicitly to know they were parsed but returned blank
                            log_entry = (
                                f"=== Post ID: {data['message_id']} (Scraper Mode) ===\n"
                                f"URL: {post_url or 'N/A'}\n"
                                f"Text Preview: (Empty/Could not extract text)\n"
                                f"Result: SKIPPED (Empty text)\n\n"
                            )
                            self.log_ingestion(log_entry)
                            continue

                        # If scrape_only, collect the raw post data, save it to cache, and proceed
                        if scrape_only:
                            if not post_url or post_url not in raw_posts_dict:
                                raw_entry = {
                                    'message_id': data['message_id'],
                                    'text': text,
                                    'timestamp': str(data.get('timestamp') or datetime.now()),
                                    'post_url': post_url,
                                    'html_file': data.get('html_file', ''),
                                    'group_name': group_url_or_name
                                }
                                existing_raw_posts.append(raw_entry)
                                if post_url:
                                    raw_posts_dict[post_url] = raw_entry
                                print(f"📝 Scraped raw post: {data['message_id']} - URL: {post_url or 'N/A'}")
                            continue

                        is_rental = self.is_rental_post(text)
                        
                        log_entry = (
                            f"=== Post ID: {data['message_id']} (Scraper Mode) ===\n"
                            f"URL: {post_url or 'N/A'}\n"
                            f"Text Preview: {text[:300]}...\n"
                            f"Is Rental Post: {is_rental}\n"
                        )

                        if not is_rental:
                            log_entry += "Result: SKIPPED (Not classified as rental post)\n\n"
                            self.log_ingestion(log_entry)
                            continue

                        result = self.process_raw_data(data)
                        if result:
                            log_entry += (
                                f"Result: PROCESSED\n"
                                f"  Location: {result.get('location')}\n"
                                f"  City: {result.get('city')}\n"
                                f"  Rent: {result.get('rent')}\n"
                                f"  BHK: {result.get('bhk')}\n"
                                f"  Gender Preference: {result.get('gender_preference')}\n"
                                f"  Furnishing Status: {result.get('furnishing_status')}\n"
                                f"  Distance: {result.get('distance_from_office_km')} km\n\n"
                            )
                            self.log_ingestion(log_entry)
                            
                            result.update({'group_name': group_url_or_name})
                            batch_results.append(result)
                            self.bot.results.append(result)
                            if post_url:
                                processed_urls.add(post_url)
                            print(
                                f"🏡 Found property: {result['location']} - {result['distance_from_office_km']}km from office")
                        else:
                            log_entry += "Result: SKIPPED (AI extraction failed or empty location)\n\n"
                            self.log_ingestion(log_entry)

                    if batch_results:
                        with open(res_master, 'a', newline='', encoding='utf-8') as rf:
                            writer = csv.writer(rf)
                            for result in batch_results:
                                writer.writerow([
                                    result['message_id'], result['date'], result['location'],
                                    result.get('city', ''), result.get('rent', ''),
                                    result.get('bhk', ''),
                                    result.get('gender_preference', 'any'),
                                    result.get('furnishing_status', 'unfurnished'),
                                    result.get('additional_details', ''),
                                    result['latitude'], result['longitude'],
                                    result['distance_from_office_km'], result['driving_duration'],
                                    result['post_url'], result['source'], result['group_name']
                                ])
                except QuotaExceededError as qe:
                    print(f"\n🛑 LLM Quota Exceeded during Facebook processing: {qe}")
                    print("Stopping Facebook scraping and saving current progress...")
                    break

                self.posts_processed += len(raw_data_list)
                if scrape_only:
                    self.save_raw_posts(existing_raw_posts)
                else:
                    safe_name = os.path.basename(self.group_dir)
                    self.bot.save_results(f'{safe_name}/facebook_results.json')
                
                # Scroll once at the end of the batch to push feed down and load new elements
                self.page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                self.page.wait_for_timeout(1000)

            print(f"✅ All done. Processed {self.posts_processed} posts")

        except Exception as e:
            print(f"❌ Error during Facebook scraping: {e}")
        finally:
            if hasattr(self, 'context') and self.context:
                self.context.close()
            if hasattr(self, 'playwright') and self.playwright:
                self.playwright.stop()

    def save_results(self, filename_prefix="facebook_house_hunting"):
        """Save results using the HouseHuntingBot methods inside self.group_dir."""
        safe_name = os.path.basename(self.group_dir)
        if self.bot.results:
            self.bot.save_results(f'{safe_name}/{filename_prefix}_results.json')
            self.bot.save_results_to_csv(f'{safe_name}/{filename_prefix}_results.csv')
            self.bot.display_results(sort_by_distance=True)
        else:
            print("❌ No results to save")

    def normalize_post_url(self, url: str) -> str:
        """Normalize Facebook post URL to canonical group post link format."""
        if not url:
            return url
        m = re.search(r"(https://www\.facebook\.com/groups/[^/]+/posts/\d+)", url)
        if m:
            return m.group(1) + '/'
        m2 = re.search(r"story\.php\?story_fbid=(\d+)&id=(\d+)", url)
        if m2:
            post_id, group_id = m2.group(1), m2.group(2)
            return f"https://www.facebook.com/groups/{group_id}/posts/{post_id}/"
        return url

    def save_post_html(self, post_element, file_path):
        """Save HTML of a post element to a file."""
        os.makedirs(os.path.dirname(file_path), exist_ok=True)
        try:
            html = post_element.inner_html()
            with open(file_path, 'w', encoding='utf-8') as f:
                f.write(html)
        except Exception as e:
            print(f"⚠️ Error saving post HTML: {e}")

    def process_raw_data(self, raw_data):
        """Process raw data dict to extract fields important to us."""
        timestamp = raw_data.get('timestamp')
        if isinstance(timestamp, str):
            try:
                t_str = timestamp.strip()
                if ' ' in t_str:
                    if '.' in t_str:
                        timestamp = datetime.strptime(t_str, "%Y-%m-%d %H:%M:%S.%f")
                    else:
                        timestamp = datetime.strptime(t_str, "%Y-%m-%d %H:%M:%S")
                else:
                    timestamp = datetime.fromisoformat(t_str)
            except Exception as e:
                print(f"⚠️ Failed to parse timestamp '{timestamp}': {e}. Using current time.")
                timestamp = datetime.now()
        elif not timestamp:
            timestamp = datetime.now()

        message = type('FacebookPost', (), {
            'text': raw_data.get('text', ''),
            'date': timestamp,
            'id': raw_data.get('message_id')
        })()
        result = self.bot.process_message(message)
        if result:
            result.update({
                'post_url': raw_data.get('post_url', ''),
                'source': 'facebook_group'
            })
        return result

    def load_raw_posts(self) -> list:
        """Load raw posts from facebook_raw_posts.json inside self.group_dir."""
        filepath = os.path.join(self.group_dir, 'facebook_raw_posts.json')
        if os.path.exists(filepath):
            try:
                import json
                with open(filepath, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except Exception as e:
                print(f"⚠️ Failed to load raw posts from {filepath}: {e}")
        return []

    def save_raw_posts(self, raw_posts):
        """Save raw posts list to facebook_raw_posts.json inside self.group_dir."""
        os.makedirs(self.group_dir, exist_ok=True)
        filepath = os.path.join(self.group_dir, 'facebook_raw_posts.json')
        try:
            import json
            with open(filepath, 'w', encoding='utf-8') as f:
                json.dump(raw_posts, f, indent=4, ensure_ascii=False)
            print(f"💾 Saved {len(raw_posts)} raw posts to {filepath}")
        except Exception as e:
            print(f"⚠️ Failed to save raw posts to {filepath}: {e}")

    def analyze_scraped_posts(self):
        """Analyze previously scraped posts from results/facebook_raw_posts.json using LLM + Google Maps in parallel."""
        self.group_dir = self.choose_group_dir_interactively()
        if not self.group_dir:
            print("❌ No raw posts found to analyze. Please run the scraper first.")
            return

        safe_name = os.path.basename(self.group_dir)
        print(f"\n🤖 Starting Offline AI Analysis of Scraped Facebook Posts for '{safe_name}'")
        print("=" * 50)
        
        raw_posts = self.load_raw_posts()
        if not raw_posts:
            print("❌ No raw posts found in this directory.")
            return

        self.bot.load_existing_results(f'{safe_name}/facebook_house_hunting_results.json')
        processed_urls = {r.get('post_url') for r in self.bot.results if r.get('post_url')}

        res_master = os.path.join(self.group_dir, 'facebook_results.csv')
        file_exists = os.path.exists(res_master) and os.path.getsize(res_master) > 0
        if not file_exists:
            with open(res_master, 'w', newline='', encoding='utf-8') as rf:
                writer = csv.writer(rf)
                writer.writerow([
                    'message_id', 'date', 'location', 'city', 'rent', 'bhk',
                    'gender_preference', 'furnishing_status',
                    'additional_details', 'latitude', 'longitude',
                    'distance_from_office_km', 'driving_duration', 'post_url',
                    'source', 'group_name'
                ])

        # Filter out posts that are already processed
        posts_to_process = []
        for idx, post in enumerate(raw_posts):
            post_url = post.get('post_url')
            if post_url and post_url in processed_urls:
                continue
            posts_to_process.append((idx + 1, post))

        total_posts = len(raw_posts)
        to_process_count = len(posts_to_process)
        if to_process_count == 0:
            print("✅ All posts have already been analyzed!")
            return

        print(f"📊 Loaded {total_posts} raw posts. {to_process_count} posts need analysis. Processing in parallel...")

        import concurrent.futures
        import threading
        
        write_lock = threading.Lock()
        
        added_count = 0
        processed_count = 0
        quota_exhausted = False

        def process_single_post(item):
            nonlocal added_count, processed_count, quota_exhausted
            if quota_exhausted:
                return

            original_idx, post = item
            post_url = post.get('post_url')
            text = post.get('text', '')
            message_id = post.get('message_id', f"fb_post_{original_idx}")
            group_name = post.get('group_name', 'unknown')

            try:
                is_rental = self.is_rental_post(text)
                
                log_entry = (
                    f"=== Post ID: {message_id} (Analyzer Mode) ===\n"
                    f"URL: {post_url or 'N/A'}\n"
                    f"Text Preview: {text[:300]}...\n"
                    f"Is Rental Post: {is_rental}\n"
                )

                if not is_rental:
                    log_entry += "Result: SKIPPED (Not classified as rental post)\n\n"
                    with write_lock:
                        self.log_ingestion(log_entry)
                        processed_count += 1
                        print(f"🤖 [{processed_count}/{to_process_count}] fb_post_{original_idx} analyzed (skipped - not rental)")
                    return

                # Prepare raw_data dict format matching process_raw_data expectations
                raw_data = {
                    'text': text,
                    'timestamp': post.get('timestamp'),
                    'message_id': message_id,
                    'post_url': post_url
                }

                result = self.process_raw_data(raw_data)
                if result:
                    log_entry += (
                        f"Result: PROCESSED\n"
                        f"  Location: {result.get('location')}\n"
                        f"  City: {result.get('city')}\n"
                        f"  Rent: {result.get('rent')}\n"
                        f"  BHK: {result.get('bhk')}\n"
                        f"  Gender Preference: {result.get('gender_preference')}\n"
                        f"  Furnishing Status: {result.get('furnishing_status')}\n"
                        f"  Distance: {result.get('distance_from_office_km')} km\n\n"
                    )
                    
                    with write_lock:
                        self.log_ingestion(log_entry)
                        result.update({'group_name': group_name})
                        self.bot.results.append(result)
                        if post_url:
                            processed_urls.add(post_url)
                        
                        # Write to final CSV
                        with open(res_master, 'a', newline='', encoding='utf-8') as rf:
                            writer = csv.writer(rf)
                            writer.writerow([
                                result['message_id'], result['date'], result['location'],
                                result.get('city', ''), result.get('rent', ''),
                                result.get('bhk', ''),
                                result.get('gender_preference', 'any'),
                                result.get('furnishing_status', 'unfurnished'),
                                result.get('additional_details', ''),
                                result['latitude'], result['longitude'],
                                result['distance_from_office_km'], result['driving_duration'],
                                result['post_url'], result['source'], result['group_name']
                            ])
                        
                        added_count += 1
                        processed_count += 1
                        print(f"🏡 [{processed_count}/{to_process_count}] Found property: {result['location']} - {result['distance_from_office_km']}km from office")
                else:
                    log_entry += "Result: SKIPPED (AI extraction failed or empty location)\n\n"
                    with write_lock:
                        self.log_ingestion(log_entry)
                        processed_count += 1
                        print(f"🤖 [{processed_count}/{to_process_count}] fb_post_{original_idx} analyzed (skipped - AI extraction failed)")

            except QuotaExceededError as qe:
                with write_lock:
                    if not quota_exhausted:
                        print(f"\n🛑 LLM Quota Exceeded during parallel processing: {qe}")
                        quota_exhausted = True
            except Exception as e:
                with write_lock:
                    processed_count += 1
                    print(f"⚠️ Error processing post {message_id}: {e}")

        # Use 5 parallel workers
        num_workers = 5
        print(f"🧵 Launching {num_workers} parallel workers...")
        try:
            with concurrent.futures.ThreadPoolExecutor(max_workers=num_workers) as executor:
                executor.map(process_single_post, posts_to_process)
        except Exception as ex:
            print(f"⚠️ Thread pool execution error: {ex}")

        self.bot.save_results(f'{safe_name}/facebook_results.json')
        print(f"\n✅ Parallel analysis complete. Processed {processed_count} posts, found {added_count} matching listings.")


def main():
    load_dotenv()

    print("\n📘 Facebook Group House Hunting Options:")
    print("1. 📥 Scrape group posts only (fast, saves raw text offline)")
    print("2. 🤖 Run Offline AI Analysis on previously scraped posts")
    print("3. ⚡ Scrape & Analyze simultaneously (classic mode)")
    
    choice = ""
    while choice not in ['1', '2', '3']:
        choice = input("Enter choice (1-3): ").strip()

    scraper = FacebookGroupScraper()

    if choice == '2':
        scraper.analyze_scraped_posts()
        return

    # API or Playwright choice for scraping modes
    api_token = os.getenv('FB_ACCESS_TOKEN')
    group_id = os.getenv('FB_GROUP_ID')
    max_posts = int(os.getenv('FACEBOOK_MAX_POSTS', '50'))

    # If API token and Group ID are provided, try Graph API mode first
    api_success = False
    if api_token and group_id:
        print("🔑 FB_ACCESS_TOKEN and FB_GROUP_ID found. Attempting Graph API Ingestion...")
        api_success = scraper.process_group_posts_via_api(group_id.strip(), api_token.strip(), max_posts)
        if api_success:
            scraper.save_results()
            return
        else:
            print("⚠️ Graph API ingestion failed or returned errors. Falling back to Playwright browser automation mode...")

    # Fallback to browser automation
    group_target = os.getenv('FACEBOOK_TARGET_GROUP')
    if not group_target:
        group_target = input("Enter Facebook group URL or name: ").strip()

    if not group_target:
        print("❌ No Facebook group specified for Playwright.")
        return

    scrape_only = (choice == '1')
    scraper.process_group_posts(group_target, max_posts, scrape_only=scrape_only)
    if not scrape_only:
        scraper.save_results()


if __name__ == "__main__":
    main()
