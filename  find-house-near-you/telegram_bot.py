import os
import json
import csv
import time
import re
from typing import Any, Dict, Optional, Tuple

from telethon.sync import TelegramClient
from telethon.errors import SessionPasswordNeededError
from dotenv import load_dotenv
import openai
import googlemaps

try:
    from google import genai
    from google.genai import types
except ImportError:
    genai = None
    types = None

# Load environment variables
load_dotenv()


class QuotaExceededError(Exception):
    """Custom exception raised when LLM API quota or rate limit is completely exhausted."""
    pass


class HouseHuntingBot:
    def __init__(self):
        # Telegram credentials
        self.api_id = int(os.getenv('TELEGRAM_API_ID') or 0)
        self.api_hash = str(os.getenv('TELEGRAM_API_HASH'))
        self.phone = os.getenv('TELEGRAM_PHONE')
        self.target_chat = os.getenv('TARGET_CHAT', 'me')
        self.target_peer_id = os.getenv('TARGET_PEER_ID')
        if self.target_peer_id:
            self.target_peer_id = self.target_peer_id.strip().strip("'\"")

        # LLM Provider Configuration
        self.model_provider = os.getenv('MODEL_PROVIDER', 'openai').strip().lower()
        self.model_name = os.getenv('MODEL_NAME')

        # OpenAI setup
        openai.api_key = os.getenv('OPENAI_API_KEY')

        # Google Maps setup
        self.gmaps: Any = googlemaps.Client(
            key=os.getenv('GOOGLE_MAPS_API_KEY'))

        # Office location
        self.office_lat = float(os.getenv('OFFICE_LATITUDE', '28.7041'))
        self.office_lon = float(os.getenv('OFFICE_LONGITUDE', '77.1025'))
        self.office_address = os.getenv('OFFICE_ADDRESS', 'Delhi, India')

        # Results storage
        self.results = []

    def call_llm(self, prompt: str, system_instruction: Optional[str] = None, json_mode: bool = False, max_tokens: int = 300, temperature: float = 0.1, retries: int = 3) -> Optional[str]:
        """A unified method to call either OpenAI or Gemini depending on setup, with retry logic for rate limits."""
        for attempt in range(retries):
            if self.model_provider == 'gemini':
                if genai is None or types is None:
                    print("Error: google-genai library is not installed.")
                    return None
                try:
                    if not hasattr(self, 'gemini_client'):
                        api_key = os.getenv('GEMINI_API_KEY')
                        if api_key:
                            self.gemini_client = genai.Client(api_key=api_key)
                        else:
                            self.gemini_client = genai.Client()
                    
                    model = self.model_name or 'gemini-2.5-flash'
                    
                    config_args = {
                        'temperature': temperature,
                    }
                    if system_instruction:
                        config_args['system_instruction'] = system_instruction
                    if json_mode:
                        config_args['response_mime_type'] = 'application/json'
                    if max_tokens:
                        config_args['max_output_tokens'] = max_tokens
                    
                    config = types.GenerateContentConfig(**config_args)
                    
                    response = self.gemini_client.models.generate_content(
                        model=model,
                        contents=prompt,
                        config=config
                    )
                    return response.text
                except Exception as e:
                    err_str = str(e)
                    is_rate_limit = "429" in err_str or "RESOURCE_EXHAUSTED" in err_str or "Quota exceeded" in err_str or "limit exceeded" in err_str.lower()
                    if is_rate_limit and attempt < retries - 1:
                        wait_time = 5
                        match = re.search(r"retry in ([\d\.]+)s", err_str, re.IGNORECASE)
                        if match:
                            wait_time = int(float(match.group(1))) + 1
                        print(f"⚠️ Gemini rate limit hit. Waiting {wait_time}s before retry (attempt {attempt+1}/{retries})...")
                        time.sleep(wait_time)
                        continue
                    elif is_rate_limit:
                        raise QuotaExceededError(f"Gemini quota exhausted: {e}")
                    else:
                        print(f"Error calling Gemini: {e}")
                        return None
            else: # Default to OpenAI
                try:
                    model = self.model_name or 'gpt-4o-mini'
                    
                    messages = []
                    if system_instruction:
                        messages.append({"role": "system", "content": system_instruction})
                    messages.append({"role": "user", "content": prompt})
                    
                    kwargs = {
                        "model": model,
                        "messages": messages,
                        "temperature": temperature
                    }
                    if max_tokens:
                        kwargs["max_tokens"] = max_tokens
                    if json_mode:
                        kwargs["response_format"] = {"type": "json_object"}
                    
                    response = openai.chat.completions.create(**kwargs)
                    return response.choices[0].message.content
                except Exception as e:
                    err_str = str(e)
                    is_rate_limit = "429" in err_str or "insufficient_quota" in err_str or "Rate limit" in err_str
                    if is_rate_limit and attempt < retries - 1:
                        print(f"⚠️ OpenAI rate limit hit. Waiting 5s before retry (attempt {attempt+1}/{retries})...")
                        time.sleep(5)
                        continue
                    elif is_rate_limit:
                        raise QuotaExceededError(f"OpenAI quota exhausted: {e}")
                    else:
                        print(f"Error calling OpenAI: {e}")
                        return None

    def extract_location_with_gpt(self, message_text: str) -> Optional[Dict]:
        """Use LLM (OpenAI or Gemini) to extract location and rental information from message text."""
        try:
            prompt = f"""
            Analyze this rental property message and extract the following information in JSON format:
            - location: The specific area/locality/neighborhood mentioned
            - city: The city name
            - rent: The rental amount mentioned (extract number only)
            - bhk: Number of bedrooms (1BHK, 2BHK, etc.)
            - additional_details: Any other relevant details (furnished, parking, etc.)
            
            Message: "{message_text}"
            
            Return only valid JSON. If no clear location is found, return null for location.
            """

            result = self.call_llm(
                prompt=prompt,
                system_instruction="You are a helpful assistant that extracts location and rental information from text messages. Always respond with valid JSON.",
                json_mode=True,
                max_tokens=300,
                temperature=0.1
            )

            if not result:
                return None

            result = result.strip()
            # Robust JSON extraction looking for outer curly braces
            match = re.search(r'(\{.*\})', result, re.DOTALL)
            if match:
                json_str = match.group(1)
            else:
                json_str = result

            try:
                return json.loads(json_str)
            except json.JSONDecodeError as jde:
                print(f"⚠️ Failed to parse LLM JSON response: {jde}. Raw response was: {result!r}")
                return None

        except QuotaExceededError:
            raise
        except Exception as e:
            print(f"Error extracting location: {e}")
            return None


    def get_coordinates(self, location: str, city: Optional[str] = None) -> Optional[Tuple[float, float]]:
        """Get latitude and longitude for a location using Google Maps."""
        try:
            full_address = location
            if city and city.lower() not in location.lower():
                full_address = f"{location}, {city}"

            geocode_result = self.gmaps.geocode(full_address)
            if geocode_result:
                lat = geocode_result[0]['geometry']['location']['lat']
                lon = geocode_result[0]['geometry']['location']['lng']
                return (lat, lon)
            return None
        except Exception as e:
            print(f"Error geocoding location '{location}': {e}")
            return None

    def calculate_distance(self, lat: float, lon: float) -> Optional[Dict]:
        """Calculate distance and duration from office location using Google Maps."""
        try:
            office_coords = (self.office_lat, self.office_lon)
            property_coords = (lat, lon)
            matrix = self.gmaps.distance_matrix(
                office_coords, property_coords, mode="driving")

            if matrix['rows'][0]['elements'][0]['status'] == 'OK':
                distance_km = matrix['rows'][0]['elements'][0]['distance']['value'] / 1000
                duration_text = matrix['rows'][0]['elements'][0]['duration']['text']
                return {
                    'distance_km': round(distance_km, 2),
                    'duration': duration_text
                }
            return None
        except Exception as e:
            print(f"Error calculating distance: {e}")
            return None

    def get_telegram_link(self, message, chat_entity) -> Optional[str]:
        """Generate a Telegram link to the specific message."""
        # Try public username first
        username = getattr(chat_entity, 'username', None)
        if username:
            return f"https://t.me/{username}/{message.id}"
        # Fallback to chat ID based link for groups, supergroups, or private chats
        chat_id = getattr(chat_entity, 'id', None)
        if chat_id is not None:
            id_str = str(chat_id)
            # For supergroups, remove '-100' prefix
            if id_str.startswith('-100'):
                clean_id = id_str[4:]
            # For other negative IDs, remove leading '-'
            elif id_str.startswith('-'):
                clean_id = id_str[1:]
            else:
                clean_id = id_str
            return f"https://t.me/c/{clean_id}/{message.id}"
        return None

    def process_message(self, message, chat_entity=None) -> Optional[Dict]:
        """Process a single message and extract rental information."""
        if not message.text:
            return None
        # Extract property details
        extracted_info = self.extract_location_with_gpt(message.text)
        if not extracted_info or not extracted_info.get('location'):
            return None
        # Geocoding
        coords = self.get_coordinates(
            extracted_info['location'], extracted_info.get('city'))
        if not coords:
            return None
        lat, lon = coords
        # Distance calculation
        dist_info = self.calculate_distance(lat, lon)
        if not dist_info:
            return None
        # Telegram link
        link = self.get_telegram_link(
            message, chat_entity) if chat_entity else None
        # Build result
        result = {
            'message_id': message.id,
            'date': message.date.strftime('%Y-%m-%d %H:%M'),
            'location': extracted_info['location'],
            'city': extracted_info.get('city'),
            'rent': extracted_info.get('rent'),
            'bhk': extracted_info.get('bhk'),
            'additional_details': extracted_info.get('additional_details'),
            'latitude': lat,
            'longitude': lon,
            'distance_from_office_km': dist_info['distance_km'],
            'driving_duration': dist_info['duration'],
            'telegram_link': link,
            'original_message': message.text[:200] + '...' if len(message.text) > 200 else message.text
        }
        return result

    def run_analysis(self, limit: Optional[int] = None):
        """Main function to run the analysis."""
        print(f"🏠 House Hunting Bot Started")
        print(f"📍 Office Location: {self.office_address}")

        target_info = self.target_peer_id if self.target_peer_id else self.target_chat
        print(f"📱 Analyzing messages from: {target_info}")
        print("-" * 50)

        with TelegramClient("tg_session", self.api_id, self.api_hash) as client:
            # Login
            try:
                client.sign_in(self.phone)
            except SessionPasswordNeededError:
                pw = input("Two-step password: ")
                client.sign_in(password=pw)

            print(f"✅ Connected to Telegram")

            # Determine target entity (always fetch the Entity object)
            if self.target_peer_id:
                # telethon can get entity from integer peer id
                try:
                    target_entity = client.get_entity(int(self.target_peer_id))
                except (ValueError, TypeError):
                    print(
                        f"⚠️ Invalid TARGET_PEER_ID: '{self.target_peer_id}'. Must be an integer. Falling back to TARGET_CHAT.")
                    target_entity = client.get_entity(self.target_chat)
                except Exception as e:
                    print(
                        f"⚠️ Could not find entity for peer ID {self.target_peer_id}: {e}. Falling back to TARGET_CHAT.")
                    target_entity = client.get_entity(self.target_chat)
            else:
                # Fetch entity for target_chat (username or ID)
                target_entity = client.get_entity(self.target_chat)

            if isinstance(target_entity, str):
                entity_name = target_entity
            else:
                entity_name = getattr(target_entity, 'title', None) or \
                    getattr(target_entity, 'username', None) or \
                    f"Peer {getattr(target_entity, 'id', 'Unknown')}"

            print(
                f"🔍 Processing last {limit} messages from '{entity_name}'...")

            processed_count = 0
            found_properties = 0

            # Iterate through messages (all if limit is None)
            messages = client.iter_messages(
                target_entity, limit=limit) if limit else client.iter_messages(target_entity)
            for message in messages:
                processed_count += 1

                if processed_count % 10 == 0:
                    print(f"Processed {processed_count} messages...")
                    # Periodic save to prevent data loss
                    self.save_results()
                    self.save_results_to_csv()

                try:
                    result = self.process_message(message, target_entity)
                    if result:
                        found_properties += 1
                        self.results.append(result)
                        print(
                            f"🏡 Found property #{found_properties}: {result['location']} - {result['distance_from_office_km']}km from office")
                except QuotaExceededError as qe:
                    print(f"\n🛑 LLM Quota Exceeded: {qe}")
                    print("Stopping analysis and saving gathered properties...")
                    self.save_results()
                    self.save_results_to_csv()
                    break

            print(f"\n📊 Analysis Complete!")
            print(f"📱 Total messages processed: {processed_count}")
            print(f"🏠 Properties found: {found_properties}")

    def display_results(self, max_distance: Optional[float] = None, sort_by_distance: bool = True):
        """Display the results in a formatted way."""
        if not self.results:
            print("No results to display.")
            return

        # Filter by distance if specified
        filtered_results = self.results
        if max_distance:
            filtered_results = [
                r for r in self.results if r['distance_from_office_km'] <= max_distance]

        # Sort results
        if sort_by_distance:
            filtered_results.sort(key=lambda x: x['distance_from_office_km'])

        print(f"\n🏠 Found {len(filtered_results)} Properties")
        if max_distance:
            print(f"📍 Within {max_distance}km of office")
        print("=" * 80)

        for i, result in enumerate(filtered_results, 1):
            print(f"\n{i}. 📍 {result['location']}")
            if result['city']:
                print(f"   🏙️  City: {result['city']}")
            if result['rent']:
                print(f"   💰 Rent: ₹{result['rent']}")
            if result['bhk']:
                print(f"   🏠 Type: {result['bhk']}")
            print(
                f"   📏 Distance: {result['distance_from_office_km']} km from office")
            if result['driving_duration']:
                print(f"   🚗 Drive Time: {result['driving_duration']}")
            if result['additional_details']:
                print(f"   ℹ️  Details: {result['additional_details']}")
            print(f"   📅 Posted: {result['date']}")
            if result.get('telegram_link'):
                print(f"   🔗 Telegram Link: {result['telegram_link']}")
            print(f"   💬 Message: {result['original_message'][:100]}...")
            print("-" * 40)

    def save_results(self, filename: str = "house_hunting_results.json"):
        """Save results to a JSON file."""
        filepath = os.path.join('results', filename)
        with open(filepath, 'w') as f:
            json.dump(self.results, f, indent=4)
        print(f"✅ Results saved to {filepath}")

    def save_results_to_csv(self, filename: str = "house_hunting_results.csv"):
        """Save results to a CSV file."""
        if not self.results:
            return

        filepath = os.path.join('results', filename)
        keys = self.results[0].keys()
        with open(filepath, 'w', newline='') as output_file:
            dict_writer = csv.DictWriter(output_file, keys)
            dict_writer.writeheader()
            dict_writer.writerows(self.results)
        print(f"✅ Results saved to {filepath}")


def main():
    """Main function to run the house hunting bot."""

    # Check if required environment variables are set
    provider = os.getenv('MODEL_PROVIDER', 'openai').strip().lower()
    required_vars = ['TELEGRAM_API_ID', 'TELEGRAM_API_HASH', 'TELEGRAM_PHONE', 'GOOGLE_MAPS_API_KEY']
    if provider == 'gemini':
        required_vars.append('GEMINI_API_KEY')
    else:
        required_vars.append('OPENAI_API_KEY')

    missing_vars = [
        var for var in required_vars 
        if not os.getenv(var) or os.getenv(var) in [
            'your_openai_api_key_here', 'your_google_maps_api_key_here', 'your_gemini_api_key_here', ''
        ]
    ]

    if missing_vars:
        print("❌ Missing required environment variables:")
        for var in missing_vars:
            print(f"   - {var}")
        print("\n📝 Please update the .env file with your actual credentials.")
        return

    if not os.getenv('TARGET_CHAT') and not os.getenv('TARGET_PEER_ID'):
        print("❌ Missing target chat information.")
        print("\n📝 Please update the .env file with either TARGET_CHAT or TARGET_PEER_ID.")
        return

    # Create and run the bot
    bot = HouseHuntingBot()

    try:
        # Run analysis (you can adjust the limit)
        bot.run_analysis()  # process all messages by default

        # Display all results sorted by distance
        bot.display_results(sort_by_distance=True)

        # Display only properties within 20km
        print("\n" + "="*50)
        print("🎯 PROPERTIES WITHIN 20KM OF OFFICE")
        bot.display_results(max_distance=20, sort_by_distance=True)

        # Save results
        bot.save_results()
        bot.save_results_to_csv()

    except Exception as e:
        print(f"❌ Error running analysis: {e}")


if __name__ == "__main__":
    main()
