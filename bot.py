import os
import re
import logging

# Set up logging
logging.basicConfig(level=logging.INFO)

# Load environment variables
API_TOKEN = os.getenv('API_TOKEN')

# Validate the API token
if not API_TOKEN:
    logging.error('API token is not set or invalid.')
    raise ValueError('API token is required.')

def is_valid_url(url):
    # Improved URL validation using regex
    pattern = re.compile('^(http://|https://).*')
    return re.match(pattern, url) is not None

def download_media(url):
    # Check URL validity
    if not is_valid_url(url):
        logging.error('Provided URL is invalid.'); return
    try:
        # Logic for downloading the media goes here...
        logging.info(f'Downloading media from {url}')
        # Simulated download...
    except Exception as e:
        logging.error(f'Error downloading media: {e}')

if __name__ == '__main__':
    media_url = input('Enter the media URL: ')
    download_media(media_url)