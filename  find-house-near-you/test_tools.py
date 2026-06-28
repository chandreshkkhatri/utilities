import os
from google import genai
from google.genai import types
from dotenv import load_dotenv

load_dotenv()

# If key is not standard Developer Key, launch Client with defaults (which resolves credentials via ADC)
api_key = os.getenv('GEMINI_API_KEY')
if api_key and api_key.startswith('AIzaSy'):
    client = genai.Client(api_key=api_key)
else:
    client = genai.Client()

def extract_property_details(location: str, city: str, rent: float, bhk: str, additional_details: str):
    """
    Extract specific locality/neighborhood and rent details from a residential rental listing post.
    
    Args:
        location: The specific area/locality/neighborhood mentioned (e.g. 'Balewadi', 'Baner').
        city: The city name (e.g. 'Pune', 'Mumbai').
        rent: The monthly rent amount mentioned as a number (e.g. 25000).
        bhk: The configuration of the property (e.g. '1BHK', '2BHK').
        additional_details: Any other relevant details (furnished, deposit, parking, etc.).
    """
    pass

model = os.getenv('MODEL_NAME') or 'gemini-2.5-flash'
print(f"Testing tools on model: {model}")

try:
    config = types.GenerateContentConfig(
        temperature=0.1,
        tools=[extract_property_details],
        tool_config=types.ToolConfig(
            function_calling_config=types.FunctionCallingConfig(
                mode="ANY"
            )
        )
    )
    
    prompt = "Looking for a flatmate in a 2BHK fully furnished flat in Balewadi, Pune. Rent is 15000 per month."
    
    response = client.models.generate_content(
        model=model,
        contents=prompt,
        config=config
    )
    
    print("Function calls returned:")
    if response.function_calls:
        for call in response.function_calls:
            print(f"Name: {call.name}")
            print(f"Args: {call.args}")
    else:
        print("No function call returned. Response text:", response.text)
        
except Exception as e:
    print(f"Error during execution: {e}")
