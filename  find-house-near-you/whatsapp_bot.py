import os
import json
import csv
import time
import re
from datetime import datetime
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException
from webdriver_manager.chrome import ChromeDriverManager
from dotenv import load_dotenv

from telegram_bot import HouseHuntingBot


def main():
    # Load environment variables
    load_dotenv()
    chat_name = os.getenv('WHATSAPP_TARGET_CHAT')
    if not chat_name:
        print("❌ Please set WHATSAPP_TARGET_CHAT in .env file.")
        return

    # Initialize bot
    bot = HouseHuntingBot()

    # Launch Chrome and open WhatsApp Web, trying to reuse a profile
    chrome_data_dir = os.getenv('CHROME_USER_DATA_DIR')
    chrome_profile = os.getenv('CHROME_PROFILE')
    driver = None
    if chrome_data_dir and chrome_profile:
        options = Options()
        options.add_argument(f"--user-data-dir={chrome_data_dir}")
        options.add_argument(f"--profile-directory={chrome_profile}")
        try:
            driver = webdriver.Chrome(
                service=Service(ChromeDriverManager().install()),
                options=options
            )
        except Exception as e:
            print(
                f"⚠️ Could not launch with profile (in use?): {e}\nLaunching with temporary profile instead.")
    if not driver:
        driver = webdriver.Chrome(service=Service(
            ChromeDriverManager().install()))

    driver.get("https://web.whatsapp.com")
    print("Please scan the QR code to log in to WhatsApp Web.")
    input("Press Enter after scanning and chats are visible...")

    # Search and open target chat
    try:
        # WhatsApp search input has data-tab='3'
        search_box = WebDriverWait(driver, 30).until(
            EC.element_to_be_clickable(
                (By.CSS_SELECTOR, "div[contenteditable='true'][data-tab='3']"))
        )
        print("🔎 Search box found")
    except TimeoutException:
        print("❌ Could not locate WhatsApp search box. Exiting.")
        driver.quit()
        return

    search_box.click()
    search_box.send_keys(chat_name)
    time.sleep(2)
    search_box.send_keys(Keys.ENTER)
    time.sleep(2)
    print(f"✅ Opened chat: {chat_name}")
    # Auto-scroll up to load all messages
    try:
        chat_panel = WebDriverWait(driver, 10).until(
            EC.presence_of_element_located(
                (By.CSS_SELECTOR, 'div.copyable-area'))
        )
        last_height = None
        for _ in range(20):  # adjust iteration count as needed
            driver.execute_script("arguments[0].scrollTop = 0;", chat_panel)
            time.sleep(1)
            new_height = driver.execute_script(
                "return arguments[0].scrollHeight;", chat_panel)
            if new_height == last_height:
                break
            last_height = new_height
        print("🔄 Completed scrolling to load messages")
    except TimeoutException:
        print("❌ Could not locate chat panel for scrolling. Continuing...")
    # Wait for messages to load
    try:
        WebDriverWait(driver, 15).until(
            EC.presence_of_element_located(
                (By.CSS_SELECTOR, 'div.copyable-text'))
        )
    except TimeoutException:
        print("❌ Timeout waiting for messages to load. Exiting.")
        driver.quit()
        return

    # Collect all message elements
    messages = driver.find_elements(By.CSS_SELECTOR, 'div.copyable-text')
    print(f"🔍 Found {len(messages)} message elements to process")

    # Process each message element
    for idx, element in enumerate(messages, 1):
        try:
            data_pre = element.get_attribute('data-pre-plain-text')
            if not data_pre:
                continue
            # Extract timestamp
            ts_match = re.search(r"\[(.*?)\]", data_pre)
            if not ts_match:
                continue
            ts_str = ts_match.group(1)
            dt = datetime.strptime(ts_str, "%H:%M, %d/%m/%Y")
            # Extract message text
            text = element.find_element(
                By.CSS_SELECTOR, 'span.selectable-text').text
            # Build message object
            message = type('Msg', (), {'text': text, 'date': dt, 'id': idx})
            # Process via HouseHuntingBot
            result = bot.process_message(message)
            if result:
                bot.results.append(result)
                print(
                    f"🏡 Found property: {result['location']} - {result['distance_from_office_km']}km from office")
        except Exception:
            continue

    # Close browser
    driver.quit()

    # Display and save results
    bot.display_results(sort_by_distance=True)
    bot.save_results('whatsapp_house_hunting_results.json')
    bot.save_results_to_csv('whatsapp_house_hunting_results.csv')


if __name__ == "__main__":
    main()
