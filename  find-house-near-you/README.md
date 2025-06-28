# House Hunting Bot

A dual-mode Python application to extract rental property listings from **Telegram** and **WhatsApp Web** chats. It uses **OpenAI GPT** to parse location and rent details, **Google Maps** for distance calculations, and outputs results as JSON and CSV.

## Features

- 🏠 Parse rental messages from Telegram or WhatsApp
- 🤖 Use GPT to extract location, rent, BHK, and additional details
- 📍 Geocode addresses and compute driving distance/time from your office
- 💾 Save results to JSON and CSV
- 🔄 Auto-scroll WhatsApp Web to load full chat history
- 🔑 Optional Chrome profile reuse for WhatsApp session persistence

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
# (Optional) Chrome profile reuse
# CHROME_USER_DATA_DIR=/absolute/path/to/Chrome/User Data
# CHROME_PROFILE=Profile 1
```

## Usage

### 1. Telegram Bot

Run the Telegram house hunting analysis:

```bash
python main.py
```

Results will be printed and saved as:

- `house_hunting_results.json`
- `house_hunting_results.csv`

### 2. WhatsApp Web Bot

Run the WhatsApp Web automation:

```bash
python whatsapp_bot.py
```

The script will open Chrome, prompt you to scan the QR code (once per profile), auto-scroll the chat, and process messages. Outputs:

- `whatsapp_house_hunting_results.json`
- `whatsapp_house_hunting_results.csv`

## Customization

- **Message Limit**: In `main.py`, adjust `bot.run_analysis(limit=N)` to restrict number of Telegram messages.
- **Scroll Depth**: In `whatsapp_bot.py`, change the loop count for older WhatsApp messages.
- **GPT Prompt**: Tweak the prompt in `extract_location_with_gpt()` to refine parsing.

## Troubleshooting

- **Environment Variables**: Ensure no quotes around numeric API IDs.
- **WhatsApp Selectors**: WhatsApp Web layout may change—inspect and update CSS/XPath selectors.
- **Chrome Profile Locks**: Close other Chrome windows or use a dedicated profile in `.env`.
- **API Errors**: Check your OpenAI/Google Maps credentials and usage quotas.

## License

This project is licensed under the MIT License.
