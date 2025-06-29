# House Hunting Bot

A multi-platform Python application to extract rental property listings from **Telegram**, **WhatsApp Web**, and **Facebook Groups**. It uses **OpenAI GPT** to parse location and rent details, **Google Maps** for distance calculations, and outputs results as JSON and CSV.

## Features

- 🏠 Parse rental messages from Telegram, WhatsApp, or Facebook Groups
- 🤖 Use GPT to extract location, rent, BHK, and additional details
- 📍 Geocode addresses and compute driving distance/time from your office
- 💾 Save results to JSON and CSV
- 🔄 Auto-scroll WhatsApp Web and Facebook Groups to load full chat/post history
- 🔑 Optional Chrome profile reuse for session persistence
- ⚠️ Multiple robust selectors for Facebook's dynamic content

## Prerequisites

- Python 3.8 or higher
- Google Chrome browser
- Chromedriver (managed automatically via **webdriver-manager**)

## Installation

1. Clone this repository:

   ```bash
   git clone <repo-url>
   cd py-test
   ```

2. Install Python dependencies:

   ```bash
   pip install -r requirements.txt
   ```

3. Create and configure a `.env` file based on the template below.

## Environment Variables

Create a file named `.env` in the project root and add:

```ini
# --- Telegram Bot Settings ---
TELEGRAM_API_ID=your_telegram_api_id
TELEGRAM_API_HASH=your_telegram_api_hash
TELEGRAM_PHONE=+1234567890
TARGET_CHAT=@channel_or_chat_id   # or 'me' for Saved Messages
# (Optional) Use peer ID instead of chat name
TARGET_PEER_ID=

# --- OpenAI & Google Maps API ---
OPENAI_API_KEY=your_openai_api_key
GOOGLE_MAPS_API_KEY=your_google_maps_api_key

# --- Office Location ---
OFFICE_LATITUDE=12.9716
OFFICE_LONGITUDE=77.5946
OFFICE_ADDRESS="Your Office Address"

# --- WhatsApp Web Bot Settings ---
WHATSAPP_TARGET_CHAT="Exact Chat Title"

# --- Facebook Group Bot Settings ---
FACEBOOK_TARGET_GROUP="https://www.facebook.com/groups/your-group-id"
FACEBOOK_MAX_POSTS=50

# --- Chrome Profile Settings (Optional for session persistence) ---
# CHROME_USER_DATA_DIR=/absolute/path/to/Chrome/User Data
# CHROME_PROFILE=Profile 1
```

## Usage

### Option 1: Unified Interface (Recommended)

Run the unified interface to choose your platform:

```bash
python main.py
```

This will present a menu to choose between Telegram, WhatsApp, or Facebook bots.

### Option 2: Run Individual Bots

#### Telegram Bot

```bash
python telegram_bot.py
```

Results will be saved as:

- `house_hunting_results.json`
- `house_hunting_results.csv`

#### WhatsApp Web Bot

```bash
python whatsapp_bot.py
```

The script will open Chrome, prompt you to scan the QR code, auto-scroll the chat, and process messages. Outputs:

- `whatsapp_house_hunting_results.json`
- `whatsapp_house_hunting_results.csv`

#### Facebook Group Bot

⚠️ **Important**: Facebook scraping may violate their Terms of Service. Use responsibly and consider the legal implications.

```bash
python facebook_bot.py
```

The script will:

1. Open Chrome and navigate to Facebook
2. Prompt you to log in manually
3. Navigate to the specified group (URL or name)
4. Auto-scroll through posts to load content
5. Extract and process rental listings

Outputs:

- `facebook_house_hunting_results.json`
- `facebook_house_hunting_results.csv`

## Customization

- **Message Limit**: In `main.py`, adjust `bot.run_analysis(limit=N)` to restrict number of Telegram messages.
- **Scroll Depth**: In `whatsapp_bot.py`, change the loop count for older WhatsApp messages.
- **GPT Prompt**: Tweak the prompt in `extract_location_with_gpt()` to refine parsing.

## Important Considerations for Facebook

⚠️ **Legal and Ethical Warnings:**

- Facebook's Terms of Service prohibit automated scraping
- Facebook groups may contain private/personal information
- Facebook has sophisticated anti-bot detection systems
- Consider using Facebook's official Graph API for legitimate use cases
- You are responsible for compliance with applicable laws and terms of service

## Troubleshooting

- **Environment Variables**: Ensure no quotes around numeric API IDs.
- **WhatsApp Selectors**: WhatsApp Web layout may change—inspect and update CSS/XPath selectors.
- **Facebook Selectors**: Facebook frequently changes their DOM structure—selectors may need updates.
- **Chrome Profile Locks**: Close other Chrome windows or use a dedicated profile in `.env`.
- **API Errors**: Check your OpenAI/Google Maps credentials and usage quotas.
- **Facebook Login Issues**: Ensure you're logged into the correct Facebook account and have access to the target group.
- **Rate Limiting**: If Facebook blocks requests, try reducing scroll speed or using longer delays.

## License

This project is licensed under the MIT License.
