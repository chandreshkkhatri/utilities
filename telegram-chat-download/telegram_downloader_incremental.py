import asyncio
import json
import os
import re
import csv
from datetime import datetime
from typing import Optional, List, Dict, Any, Union
from telethon import TelegramClient
from telethon.errors import SessionPasswordNeededError, FloodWaitError
from telethon.tl.types import (
    PeerChannel, Message, MessageMediaPhoto, MessageMediaDocument,
    Channel, Chat, User
)
from dotenv import load_dotenv
import time

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
        self.progress_file = None
        
    async def connect(self, password: Optional[str] = None):
        await self.client.start(phone=self.phone, password=password)
        me = await self.client.get_me()
        print(f"Connected as {me.username or me.first_name}")
        
    async def disconnect(self):
        if self.csv_file:
            self.csv_file.close()
        if self.json_file:
            self.json_file.close()
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
                return json.load(f)
        return {'last_message_id': 0, 'total_downloaded': 0}
    
    def save_progress(self, filename: str, progress: Dict[str, Any]):
        """Save download progress to file"""
        filepath = os.path.join(self.output_dir, filename)
        with open(filepath, 'w') as f:
            json.dump(progress, f)
    
    async def _parse_message(self, message: Message, download_media: bool = False) -> Dict[str, Any]:
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
            'media_path': None
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
                
            if download_media:
                try:
                    media_dir = os.path.join(self.output_dir, 'media')
                    os.makedirs(media_dir, exist_ok=True)
                    filename = f"{media_dir}/{message.id}_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
                    path = await message.download_media(file=filename)
                    msg_dict['media_path'] = path
                except Exception as e:
                    print(f"Error downloading media for message {message.id}: {e}")
                
        return msg_dict
    
    def setup_output_files(self, base_filename: str, save_format: str):
        """Setup CSV and JSON files for incremental writing"""
        if save_format in ['csv', 'both']:
            csv_filename = os.path.join(self.output_dir, f"{base_filename}.csv")
            self.csv_file = open(csv_filename, 'w', newline='', encoding='utf-8')
            self.csv_writer = None
            print(f"CSV file created: {csv_filename}")
            
        if save_format in ['json', 'both']:
            json_filename = os.path.join(self.output_dir, f"{base_filename}.json")
            self.json_file = open(json_filename, 'w', encoding='utf-8')
            self.json_file.write('[\n')
            print(f"JSON file created: {json_filename}")
    
    def write_message_incremental(self, message_data: Dict[str, Any], is_first: bool = False):
        """Write a single message to CSV and/or JSON files incrementally"""
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
    
    def finalize_json_file(self):
        """Close the JSON array properly"""
        if self.json_file:
            self.json_file.write('\n]')
            self.json_file.flush()
    
    async def download_messages_incremental(
        self, 
        channel_input: Union[str, int],
        save_format: str = 'both',
        download_media: bool = False,
        batch_size: int = 50,
        max_messages: Optional[int] = None,
        resume: bool = True
    ):
        """Download messages incrementally with real-time saving"""
        
        channel = await self.get_entity_from_input(channel_input)
        channel_info = await self.get_channel_info(channel_input)
        
        # Setup filenames
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        safe_title = re.sub(r'[^\w\s-]', '', channel_info.get('title', 'unknown'))[:50]
        base_filename = f"{safe_title}_{timestamp}"
        
        # Setup progress tracking
        progress_filename = f"{base_filename}_progress.json"
        progress = self.load_progress(progress_filename) if resume else {'last_message_id': 0, 'total_downloaded': 0}
        
        print(f"\nDownloading from: {channel_info.get('title', 'Unknown')}")
        print(f"Channel ID: {channel_info.get('id', 'Unknown')}")
        if progress['total_downloaded'] > 0:
            print(f"Resuming from message {progress['last_message_id']} (already downloaded: {progress['total_downloaded']})")
        
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
                
                batch_messages = []
                batch_count = 0
                
                try:
                    async for message in self.client.iter_messages(
                        channel,
                        limit=current_batch_size,
                        offset_id=offset_id,
                        reverse=False
                    ):
                        # Parse message
                        msg_data = await self._parse_message(message, download_media)
                        
                        # Write immediately
                        self.write_message_incremental(msg_data, is_first)
                        is_first = False
                        
                        batch_count += 1
                        total_downloaded += 1
                        offset_id = message.id
                        
                        # Show progress every 10 messages
                        if batch_count % 10 == 0:
                            elapsed = time.time() - start_time
                            rate = total_downloaded / elapsed if elapsed > 0 else 0
                            print(f"  Downloaded: {total_downloaded} messages ({rate:.1f} msg/sec)")
                        
                        # Save progress periodically
                        if batch_count % 25 == 0:
                            progress = {'last_message_id': offset_id, 'total_downloaded': total_downloaded}
                            self.save_progress(progress_filename, progress)
                    
                except FloodWaitError as e:
                    print(f"Rate limit hit! Waiting {e.seconds} seconds...")
                    await asyncio.sleep(e.seconds)
                    continue
                
                if batch_count == 0:
                    print("No more messages to download.")
                    break
                
                # Save progress after each batch
                progress = {'last_message_id': offset_id, 'total_downloaded': total_downloaded}
                self.save_progress(progress_filename, progress)
                
                print(f"Batch complete. Total messages: {total_downloaded}")
                
                # Small delay between batches
                await asyncio.sleep(1)
            
        except KeyboardInterrupt:
            print("\n\nDownload interrupted by user.")
            print(f"Progress saved. Resume by running the script again.")
            print(f"Downloaded {total_downloaded} messages so far.")
            
        except Exception as e:
            print(f"\nError during download: {e}")
            print(f"Progress saved. Downloaded {total_downloaded} messages.")
            
        finally:
            # Finalize files
            self.finalize_json_file()
            if self.csv_file:
                self.csv_file.close()
            if self.json_file:
                self.json_file.close()
            
            # Save final progress
            progress = {'last_message_id': offset_id, 'total_downloaded': total_downloaded}
            self.save_progress(progress_filename, progress)
            
            elapsed = time.time() - start_time
            print(f"\n{'='*60}")
            print(f"Download Complete!")
            print(f"Total messages: {total_downloaded}")
            print(f"Time taken: {elapsed/60:.1f} minutes")
            print(f"Average rate: {total_downloaded/elapsed:.1f} messages/second")
            print(f"Files saved in: {self.output_dir}/")
            print(f"{'='*60}")


async def main():
    API_ID = int(os.getenv('API_ID', '0'))
    API_HASH = os.getenv('API_HASH', '')
    PHONE = os.getenv('PHONE', '')
    
    if not all([API_ID, API_HASH, PHONE]):
        print("Please set API_ID, API_HASH, and PHONE in your .env file")
        return
    
    print("\n" + "="*60)
    print("TELEGRAM INCREMENTAL DOWNLOADER")
    print("="*60)
    print("\nFeatures:")
    print("✓ Real-time file saving (messages saved immediately)")
    print("✓ Resume support (continue interrupted downloads)")
    print("✓ Progress tracking")
    print("✓ Faster without media downloads")
    
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
        
        save_format = input("Save format (json/csv/both) [default: both]: ").lower() or 'both'
        
        download_media = input("Download media files? (y/n) [default: n]: ").lower() == 'y'
        if download_media:
            print("⚠️  Warning: Media downloads significantly slow down the process!")
        
        max_messages_str = input("Maximum messages to download (leave empty for all): ")
        max_messages = int(max_messages_str) if max_messages_str else None
        
        batch_size = int(input("Batch size (10-200) [default: 50]: ") or "50")
        batch_size = max(10, min(200, batch_size))
        
        print("\n" + "="*60)
        print("Starting download... (Press Ctrl+C to pause)")
        print("="*60)
        
        await downloader.download_messages_incremental(
            channel_identifier,
            save_format=save_format,
            download_media=download_media,
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