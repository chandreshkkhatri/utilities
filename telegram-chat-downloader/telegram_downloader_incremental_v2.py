import asyncio
import json
import os
import re
import csv
import glob
from datetime import datetime
from typing import Optional, List, Dict, Any, Union, Tuple
from telethon import TelegramClient
from telethon.errors import SessionPasswordNeededError, FloodWaitError
from telethon.tl.types import (
    PeerChannel, Message, MessageMediaPhoto, MessageMediaDocument,
    Channel, Chat, User
)
from dotenv import load_dotenv
import time
import html

load_dotenv()


class IncrementalTelegramDownloader:
    def __init__(self, api_id: int, api_hash: str, phone: str, session_name: str = 'session', output_dir: str = 'downloads'):
        self.api_id = api_id
        self.api_hash = api_hash
        self.phone = phone
        self.session_name = session_name
        self.client = TelegramClient(session_name, api_id, api_hash)
        self.output_dir = output_dir
        os.makedirs(self.output_dir, exist_ok=True)
        self.csv_writer = None
        self.csv_file = None
        self.json_file = None
        self.html_file = None
        self.progress_file = None
        self.messages_with_media = []  # Track messages that have media
        
    async def connect(self, password: Optional[str] = None):
        await self.client.start(phone=self.phone, password=password)
        me = await self.client.get_me()
        print(f"Connected as {me.username or me.first_name}")
        
    async def disconnect(self):
        if self.csv_file:
            self.csv_file.close()
        if self.json_file:
            self.json_file.close()
        if self.html_file:
            self.html_file.close()
        await self.client.disconnect()
    
    async def list_all_dialogs(self, limit: int = None) -> List[Dict[str, Any]]:
        """List all dialogs (chats, channels, groups) the user is part of"""
        dialogs_list = []
        async for dialog in self.client.iter_dialogs(limit=limit):
            dialog_info = {
                'id': dialog.id,
                'title': dialog.title or dialog.name,
                'is_channel': dialog.is_channel,
                'is_group': dialog.is_group,
                'is_user': dialog.is_user,
                'unread_count': dialog.unread_count,
                'entity_type': type(dialog.entity).__name__
            }
            
            if hasattr(dialog.entity, 'username'):
                dialog_info['username'] = dialog.entity.username
            
            if isinstance(dialog.entity, Channel):
                dialog_info['participants_count'] = getattr(dialog.entity, 'participants_count', None)
                dialog_info['megagroup'] = dialog.entity.megagroup
                
            dialogs_list.append(dialog_info)
            
        return dialogs_list
    
    async def search_channels(self, search_term: str) -> List[Dict[str, Any]]:
        """Search for channels by name"""
        matching_dialogs = []
        async for dialog in self.client.iter_dialogs():
            title = dialog.title or dialog.name or ""
            if search_term.lower() in title.lower():
                dialog_info = {
                    'id': dialog.id,
                    'title': title,
                    'is_channel': dialog.is_channel,
                    'is_group': dialog.is_group,
                }
                if hasattr(dialog.entity, 'username'):
                    dialog_info['username'] = dialog.entity.username
                matching_dialogs.append(dialog_info)
        
        return matching_dialogs
    
    async def get_entity_from_input(self, channel_input: Union[str, int]) -> Any:
        """Get entity from various input formats"""
        try:
            # Handle t.me links
            if 't.me/' in str(channel_input):
                match = re.search(r't\.me/(?:joinchat/)?([a-zA-Z0-9_\-]+)', str(channel_input))
                if match:
                    identifier = match.group(1)
                    if 'joinchat' in str(channel_input):
                        return await self.client.get_entity(f"https://t.me/joinchat/{identifier}")
                    else:
                        channel_input = identifier
            
            # Handle username
            if isinstance(channel_input, str) and channel_input.startswith('@'):
                channel_input = channel_input[1:]
            
            # Try to parse as integer
            try:
                channel_id = int(channel_input)
                if channel_id > 0:
                    channel_id = -100 * (10 ** len(str(channel_id)) + channel_id)
                return await self.client.get_entity(channel_id)
            except (ValueError, TypeError):
                pass
            
            return await self.client.get_entity(channel_input)
            
        except Exception as e:
            print(f"Could not resolve entity '{channel_input}': {e}")
            print("Searching through your dialogs...")
            async for dialog in self.client.iter_dialogs():
                if str(dialog.id) == str(channel_input):
                    return dialog.entity
                title = dialog.title or dialog.name or ""
                if str(channel_input).lower() in title.lower():
                    print(f"Found matching dialog: {title}")
                    return dialog.entity
            raise Exception(f"Could not find channel: {channel_input}")
    
    async def get_channel_info(self, channel_input: Union[str, int]) -> Dict[str, Any]:
        """Get channel information"""
        try:
            channel = await self.get_entity_from_input(channel_input)
            
            info = {
                'id': channel.id,
                'title': getattr(channel, 'title', getattr(channel, 'first_name', 'Unknown')),
                'username': getattr(channel, 'username', None),
                'type': type(channel).__name__
            }
            
            if isinstance(channel, Channel):
                info.update({
                    'participants_count': getattr(channel, 'participants_count', None),
                    'date': getattr(channel, 'date', None),
                    'megagroup': channel.megagroup,
                    'restricted': getattr(channel, 'restricted', False),
                    'verified': getattr(channel, 'verified', False),
                    'about': getattr(channel, 'about', None)
                })
            
            return info
            
        except Exception as e:
            print(f"Error getting channel info: {e}")
            return {}
    
    def load_progress(self, filename: str) -> Dict[str, Any]:
        """Load download progress from file"""
        filepath = os.path.join(self.output_dir, filename)
        if os.path.exists(filepath):
            with open(filepath, 'r') as f:
                data = json.load(f)
                # Load messages with media if exists
                self.messages_with_media = data.get('messages_with_media', [])
                return data
        return {'last_message_id': 0, 'total_downloaded': 0, 'media_downloaded': False, 'messages_with_media': []}
    
    def save_progress(self, filename: str, progress: Dict[str, Any]):
        """Save download progress to file"""
        filepath = os.path.join(self.output_dir, filename)
        progress['messages_with_media'] = self.messages_with_media
        with open(filepath, 'w') as f:
            json.dump(progress, f)
    
    async def _parse_message(self, message: Message, download_media: bool = False, track_media: bool = True) -> Dict[str, Any]:
        msg_dict = {
            'id': message.id,
            'date': message.date.isoformat() if message.date else None,
            'text': message.text,
            'sender_id': message.sender_id,
            'reply_to_msg_id': message.reply_to_msg_id,
            'forwards': message.forwards,
            'views': message.views,
            'edit_date': message.edit_date.isoformat() if message.edit_date else None,
            'media_type': None,
            'media_path': None,
            'has_media': bool(message.media)
        }
        
        # Add sender information
        if message.sender:
            if isinstance(message.sender, User):
                msg_dict['sender_name'] = f"{message.sender.first_name or ''} {message.sender.last_name or ''}".strip()
                msg_dict['sender_username'] = message.sender.username
            elif isinstance(message.sender, (Channel, Chat)):
                msg_dict['sender_name'] = message.sender.title
                msg_dict['sender_username'] = getattr(message.sender, 'username', None)
        
        # Handle media
        if message.media:
            if isinstance(message.media, MessageMediaPhoto):
                msg_dict['media_type'] = 'photo'
            elif isinstance(message.media, MessageMediaDocument):
                msg_dict['media_type'] = 'document'
            else:
                msg_dict['media_type'] = 'other'
            
            # Track messages with media for later download
            if track_media and message.id not in self.messages_with_media:
                self.messages_with_media.append(message.id)
                
            if download_media:
                try:
                    media_dir = os.path.join(self.output_dir, 'media')
                    os.makedirs(media_dir, exist_ok=True)
                    filename = f"{message.id}_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
                    full_path = os.path.join(media_dir, filename)
                    path = await message.download_media(file=full_path)
                    if path:
                        # Store relative path for HTML
                        msg_dict['media_path'] = f"media/{os.path.basename(path)}"
                except Exception as e:
                    print(f"Error downloading media for message {message.id}: {e}")
                
        return msg_dict
    
    def setup_output_files(self, base_filename: str, save_format: str):
        """Setup CSV, JSON and HTML files for incremental writing"""
        if save_format in ['csv', 'both', 'all']:
            csv_filename = os.path.join(self.output_dir, f"{base_filename}.csv")
            self.csv_file = open(csv_filename, 'w', newline='', encoding='utf-8')
            self.csv_writer = None
            print(f"CSV file created: {csv_filename}")
            
        if save_format in ['json', 'both', 'all']:
            json_filename = os.path.join(self.output_dir, f"{base_filename}.json")
            self.json_file = open(json_filename, 'w', encoding='utf-8')
            self.json_file.write('[\n')
            print(f"JSON file created: {json_filename}")
        
        if save_format in ['html', 'all']:
            html_filename = os.path.join(self.output_dir, f"{base_filename}.html")
            self.html_file = open(html_filename, 'w', encoding='utf-8')
            self.start_html_file()
            print(f"HTML file created: {html_filename}")
    
    def start_html_file(self):
        """Write HTML header and start of the document"""
        if self.html_file:
            html_header = """<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Telegram Channel Messages</title>
    <style>
        body {
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif;
            background: #f5f5f5;
            margin: 0;
            padding: 20px;
        }
        .container {
            max-width: 900px;
            margin: 0 auto;
        }
        .channel-header {
            background: white;
            padding: 20px;
            border-radius: 10px;
            margin-bottom: 20px;
            box-shadow: 0 2px 4px rgba(0,0,0,0.1);
        }
        .channel-title {
            font-size: 24px;
            font-weight: bold;
            color: #333;
            margin-bottom: 10px;
        }
        .channel-info {
            color: #666;
            font-size: 14px;
        }
        .message {
            background: white;
            margin-bottom: 15px;
            padding: 15px;
            border-radius: 10px;
            box-shadow: 0 2px 4px rgba(0,0,0,0.1);
        }
        .message-header {
            display: flex;
            justify-content: space-between;
            margin-bottom: 10px;
            padding-bottom: 10px;
            border-bottom: 1px solid #eee;
        }
        .sender {
            font-weight: bold;
            color: #0088cc;
        }
        .date {
            color: #999;
            font-size: 12px;
        }
        .message-text {
            line-height: 1.5;
            color: #333;
            white-space: pre-wrap;
            word-wrap: break-word;
        }
        .message-media {
            margin-top: 10px;
        }
        .message-media img {
            max-width: 100%;
            height: auto;
            border-radius: 5px;
        }
        .message-media video {
            max-width: 100%;
            height: auto;
            border-radius: 5px;
        }
        .media-placeholder {
            background: #f0f0f0;
            padding: 10px;
            border-radius: 5px;
            color: #666;
            font-style: italic;
        }
        .message-footer {
            margin-top: 10px;
            padding-top: 10px;
            border-top: 1px solid #eee;
            display: flex;
            gap: 20px;
            font-size: 12px;
            color: #999;
        }
        .loading {
            text-align: center;
            padding: 20px;
            color: #666;
        }
    </style>
</head>
<body>
    <div class="container">
        <div class="channel-header">
            <div class="channel-title">Telegram Channel Messages</div>
            <div class="channel-info">Downloaded on """ + datetime.now().strftime('%Y-%m-%d %H:%M:%S') + """</div>
        </div>
        <div id="messages">
"""
            self.html_file.write(html_header)
            self.html_file.flush()
    
    def write_message_incremental(self, message_data: Dict[str, Any], is_first: bool = False):
        """Write a single message to CSV, JSON and HTML files incrementally"""
        # Write to CSV
        if self.csv_file:
            if self.csv_writer is None:
                # First message - create CSV writer with headers
                self.csv_writer = csv.DictWriter(
                    self.csv_file, 
                    fieldnames=message_data.keys(),
                    extrasaction='ignore'
                )
                self.csv_writer.writeheader()
            self.csv_writer.writerow(message_data)
            self.csv_file.flush()
        
        # Write to JSON
        if self.json_file:
            if not is_first:
                self.json_file.write(',\n')
            json.dump(message_data, self.json_file, ensure_ascii=False, indent=2)
            self.json_file.flush()
        
        # Write to HTML
        if self.html_file:
            self.write_message_to_html(message_data)
    
    def write_message_to_html(self, message_data: Dict[str, Any]):
        """Write a single message to HTML file"""
        if not self.html_file:
            return
        
        sender_name = message_data.get('sender_name', 'Unknown')
        sender_username = message_data.get('sender_username', '')
        if sender_username:
            sender_display = f"{sender_name} (@{sender_username})"
        else:
            sender_display = sender_name
        
        date_str = message_data.get('date', '')
        if date_str:
            try:
                date_obj = datetime.fromisoformat(date_str)
                date_display = date_obj.strftime('%Y-%m-%d %H:%M:%S')
            except:
                date_display = date_str
        else:
            date_display = 'Unknown date'
        
        text = html.escape(message_data.get('text', '') or '')
        
        html_message = f"""
        <div class="message" data-message-id="{message_data.get('id', '')}">
            <div class="message-header">
                <span class="sender">{html.escape(sender_display)}</span>
                <span class="date">{date_display}</span>
            </div>
            <div class="message-text">{text}</div>
"""
        
        # Add media if present
        if message_data.get('media_path'):
            media_path = message_data.get('media_path', '')
            media_type = message_data.get('media_type', 'other')
            
            if media_type == 'photo' or media_path.lower().endswith(('.jpg', '.jpeg', '.png', '.gif', '.webp')):
                html_message += f"""
            <div class="message-media">
                <img src="{html.escape(media_path)}" alt="Image" loading="lazy">
            </div>
"""
            elif media_path.lower().endswith(('.mp4', '.webm', '.mov')):
                html_message += f"""
            <div class="message-media">
                <video controls>
                    <source src="{html.escape(media_path)}" type="video/mp4">
                    Your browser does not support the video tag.
                </video>
            </div>
"""
            else:
                html_message += f"""
            <div class="message-media">
                <div class="media-placeholder">
                    📎 Attachment: <a href="{html.escape(media_path)}">{html.escape(os.path.basename(media_path))}</a>
                </div>
            </div>
"""
        elif message_data.get('has_media'):
            media_type = message_data.get('media_type', 'media')
            html_message += f"""
            <div class="message-media">
                <div class="media-placeholder">
                    📎 {media_type.capitalize()} (not downloaded yet)
                </div>
            </div>
"""
        
        # Add footer with stats
        views = message_data.get('views', 0)
        forwards = message_data.get('forwards', 0)
        if views or forwards:
            html_message += """
            <div class="message-footer">
"""
            if views:
                html_message += f'                <span>👁 {views} views</span>\n'
            if forwards:
                html_message += f'                <span>↗️ {forwards} forwards</span>\n'
            html_message += """            </div>
"""
        
        html_message += """        </div>
"""
        
        self.html_file.write(html_message)
        self.html_file.flush()
    
    def update_html_message_media(self, message_id: int, media_path: str):
        """Update HTML file with downloaded media (requires re-reading and rewriting the file)"""
        # This would be complex to implement incrementally
        # For now, media will be added during the media download phase
        pass
    
    def find_existing_downloads(self, channel_title: str) -> List[Tuple[str, Dict]]:
        """Find existing progress files for a channel in the output directory"""
        existing_downloads = []
        
        # Search for progress files
        pattern = os.path.join(self.output_dir, "*_progress.json")
        progress_files = glob.glob(pattern)
        
        for progress_file in progress_files:
            try:
                with open(progress_file, 'r') as f:
                    progress_data = json.load(f)
                
                # Extract base filename (without _progress.json)
                base_name = os.path.basename(progress_file).replace('_progress.json', '')
                
                # Check if this might be for the same channel
                # (fuzzy match on channel name in filename)
                safe_title = re.sub(r'[^\w\s-]', '', channel_title)[:50]
                if safe_title.lower() in base_name.lower() or any(word in base_name.lower() for word in safe_title.lower().split()):
                    existing_downloads.append((base_name, progress_data))
            except:
                continue
        
        return existing_downloads
    
    def finalize_files(self):
        """Close all files properly"""
        if self.json_file:
            self.json_file.write('\n]')
            self.json_file.flush()
            
        if self.html_file:
            html_footer = """
        </div>
    </div>
</body>
</html>"""
            self.html_file.write(html_footer)
            self.html_file.flush()
    
    async def download_messages_incremental(
        self, 
        channel_input: Union[str, int],
        save_format: str = 'all',
        download_media_later: bool = True,
        batch_size: int = 50,
        max_messages: Optional[int] = None,
        resume: bool = True
    ):
        """Download messages incrementally - text first, then media"""
        
        channel = await self.get_entity_from_input(channel_input)
        channel_info = await self.get_channel_info(channel_input)
        channel_title = channel_info.get('title', 'unknown')
        
        base_filename = None
        
        # Check for existing downloads if resume is enabled
        if resume:
            existing_downloads = self.find_existing_downloads(channel_title)
            
            if existing_downloads:
                print("\n" + "="*60)
                print("EXISTING DOWNLOADS FOUND")
                print("="*60)
                
                for i, (filename, progress_data) in enumerate(existing_downloads, 1):
                    total = progress_data.get('total_downloaded', 0)
                    media_done = progress_data.get('media_downloaded', False)
                    media_status = "✓ Media downloaded" if media_done else "⚠ Media pending"
                    print(f"{i}. {filename}")
                    print(f"   Messages: {total} | {media_status}")
                
                print(f"{len(existing_downloads) + 1}. Start new download")
                
                choice = input(f"\nSelect option (1-{len(existing_downloads) + 1}): ")
                
                try:
                    choice_idx = int(choice) - 1
                    if 0 <= choice_idx < len(existing_downloads):
                        base_filename = existing_downloads[choice_idx][0]
                        print(f"\nResuming download: {base_filename}")
                except:
                    pass
        
        # Create new filename if not resuming
        if not base_filename:
            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
            safe_title = re.sub(r'[^\w\s-]', '', channel_title)[:50]
            base_filename = f"{safe_title}_{timestamp}"
        
        # Setup progress tracking
        progress_filename = f"{base_filename}_progress.json"
        progress = self.load_progress(progress_filename) if resume else {
            'last_message_id': 0, 
            'total_downloaded': 0, 
            'media_downloaded': False,
            'messages_with_media': []
        }
        
        print(f"\nDownloading from: {channel_title}")
        print(f"Channel ID: {channel_info.get('id', 'Unknown')}")
        
        # Check if text download is complete (last_message_id very low means we reached the end)
        text_download_complete = progress.get('last_message_id', 0) <= 10 and progress.get('total_downloaded', 0) > 0
        
        # Phase 1: Download text messages
        if not progress.get('media_downloaded', False) and not text_download_complete:
            print("\n" + "="*60)
            print("PHASE 1: Downloading text messages (fast)")
            print("="*60)
            
            if progress['total_downloaded'] > 0:
                print(f"✅ Resuming from message {progress['last_message_id']}")
                print(f"✅ Already downloaded: {progress['total_downloaded']} messages")
            
            # Setup output files
            self.setup_output_files(base_filename, save_format)
            
            total_downloaded = progress['total_downloaded']
            offset_id = progress['last_message_id']
            is_first = (total_downloaded == 0)
            start_time = time.time()
            
            try:
                while True:
                    if max_messages and total_downloaded >= max_messages:
                        break
                    
                    current_batch_size = batch_size
                    if max_messages:
                        current_batch_size = min(batch_size, max_messages - total_downloaded)
                    
                    print(f"\n[{datetime.now().strftime('%H:%M:%S')}] Fetching batch (offset: {offset_id})...")
                    
                    batch_count = 0
                    
                    try:
                        async for message in self.client.iter_messages(
                            channel,
                            limit=current_batch_size,
                            offset_id=offset_id,
                            reverse=False
                        ):
                            # Parse message WITHOUT downloading media
                            msg_data = await self._parse_message(message, download_media=False, track_media=True)
                            
                            # Write immediately
                            self.write_message_incremental(msg_data, is_first)
                            is_first = False
                            
                            batch_count += 1
                            total_downloaded += 1
                            
                            # Store the actual message ID for resuming
                            # Telegram messages go from high to low IDs
                            offset_id = message.id
                            
                            # Show progress every 10 messages
                            if batch_count % 10 == 0:
                                elapsed = time.time() - start_time
                                rate = total_downloaded / elapsed if elapsed > 0 else 0
                                print(f"  Downloaded: {total_downloaded} messages ({rate:.1f} msg/sec)")
                            
                            # Save progress periodically
                            if batch_count % 25 == 0:
                                progress = {
                                    'last_message_id': offset_id, 
                                    'total_downloaded': total_downloaded,
                                    'media_downloaded': False,
                                    'messages_with_media': self.messages_with_media
                                }
                                self.save_progress(progress_filename, progress)
                        
                    except FloodWaitError as e:
                        print(f"Rate limit hit! Waiting {e.seconds} seconds...")
                        await asyncio.sleep(e.seconds)
                        continue
                    
                    if batch_count == 0:
                        print("No more messages to download.")
                        break
                    
                    # Save progress after each batch
                    progress = {
                        'last_message_id': offset_id, 
                        'total_downloaded': total_downloaded,
                        'media_downloaded': False,
                        'messages_with_media': self.messages_with_media
                    }
                    self.save_progress(progress_filename, progress)
                    
                    print(f"Batch complete. Total messages: {total_downloaded}")
                    
                    # Small delay between batches
                    await asyncio.sleep(1)
                
                elapsed = time.time() - start_time
                print(f"\n{'='*60}")
                print(f"Text download complete!")
                print(f"Total messages: {total_downloaded}")
                print(f"Time taken: {elapsed/60:.1f} minutes")
                print(f"Average rate: {total_downloaded/elapsed if elapsed > 0 else 0:.1f} messages/second")
                print(f"Messages with media: {len(self.messages_with_media)}")
                print(f"{'='*60}")
                
            except KeyboardInterrupt:
                print("\n\nDownload interrupted by user.")
                print(f"Progress saved. Resume by running the script again.")
                print(f"Downloaded {total_downloaded} messages so far.")
                
            except Exception as e:
                print(f"\nError during download: {e}")
                print(f"Progress saved. Downloaded {total_downloaded} messages.")
            
            finally:
                # Finalize files
                self.finalize_files()
                if self.csv_file:
                    self.csv_file.close()
                if self.json_file:
                    self.json_file.close()
                if self.html_file:
                    self.html_file.close()
                
                # Mark text phase as complete if we finished all messages
                if text_download_complete or batch_count == 0:
                    progress['text_complete'] = True
                progress['media_downloaded'] = not download_media_later
                self.save_progress(progress_filename, progress)
        elif text_download_complete:
            print("\n" + "="*60)
            print("Text messages already downloaded!")
            print(f"Total messages: {progress.get('total_downloaded', 0)}")
            print(f"Messages with media: {len(progress.get('messages_with_media', []))}")
            print("="*60)
        
        # Phase 2: Download media if requested
        if download_media_later and len(self.messages_with_media) > 0 and not progress.get('media_downloaded', False):
            print("\n" + "="*60)
            print("PHASE 2: Downloading media files")
            print("="*60)
            print(f"Found {len(self.messages_with_media)} messages with media")
            
            download_media_now = input("\nDownload media files now? (y/n) [default: n]: ").lower() == 'y'
            
            if download_media_now:
                media_downloaded = 0
                media_skipped = 0
                media_start_time = time.time()
                media_dir = os.path.join(self.output_dir, 'media')
                os.makedirs(media_dir, exist_ok=True)
                
                # Get list of already downloaded media (by message ID prefix)
                existing_media = set()
                if os.path.exists(media_dir):
                    for filename in os.listdir(media_dir):
                        # Extract message ID from filename (e.g., "5861_20250904_141300.mp4" -> "5861")
                        if '_' in filename:
                            msg_id_str = filename.split('_')[0]
                            try:
                                existing_media.add(int(msg_id_str))
                            except ValueError:
                                pass
                
                print(f"Found {len(existing_media)} media files already downloaded")
                
                # Filter out already downloaded media
                media_to_download = [msg_id for msg_id in self.messages_with_media if msg_id not in existing_media]
                
                if len(media_to_download) == 0:
                    print("All media files already downloaded!")
                    progress['media_downloaded'] = True
                    self.save_progress(progress_filename, progress)
                else:
                    print(f"Need to download {len(media_to_download)} more media files")
                    
                    for i, msg_id in enumerate(media_to_download, 1):
                        try:
                            print(f"\r[{i}/{len(media_to_download)}] Downloading media for message {msg_id}...", end='')
                            
                            # Get the message again to download its media
                            message = await self.client.get_messages(channel, ids=msg_id)
                            if message and message.media:
                                filename = f"{message.id}_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
                                full_path = os.path.join(media_dir, filename)
                                await message.download_media(file=full_path)
                                media_downloaded += 1
                            
                            # Small delay to avoid rate limits
                            if i % 10 == 0:
                                await asyncio.sleep(1)
                                
                        except FloodWaitError as e:
                            print(f"\nRate limit hit! Waiting {e.seconds} seconds...")
                            await asyncio.sleep(e.seconds)
                        except Exception as e:
                            print(f"\nError downloading media for message {msg_id}: {e}")
                
                    media_elapsed = time.time() - media_start_time
                    print(f"\n\n{'='*60}")
                    print(f"Media download complete!")
                    print(f"Downloaded: {media_downloaded} new media files")
                    print(f"Already existed: {len(existing_media)} media files")
                    print(f"Total: {len(existing_media) + media_downloaded}/{len(self.messages_with_media)} media files")
                    print(f"Time taken: {media_elapsed/60:.1f} minutes")
                    print(f"{'='*60}")
                    
                    # Mark media as downloaded if all are done
                    if len(media_to_download) == media_downloaded:
                        progress['media_downloaded'] = True
                        self.save_progress(progress_filename, progress)
            else:
                print("Skipping media download. You can run the script again later to download media.")
        
        print(f"\n{'='*60}")
        print(f"All done! Files saved in: {self.output_dir}/")
        print(f"{'='*60}")


async def main():
    API_ID = int(os.getenv('API_ID', '0'))
    API_HASH = os.getenv('API_HASH', '')
    PHONE = os.getenv('PHONE', '')
    
    if not all([API_ID, API_HASH, PHONE]):
        print("Please set API_ID, API_HASH, and PHONE in your .env file")
        return
    
    print("\n" + "="*60)
    print("TELEGRAM INCREMENTAL DOWNLOADER V2")
    print("="*60)
    print("\nFeatures:")
    print("✓ Two-phase download: Text first (fast), Media later (optional)")
    print("✓ HTML export with embedded images and videos")
    print("✓ Real-time file saving")
    print("✓ Resume support")
    
    # Ask for output directory
    output_dir = input("\nEnter output directory (press Enter for 'downloads'): ").strip()
    if not output_dir:
        output_dir = "downloads"
    
    downloader = IncrementalTelegramDownloader(API_ID, API_HASH, PHONE, output_dir=output_dir)
    print(f"Messages will be saved to: {os.path.abspath(output_dir)}")
    
    try:
        await downloader.connect()
        
        print("\nOptions:")
        print("1. List all your channels/chats")
        print("2. Search for a channel by name")
        print("3. Enter channel identifier directly")
        
        main_choice = input("\nChoice (1/2/3): ")
        
        channel_identifier = None
        
        if main_choice == '1':
            print("\nFetching all your dialogs...")
            dialogs = await downloader.list_all_dialogs()
            channels = [d for d in dialogs if d.get('is_channel') or d.get('is_group')]
            
            if not channels:
                print("No channels or groups found!")
                return
            
            print(f"\nFound {len(channels)} channels/groups:")
            for i, dialog in enumerate(channels, 1):
                username = f" (@{dialog['username']})" if dialog.get('username') else ""
                print(f"{i}. {dialog['title']}{username} (ID: {dialog['id']})")
            
            choice_num = int(input("\nEnter number: ")) - 1
            if 0 <= choice_num < len(channels):
                channel_identifier = channels[choice_num]['id']
                
        elif main_choice == '2':
            search_term = input("Enter search term: ")
            results = await downloader.search_channels(search_term)
            
            if not results:
                print("No matching channels found!")
                return
            
            print(f"\nFound {len(results)} matching channels:")
            for i, ch in enumerate(results, 1):
                username = f" (@{ch['username']})" if ch.get('username') else ""
                print(f"{i}. {ch['title']}{username}")
            
            choice_num = int(input("\nEnter number: ")) - 1
            if 0 <= choice_num < len(results):
                channel_identifier = results[choice_num]['id']
                
        elif main_choice == '3':
            print("\nEnter username, channel link, or channel ID:")
            channel_identifier = input("Channel: ")
        
        if not channel_identifier:
            print("No channel selected!")
            return
        
        # Download options
        print("\n" + "="*60)
        print("DOWNLOAD OPTIONS")
        print("="*60)
        
        print("\nSave format options:")
        print("1. HTML only (best for viewing)")
        print("2. JSON only")
        print("3. CSV only")
        print("4. All formats (HTML + JSON + CSV)")
        
        format_choice = input("\nChoice (1/2/3/4) [default: 1]: ").strip() or "1"
        format_map = {"1": "html", "2": "json", "3": "csv", "4": "all"}
        save_format = format_map.get(format_choice, "html")
        
        max_messages_str = input("Maximum messages to download (leave empty for all): ")
        max_messages = int(max_messages_str) if max_messages_str else None
        
        batch_size = int(input("Batch size (10-200) [default: 100]: ") or "100")
        batch_size = max(10, min(200, batch_size))
        
        print("\n" + "="*60)
        print("Starting download... (Press Ctrl+C to pause)")
        print("="*60)
        
        await downloader.download_messages_incremental(
            channel_identifier,
            save_format=save_format,
            download_media_later=True,
            batch_size=batch_size,
            max_messages=max_messages,
            resume=True
        )
        
    except SessionPasswordNeededError:
        password = input("Two-factor authentication is enabled. Please enter your password: ")
        await downloader.connect(password=password)
        
    except Exception as e:
        print(f"An error occurred: {e}")
        import traceback
        traceback.print_exc()
        
    finally:
        await downloader.disconnect()


if __name__ == "__main__":
    asyncio.run(main())