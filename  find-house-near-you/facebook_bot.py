import os
import json
import csv
import time
import re
from datetime import datetime, timedelta
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
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
        post_selector = "div[role='feed'] > div"

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

            return {
                'text': post_text,
                'timestamp': timestamp,
                # First 500 chars for debugging
                'raw_html': post_element.get_attribute('innerHTML')[:500]
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

    def process_group_posts(self, group_url_or_name, max_posts=50):
        """Main method to scrape and process Facebook group posts in batches with aggregated CSV outputs."""
        print("🏠 Facebook Group House Hunting Started")
        print(f"📍 Office Location: {self.bot.office_address}")
        print(f"👥 Target Group: {group_url_or_name}")
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

            # Initialize aggregated CSV files
            raw_master = 'results/facebook_raw.csv'
            res_master = 'results/facebook_results.csv'
            # Create/overwrite raw CSV
            with open(raw_master, 'w', newline='') as rf:
                writer = csv.writer(rf)
                writer.writerow(['id', 'text', 'timestamp'])
            # Create/overwrite results CSV with known headers
            with open(res_master, 'w', newline='') as rf:
                writer = csv.writer(rf)
                writer.writerow([
                    'message_id', 'date', 'location', 'city', 'rent', 'bhk',
                    'additional_details', 'latitude', 'longitude',
                    'distance_from_office_km', 'driving_duration',
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

                # Append raw batch to aggregated CSV
                with open(raw_master, 'a', newline='') as rf:
                    writer = csv.writer(rf)
                    for idx, post in enumerate(batch_posts, start=self.posts_processed+1):
                        data = self.extract_post_data(post) or {}
                        text = ' '.join(data.get('text', '').split())
                        timestamp = data.get('timestamp', '')
                        writer.writerow([f"fb_post_{idx}", text, timestamp])

                # Process batch and append results
                batch_results = []
                for idx, post in enumerate(batch_posts, start=self.posts_processed+1):
                    try:
                        post_data = self.extract_post_data(post)
                        if not post_data or not post_data['text']:
                            continue
                        if self.skip_based_on_preference(post_data['text']):
                            continue
                        message = type('FacebookPost', (), {
                            'text': post_data['text'],
                            'date': post_data['timestamp'],
                            'id': f"fb_post_{idx}"
                        })()
                        result = self.bot.process_message(message)
                        if result:
                            result.update(
                                {'source': 'facebook_group', 'group_name': group_url_or_name})
                            batch_results.append(result)
                            self.bot.results.append(result)
                            print(
                                f"🏡 Found property: {result['location']} - {result['distance_from_office_km']}km from office")
                    except Exception as e:
                        print(f"⚠️ Error processing post {idx}: {e}")
                        continue

                if batch_results:
                    with open(res_master, 'a', newline='') as rf:
                        writer = csv.writer(rf)
                        for result in batch_results:
                            writer.writerow([
                                result['message_id'], result['date'], result['location'],
                                result.get('city', ''), result.get('rent', ''),
                                result.get('bhk', ''), result.get('additional_details', ''),
                                result['latitude'], result['longitude'],
                                result['distance_from_office_km'], result['driving_duration'],
                                result['source'], result['group_name']
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
