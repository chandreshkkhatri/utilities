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
- 🧩 Chrome Extension: extract rental details from any website selection with AI parsing, view results in a table, and export CSV
  - Supports selecting multiple posts at once: split by blank lines or separators

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

## Configuration

Ensure you have the following environment variables set in your `.env` file:

- `TELEGRAM_API_ID` and `TELEGRAM_API_HASH`
- `TELEGRAM_PHONE`
- `OPENAI_API_KEY`
- `GOOGLE_MAPS_API_KEY`
- **Either** `TARGET_CHAT` **or** `TARGET_PEER_ID` (preferred):
  - `TARGET_CHAT`: the username of the Telegram channel or group (e.g. `RentRadar.in`)
  - `TARGET_PEER_ID`: the numeric peer ID of the chat (for supergroups/channels use the `-100...` ID)

Setting `TARGET_CHAT` to a group/channel username ensures that generated links are in the form `https://t.me/<username>/<message_id>`.  
If you use `TARGET_PEER_ID`, the bot will generate links like `https://t.me/c/<clean_id>/<message_id>` (where `<clean_id>` is the peer ID without the `-100` prefix).

Make sure to rerun the bot after updating these variables to regenerate results with proper Telegram post links.

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

### Option 3: Chrome Extension (Recommended for Facebook and general web)

The extension lets you select any text on a page (e.g., a Facebook/Reddit/Forum housing post) and extract structured rental details using AI or a regex fallback.

1. Open Chrome and go to: chrome://extensions
2. Enable "Developer mode" (top right)
3. Click "Load unpacked" and select the `extension` folder in this repository
4. Click the extension icon (puzzle piece), pin "Find House Near You - Extractor"
5. Open the extension's Options page to set:
   - OpenAI-compatible Base URL (default: https://api.openai.com/v1)
   - API Key and Model (e.g., gpt-4o-mini)
   - Optional: Google Maps API Key, office latitude/longitude, and enable distance calculation
6. On any page, select the rental post text, right-click, and choose: "Extract rental details from selection"
7. Open the popup to see the results table and export CSV.
   - Tip: You can select multiple posts at once. The extension splits by blank lines (or separators like ---) and parses each as a separate entry.

Notes:

- AI parsing requires an API key. Without it, the extension uses a heuristic regex fallback (less accurate).
- For distance calculation, both Google Maps API key and office coordinates are needed.
- Results are stored locally in the browser (chrome.storage.local); settings sync with your account (chrome.storage.sync).
- The extension performs requests from your browser only; no external server is used by this project.

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
- **Extension not loading**: Ensure Manifest V3 is supported (recent Chrome). Use "Load unpacked" on the `extension` directory.
- **No AI results**: Set your API key and model in the Options page. Verify billing/quotas with your AI provider.
- **Distance not shown**: Add Google Maps API key, enable "Compute distance", and set your office coordinates in Options.
- **CSV empty**: Ensure you've extracted at least one result via right-click or the popup paste-parse.

## License

This project is licensed under the MIT License.
