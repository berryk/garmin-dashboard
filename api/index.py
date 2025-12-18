from flask import Flask, jsonify
import os
import json
import traceback
from garminconnect import Garmin
from datetime import datetime, date

app = Flask(__name__)

def get_garmin_client():
    """Initialize and return authenticated Garmin client using stored session or credentials."""
    email = os.environ.get('GARMIN_EMAIL')
    password = os.environ.get('GARMIN_PASSWORD')
    tokens_json = os.environ.get('GARMIN_TOKENS')
    
    if tokens_json:
        try:
            client = Garmin()
            client.garth.loads(tokens_json)
            client.display_name = client.garth.profile["displayName"]
            return client
        except Exception as e:
            print(f"Stored tokens failed, trying credential login: {e}")
    
    if not email or not password:
        raise ValueError(f"Missing credentials: email={'set' if email else 'missing'}, password={'set' if password else 'missing'}")
    
    client = Garmin(email, password)
    client.login()
    return client

@app.route('/api/stats')
def get_stats():
    """Fetch today's Garmin stats and return as JSON."""
    try:
        client = get_garmin_client()
        today = date.today().isoformat()
        
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
        except Exception as e:
            print(f"Error fetching sleep data: {e}")
        
        try:
            stress_data = client.get_stress_data(today) or {}
        except Exception as e:
            print(f"Error fetching stress data: {e}")
        
        try:
            body_battery = client.get_body_battery(today) or []
        except Exception as e:
            print(f"Error fetching body battery: {e}")
        
        # Extract sleep details from dailySleepDTO
        sleep_dto = {}
        if isinstance(sleep_data, dict):
            sleep_dto = sleep_data.get('dailySleepDTO', {}) or {}
        
        # Sleep stages are directly in dailySleepDTO, not nested
        deep_seconds = sleep_dto.get('deepSleepSeconds', 0) or 0
        light_seconds = sleep_dto.get('lightSleepSeconds', 0) or 0
        rem_seconds = sleep_dto.get('remSleepSeconds', 0) or 0
        awake_seconds = sleep_dto.get('awakeSleepSeconds', 0) or 0
        
        # Get sleep score from nested structure
        sleep_scores = sleep_dto.get('sleepScores', {}) or {}
        overall_score = 0
        if isinstance(sleep_scores, dict):
            overall_obj = sleep_scores.get('overall', {}) or {}
            if isinstance(overall_obj, dict):
                overall_score = overall_obj.get('value', 0) or 0
        
        # Body battery - it's a list with one dict containing the data
        bb_highest = 0
        bb_lowest = 100
        bb_charged = 0
        bb_drained = 0
        
        if isinstance(body_battery, list) and len(body_battery) > 0:
            bb_data = body_battery[0] if isinstance(body_battery[0], dict) else {}
            
            # Get charged/drained directly
            bb_charged = bb_data.get('charged', 0) or 0
            bb_drained = bb_data.get('drained', 0) or 0
            
            # Get highest/lowest from bodyBatteryValuesArray [[timestamp, level], ...]
            values_array = bb_data.get('bodyBatteryValuesArray', []) or []
            if values_array:
                levels = [item[1] for item in values_array if isinstance(item, list) and len(item) > 1 and item[1] is not None]
                if levels:
                    bb_highest = max(levels)
                    bb_lowest = min(levels)
        
        if bb_lowest == 100:
            bb_lowest = 0
        
        # Stress data - calculate durations from stressValuesArray
        # Stress levels: -2/-1 = unmeasured, 0-25 = rest, 26-50 = low, 51-75 = medium, 76-100 = high
        rest_duration = 0
        low_duration = 0
        medium_duration = 0
        high_duration = 0
        
        if isinstance(stress_data, dict):
            stress_values = stress_data.get('stressValuesArray', []) or []
            for item in stress_values:
                if isinstance(item, list) and len(item) > 1:
                    level = item[1]
                    if level is not None and level >= 0:
                        # Each reading is 3 minutes (180 seconds)
                        if level <= 25:
                            rest_duration += 180
                        elif level <= 50:
                            low_duration += 180
                        elif level <= 75:
                            medium_duration += 180
                        else:
                            high_duration += 180
        
        # Calculate intensity minutes
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
                "overallScore": overall_score,
                "totalSeconds": sleep_dto.get('sleepTimeSeconds', 0) or 0,
                "deepSeconds": deep_seconds,
                "lightSeconds": light_seconds,
                "remSeconds": rem_seconds,
                "awakeSeconds": awake_seconds,
                "avgStress": sleep_dto.get('avgSleepStress', 0) or 0,
                "avgSpO2": sleep_dto.get('averageSpO2Value', 0) or 0,
                "avgRespiration": sleep_dto.get('averageRespirationValue', 0) or 0,
                "startTime": sleep_dto.get('sleepStartTimestampGMT', 0) or 0,
                "endTime": sleep_dto.get('sleepEndTimestampGMT', 0) or 0
            },
            "stress": {
                "averageLevel": (stress_data.get('avgStressLevel', 0) if isinstance(stress_data, dict) else 0) or 0,
                "maxLevel": (stress_data.get('maxStressLevel', 0) if isinstance(stress_data, dict) else 0) or 0,
                "restDurationSeconds": rest_duration,
                "lowDurationSeconds": low_duration,
                "mediumDurationSeconds": medium_duration,
                "highDurationSeconds": high_duration
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

if __name__ == '__main__':
    from dotenv import load_dotenv
    load_dotenv()
    app.run(debug=True, port=5000)
