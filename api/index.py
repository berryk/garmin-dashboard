from flask import Flask, jsonify
import os
from garminconnect import Garmin
from datetime import datetime, date

app = Flask(__name__)

def get_garmin_client():
    """Initialize and return authenticated Garmin client."""
    email = os.environ.get('GARMIN_EMAIL')
    password = os.environ.get('GARMIN_PASSWORD')
    
    if not email or not password:
        raise ValueError("GARMIN_EMAIL and GARMIN_PASSWORD environment variables must be set")
    
    client = Garmin(email, password)
    client.login()
    return client

@app.route('/api/stats')
def get_stats():
    """Fetch today's Garmin stats and return as JSON."""
    try:
        client = get_garmin_client()
        today = date.today().isoformat()
        
        # Fetch all data
        daily_stats = client.get_stats(today)
        sleep_data = client.get_sleep_data(today)
        stress_data = client.get_stress_data(today)
        body_battery = client.get_body_battery(today)
        
        # Extract sleep details
        sleep_details = sleep_data.get('dailySleepDTO', {})
        sleep_levels = sleep_details.get('sleepLevels', {})
        
        # Extract body battery values
        bb_list = body_battery if isinstance(body_battery, list) else []
        bb_values = [item.get('bodyBatteryLevel', 0) for item in bb_list if item.get('bodyBatteryLevel')]
        bb_charged = sum(item.get('bodyBatteryChargedValue', 0) for item in bb_list)
        bb_drained = sum(item.get('bodyBatteryDrainedValue', 0) for item in bb_list)
        
        response = {
            "date": today,
            "summary": {
                "totalSteps": daily_stats.get('totalSteps', 0),
                "restingHeartRate": daily_stats.get('restingHeartRate', 0),
                "minHeartRate": daily_stats.get('minHeartRate', 0),
                "maxHeartRate": daily_stats.get('maxHeartRate', 0),
                "activeKilocalories": daily_stats.get('activeKilocalories', 0),
                "totalKilocalories": daily_stats.get('totalKilocalories', 0),
                "intensityMinutes": daily_stats.get('intensityMinutes', 0) or daily_stats.get('moderateIntensityMinutes', 0) + daily_stats.get('vigorousIntensityMinutes', 0)
            },
            "sleep": {
                "overallScore": sleep_details.get('sleepScores', {}).get('overall', {}).get('value', 0),
                "totalSeconds": sleep_details.get('sleepTimeSeconds', 0),
                "deepSeconds": sleep_levels.get('deepSleepSeconds', 0),
                "lightSeconds": sleep_levels.get('lightSleepSeconds', 0),
                "remSeconds": sleep_levels.get('remSleepSeconds', 0),
                "awakeSeconds": sleep_levels.get('awakeSleepSeconds', 0),
                "avgStress": sleep_details.get('avgSleepStress', 0),
                "avgSpO2": sleep_details.get('averageSpO2Value', 0),
                "avgRespiration": sleep_details.get('averageRespirationValue', 0),
                "startTime": sleep_details.get('sleepStartTimestampGMT', 0),
                "endTime": sleep_details.get('sleepEndTimestampGMT', 0)
            },
            "stress": {
                "averageLevel": stress_data.get('avgStressLevel', 0) if stress_data else 0,
                "maxLevel": stress_data.get('maxStressLevel', 0) if stress_data else 0,
                "restDurationSeconds": stress_data.get('restStressDuration', 0) if stress_data else 0,
                "lowDurationSeconds": stress_data.get('lowStressDuration', 0) if stress_data else 0,
                "mediumDurationSeconds": stress_data.get('mediumStressDuration', 0) if stress_data else 0,
                "highDurationSeconds": stress_data.get('highStressDuration', 0) if stress_data else 0
            },
            "bodyBattery": {
                "highest": max(bb_values) if bb_values else 0,
                "lowest": min(bb_values) if bb_values else 0,
                "charged": bb_charged,
                "drained": bb_drained
            }
        }
        
        return jsonify(response)
    
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/api/health')
def health():
    """Health check endpoint."""
    return jsonify({"status": "ok"})

# For local development
if __name__ == '__main__':
    from dotenv import load_dotenv
    load_dotenv()
    app.run(debug=True, port=5000)
