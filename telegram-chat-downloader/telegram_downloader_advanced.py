import asyncio
import json
import os
import re
from datetime import datetime
from typing import Optional, List, Dict, Any, Union
import pandas as pd
from telethon import TelegramClient
from telethon.errors import SessionPasswordNeededError
from telethon.tl.types import (
    PeerChannel, Message, MessageMediaPhoto, MessageMediaDocument,
    Channel, Chat, User
)
from dotenv import load_dotenv

load_dotenv()


class AdvancedTelegramDownloader:
    def __init__(self, api_id: int, api_hash: str, phone: str, session_name: str = 'session', output_dir: str = 'downloads'):
        self.api_id = api_id
        self.api_hash = api_hash
        self.phone = phone
        self.session_name = session_name
        self.client = TelegramClient(session_name, api_id, api_hash)
        self.output_dir = output_dir
        os.makedirs(self.output_dir, exist_ok=True)
        
    async def connect(self, password: Optional[str] = None):
        await self.client.start(phone=self.phone, password=password)
        me = await self.client.get_me()
        print(f"Connected as {me.username or me.first_name}")
        
    async def disconnect(self):
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
        """
        Get entity from various input formats:
        - Username (with or without @)
        - Channel ID (numeric)
        - Channel invite link (t.me/joinchat/xxx or t.me/xxx)
        - Direct numeric ID
        """
        try:
            # Handle t.me links
            if 't.me/' in str(channel_input):
                # Extract username or invite hash from link
                match = re.search(r't\.me/(?:joinchat/)?([a-zA-Z0-9_\-]+)', str(channel_input))
                if match:
                    identifier = match.group(1)
                    if 'joinchat' in str(channel_input):
                        # It's an invite link
                        return await self.client.get_entity(f"https://t.me/joinchat/{identifier}")
                    else:
                        # It's a username link
                        channel_input = identifier
            
            # Handle username (remove @ if present)
            if isinstance(channel_input, str) and channel_input.startswith('@'):
                channel_input = channel_input[1:]
            
            # Try to parse as integer (channel ID)
            try:
                channel_id = int(channel_input)
                # Telegram channel IDs are negative 100 followed by the actual ID
                if channel_id > 0:
                    channel_id = -100 * (10 ** len(str(channel_id)) + channel_id)
                return await self.client.get_entity(channel_id)
            except (ValueError, TypeError):
                pass
            
            # Try as username or other string identifier
            return await self.client.get_entity(channel_input)
            
        except Exception as e:
            print(f"Could not resolve entity '{channel_input}': {e}")
            
            # If direct resolution fails, search through dialogs
            print("Searching through your dialogs...")
            async for dialog in self.client.iter_dialogs():
                # Check by ID
                if str(dialog.id) == str(channel_input):
                    return dialog.entity
                
                # Check by title (partial match)
                title = dialog.title or dialog.name or ""
                if str(channel_input).lower() in title.lower():
                    print(f"Found matching dialog: {title}")
                    return dialog.entity
            
            raise Exception(f"Could not find channel: {channel_input}")
    
    async def get_channel_info(self, channel_input: Union[str, int]) -> Dict[str, Any]:
        """Get channel information from various input formats"""
        try:
            channel = await self.get_entity_from_input(channel_input)
            
            info = {
                'id': channel.id,
                'title': getattr(channel, 'title', getattr(channel, 'first_name', 'Unknown')),
                'username': getattr(channel, 'username', None),
                'type': type(channel).__name__
            }
            
            # Add channel-specific info
            if isinstance(channel, Channel):
                info.update({
                    'participants_count': getattr(channel, 'participants_count', None),
                    'date': getattr(channel, 'date', None),
                    'megagroup': channel.megagroup,
                    'restricted': getattr(channel, 'restricted', False),
                    'verified': getattr(channel, 'verified', False),
                    'about': getattr(channel, 'about', None)
                })
            
            # Get full channel info if available
            if hasattr(channel, 'full_chat'):
                full = await self.client(GetFullChannelRequest(channel))
                if full:
                    info['about'] = getattr(full.full_chat, 'about', None)
                    info['participants_count'] = getattr(full.full_chat, 'participants_count', None)
            
            return info
            
        except Exception as e:
            print(f"Error getting channel info: {e}")
            return {}
    
    async def download_messages(
        self, 
        channel_input: Union[str, int], 
        limit: int = 100, 
        offset_id: int = 0,
        min_id: int = 0,
        max_id: int = 0,
        download_media: bool = False
    ) -> List[Dict[str, Any]]:
        """Download messages from channel using various input formats"""
        
        channel = await self.get_entity_from_input(channel_input)
        messages_data = []
        
        async for message in self.client.iter_messages(
            channel,
            limit=limit,
            offset_id=offset_id,
            min_id=min_id,
            max_id=max_id
        ):
            msg_data = await self._parse_message(message, download_media)
            messages_data.append(msg_data)
            
        return messages_data
    
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
        
        # Add sender information if available
        if message.sender:
            if isinstance(message.sender, User):
                msg_dict['sender_name'] = f"{message.sender.first_name or ''} {message.sender.last_name or ''}".strip()
                msg_dict['sender_username'] = message.sender.username
            elif isinstance(message.sender, (Channel, Chat)):
                msg_dict['sender_name'] = message.sender.title
                msg_dict['sender_username'] = getattr(message.sender, 'username', None)
        
        if message.media and download_media:
            media_path = await self._download_media(message)
            msg_dict['media_path'] = media_path
            
            if isinstance(message.media, MessageMediaPhoto):
                msg_dict['media_type'] = 'photo'
            elif isinstance(message.media, MessageMediaDocument):
                msg_dict['media_type'] = 'document'
            else:
                msg_dict['media_type'] = 'other'
                
        return msg_dict
    
    async def _download_media(self, message: Message) -> Optional[str]:
        try:
            media_dir = os.path.join(self.output_dir, 'media')
            os.makedirs(media_dir, exist_ok=True)
            filename = f"{media_dir}/{message.id}_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
            path = await message.download_media(file=filename)
            return path
        except Exception as e:
            print(f"Error downloading media for message {message.id}: {e}")
            return None
    
    async def download_all_messages(
        self, 
        channel_input: Union[str, int],
        batch_size: int = 100,
        download_media: bool = False
    ) -> List[Dict[str, Any]]:
        """Download all messages from channel"""
        
        all_messages = []
        offset_id = 0
        
        channel_info = await self.get_channel_info(channel_input)
        print(f"Downloading from: {channel_info.get('title', 'Unknown')}")
        print(f"Channel ID: {channel_info.get('id', 'Unknown')}")
        
        while True:
            print(f"Downloading batch starting from message ID {offset_id}...")
            messages = await self.download_messages(
                channel_input,
                limit=batch_size,
                offset_id=offset_id,
                download_media=download_media
            )
            
            if not messages:
                break
                
            all_messages.extend(messages)
            offset_id = messages[-1]['id']
            print(f"Downloaded {len(all_messages)} messages so far...")
            
            await asyncio.sleep(1)
            
        return all_messages
    
    def save_to_json(self, messages: List[Dict[str, Any]], filename: str = 'messages.json'):
        filepath = os.path.join(self.output_dir, filename)
        with open(filepath, 'w', encoding='utf-8') as f:
            json.dump(messages, f, ensure_ascii=False, indent=2)
        print(f"Saved {len(messages)} messages to {filepath}")
        
    def save_to_csv(self, messages: List[Dict[str, Any]], filename: str = 'messages.csv'):
        filepath = os.path.join(self.output_dir, filename)
        df = pd.DataFrame(messages)
        df.to_csv(filepath, index=False, encoding='utf-8')
        print(f"Saved {len(messages)} messages to {filepath}")
        
    async def search_messages(
        self,
        channel_input: Union[str, int],
        search_query: str,
        limit: int = 100
    ) -> List[Dict[str, Any]]:
        """Search messages in channel"""
        
        channel = await self.get_entity_from_input(channel_input)
        messages_data = []
        
        async for message in self.client.iter_messages(
            channel,
            search=search_query,
            limit=limit
        ):
            msg_data = await self._parse_message(message)
            messages_data.append(msg_data)
            
        return messages_data


async def main():
    API_ID = int(os.getenv('API_ID', '0'))
    API_HASH = os.getenv('API_HASH', '')
    PHONE = os.getenv('PHONE', '')
    
    if not all([API_ID, API_HASH, PHONE]):
        print("Please set API_ID, API_HASH, and PHONE in your .env file")
        print("\nTo get your API credentials:")
        print("1. Go to https://my.telegram.org")
        print("2. Log in with your phone number")
        print("3. Go to 'API development tools'")
        print("4. Create an app if you haven't already")
        print("5. Copy your api_id and api_hash")
        return
    
    print("\n" + "="*60)
    print("TELEGRAM CHANNEL DOWNLOADER - ADVANCED")
    print("="*60)
    
    # Ask for output directory
    output_dir = input("\nEnter output directory (press Enter for 'downloads'): ").strip()
    if not output_dir:
        output_dir = "downloads"
    
    downloader = AdvancedTelegramDownloader(API_ID, API_HASH, PHONE, output_dir=output_dir)
    print(f"Messages will be saved to: {os.path.abspath(output_dir)}")
    
    try:
        await downloader.connect()
        
        print("\nOptions:")
        print("1. List all your channels/chats")
        print("2. Search for a channel by name")
        print("3. Download from specific channel")
        print("4. Enter channel ID directly")
        
        main_choice = input("\nChoice (1/2/3/4): ")
        
        channel_identifier = None
        
        if main_choice == '1':
            print("\nFetching all your dialogs...")
            dialogs = await downloader.list_all_dialogs()
            
            # Filter to show only channels and groups
            channels = [d for d in dialogs if d.get('is_channel') or d.get('is_group')]
            
            if not channels:
                print("No channels or groups found!")
                return
            
            print(f"\nFound {len(channels)} channels/groups:")
            print("-" * 60)
            
            for i, dialog in enumerate(channels, 1):
                username = f" (@{dialog['username']})" if dialog.get('username') else ""
                participants = f" - {dialog.get('participants_count', 'N/A')} members" if dialog.get('participants_count') else ""
                print(f"{i}. {dialog['title']}{username} (ID: {dialog['id']}){participants}")
            
            choice_num = int(input("\nEnter number to select channel: ")) - 1
            if 0 <= choice_num < len(channels):
                channel_identifier = channels[choice_num]['id']
            else:
                print("Invalid selection")
                return
                
        elif main_choice == '2':
            search_term = input("Enter search term: ")
            results = await downloader.search_channels(search_term)
            
            if not results:
                print("No matching channels found!")
                return
            
            print(f"\nFound {len(results)} matching channels:")
            for i, ch in enumerate(results, 1):
                username = f" (@{ch['username']})" if ch.get('username') else ""
                print(f"{i}. {ch['title']}{username} (ID: {ch['id']})")
            
            choice_num = int(input("\nEnter number to select channel: ")) - 1
            if 0 <= choice_num < len(results):
                channel_identifier = results[choice_num]['id']
            else:
                print("Invalid selection")
                return
                
        elif main_choice == '3':
            print("\nYou can enter:")
            print("- Username (with or without @)")
            print("- Channel link (t.me/channelname)")
            print("- Invite link (t.me/joinchat/...)")
            print("- Channel ID (numeric)")
            channel_identifier = input("\nEnter channel identifier: ")
            
        elif main_choice == '4':
            channel_identifier = input("Enter channel ID (numeric): ")
        else:
            print("Invalid choice")
            return
        
        if not channel_identifier:
            print("No channel selected!")
            return
        
        # Get and display channel info
        channel_info = await downloader.get_channel_info(channel_identifier)
        if channel_info:
            print(f"\n{'='*60}")
            print("CHANNEL INFORMATION:")
            print('-'*60)
            for key, value in channel_info.items():
                if value is not None:
                    print(f"{key}: {value}")
            print('='*60)
        
        # Download options
        print("\nDownload Options:")
        print("1. Download recent messages")
        print("2. Download all messages")
        print("3. Search messages")
        
        download_choice = input("\nChoice (1/2/3): ")
        
        messages = []
        
        if download_choice == '1':
            limit = int(input("How many recent messages to download? "))
            download_media = input("Download media files? (y/n): ").lower() == 'y'
            
            messages = await downloader.download_messages(
                channel_identifier,
                limit=limit,
                download_media=download_media
            )
            
        elif download_choice == '2':
            download_media = input("Download media files? (y/n): ").lower() == 'y'
            messages = await downloader.download_all_messages(
                channel_identifier,
                download_media=download_media
            )
            
        elif download_choice == '3':
            search_query = input("Enter search query: ")
            limit = int(input("Maximum results: "))
            messages = await downloader.search_messages(
                channel_identifier,
                search_query,
                limit
            )
        else:
            print("Invalid choice")
            return
        
        if messages:
            save_format = input("\nSave as (json/csv/both): ").lower()
            
            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
            safe_title = re.sub(r'[^\w\s-]', '', channel_info.get('title', 'unknown'))[:50]
            base_filename = f"{safe_title}_{timestamp}"
            
            if save_format in ['json', 'both']:
                downloader.save_to_json(messages, f"{base_filename}.json")
            if save_format in ['csv', 'both']:
                downloader.save_to_csv(messages, f"{base_filename}.csv")
                
            print(f"\n{'='*60}")
            print(f"SUCCESS: Downloaded {len(messages)} messages!")
            print(f"{'='*60}")
        else:
            print("\nNo messages downloaded.")
        
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