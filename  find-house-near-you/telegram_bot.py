import os
import json
import csv
import time
import re
from typing import Any, Dict, Optional, Tuple, Literal

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
        """Use LLM (OpenAI or Gemini) to extract location and rental details using Function Calling (Tools)."""
        
        def extract_property_details(
            location: str, 
            city: str, 
            rent: float, 
            bhk: str, 
            gender_preference: Literal['male', 'female', 'family', 'bachelor', 'any'],
            furnishing_status: Literal['fully furnished', 'semi furnished', 'unfurnished'],
            additional_details: str
        ):
            """
            Extract specific locality/neighborhood and rent details from a residential rental listing post.
            
            Args:
                location: The specific area/locality/neighborhood mentioned (e.g. 'Balewadi', 'Baner'). Return None or empty if no specific area is mentioned.
                city: The city name (e.g. 'Pune', 'Mumbai').
                rent: The monthly rent amount mentioned as a number (e.g. 25000). Return None or 0 if not specified.
                bhk: The configuration of the property (e.g. '1BHK', '2BHK', '1 RK').
                gender_preference: Preferred gender or type of tenants. Choose 'any' if not explicitly specified.
                furnishing_status: Furnishing state of the property. Choose 'unfurnished' if not specified.
                additional_details: Any other relevant details (furnished, deposit, parking, etc.).
            """
            pass

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
                
                config = types.GenerateContentConfig(
                    temperature=0.1,
                    max_output_tokens=2048,
                    tools=[extract_property_details],
                    tool_config=types.ToolConfig(
                        function_calling_config=types.FunctionCallingConfig(
                            mode="ANY"
                        )
                    )
                )
                
                response = self.gemini_client.models.generate_content(
                    model=model,
                    contents=message_text,
                    config=config
                )
                
                if response.function_calls:
                    call = response.function_calls[0]
                    return {
                        'location': call.args.get('location'),
                        'city': call.args.get('city'),
                        'rent': call.args.get('rent'),
                        'bhk': call.args.get('bhk'),
                        'gender_preference': call.args.get('gender_preference'),
                        'furnishing_status': call.args.get('furnishing_status'),
                        'additional_details': call.args.get('additional_details')
                    }
                return None
                
            except Exception as e:
                err_str = str(e)
                is_rate_limit = "429" in err_str or "RESOURCE_EXHAUSTED" in err_str or "Quota exceeded" in err_str or "limit exceeded" in err_str.lower()
                if is_rate_limit:
                    raise QuotaExceededError(f"Gemini quota exhausted: {e}")
                print(f"Error extracting location with Gemini: {e}")
                return None
        else: # Default to OpenAI
            try:
                model = self.model_name or 'gpt-4o-mini'
                
                kwargs = {
                    "model": model,
                    "messages": [
                        {"role": "system", "content": "You are a helpful assistant that extracts location and rental details from text listings."},
                        {"role": "user", "content": message_text}
                    ],
                    "temperature": 0.1,
                    "tools": [{
                        "type": "function",
                        "function": {
                            "name": "extract_property_details",
                            "description": "Extract specific locality/neighborhood and rent details from a residential rental listing post.",
                            "parameters": {
                                "type": "object",
                                "properties": {
                                    "location": {
                                        "type": "string",
                                        "description": "The specific area/locality/neighborhood mentioned (e.g. 'Balewadi', 'Baner')."
                                    },
                                    "city": {
                                        "type": "string",
                                        "description": "The city name (e.g. 'Pune', 'Mumbai')."
                                    },
                                    "rent": {
                                        "type": "number",
                                        "description": "The monthly rent amount mentioned as a number (e.g. 25000)."
                                    },
                                    "bhk": {
                                        "type": "string",
                                        "description": "The configuration of the property (e.g. '1BHK', '2BHK')."
                                    },
                                    "gender_preference": {
                                        "type": "string",
                                        "enum": ["male", "female", "family", "bachelor", "any"],
                                        "description": "Preferred tenant type. Choose 'any' if not explicitly specified."
                                    },
                                    "furnishing_status": {
                                        "type": "string",
                                        "enum": ["fully furnished", "semi furnished", "unfurnished"],
                                        "description": "Furnishing state of the property. Choose 'unfurnished' if not specified."
                                    },
                                    "additional_details": {
                                        "type": "string",
                                        "description": "Any other relevant details (furnished, deposit, parking, etc.)."
                                    }
                                },
                                "required": ["location", "city", "rent", "bhk", "gender_preference", "furnishing_status", "additional_details"]
                            }
                        }
                    }],
                    "tool_choice": {"type": "function", "function": {"name": "extract_property_details"}}
                }
                
                response = openai.chat.completions.create(**kwargs)
                tool_calls = response.choices[0].message.tool_calls
                if tool_calls:
                    call = tool_calls[0]
                    return json.loads(call.function.arguments)
                return None
            except Exception as e:
                err_str = str(e)
                is_rate_limit = "429" in err_str or "insufficient_quota" in err_str or "Rate limit" in err_str
                if is_rate_limit:
                    raise QuotaExceededError(f"OpenAI quota exhausted: {e}")
                print(f"Error extracting location with OpenAI: {e}")
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
        
        # Geocoding (optional)
        lat = None
        lon = None
        distance_km = None
        duration = None
        
        try:
            coords = self.get_coordinates(
                extracted_info['location'], extracted_info.get('city'))
            if coords:
                lat, lon = coords
                # Distance calculation
                dist_info = self.calculate_distance(lat, lon)
                if dist_info:
                    distance_km = dist_info['distance_km']
                    duration = dist_info['duration']
        except Exception as e:
            print(f"⚠️ Geocoding/Distance calculation skipped: {e}")

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
            'gender_preference': extracted_info.get('gender_preference', 'any'),
            'furnishing_status': extracted_info.get('furnishing_status', 'unfurnished'),
            'additional_details': extracted_info.get('additional_details'),
            'latitude': lat,
            'longitude': lon,
            'distance_from_office_km': distance_km,
            'driving_duration': duration,
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
                r for r in self.results if r.get('distance_from_office_km') is not None and r['distance_from_office_km'] <= max_distance]

        # Sort results
        if sort_by_distance:
            filtered_results.sort(key=lambda x: (x.get('distance_from_office_km') is None, x.get('distance_from_office_km') or 99999))

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
            if result.get('gender_preference'):
                print(f"   👥 Gender Preference: {result['gender_preference']}")
            if result.get('furnishing_status'):
                print(f"   🛋️  Furnished: {result['furnishing_status']}")
            
            dist = f"{result['distance_from_office_km']} km" if result.get('distance_from_office_km') is not None else "N/A"
            print(f"   📏 Distance: {dist} from office")
            
            if result.get('driving_duration'):
                print(f"   🚗 Drive Time: {result['driving_duration']}")
            if result.get('additional_details'):
                print(f"   ℹ️  Details: {result['additional_details']}")
            print(f"   📅 Posted: {result['date']}")
            if result.get('telegram_link'):
                print(f"   🔗 Telegram Link: {result['telegram_link']}")
            print(f"   💬 Message: {result['original_message'][:100]}..." if result.get('original_message') else "")
            print("-" * 40)

    def load_existing_results(self, filename: str):
        """Load previously saved results from JSON if it exists."""
        os.makedirs('results', exist_ok=True)
        filepath = os.path.join('results', filename)
        if os.path.exists(filepath):
            try:
                with open(filepath, 'r') as f:
                    data = json.load(f)
                    if isinstance(data, list):
                        self.results = data
                        print(f"📂 Loaded {len(self.results)} existing properties from {filepath}")
            except Exception as e:
                print(f"⚠️ Failed to load existing results from {filepath}: {e}")

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
