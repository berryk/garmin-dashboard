"""
Script to generate Garmin authentication tokens locally.
Run this once to get tokens, then add them to your Vercel environment variables.
"""
import os
from garminconnect import Garmin
from dotenv import load_dotenv

load_dotenv()

email = os.environ.get('GARMIN_EMAIL')
password = os.environ.get('GARMIN_PASSWORD')

if not email or not password:
    print("Error: Set GARMIN_EMAIL and GARMIN_PASSWORD in your .env file")
    exit(1)

print(f"Logging in as {email}...")

try:
    client = Garmin(email, password)
    client.login()
    
    # Get the session tokens as JSON string
    tokens = client.garth.dumps()
    
    print("\n" + "="*60)
    print("SUCCESS! Copy the following token to your Vercel environment")
    print("Add it as GARMIN_TOKENS in Vercel project settings:")
    print("="*60 + "\n")
    print(tokens)
    print("\n" + "="*60)
    
    # Also save to a file for reference
    with open('garmin_tokens.json', 'w') as f:
        f.write(tokens)
    print("\nTokens also saved to garmin_tokens.json")
    print("Note: Keep this file safe and DO NOT commit it to git!")
    
except Exception as e:
    print(f"Login failed: {e}")
    print("\nTroubleshooting:")
    print("1. Check your credentials are correct")
    print("2. Try logging into connect.garmin.com in a browser first")
    print("3. You may need to complete a CAPTCHA or 2FA verification")
    exit(1)
