import asyncio
import json
import os
from datetime import datetime
from typing import Optional, List, Dict, Any
import pandas as pd
from telethon import TelegramClient
from telethon.errors import SessionPasswordNeededError
from telethon.tl.functions.messages import GetHistoryRequest
from telethon.tl.types import PeerChannel, Message, MessageMediaPhoto, MessageMediaDocument
from dotenv import load_dotenv

load_dotenv()


class TelegramChannelDownloader:
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
        print(f"Connected as {(await self.client.get_me()).username}")
        
    async def disconnect(self):
        await self.client.disconnect()
        
    async def get_channel_info(self, channel_username: str) -> Dict[str, Any]:
        try:
            channel = await self.client.get_entity(channel_username)
            return {
                'id': channel.id,
                'title': channel.title,
                'username': getattr(channel, 'username', None),
                'participants_count': getattr(channel, 'participants_count', None),
                'date': getattr(channel, 'date', None),
                'about': getattr(channel, 'about', None)
            }
        except Exception as e:
            print(f"Error getting channel info: {e}")
            return {}
    
    async def download_messages(
        self, 
        channel_username: str, 
        limit: int = 100, 
        offset_id: int = 0,
        min_id: int = 0,
        max_id: int = 0,
        download_media: bool = False
    ) -> List[Dict[str, Any]]:
        
        channel = await self.client.get_entity(channel_username)
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
        channel_username: str,
        batch_size: int = 100,
        download_media: bool = False
    ) -> List[Dict[str, Any]]:
        
        all_messages = []
        offset_id = 0
        
        channel_info = await self.get_channel_info(channel_username)
        print(f"Downloading from channel: {channel_info.get('title', channel_username)}")
        
        while True:
            print(f"Downloading batch starting from message ID {offset_id}...")
            messages = await self.download_messages(
                channel_username,
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
        channel_username: str,
        search_query: str,
        limit: int = 100
    ) -> List[Dict[str, Any]]:
        
        channel = await self.client.get_entity(channel_username)
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
    
    # Ask for output directory
    output_dir = input("Enter output directory (press Enter for 'downloads'): ").strip()
    if not output_dir:
        output_dir = "downloads"
    
    downloader = TelegramChannelDownloader(API_ID, API_HASH, PHONE, output_dir=output_dir)
    print(f"Messages will be saved to: {os.path.abspath(output_dir)}")
    
    try:
        await downloader.connect()
        
        channel_username = input("\nEnter channel username (without @): ")
        
        channel_info = await downloader.get_channel_info(channel_username)
        print(f"\nChannel Information:")
        for key, value in channel_info.items():
            print(f"  {key}: {value}")
        
        download_choice = input("\nOptions:\n1. Download recent messages\n2. Download all messages\n3. Search messages\nChoice (1/2/3): ")
        
        if download_choice == '1':
            limit = int(input("How many recent messages to download? "))
            download_media = input("Download media files? (y/n): ").lower() == 'y'
            
            messages = await downloader.download_messages(
                channel_username,
                limit=limit,
                download_media=download_media
            )
            
        elif download_choice == '2':
            download_media = input("Download media files? (y/n): ").lower() == 'y'
            messages = await downloader.download_all_messages(
                channel_username,
                download_media=download_media
            )
            
        elif download_choice == '3':
            search_query = input("Enter search query: ")
            limit = int(input("Maximum results: "))
            messages = await downloader.search_messages(
                channel_username,
                search_query,
                limit
            )
        else:
            print("Invalid choice")
            return
        
        if messages:
            save_format = input("\nSave as (json/csv/both): ").lower()
            
            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
            base_filename = f"{channel_username}_{timestamp}"
            
            if save_format in ['json', 'both']:
                downloader.save_to_json(messages, f"{base_filename}.json")
            if save_format in ['csv', 'both']:
                downloader.save_to_csv(messages, f"{base_filename}.csv")
                
            print(f"\nSuccessfully downloaded {len(messages)} messages!")
        
    except SessionPasswordNeededError:
        password = input("Two-factor authentication is enabled. Please enter your password: ")
        await downloader.connect(password=password)
        
    except Exception as e:
        print(f"An error occurred: {e}")
        
    finally:
        await downloader.disconnect()


if __name__ == "__main__":
    asyncio.run(main())