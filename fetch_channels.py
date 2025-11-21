import requests
import json
import os
import sys
from dotenv import load_dotenv

# Load environment variables from .env file if it exists (for local testing)
load_dotenv()

# --- Configuration from your 'Ayna OTT.json' file ---

# Endpoints
LOGIN_URL = "https://web.aynaott.com/api/authorization/login"
CHANNELS_URL = "https://web.aynaott.com/api/player/channels"
STREAM_URL = "https://web.aynaott.com/api/player/streams"
OUTPUT_FILE_NAME = "output.json"

# Base parameters for the Login request body
LOGIN_BASE_PARAMS = {
    "language": "en",
    "operator_id": "1fb1b4c7-dbd9-469e-88a2-c207dc195869",
    "density": 1,
    "client": "browser",
    "platform": "web",
    "os": "windows",
    "device_id": os.environ.get("LOGIN_DEVICE_ID", "740B26C4302E8EB5CA6C2584026D8277") 
}

# Channel List Query Parameters
CHANNELS_QUERY_PARAMS = {
    "language": "en",
    "operator_id": "1fb1b4c7-dbd9-469e-88a2-c207dc195869",
    "device_id": os.environ.get("CHANNEL_DEVICE_ID", "89E08DCB2AED39234661607AF770A98E"),
    "density": 1,
    "client": "browser",
    "platform": "web",
    "os": "windows",
    "page": 1,
    "per_page": 1000,
    "category_ids[0]": "1959dec0-6f7b-4adc-9ede-f4d2f111ae3f" 
}

def get_auth_token(email, password):
    """Logs in and returns a new Bearer token."""
    login_data = LOGIN_BASE_PARAMS.copy()
    login_data.update({"login": email, "password": password})
    
    print("Attempting to get a new Bearer Token...")
    
    try:
        response = requests.post(
            LOGIN_URL, 
            json=login_data, 
            headers={"Content-Type": "application/json"}
        )
        response.raise_for_status() 
        
        data = response.json()
        print(f"Login response: {data}")  # Debug: print full response
        if "content" not in data or "token" not in data["content"]:
            print(f"Login failed. Full response: {data}")
            sys.exit(1)
        
        token = data["content"]["token"]["access_token"]
        if not token:
            raise ValueError("Login successful but 'access_token' field is missing in the response.")
            
        print("Successfully obtained new Bearer Token.")
        return token

    except requests.exceptions.RequestException as e:
        print(f"Error during login: {e}")
        if 'response' in locals() and response is not None:
             print(f"Response content: {response.text[:500]}...")
        sys.exit(1)
    except (KeyError, ValueError) as e:
        print(f"Login response parsing error: {e}")
        if 'response' in locals() and response is not None:
             print(f"Response content: {response.text[:500]}...")
        sys.exit(1)


def get_stream_url(token, channel_id):
    """Fetches the stream URL for a given channel ID."""
    headers = {
        'Authorization': f'Bearer {token}',
    }
    params = {
        "language": "en",
        "operator_id": "1fb1b4c7-dbd9-469e-88a2-c207dc195869",
        "device_id": "89E08DCB2AED39234661607AF770A98E",
        "density": "1",
        "client": "browser",
        "platform": "web",
        "os": "windows",
        "media_id": channel_id
    }
    
    try:
        response = requests.get(STREAM_URL, headers=headers, params=params)
        response.raise_for_status()
        stream_data = response.json()
        # Assuming content is a list with one item
        if stream_data.get("content") and len(stream_data["content"]) > 0:
            url = stream_data["content"][0].get("src", {}).get("url", "").strip()
            return url
        return ""
    except requests.exceptions.RequestException as e:
        print(f"Error fetching stream for channel {channel_id}: {e}")
        return ""


def fetch_and_transform_channels(token):
    """Fetches, transforms, and saves the channel list to output.json."""
    print(f"Attempting to fetch channels from: {CHANNELS_URL}")
    
    headers = {"Authorization": f"Bearer {token}"}
    
    try:
        response = requests.get(CHANNELS_URL, headers=headers, params=CHANNELS_QUERY_PARAMS)
        response.raise_for_status() 
        raw_data = response.json()
        
        # Check if the expected 'content.data' key exists
        raw_channels = raw_data.get("content", {}).get("data", [])
        
        if not raw_channels:
            print("Warning: Channel list response is empty.")
            
        print(f"✅ Successfully fetched raw channel data. Total channels found: {len(raw_channels)}")

        # --- Data Transformation ---
        transformed_channels = []
        for channel in raw_channels:
            channel_id = channel.get('id')
            stream_url = get_stream_url(token, channel_id) if channel_id else ""
            transformed_channels.append({
                "id": channel_id or 'N/A',
                "title": channel.get('title', 'N/A'),
                "logo": channel.get('image', 'N/A'),
                "url": stream_url,
                "category": 'Channels'  # Default category
            })
        
        final_output = {"channels": transformed_channels}

        # --- Data Saving ---
        with open(OUTPUT_FILE_NAME, "w") as f:
            json.dump(final_output, f, indent=2)
            
        print(f"💾 Successfully saved transformed data to {OUTPUT_FILE_NAME}.")

    except requests.exceptions.RequestException as e:
        print(f"Error fetching or processing channels: {e}")
        if 'response' in locals() and response is not None:
            print(f"Response content: {response.text[:500]}...")
        sys.exit(1)

if __name__ == "__main__":
    LOGIN_EMAIL = os.environ.get("AYNA_OTT_EMAIL")
    PASSWORD = os.environ.get("AYNA_OTT_PASSWORD")
    
    if not LOGIN_EMAIL or not PASSWORD:
        print("🚨 Error: AYNA_OTT_EMAIL or AYNA_OTT_PASSWORD environment variables not set.")
        sys.exit(1)
        
    # 1. Get a fresh token
    new_token = get_auth_token(LOGIN_EMAIL, PASSWORD)
    
    # 2. Use the fresh token to fetch, transform, and save the channels
    fetch_and_transform_channels(new_token)