from flask import Flask, jsonify
import os
import json
import traceback
from garminconnect import Garmin
from datetime import datetime, date

app = Flask(__name__)

# Token storage path for Garmin session
GARMIN_SESSION = None

def get_garmin_client():
    """Initialize and return authenticated Garmin client using stored session or credentials."""
    global GARMIN_SESSION
    
    email = os.environ.get('GARMIN_EMAIL')
    password = os.environ.get('GARMIN_PASSWORD')
    tokens_json = os.environ.get('GARMIN_TOKENS')
    
    if tokens_json:
        # Use stored tokens (preferred method for serverless)
        try:
            client = Garmin()
            # tokens_json is already base64 encoded from garth.dumps()
            client.garth.loads(tokens_json)
            # Test if session is still valid
            client.display_name = client.garth.profile["displayName"]
            return client
        except Exception as e:
            print(f"Stored tokens failed, trying credential login: {e}")
    
    if not email or not password:
        raise ValueError(f"Missing credentials: email={'set' if email else 'missing'}, password={'set' if password else 'missing'}")
    
    # Try login with credentials
    client = Garmin(email, password)
    client.login()
    
    # Save session for future use
    GARMIN_SESSION = client.garth.dumps()
    
    return client

@app.route('/api/stats')
def get_stats():
    """Fetch today's Garmin stats and return as JSON."""
    try:
        client = get_garmin_client()
        today = date.today().isoformat()
        
        # Fetch all data with individual error handling
        daily_stats = {}
        sleep_data = {}
        stress_data = {}
        body_battery = []
        
        try:
            daily_stats = client.get_stats(today) or {}
        except Exception as e:
            print(f"Error fetching daily stats: {e}")
        
        try:
            sleep_data = client.get_sleep_data(today) or {}
            print(f"Sleep data keys: {sleep_data.keys() if isinstance(sleep_data, dict) else 'not dict'}")
        except Exception as e:
            print(f"Error fetching sleep data: {e}")
        
        try:
            stress_data = client.get_stress_data(today) or {}
            print(f"Stress data keys: {stress_data.keys() if isinstance(stress_data, dict) else 'not dict'}")
        except Exception as e:
            print(f"Error fetching stress data: {e}")
        
        try:
            body_battery = client.get_body_battery(today) or []
            print(f"Body battery type: {type(body_battery)}, length: {len(body_battery) if isinstance(body_battery, list) else 'N/A'}")
            if isinstance(body_battery, list) and len(body_battery) > 0:
                print(f"Body battery first item keys: {body_battery[0].keys() if isinstance(body_battery[0], dict) else body_battery[0]}")
        except Exception as e:
            print(f"Error fetching body battery: {e}")
        
        # Extract sleep details - handle different API response structures
        sleep_details = {}
        sleep_levels = {}
        
        if isinstance(sleep_data, dict):
            # Try different possible structures
            sleep_details = sleep_data.get('dailySleepDTO', {}) or sleep_data
            if isinstance(sleep_details, dict):
                sleep_levels = sleep_details.get('sleepLevels', {}) or {}
                # Also check sleepLevelsMap structure
                if not sleep_levels and 'sleepLevelsMap' in sleep_details:
                    sleep_levels_map = sleep_details.get('sleepLevelsMap', {})
                    sleep_levels = {
                        'deepSleepSeconds': sum(item.get('endGMT', 0) - item.get('startGMT', 0) for item in sleep_levels_map.get('deep', [])) // 1000 if sleep_levels_map.get('deep') else 0,
                        'lightSleepSeconds': sum(item.get('endGMT', 0) - item.get('startGMT', 0) for item in sleep_levels_map.get('light', [])) // 1000 if sleep_levels_map.get('light') else 0,
                        'remSleepSeconds': sum(item.get('endGMT', 0) - item.get('startGMT', 0) for item in sleep_levels_map.get('rem', [])) // 1000 if sleep_levels_map.get('rem') else 0,
                        'awakeSleepSeconds': sum(item.get('endGMT', 0) - item.get('startGMT', 0) for item in sleep_levels_map.get('awake', [])) // 1000 if sleep_levels_map.get('awake') else 0,
                    }
            print(f"Sleep details keys: {sleep_details.keys() if isinstance(sleep_details, dict) else 'not dict'}")
        
        # Extract body battery values - try different structures
        bb_highest = 0
        bb_lowest = 100
        bb_charged = 0
        bb_drained = 0
        
        if isinstance(body_battery, list) and len(body_battery) > 0:
            for item in body_battery:
                if isinstance(item, dict):
                    level = item.get('bodyBatteryLevel') or item.get('value', 0)
                    if level:
                        bb_highest = max(bb_highest, level)
                        bb_lowest = min(bb_lowest, level)
                    bb_charged += item.get('bodyBatteryChargedValue', 0) or item.get('charged', 0) or 0
                    bb_drained += item.get('bodyBatteryDrainedValue', 0) or item.get('drained', 0) or 0
        elif isinstance(body_battery, dict):
            # Sometimes returned as a dict with different structure
            bb_highest = body_battery.get('bodyBatteryHighestValue', 0) or body_battery.get('highest', 0) or 0
            bb_lowest = body_battery.get('bodyBatteryLowestValue', 0) or body_battery.get('lowest', 0) or 0
            bb_charged = body_battery.get('bodyBatteryChargedValue', 0) or body_battery.get('charged', 0) or 0
            bb_drained = body_battery.get('bodyBatteryDrainedValue', 0) or body_battery.get('drained', 0) or 0
        
        if bb_lowest == 100:
            bb_lowest = 0
        
        # Calculate intensity minutes safely
        intensity_mins = daily_stats.get('intensityMinutes', 0) or 0
        if not intensity_mins:
            mod_mins = daily_stats.get('moderateIntensityMinutes', 0) or 0
            vig_mins = daily_stats.get('vigorousIntensityMinutes', 0) or 0
            intensity_mins = mod_mins + vig_mins
        
        response = {
            "date": today,
            "summary": {
                "totalSteps": daily_stats.get('totalSteps', 0) or 0,
                "restingHeartRate": daily_stats.get('restingHeartRate', 0) or 0,
                "minHeartRate": daily_stats.get('minHeartRate', 0) or 0,
                "maxHeartRate": daily_stats.get('maxHeartRate', 0) or 0,
                "activeKilocalories": daily_stats.get('activeKilocalories', 0) or 0,
                "totalKilocalories": daily_stats.get('totalKilocalories', 0) or 0,
                "intensityMinutes": intensity_mins
            },
            "sleep": {
                "overallScore": (sleep_details.get('sleepScores', {}) or {}).get('overall', {}).get('value', 0) or 0,
                "totalSeconds": sleep_details.get('sleepTimeSeconds', 0) or 0,
                "deepSeconds": sleep_levels.get('deepSleepSeconds', 0) or 0,
                "lightSeconds": sleep_levels.get('lightSleepSeconds', 0) or 0,
                "remSeconds": sleep_levels.get('remSleepSeconds', 0) or 0,
                "awakeSeconds": sleep_levels.get('awakeSleepSeconds', 0) or 0,
                "avgStress": sleep_details.get('avgSleepStress', 0) or 0,
                "avgSpO2": sleep_details.get('averageSpO2Value', 0) or 0,
                "avgRespiration": sleep_details.get('averageRespirationValue', 0) or 0,
                "startTime": sleep_details.get('sleepStartTimestampGMT', 0) or 0,
                "endTime": sleep_details.get('sleepEndTimestampGMT', 0) or 0
            },
            "stress": {
                "averageLevel": (stress_data.get('avgStressLevel', 0) if isinstance(stress_data, dict) else 0) or 0,
                "maxLevel": (stress_data.get('maxStressLevel', 0) if isinstance(stress_data, dict) else 0) or 0,
                "restDurationSeconds": (stress_data.get('restStressDuration', 0) if isinstance(stress_data, dict) else 0) or 0,
                "lowDurationSeconds": (stress_data.get('lowStressDuration', 0) if isinstance(stress_data, dict) else 0) or 0,
                "mediumDurationSeconds": (stress_data.get('mediumStressDuration', 0) if isinstance(stress_data, dict) else 0) or 0,
                "highDurationSeconds": (stress_data.get('highStressDuration', 0) if isinstance(stress_data, dict) else 0) or 0
            },
            "bodyBattery": {
                "highest": bb_highest,
                "lowest": bb_lowest,
                "charged": bb_charged,
                "drained": bb_drained
            }
        }
        
        return jsonify(response)
    
    except Exception as e:
        error_msg = str(e) if str(e) else type(e).__name__
        traceback_str = traceback.format_exc()
        print(f"Error in get_stats: {error_msg}")
        print(f"Traceback: {traceback_str}")
        return jsonify({"error": error_msg, "details": traceback_str}), 500

@app.route('/api/debug')
def debug():
    """Debug endpoint to see raw API responses."""
    try:
        client = get_garmin_client()
        today = date.today().isoformat()
        
        sleep_data = {}
        stress_data = {}
        body_battery = {}
        
        try:
            sleep_data = client.get_sleep_data(today) or {}
        except Exception as e:
            sleep_data = {"error": str(e)}
        
        try:
            stress_data = client.get_stress_data(today) or {}
        except Exception as e:
            stress_data = {"error": str(e)}
        
        try:
            body_battery = client.get_body_battery(today) or {}
        except Exception as e:
            body_battery = {"error": str(e)}
        
        return jsonify({
            "date": today,
            "sleep_raw": sleep_data,
            "stress_raw": stress_data,
            "body_battery_raw": body_battery
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/api/health')
def health():
    """Health check endpoint."""
    email = os.environ.get('GARMIN_EMAIL', '')
    password = os.environ.get('GARMIN_PASSWORD', '')
    tokens = os.environ.get('GARMIN_TOKENS', '')
    
    # Try to load tokens and report status
    token_load_status = "not_attempted"
    token_error = None
    profile_name = None
    
    if tokens:
        try:
            client = Garmin()
            client.garth.loads(tokens)
            profile_name = client.garth.profile.get("displayName", "unknown")
            token_load_status = "success"
        except Exception as e:
            token_load_status = "failed"
            token_error = str(e)
    
    return jsonify({
        "status": "ok",
        "env_check": {
            "email_set": bool(email),
            "email_length": len(email),
            "password_set": bool(password),
            "password_length": len(password),
            "tokens_set": bool(tokens),
            "tokens_length": len(tokens),
            "token_load_status": token_load_status,
            "token_error": token_error,
            "profile_name": profile_name
        }
    })

# For local development
if __name__ == '__main__':
    from dotenv import load_dotenv
    load_dotenv()
    app.run(debug=True, port=5000)
