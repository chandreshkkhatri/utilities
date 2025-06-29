#!/usr/bin/env python3
"""
House Hunting Bot - Unified Interface
Choose between Telegram, WhatsApp, or Facebook scraping.
"""

import os
import sys
from dotenv import load_dotenv


def main():
    print("🏠 House Hunting Bot - Multi-Platform Interface")
    print("=" * 50)
    print("Choose your platform:")
    print("1. 📱 Telegram Bot")
    print("2. 💬 WhatsApp Web Bot")
    print("3. 📘 Facebook Group Bot")
    print("4. ❌ Exit")
    print("=" * 50)

    while True:
        try:
            choice = input("Enter your choice (1-4): ").strip()

            if choice == '1':
                print("\n🚀 Starting Telegram Bot...")
                from telegram_bot import main as telegram_main
                telegram_main()
                break

            elif choice == '2':
                print("\n🚀 Starting WhatsApp Bot...")
                from whatsapp_bot import main as whatsapp_main
                whatsapp_main()
                break

            elif choice == '3':
                print("\n⚠️  Facebook Group Bot")
                print("WARNING: Facebook scraping may violate their Terms of Service.")
                print("Use responsibly and at your own risk.")
                confirm = input(
                    "Do you want to continue? (y/N): ").strip().lower()

                if confirm in ['y', 'yes']:
                    print("\n🚀 Starting Facebook Bot...")
                    from facebook_bot import main as facebook_main
                    facebook_main()
                else:
                    print("Facebook bot cancelled.")
                break

            elif choice == '4':
                print("👋 Goodbye!")
                sys.exit(0)

            else:
                print("❌ Invalid choice. Please enter 1, 2, 3, or 4.")

        except KeyboardInterrupt:
            print("\n👋 Goodbye!")
            sys.exit(0)
        except Exception as e:
            print(f"❌ Error: {e}")
            print("Please try again.")


if __name__ == "__main__":
    # Load environment variables
    load_dotenv()

    # Check if basic requirements are met
    required_vars = ['OPENAI_API_KEY', 'GOOGLE_MAPS_API_KEY']
    missing_vars = [var for var in required_vars if not os.getenv(var)]

    if missing_vars:
        print("❌ Missing required environment variables:")
        for var in missing_vars:
            print(f"   - {var}")
        print("\n📝 Please create a .env file with your API credentials.")
        print("See README.md for setup instructions.")
        sys.exit(1)

    main()
