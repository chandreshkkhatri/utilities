import os
import csv
import time
import re
import requests
from datetime import datetime, timedelta
from playwright.sync_api import sync_playwright
from dotenv import load_dotenv

from telegram_bot import HouseHuntingBot


class FacebookGroupScraper:
    def __init__(self):
        self.bot = HouseHuntingBot()
        self.playwright = None
        self.context = None
        self.page = None
        self.posts_processed = 0

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
                args=["--disable-blink-features=AutomationControlled"]
            )
            self.page = self.context.pages[0] if self.context.pages else self.context.new_page()
        except Exception as e:
            print(f"⚠️ Could not launch Chrome with configured profile: {e}")
            print("Launching standard Chrome instance instead...")
            self.browser = self.playwright.chromium.launch(headless=False, channel="chrome")
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
        """Scroll through the group feed to load posts."""
        print(f"🔄 Loading posts (max {max_posts} posts, {max_scroll_time}s timeout)")

        start_time = time.time()
        
        # More robust selector for posts
        post_selector = "div.x1a2a7pz[aria-posinset]"
        posts_found = 0

        while posts_found < max_posts and (time.time() - start_time) < max_scroll_time:
            # Scroll down
            self.page.evaluate("window.scrollTo(0, document.body.scrollHeight)")

            # Wait for new content to load
            self.page.wait_for_timeout(2000)

            # Check current number of posts
            try:
                posts = self.page.query_selector_all(post_selector)
                posts_found = len(posts)

                # Try clicking "See More" buttons to load more text
                see_more_buttons = self.page.query_selector_all("//span[contains(text(), 'See more') or contains(text(), 'See More')]")
                for button in see_more_buttons[-3:]:
                    try:
                        button.click()
                        self.page.wait_for_timeout(500)
                    except:
                        pass

            except Exception as e:
                print(f"⚠️ Error counting posts: {e}")
                break

        final_posts = self.page.query_selector_all(post_selector)
        print(f"📊 Found {len(final_posts)} posts to process")
        return final_posts

    def extract_post_data(self, post_element):
        """Extract text and metadata from a Facebook post."""
        try:
            # Expand 'See more' links within the post to reveal full content
            try:
                buttons = post_element.query_selector_all("span:has-text('See more'), span:has-text('See More')")
                for btn in buttons:
                    try:
                        btn.click()
                        self.page.wait_for_timeout(500)
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
                    elements = post_element.query_selector_all(selector)
                    for element in elements:
                        text = element.inner_text().strip()
                        if text and len(text) > len(post_text):
                            post_text = text
                except:
                    continue

            if not post_text:
                return None

            # Try to extract timestamp
            timestamp = datetime.now()  # Default to current time

            try:
                time_selectors = [
                    "[data-testid='story-subtitle'] a",
                    "time",
                    "a[role='link'][tabindex='0']",
                    ".x1i10hfl.xjbqb8w"
                ]

                for selector in time_selectors:
                    time_elements = post_element.query_selector_all(selector)
                    for time_elem in time_elements:
                        time_text = time_elem.get_attribute('title') or time_elem.get_attribute('aria-label') or time_elem.inner_text()
                        if time_text and any(word in time_text.lower() for word in ['ago', 'at', 'yesterday', 'hour', 'min']):
                            timestamp = self.parse_facebook_time(time_text)
                            break
                    if timestamp != datetime.now():
                        break
            except Exception as e:
                print(f"⚠️ Error extracting timestamp: {e}")

            # Get post URL
            post_url = ''
            # First, try to get URL from time element's parent link
            try:
                time_elem = post_element.query_selector('time')
                if time_elem:
                    parent_link = time_elem.evaluate_handle("el => el.closest('a')")
                    if parent_link:
                        post_url = parent_link.json_value().get_attribute('href')
            except:
                pass
            # Fallback to any link matching common post patterns
            if not post_url:
                try:
                    link_elem = post_element.query_selector("a[href*='/posts/'], a[href*='/permalink/'], a[href*='story.php']")
                    if link_elem:
                        post_url = link_elem.get_attribute('href')
                except:
                    pass
            # Normalize URL to canonical group post link
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
        """Use LLM to determine if the listing excludes males (female-only) or is family-only."""
        try:
            prompt = (
                f"Determine if this rental listing text indicates that the listing is "
                f"for female-only or family-only tenants. Reply YES or NO.\nText: '''{text}'''"
            )
            response = self.bot.call_llm(
                prompt=prompt,
                temperature=0.0,
                max_tokens=5
            )
            if not response:
                return False
            answer = response.strip().lower()
            return answer.startswith("yes")
        except Exception:
            return False

    def is_rental_post(self, text: str) -> bool:
        """Use LLM or keyword-based fallback to determine if post is about renting property."""
        try:
            prompt = (
                f"Determine if this Facebook post is about renting residential property. "
                f"Reply YES or NO.\nText: '''{text}'''"
            )
            response = self.bot.call_llm(
                prompt=prompt,
                temperature=0.0,
                max_tokens=5
            )
            if response:
                answer = response.strip().lower()
                return answer.startswith("yes")
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

        # Initialize results files & directories
        os.makedirs('results', exist_ok=True)
        res_master = 'results/facebook_results.csv'
        with open(res_master, 'w', newline='', encoding='utf-8') as rf:
            writer = csv.writer(rf)
            writer.writerow([
                'message_id', 'date', 'location', 'city', 'rent', 'bhk',
                'additional_details', 'latitude', 'longitude',
                'distance_from_office_km', 'driving_duration', 'post_url',
                'source', 'group_name'
            ])

        api_url = f"https://graph.facebook.com/v20.0/{group_id}/feed"
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
                    
                    posts_fetched += 1
                    post_id = post.get('id')
                    message_text = post.get('message', '')
                    created_time = post.get('created_time')
                    post_url = post.get('permalink_url', f"https://www.facebook.com/groups/{group_id}/posts/{post_id}/")

                    if not message_text:
                        continue

                    if not self.is_rental_post(message_text):
                        continue

                    if self.skip_based_on_preference(message_text):
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
                        result.update({'group_name': group_id})
                        batch_results.append(result)
                        self.bot.results.append(result)
                        found_properties += 1
                        print(f"🏡 Found property #{found_properties}: {result['location']} - {result['distance_from_office_km']}km from office")

                if batch_results:
                    with open(res_master, 'a', newline='', encoding='utf-8') as rf:
                        writer = csv.writer(rf)
                        for result in batch_results:
                            writer.writerow([
                                result['message_id'], result['date'], result['location'],
                                result.get('city', ''), result.get('rent', ''),
                                result.get('bhk', ''), result.get('additional_details', ''),
                                result['latitude'], result['longitude'],
                                result['distance_from_office_km'], result['driving_duration'],
                                result['post_url'], result['source'], result['group_name']
                            ])

                self.bot.save_results('facebook_results.json')
                api_url = resp_data.get('paging', {}).get('next')

            except Exception as e:
                print(f"❌ Error during Facebook Graph API request: {e}")
                return False

        print(f"✅ API Ingestion done. Fetched {posts_fetched} posts, found {found_properties} properties.")
        return True

    def process_group_posts(self, group_url_or_name, max_posts=50):
        """Main method to scrape and process Facebook group posts in batches with aggregated CSV outputs."""
        print("🏠 Facebook Group House Hunting Started")
        print(f"📍 Office Location: {self.bot.office_address}")
        print(f"👥 Target Group: {group_url_or_name}")
        os.makedirs('results/html', exist_ok=True)
        print("-" * 50)

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

            # Initialize aggregated results CSV
            res_master = 'results/facebook_results.csv'
            with open(res_master, 'w', newline='', encoding='utf-8') as rf:
                writer = csv.writer(rf)
                writer.writerow([
                    'message_id', 'date', 'location', 'city', 'rent', 'bhk',
                    'additional_details', 'latitude', 'longitude',
                    'distance_from_office_km', 'driving_duration', 'post_url',
                    'source', 'group_name'
                ])

            batch_size = 20  # Reduce batch size to 20 posts
            while self.posts_processed < max_posts:
                target_load = min(self.posts_processed + batch_size, max_posts)
                posts = self.scroll_and_load_posts(max_posts=target_load)
                if not posts or len(posts) <= self.posts_processed:
                    print("📄 No new posts to process")
                    break

                batch_posts = posts[self.posts_processed:target_load]

                # Save raw batch to CSV with post URLs and debug info
                raw_file = f"results/facebook_raw_{self.posts_processed+1}_{target_load}.csv"
                with open(raw_file, 'w', newline='', encoding='utf-8') as rf:
                    writer = csv.writer(rf)
                    writer.writerow(
                        ['message_id', 'text', 'timestamp', 'post_url'])
                    raw_data_list = []
                    for idx, post in enumerate(batch_posts, start=self.posts_processed+1):
                        try:
                            cls = post.get_attribute('class') or ''
                            if 'x1a2a7pz' not in cls:
                                print(f"⚠️ Skipping element {idx} - doesn't match post selector")
                                continue
                        except Exception as e:
                            print(f"⚠️ Error validating element {idx}: {e}")
                            continue

                        html_path = f"results/html/fb_post_{idx}.html"
                        self.save_post_html(post, html_path)

                        data = self.extract_post_data(post) or {}
                        data['message_id'] = f"fb_post_{idx}"
                        data['html_file'] = html_path
                        text = ' '.join(data.get('text', '').split())
                        if not text or not self.is_rental_post(text):
                            continue
                        raw_data_list.append(data)
                        writer.writerow([data['message_id'], text, data.get(
                            'timestamp', ''), data.get('post_url', '')])
                print(f"🔖 Raw batch saved to {raw_file}")

                batch_results = []
                for data in raw_data_list:
                    if self.skip_based_on_preference(data['text']):
                        continue
                    result = self.process_raw_data(data)
                    if result:
                        result.update({'group_name': group_url_or_name})
                        batch_results.append(result)
                        self.bot.results.append(result)
                        print(
                            f"🏡 Found property: {result['location']} - {result['distance_from_office_km']}km from office")

                if batch_results:
                    with open(res_master, 'a', newline='', encoding='utf-8') as rf:
                        writer = csv.writer(rf)
                        for result in batch_results:
                            writer.writerow([
                                result['message_id'], result['date'], result['location'],
                                result.get('city', ''), result.get('rent', ''),
                                result.get('bhk', ''), result.get('additional_details', ''),
                                result['latitude'], result['longitude'],
                                result['distance_from_office_km'], result['driving_duration'],
                                result['post_url'], result['source'], result['group_name']
                            ])

                self.posts_processed = target_load
                if self.posts_processed < max_posts:
                    print(f"🔄 Loading next batch...")

            print(f"✅ All done. Processed {self.posts_processed} posts")

        except Exception as e:
            print(f"❌ Error during Facebook scraping: {e}")
        finally:
            if hasattr(self, 'context') and self.context:
                self.context.close()
            if hasattr(self, 'playwright') and self.playwright:
                self.playwright.stop()

    def save_results(self, filename_prefix="facebook_house_hunting"):
        """Save results using the HouseHuntingBot methods."""
        if self.bot.results:
            self.bot.save_results(f'results/{filename_prefix}_results.json')
            self.bot.save_results_to_csv(f'results/{filename_prefix}_results.csv')
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
        message = type('FacebookPost', (), {
            'text': raw_data.get('text', ''),
            'date': raw_data.get('timestamp'),
            'id': raw_data.get('message_id')
        })()
        result = self.bot.process_message(message)
        if result:
            result.update({
                'post_url': raw_data.get('post_url', ''),
                'source': 'facebook_group'
            })
        return result


def main():
    load_dotenv()

    # Get credentials for API mode
    api_token = os.getenv('FB_ACCESS_TOKEN')
    group_id = os.getenv('FB_GROUP_ID')
    max_posts = int(os.getenv('FACEBOOK_MAX_POSTS', '50'))

    scraper = FacebookGroupScraper()

    # If API token and Group ID are provided, try Graph API mode first
    api_success = False
    if api_token and group_id:
        print("🔑 FB_ACCESS_TOKEN and FB_GROUP_ID found. Attempting Graph API ingestion...")
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
        print("❌ No Facebook group specified for Playwright fallback.")
        return

    scraper.process_group_posts(group_target, max_posts)
    scraper.save_results()


if __name__ == "__main__":
    main()
