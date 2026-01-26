import requests
import json
import os
import sys
from dotenv import load_dotenv
from datetime import datetime, timezone, timedelta

# Load environment variables from .env file if it exists (for local testing)
load_dotenv()

def get_proxies():
    """Get proxy configuration from environment variables."""
    proxy_host = os.environ.get("SOCKS5_PROXY_HOST")
    proxy_port = os.environ.get("SOCKS5_PROXY_PORT")
    proxy_user = os.environ.get("SOCKS5_PROXY_USER")
    proxy_pass = os.environ.get("SOCKS5_PROXY_PASS")
    
    if proxy_host and proxy_port:
        proxy_url = f"socks5://{proxy_user}:{proxy_pass}@{proxy_host}:{proxy_port}" if proxy_user and proxy_pass else f"socks5://{proxy_host}:{proxy_port}"
        return {
            'http': proxy_url,
            'https': proxy_url
        }
    return None

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
    "device_id": os.environ.get("LOGIN_DEVICE_ID", "21BDE34FC53FD6C549114E67DABAFC79") 
}

# Channel List Query Parameters
CHANNELS_QUERY_PARAMS = {
    "language": "en",
    "operator_id": "1fb1b4c7-dbd9-469e-88a2-c207dc195869",
    "device_id": os.environ.get("CHANNEL_DEVICE_ID", "21BDE34FC53FD6C549114E67DABAFC79"),
    "density": 1,
    "client": "browser",
    "platform": "web",
    "os": "windows",
    # initial pagination values (will be updated when fetching)
    "page": 1,
    "per_page": 100,
    "category_ids[0]": "1959dec0-6f7b-4adc-9ede-f4d2f111ae3f" 
}

def get_auth_token(email, password):
    """Logs in and returns a new Bearer token."""
    login_data = LOGIN_BASE_PARAMS.copy()
    login_data.update({"login": email, "password": password})
    
    proxies = get_proxies()
    
    print("Attempting to get a new Bearer Token...")
    
    try:
        response = requests.post(
            LOGIN_URL, 
            json=login_data, 
            headers={"Content-Type": "application/json"},
            proxies=proxies
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
        "device_id": "21BDE34FC53FD6C549114E67DABAFC79",
        "density": "1",
        "client": "browser",
        "platform": "web",
        "os": "windows",
        "media_id": channel_id
    }
    proxies = get_proxies()
    
    try:
        response = requests.get(STREAM_URL, headers=headers, params=params, proxies=proxies)
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
    """Fetches (all pages), preserves full channel objects and saves them to output.json.

    The function will fetch all pages from the channels endpoint (robust to
    different pagination metadata shapes), attach a resolved `url` field for
    each channel (calling `get_stream_url`) and write the complete list to
    `output.json`.
    """

    print(f"Attempting to fetch channels from: {CHANNELS_URL}")
    headers = {"Authorization": f"Bearer {token}"}
    proxies = get_proxies()

    try:
        # --- Fetch all pages robustly ---
        all_raw_channels = []
        params = CHANNELS_QUERY_PARAMS.copy()
        page = 1
        per_page = int(params.get("per_page", 100))

        while True:
            params["page"] = page
            response = requests.get(CHANNELS_URL, headers=headers, params=params, proxies=proxies)
            response.raise_for_status()
            data = response.json()

            page_channels = data.get("content", {}).get("data", [])
            if not page_channels:
                # nothing on this page — stop
                break

            all_raw_channels.extend(page_channels)

            # Try to detect pagination metadata in a few common shapes
            content = data.get("content", {})
            meta = content.get("meta") or content.get("pagination") or {}
            current_page = meta.get("current_page") or meta.get("current")
            last_page = meta.get("last_page") or meta.get("last") or meta.get("total_pages")
            next_page_url = content.get("next_page_url") or meta.get("next_page_url") or None

            # If explicit last page info is available, use it
            if current_page is not None and last_page is not None:
                try:
                    if int(current_page) >= int(last_page):
                        break
                except Exception:
                    pass

            # If next_page_url is present, continue
            if next_page_url:
                page += 1
                continue

            # Fallback: if number of items returned is less than requested per_page, we've reached the last page
            if len(page_channels) < per_page:
                break

            # Otherwise, attempt next page
            page += 1

        if not all_raw_channels:
            print("Warning: Channel list response is empty.")

        print(f"✅ Successfully fetched raw channel data. Total channels found: {len(all_raw_channels)}")

        # --- Data Transformation ---
        transformed_channels = []
        for channel in all_raw_channels:
            # Preserve the full channel object, but normalize some fields and add 'url'
            channel_copy = channel.copy() if isinstance(channel, dict) else {"raw": channel}

            channel_id = channel_copy.get("id")
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
        with open(OUTPUT_FILE_NAME, "w", encoding="utf-8") as f:
            json.dump(final_output, f, indent=2, ensure_ascii=False)

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
