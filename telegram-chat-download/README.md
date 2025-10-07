# Telegram Channel Downloader

A Python script to download messages and media from Telegram channels using Telethon.

## Features

- Download recent messages from channels
- Download all messages from a channel
- Search messages within a channel
- Download media files (photos, documents)
- Export data to JSON or CSV format
- Channel information retrieval

## Setup

1. **Install dependencies:**
   ```bash
   pip install -r requirements.txt
   ```

2. **Get Telegram API credentials:**
   - Go to https://my.telegram.org
   - Log in with your phone number
   - Navigate to 'API development tools'
   - Create an app if you haven't already
   - Copy your `api_id` and `api_hash`

3. **Configure environment variables:**
   - Copy `.env.example` to `.env`
   - Add your API credentials and phone number:
     ```
     API_ID=your_api_id
     API_HASH=your_api_hash
     PHONE=+your_phone_number
     ```

## Usage

Run the script:
```bash
python telegram_downloader.py
```

The script will:
1. Connect to Telegram using your credentials
2. Ask for the channel username (without @)
3. Display channel information
4. Offer options to:
   - Download recent messages
   - Download all messages
   - Search messages
5. Save results in JSON or CSV format

## Output

- **JSON format**: Complete message data with all metadata
- **CSV format**: Tabular format for easy analysis
- **Media files**: Saved in `media/` directory (if enabled)

## Security Notes

- Never share your `.env` file or session files
- The `.gitignore` is configured to exclude sensitive files
- Session files allow persistent login without re-authentication

## Message Data Fields

Each message includes:
- `id`: Message ID
- `date`: Message timestamp
- `text`: Message content
- `sender_id`: Sender's user ID
- `reply_to_msg_id`: ID of replied message
- `forwards`: Forward count
- `views`: View count
- `media_type`: Type of attached media
- `media_path`: Local path to downloaded media