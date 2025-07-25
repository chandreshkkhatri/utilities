import os
import csv
import time
import re
from datetime import datetime, timedelta
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, NoSuchElementException
from webdriver_manager.chrome import ChromeDriverManager
from dotenv import load_dotenv

from telegram_bot import HouseHuntingBot

import openai


class FacebookGroupScraper:
    def __init__(self):
        self.bot = HouseHuntingBot()
        self.driver = None
        self.posts_processed = 0

    def setup_driver(self):
        """Setup Chrome driver with Facebook-optimized settings."""
        load_dotenv()

        chrome_options = Options()

        # Use existing Chrome profile if specified
        chrome_data_dir = os.getenv('CHROME_USER_DATA_DIR')
        chrome_profile = os.getenv('CHROME_PROFILE')

        if chrome_data_dir and chrome_profile:
            chrome_options.add_argument(f"--user-data-dir={chrome_data_dir}")
            chrome_options.add_argument(
                f"--profile-directory={chrome_profile}")

        # Additional options for Facebook
        chrome_options.add_argument(
            "--disable-blink-features=AutomationControlled")
        chrome_options.add_experimental_option(
            "excludeSwitches", ["enable-automation"])
        chrome_options.add_experimental_option('useAutomationExtension', False)
        chrome_options.add_argument("--disable-web-security")
        chrome_options.add_argument("--allow-running-insecure-content")

        try:
            self.driver = webdriver.Chrome(
                service=Service(ChromeDriverManager().install()),
                options=chrome_options
            )

            # Execute script to hide webdriver property
            self.driver.execute_script(
                "Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")

        except Exception as e:
            print(f"⚠️ Error setting up driver: {e}")
            raise

    def login_to_facebook(self):
        """Navigate to Facebook and wait for manual login."""
        print("🌐 Opening Facebook...")
        self.driver.get("https://www.facebook.com")

        # Check if already logged in
        try:
            WebDriverWait(self.driver, 10).until(
                EC.presence_of_element_located(
                    (By.CSS_SELECTOR, "[data-testid='home-icon']"))
            )
            print("✅ Already logged in to Facebook")
            return True
        except TimeoutException:
            pass

        print("🔐 Please log in to Facebook manually in the browser window")
        print("⏳ Waiting for login completion...")

        # Wait for login completion (home feed or profile icon)
        try:
            WebDriverWait(self.driver, 300).until(  # 5 minutes timeout
                EC.any_of(
                    EC.presence_of_element_located(
                        (By.CSS_SELECTOR, "[data-testid='home-icon']")),
                    EC.presence_of_element_located(
                        (By.CSS_SELECTOR, "[aria-label='Facebook']"))
                )
            )
            print("✅ Successfully logged in to Facebook")
            return True
        except TimeoutException:
            print("❌ Login timeout. Please try again.")
            return False

    def navigate_to_group(self, group_url_or_name):
        """Navigate to the specified Facebook group."""
        if group_url_or_name.startswith('http'):
            self.driver.get(group_url_or_name)
        else:
            # Search for group by name
            search_url = f"https://www.facebook.com/search/groups/?q={group_url_or_name}"
            self.driver.get(search_url)

            # Wait for search results and click first group
            try:
                first_group = WebDriverWait(self.driver, 15).until(
                    EC.element_to_be_clickable(
                        (By.CSS_SELECTOR, "[role='article'] a"))
                )
                first_group.click()
            except TimeoutException:
                print(f"❌ Could not find group: {group_url_or_name}")
                return False

        # Wait for group page to load
        try:
            WebDriverWait(self.driver, 15).until(
                EC.presence_of_element_located(
                    (By.CSS_SELECTOR, "[role='main']"))
            )
            print(f"✅ Successfully navigated to group")
            return True
        except TimeoutException:
            print("❌ Group page failed to load")
            return False

    def scroll_and_load_posts(self, max_posts=50, max_scroll_time=300):
        """Scroll through the group feed to load posts."""
        print(
            f"🔄 Loading posts (max {max_posts} posts, {max_scroll_time}s timeout)")

        start_time = time.time()
        last_height = self.driver.execute_script(
            "return document.body.scrollHeight")

        # More robust selector for posts
        post_selector = "div.x1a2a7pz[aria-posinset]"

        posts_found = 0

        while posts_found < max_posts and (time.time() - start_time) < max_scroll_time:
            # Scroll down
            self.driver.execute_script(
                "window.scrollTo(0, document.body.scrollHeight);")

            # Wait for new content to load
            time.sleep(2)

            # Check current number of posts
            try:
                posts = self.driver.find_elements(
                    By.CSS_SELECTOR, post_selector)
                posts_found = len(posts)

                # Check if page height changed (new content loaded)
                new_height = self.driver.execute_script(
                    "return document.body.scrollHeight")
                if new_height == last_height:
                    # Try clicking "See More" buttons if available
                    see_more_buttons = self.driver.find_elements(
                        By.XPATH, "//span[contains(text(), 'See more') or contains(text(), 'See More')]")
                    # Click last 3 buttons
                    for button in see_more_buttons[-3:]:
                        try:
                            button.click()
                            time.sleep(1)
                        except:
                            pass

                    # If still no new content, we've reached the end
                    time.sleep(3)
                    final_height = self.driver.execute_script(
                        "return document.body.scrollHeight")
                    if final_height == new_height:
                        print("📄 Reached end of available posts")
                        break

                last_height = new_height

            except Exception as e:
                print(f"⚠️ Error counting posts: {e}")
                break

        final_posts = self.driver.find_elements(By.CSS_SELECTOR, post_selector)
        print(f"📊 Found {len(final_posts)} posts to process")
        return final_posts

    def extract_post_data(self, post_element):
        """Extract text and metadata from a Facebook post."""
        try:
            # Expand 'See more' links within the post to reveal full content
            see_more_xpaths = [
                ".//span[contains(text(), 'See more')]",
                ".//span[contains(text(), 'See More')]"
            ]
            for xpath in see_more_xpaths:
                try:
                    buttons = post_element.find_elements(By.XPATH, xpath)
                    for btn in buttons:
                        self.driver.execute_script(
                            "arguments[0].click();", btn)
                        time.sleep(0.5)
                except Exception:
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
                    elements = post_element.find_elements(
                        By.CSS_SELECTOR, selector)
                    for element in elements:
                        text = element.text.strip()
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
                    time_elements = post_element.find_elements(
                        By.CSS_SELECTOR, selector)
                    for time_elem in time_elements:
                        time_text = time_elem.get_attribute(
                            'title') or time_elem.get_attribute('aria-label') or time_elem.text
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
                time_elem = post_element.find_element(By.TAG_NAME, 'time')
                parent_link = time_elem.find_element(By.XPATH, './ancestor::a')
                post_url = parent_link.get_attribute('href')
            except:
                pass
            # Fallback to any link matching common post patterns
            if not post_url:
                try:
                    link_elem = post_element.find_element(
                        By.XPATH,
                        ".//a[contains(@href, '/posts/') or contains(@href, '/permalink/') or contains(@href, 'story.php')]"
                    )
                    post_url = link_elem.get_attribute('href')
                except:
                    pass
            # Normalize URL to canonical group post link
            post_url = self.normalize_post_url(post_url)

            return {
                'text': post_text,
                'timestamp': timestamp,
                'raw_html': post_element.get_attribute('innerHTML')[:500],
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
                # Try to parse absolute dates
                try:
                    return datetime.strptime(time_text, "%B %d at %I:%M %p")
                except:
                    return now
        except:
            return datetime.now()

    def skip_based_on_preference(self, text: str) -> bool:
        """Use GPT to determine if the listing excludes males (female-only) or is family-only."""
        try:
            prompt = (
                f"Determine if this rental listing text indicates that the listing is "
                f"for female-only or family-only tenants. Reply YES or NO.\nText: '''{text}'''"
            )
            response = openai.chat.completions.create(
                model="gpt-3.5-turbo",
                messages=[{"role": "user", "content": prompt}],
                temperature=0,
                max_tokens=5
            )
            answer = response.choices[0].message.content.strip().lower()
            return answer.startswith("yes")
        except Exception:
            return False

    def is_rental_post(self, text: str) -> bool:
        """Use GPT or keyword-based fallback to determine if post is about renting property."""
        try:
            prompt = (
                f"Determine if this Facebook post is about renting residential property. "
                f"Reply YES or NO.\nText: '''{text}'''"
            )
            response = openai.chat.completions.create(
                model="gpt-3.5-turbo",
                messages=[{"role": "user", "content": prompt}],
                temperature=0,
                max_tokens=5
            )
            answer = response.choices[0].message.content.strip().lower()
            return answer.startswith("yes")
        except Exception:
            # Fallback to simple keyword check
            keywords = ['rent', 'for rent', 'room for rent',
                        'apartment for rent', 'flat for rent', 'house for rent']
            text_lower = text.lower()
            return any(k in text_lower for k in keywords)

    def process_group_posts(self, group_url_or_name, max_posts=50):
        """Main method to scrape and process Facebook group posts in batches with aggregated CSV outputs."""
        print("🏠 Facebook Group House Hunting Started")
        print(f"📍 Office Location: {self.bot.office_address}")
        print(f"👥 Target Group: {group_url_or_name}")
        os.makedirs('results/html', exist_ok=True)
        print("-" * 50)

        try:
            self.setup_driver()
            if not self.login_to_facebook():
                return
            if not self.navigate_to_group(group_url_or_name):
                return

            # Switch to "New listings" feed
            try:
                # Open the sort menu
                sort_menu = WebDriverWait(self.driver, 10).until(
                    EC.element_to_be_clickable(
                        (By.XPATH, "//div[@aria-label='Sort group posts']"))
                )
                sort_menu.click()
                # Select "New listings"
                new_btn = WebDriverWait(self.driver, 5).until(
                    EC.element_to_be_clickable(
                        (By.XPATH, "//span[text()='New listings']"))
                )
                new_btn.click()
                print("🔄 Switched to New listings feed")
                time.sleep(2)
            except Exception as e:
                print(f"⚠️ Could not switch feed to New listings: {e}")

            # Initialize aggregated results CSV (no raw posts CSV)
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
                        # Validate that the element still matches our selector
                        try:
                            if not (post.get_attribute('class') and 'x1a2a7pz' in post.get_attribute('class')
                                    and post.get_attribute('aria-posinset')):
                                print(
                                    f"⚠️ Skipping element {idx} - doesn't match post selector")
                                continue
                        except Exception as e:
                            print(f"⚠️ Error validating element {idx}: {e}")
                            continue

                        # Block 1: Save HTML
                        html_path = f"results/html/fb_post_{idx}.html"
                        self.save_post_html(post, html_path)

                        # Block 2: Extract raw info
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
                # Block 3: Process extracted data
                for data in raw_data_list:
                    # Skip based on preferences
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
                                result.get('bhk', ''), result.get(
                                    'additional_details', ''),
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
            if self.driver:
                input("Press Enter to close browser...")
                self.driver.quit()

    def save_results(self, filename_prefix="facebook_house_hunting"):
        """Save results using the HouseHuntingBot methods."""
        if self.bot.results:
            self.bot.save_results(f'results/{filename_prefix}_results.json')
            self.bot.save_results_to_csv(
                f'results/{filename_prefix}_results.csv')
            self.bot.display_results(sort_by_distance=True)
        else:
            print("❌ No results to save")

    def normalize_post_url(self, url: str) -> str:
        """Normalize Facebook post URL to canonical group post link format."""
        if not url:
            return url
        # Match /groups/.../posts/<post_id>
        m = re.search(
            r"(https://www\.facebook\.com/groups/[^/]+/posts/\d+)", url)
        if m:
            return m.group(1) + '/'
        # Match story.php links with story_fbid
        m2 = re.search(r"story\.php\?story_fbid=(\d+)&id=(\d+)", url)
        if m2:
            post_id, group_id = m2.group(1), m2.group(2)
            return f"https://www.facebook.com/groups/{group_id}/posts/{post_id}/"
        return url

    def save_post_html(self, post_element, file_path):
        """Save HTML of a post element to a file."""
        os.makedirs(os.path.dirname(file_path), exist_ok=True)
        html = post_element.get_attribute('innerHTML')
        with open(file_path, 'w', encoding='utf-8') as f:
            f.write(html)

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

    # Get group URL or name from environment or user input
    group_target = os.getenv('FACEBOOK_TARGET_GROUP')
    if not group_target:
        group_target = input("Enter Facebook group URL or name: ").strip()

    if not group_target:
        print("❌ No Facebook group specified")
        return

    # Get max posts to process
    max_posts = int(os.getenv('FACEBOOK_MAX_POSTS', '50'))

    # Initialize and run scraper
    scraper = FacebookGroupScraper()
    scraper.process_group_posts(group_target, max_posts)
    scraper.save_results()


if __name__ == "__main__":
    main()
