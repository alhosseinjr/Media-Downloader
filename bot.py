# Updated bot.py

# Import statements
import os
import re
import requests
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

# Constants
API_KEY = os.getenv('API_KEY')

# Function to validate tokens
def validate_token(token):
    if len(token) != 32 or not re.match("^[a-fA-F0-9]*$, token):
        raise ValueError("Invalid token")

# Example function that uses the API key

def fetch_data(endpoint):
    validate_token(API_KEY)
    response = requests.get(endpoint, headers={'Authorization': f'Bearer {API_KEY}'})
    if response.status_code != 200:
        raise Exception('Failed to fetch data')
    return response.json()

# Example of usage
if __name__ == '__main__':
    try:
        data = fetch_data('https://api.example.com/data')
        print(data)
    except Exception as e:
        print(f'Error: {e}')