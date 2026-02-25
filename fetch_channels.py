import requests
import json
import os
import sys
import time
import logging
from datetime import datetime, timezone, timedelta
from dotenv import load_dotenv
from concurrent.futures import ThreadPoolExecutor, as_completed

# Load environment variables from .env file if it exists (for local testing)
load_dotenv()

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Configuration
MAX_RETRIES = 3
RETRY_DELAY = 5  # seconds
REQUEST_TIMEOUT = 30  # seconds
MAX_WORKERS = 8  # Concurrent stream URL fetch workers

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

# --- Configuration ---

# Endpoints
LOGIN_URL = "https://web.aynaott.com/api/authorization/login"
CHANNELS_URL = "https://web.aynaott.com/api/player/channels"
STREAM_URL = "https://web.aynaott.com/api/player/streams"
OUTPUT_FILE_NAME = "output.json"
PLAYER_BASE = os.environ.get("PLAYER_BASE", "https://streamer.bdstream.site")

# Base parameters for the Login request body
DEVICE_ID = os.environ.get("LOGIN_DEVICE_ID")
LOGIN_DEVICE_ID = DEVICE_ID
CHANNEL_DEVICE_ID = DEVICE_ID

LOGIN_BASE_PARAMS = {
    "language": "en",
    "operator_id": "1fb1b4c7-dbd9-469e-88a2-c207dc195869",
    "density": 1,
    "client": "browser",
    "platform": "web",
    "os": "windows",
    "device_id": LOGIN_DEVICE_ID
}

# Channel List Query Parameters
CHANNELS_QUERY_PARAMS = {
    "language": "en",
    "operator_id": "1fb1b4c7-dbd9-469e-88a2-c207dc195869",
    "device_id": CHANNEL_DEVICE_ID,
    "density": 1,
    "client": "browser",
    "platform": "web",
    "os": "windows",
    "page": 1,
    "per_page": 500
}

def get_auth_token(email, password):
    """Logs in and returns a new Bearer token with retry logic."""
    login_data = LOGIN_BASE_PARAMS.copy()
    login_data.update({"login": email, "password": password})
    
    proxies = get_proxies()
    
    logger.info("Attempting to get a new Bearer Token...")
    
    for attempt in range(MAX_RETRIES):
        try:
            response = requests.post(
                LOGIN_URL, 
                json=login_data, 
                headers={"Content-Type": "application/json"},
                proxies=proxies,
                timeout=REQUEST_TIMEOUT
            )
            response.raise_for_status() 
            
            data = response.json()
            logger.debug(f"Login response: {data}")
            if "content" not in data or "token" not in data["content"]:
                logger.warning(f"Login failed. Full response: {data}")
                if attempt < MAX_RETRIES - 1:
                    logger.info(f"Retrying login (attempt {attempt + 2}/{MAX_RETRIES})...")
                    time.sleep(RETRY_DELAY)
                    continue
                raise ValueError("Login response structure invalid")
            
            token = data["content"]["token"]["access_token"]
            if not token:
                raise ValueError("Login successful but 'access_token' field is missing in the response.")
                
            logger.info("Successfully obtained new Bearer Token.")
            return token

        except requests.exceptions.RequestException as e:
            logger.error(f"Network error during login (attempt {attempt + 1}/{MAX_RETRIES}): {e}")
            if 'response' in locals() and response is not None:
                logger.error(f"Response content: {response.text[:500]}...")
            if attempt < MAX_RETRIES - 1:
                logger.info(f"Retrying login in {RETRY_DELAY} seconds...")
                time.sleep(RETRY_DELAY)
            else:
                logger.critical("All login retry attempts failed")
                raise
        except (KeyError, ValueError) as e:
            logger.error(f"Login response parsing error (attempt {attempt + 1}/{MAX_RETRIES}): {e}")
            if 'response' in locals() and response is not None:
                logger.error(f"Response content: {response.text[:500]}...")
            if attempt < MAX_RETRIES - 1:
                logger.info(f"Retrying login in {RETRY_DELAY} seconds...")
                time.sleep(RETRY_DELAY)
            else:
                logger.critical("All login retry attempts failed")
                raise
    
    raise Exception("Failed to obtain authentication token after all retry attempts")


def get_stream_url(token, channel_id, retry_count=0):
    """Fetches the stream URL for a given channel ID with retry logic."""
    headers = {
        'Authorization': f'Bearer {token}',
    }
    params = {
        "language": "en",
        "operator_id": "1fb1b4c7-dbd9-469e-88a2-c207dc195869",
        "device_id": CHANNEL_DEVICE_ID,
        "density": "1",
        "client": "browser",
        "platform": "web",
        "os": "windows",
        "media_id": channel_id
    }
    proxies = get_proxies()
    
    try:
        response = requests.get(
            STREAM_URL, 
            headers=headers, 
            params=params, 
            proxies=proxies,
            timeout=REQUEST_TIMEOUT
        )
        response.raise_for_status()
        stream_data = response.json()
        if stream_data.get("content") and len(stream_data["content"]) > 0:
            url = stream_data["content"][0].get("src", {}).get("url", "").strip()
            return url
        return ""
    except requests.exceptions.RequestException as e:
        if retry_count < MAX_RETRIES - 1:
            time.sleep(RETRY_DELAY)
            return get_stream_url(token, channel_id, retry_count + 1)
        logger.debug(f"Failed to fetch stream for channel {channel_id} after {MAX_RETRIES} attempts: {e}")
        return ""


def fetch_stream_urls_batch(token, channels):
    """Fetch stream URLs for multiple channels in parallel using thread pool."""
    results = {}
    
    def fetch_url_task(channel):
        channel_id = channel.get("id")
        url = get_stream_url(token, channel_id) if channel_id else ""
        return (channel_id, url)
    
    logger.info(f"🚀 Starting parallel fetch of {len(channels)} stream URLs using {MAX_WORKERS} workers...")
    
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        futures = {executor.submit(fetch_url_task, ch): i for i, ch in enumerate(channels)}
        
        completed = 0
        for future in as_completed(futures):
            try:
                channel_id, url = future.result()
                results[channel_id] = url
                completed += 1
                if completed % max(1, len(channels) // 10) == 0 and len(channels) > 10:
                    logger.info(f"  ⏳ Progress: {completed}/{len(channels)} streams fetched...")
            except Exception as e:
                logger.warning(f"Task exception: {e}")
    
    logger.info(f"✅ Batch fetch complete: {len(results)}/{len(channels)} URLs retrieved")
    return results


def _pick_first_non_empty(value):
    if value is None:
        return ""
    if isinstance(value, list):
        for v in value:
            if v:
                return str(v)
        return ""
    return str(value)


def build_m3u(channels, file_name, url_builder):
    lines = ["#EXTM3U", ""]

    for channel in channels:
        url = url_builder(channel).strip()
        if not url:
            continue

        tvg_id = channel.get("id", "").strip()
        tvg_name = channel.get("title", "").strip()
        tvg_logo = channel.get("logo") or channel.get("image") or ""

        group_title = _pick_first_non_empty(channel.get("category") or channel.get("categories") or channel.get("genre") or channel.get("genres") or channel.get("group") or channel.get("group_title")) or "Unknown"
        region = _pick_first_non_empty(channel.get("region") or channel.get("country") or channel.get("country_code") or channel.get("countryCode")) or "Unknown"

        extinf = (
            f'#EXTINF:-1 tvg-id="{tvg_id}" tvg-name="{tvg_name}" tvg-logo="{tvg_logo}" '
            f'group-title="{group_title}" region="{region}", {tvg_name}'
        )
        lines.append(extinf)
        lines.append(url)
        lines.append("")

    output = "\n".join(lines)
    with open(file_name, "w", encoding="utf-8") as f:
        f.write(output)

    logger.info(f"Generated M3U {file_name} with {(len(lines) - 2) // 3} entries.")


def fetch_and_transform_channels(token, retry_count=0):
    """Fetches all pages, deduplicates, and attaches stream URLs."""
    logger.info(f"Attempting to fetch channels from: {CHANNELS_URL}")
    headers = {"Authorization": f"Bearer {token}"}
    proxies = get_proxies()

    # Always start from a clean slate so we never mix old and new data
    if os.path.exists(OUTPUT_FILE_NAME):
        try:
            os.remove(OUTPUT_FILE_NAME)
            logger.info(f"Removed existing {OUTPUT_FILE_NAME} to write fresh data")
        except OSError as e:
            logger.warning(f"Could not remove existing {OUTPUT_FILE_NAME}: {e}")

    try:
        # --- Fetch all pages robustly ---
        all_raw_channels = []
        params = CHANNELS_QUERY_PARAMS.copy()
        page = 1
        per_page = int(params.get("per_page", 100))
        server_reported_total = None

        while True:
            params["page"] = page
            response = requests.get(
                CHANNELS_URL, 
                headers=headers, 
                params=params, 
                proxies=proxies,
                timeout=REQUEST_TIMEOUT
            )
            response.raise_for_status()
            data = response.json()

            page_channels = data.get("content", {}).get("data", [])
            if not page_channels:
                break

            all_raw_channels.extend(page_channels)

            # Try to detect pagination metadata
            content = data.get("content", {})
            meta = content.get("meta") or content.get("pagination") or {}
            current_page = meta.get("current_page") or meta.get("current")
            last_page = meta.get("last_page") or meta.get("last") or meta.get("total_pages")
            server_total = meta.get("total") or meta.get("total_items") or meta.get("count")
            next_page_url = content.get("next_page_url") or meta.get("next_page_url") or None

            if server_total is not None:
                server_reported_total = server_total

            if meta:
                logger.info(f"Page {current_page or page} of {last_page or '?'} (server total reported: {server_total or 'unknown'})")

            if current_page is not None and last_page is not None:
                try:
                    if int(current_page) >= int(last_page):
                        break
                except Exception:
                    pass

            if next_page_url:
                page += 1
                continue

            if len(page_channels) < per_page:
                break

            page += 1

        if not all_raw_channels:
            logger.error("❌ CRITICAL: Channel list response is empty!")
            logger.error("Cannot use fallback data - URLs and tokens are expired and useless.")
            raise RuntimeError("No channels returned from API - fetch failed completely")

        logger.info(f"✅ Successfully fetched raw channel data. Total channels found: {len(all_raw_channels)}")

        # --- Parallel Stream URL Fetching ---
        stream_urls = fetch_stream_urls_batch(token, all_raw_channels)

        # --- Data Transformation & Deduplication ---
        seen_ids = {}
        transformed_channels = []
        
        for channel in all_raw_channels:
            channel_copy = channel.copy() if isinstance(channel, dict) else {"raw": channel}
            channel_id = channel_copy.get("id")
            
            # Deduplicate: keep only first occurrence of each channel ID
            if channel_id and channel_id in seen_ids:
                logger.debug(f"Skipping duplicate channel ID: {channel_id}")
                continue
            
            if channel_id:
                seen_ids[channel_id] = True

            # Get pre-fetched stream URL
            stream_url = stream_urls.get(channel_id, "")

            channel_copy["id"] = channel_id or channel_copy.get("id", "N/A")
            channel_copy["title"] = channel_copy.get("title", "N/A")
            if "image" in channel_copy and "logo" not in channel_copy:
                channel_copy["logo"] = channel_copy.get("image")
            channel_copy["url"] = stream_url

            transformed_channels.append(channel_copy)

        final_output = {
            "created_at": datetime.now(timezone(timedelta(hours=6))).isoformat(),
            "disclaimer": "We do not host or serve any content. All channels and streams listed are publicly available from third-party providers.",
            "total_channels": len(transformed_channels),
            "server_total_reported": server_reported_total,
            "channels": transformed_channels, 
            "last_updated": datetime.now().isoformat()
        }

        # --- Data Saving ---
        with open(OUTPUT_FILE_NAME, "w", encoding="utf-8") as f:
            json.dump(final_output, f, indent=2, ensure_ascii=False)

        logger.info(f"💾 Successfully saved transformed data to {OUTPUT_FILE_NAME}.")

        # --- M3U Generation ---
        build_m3u(transformed_channels, "original_output.m3u", lambda ch: ch.get("url", ""))
        build_m3u(
            transformed_channels,
            "output.m3u",
            lambda ch: f"{PLAYER_BASE.rstrip('/')}/get-stream/{ch.get('id','').strip()}" if ch.get("id") else ""
        )

    except requests.exceptions.RequestException as e:
        logger.error(f"Error fetching or processing channels (attempt {retry_count + 1}/{MAX_RETRIES}): {e}")
        if 'response' in locals() and response is not None:
            logger.error(f"Response content: {response.text[:500]}...")
        
        if retry_count < MAX_RETRIES - 1:
            logger.info(f"Retrying channel fetch in {RETRY_DELAY} seconds...")
            time.sleep(RETRY_DELAY)
            return fetch_and_transform_channels(token, retry_count + 1)
        else:
            logger.critical(f"❌ CRITICAL: Channel fetch failed after {MAX_RETRIES} attempts!")
            logger.critical("Cannot use fallback data - previous URLs and tokens are EXPIRED and unusable.")
            logger.critical("Action required: Check API status, credentials, network connectivity, and proxy settings.")
            raise RuntimeError(f"Failed to fetch channels after {MAX_RETRIES} retry attempts")


def write_status_file(status: str, message: str = ""):
    """Write execution status to a status file for monitoring."""
    try:
        status_data = {
            "status": status,
            "timestamp": datetime.now().isoformat(),
            "message": message
        }
        with open("fetch_status.json", "w", encoding="utf-8") as f:
            json.dump(status_data, f, indent=2)
    except Exception as e:
        logger.warning(f"Could not write status file: {e}")

if __name__ == "__main__":
    try:
        logger.info("=" * 60)
        logger.info("Starting Ayna OTT Channel Fetch")
        logger.info("=" * 60)
        
        start_time = time.time()
        
        LOGIN_EMAIL = os.environ.get("AYNA_OTT_EMAIL")
        PASSWORD = os.environ.get("AYNA_OTT_PASSWORD")
        if not LOGIN_DEVICE_ID:
            logger.critical("Error: LOGIN_DEVICE_ID environment variable not set.")
            write_status_file("failed", "Missing device id env var")
            sys.exit(1)
        
        if not LOGIN_EMAIL or not PASSWORD:
            logger.critical("Error: AYNA_OTT_EMAIL or AYNA_OTT_PASSWORD environment variables not set.")
            write_status_file("failed", "Missing credentials")
            sys.exit(1)
            
        # 1. Get a fresh token
        try:
            new_token = get_auth_token(LOGIN_EMAIL, PASSWORD)
        except Exception as e:
            logger.critical(f"Failed to obtain authentication token: {e}")
            write_status_file("failed", f"Authentication failed: {str(e)}")
            sys.exit(1)
        
        # 2. Use the fresh token to fetch, transform, and save the channels
        try:
            fetch_and_transform_channels(new_token)
            write_status_file("success", "Channels fetched and updated successfully")
            
            elapsed = time.time() - start_time
            logger.info("=" * 60)
            logger.info(f"✅ Fetch completed successfully in {elapsed:.2f} seconds")
            logger.info("=" * 60)
        except Exception as e:
            logger.critical(f"Failed to fetch channels: {e}")
            write_status_file("failed", f"Channel fetch failed: {str(e)}")
            sys.exit(1)
            
    except Exception as e:
        logger.critical(f"Unexpected error: {e}", exc_info=True)
        write_status_file("failed", f"Unexpected error: {str(e)}")
        sys.exit(1)
