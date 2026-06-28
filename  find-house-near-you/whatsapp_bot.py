import os
import json
import csv
import time
import re
from datetime import datetime
from dotenv import load_dotenv
from playwright.sync_api import sync_playwright

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

    # If no data dir is set, default to a directory inside results/profiles
    user_data_path = chrome_data_dir if chrome_data_dir else "./results/profiles/whatsapp"
    
    print("🚀 Launching Chrome using Playwright...")
    with sync_playwright() as p:
        try:
            # We configure persistent context with system Chrome
            context_args = {
                "user_data_dir": user_data_path,
                "headless": False,
                "channel": "chrome",
                "args": ["--disable-blink-features=AutomationControlled"]
            }
            context = p.chromium.launch_persistent_context(**context_args)
            page = context.pages[0] if context.pages else context.new_page()
        except Exception as e:
            print(f"⚠️ Could not launch Chrome with configured profile: {e}")
            print("Launching standard Chrome instance instead...")
            browser = p.chromium.launch(headless=False, channel="chrome")
            context = browser.new_context()
            page = context.new_page()

        print("🌐 Opening WhatsApp Web...")
        page.goto("https://web.whatsapp.com")
        print("Please scan the QR code to log in to WhatsApp Web.")
        input("Press Enter after scanning and chats are visible...")

        # Search and open target chat
        try:
            # WhatsApp search input
            search_box_selector = "div[contenteditable='true'][data-tab='3']"
            page.wait_for_selector(search_box_selector, timeout=30000)
            page.click(search_box_selector)
            page.fill(search_box_selector, chat_name)
            page.wait_for_timeout(1000)
            page.press(search_box_selector, "Enter")
            page.wait_for_timeout(2000)
            print(f"✅ Opened chat: {chat_name}")
        except Exception as e:
            print(f"❌ Could not locate or open target chat: {e}")
            context.close()
            return

        # Auto-scroll up to load all messages
        try:
            scrollable_selector = "div.copyable-area"
            page.wait_for_selector(scrollable_selector, timeout=15000)
            
            # Perform scroll to top loop
            for _ in range(20):  # adjust scroll depth as needed
                page.evaluate(f"document.querySelector('{scrollable_selector}').scrollTop = 0")
                page.wait_for_timeout(1000)
                
            print("🔄 Completed scrolling to load messages")
        except Exception as e:
            print(f"❌ Could not scroll chat panel: {e}. Continuing message processing...")

        # Collect and process message elements
        try:
            msg_selector = "div.copyable-text"
            page.wait_for_selector(msg_selector, timeout=15000)
            messages = page.query_selector_all(msg_selector)
            print(f"🔍 Found {len(messages)} message elements to process")
        except Exception as e:
            print(f"❌ Timeout waiting for messages to load: {e}")
            context.close()
            return

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
                text_el = element.query_selector('span.selectable-text')
                if not text_el:
                    continue
                text = text_el.inner_text()
                
                # Build message object
                message = type('Msg', (), {'text': text, 'date': dt, 'id': idx})
                # Process via HouseHuntingBot
                result = bot.process_message(message)
                if result:
                    bot.results.append(result)
                    print(f"🏡 Found property: {result['location']} - {result['distance_from_office_km']}km from office")
            except Exception:
                continue

        # Close persistent browser context / browser
        context.close()

    # Display and save results
    bot.display_results(sort_by_distance=True)
    bot.save_results('whatsapp_house_hunting_results.json')
    bot.save_results_to_csv('whatsapp_house_hunting_results.csv')


if __name__ == "__main__":
    main()
