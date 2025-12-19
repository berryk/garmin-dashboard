from flask import Flask, jsonify, request, Response
import os
import json
import traceback
import requests
import csv
import io
from garminconnect import Garmin
from datetime import datetime, date

app = Flask(__name__)

# CSV Header columns
CSV_HEADERS = [
    'date', 'totalSteps', 'restingHeartRate', 'minHeartRate', 'maxHeartRate',
    'activeKilocalories', 'totalKilocalories', 'intensityMinutes',
    'sleepScore', 'sleepTotalSeconds', 'sleepDeep', 'sleepLight', 'sleepRem', 'sleepAwake',
    'sleepStress', 'sleepSpO2', 'sleepRespiration', 'sleepStart', 'sleepEnd',
    'stressAvg', 'stressMax', 'stressRest', 'stressLow', 'stressMed', 'stressHigh',
    'bbCurrent', 'bbHigh', 'bbLow', 'bbCharged', 'bbDrained',
    'weightKg', 'weightLbs', 'bodyFatPercent', 'bodyWaterPercent', 'muscleMassKg', 'bodyCompDate',
    'waistInches', 'waistDate'
]

BLOB_STORE_ID = os.environ.get('BLOB_STORE_ID', '')
BLOB_TOKEN = os.environ.get('BLOB_READ_WRITE_TOKEN', '')
CSV_FILENAME = 'garmin-data.csv'

def get_blob_url():
    """Get the full URL for the CSV blob."""
    if BLOB_STORE_ID:
        return f"https://{BLOB_STORE_ID}.public.blob.vercel-storage.com/{CSV_FILENAME}"
    return None

def read_csv_from_blob():
    """Read CSV data from Vercel Blob storage."""
    if not BLOB_TOKEN:
        return []
    
    try:
        blob_url = get_blob_url()
        if not blob_url:
            return []
        
        response = requests.get(blob_url, timeout=10)
        if response.status_code == 200:
            reader = csv.DictReader(io.StringIO(response.text))
            return list(reader)
        return []
    except Exception as e:
        print(f"Error reading CSV from blob: {e}")
        return []

def write_csv_to_blob(rows):
    """Write CSV data to Vercel Blob storage."""
    if not BLOB_TOKEN:
        print("BLOB_TOKEN not set, skipping CSV write")
        return False
    
    try:
        # Create CSV content
        output = io.StringIO()
        writer = csv.DictWriter(output, fieldnames=CSV_HEADERS)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)
        csv_content = output.getvalue()
        
        # Upload to Vercel Blob
        upload_url = f"https://blob.vercel-storage.com/{CSV_FILENAME}"
        headers = {
            'Authorization': f'Bearer {BLOB_TOKEN}',
            'Content-Type': 'text/csv',
            'x-api-version': '7'
        }
        
        response = requests.put(upload_url, data=csv_content.encode('utf-8'), headers=headers, timeout=30)
        
        if response.status_code in [200, 201]:
            print(f"CSV uploaded successfully")
            return True
        else:
            print(f"Failed to upload CSV: {response.status_code} - {response.text}")
            return False
    except Exception as e:
        print(f"Error writing CSV to blob: {e}")
        return False

def get_last_body_composition(rows):
    """Get the most recent body composition data from CSV."""
    for row in reversed(rows):
        if row.get('weightKg') and float(row.get('weightKg', 0)) > 0:
            return {
                'weightKg': float(row.get('weightKg', 0)),
                'weightLbs': float(row.get('weightLbs', 0)),
                'bodyFatPercent': float(row.get('bodyFatPercent', 0)),
                'bodyWaterPercent': float(row.get('bodyWaterPercent', 0)),
                'muscleMassKg': float(row.get('muscleMassKg', 0)),
                'date': row.get('bodyCompDate', row.get('date', ''))
            }
    return None

def get_last_waist(rows):
    """Get the most recent waist measurement from CSV."""
    for row in reversed(rows):
        if row.get('waistInches') and float(row.get('waistInches', 0)) > 0:
            return {
                'inches': float(row.get('waistInches', 0)),
                'date': row.get('waistDate', row.get('date', ''))
            }
    return None

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
        
        # Read existing CSV data
        csv_rows = read_csv_from_blob()
        
        # Get last known values
        last_body_comp = get_last_body_composition(csv_rows)
        last_waist = get_last_waist(csv_rows)
        
        daily_stats = {}
        sleep_data = {}
        stress_data = {}
        body_battery = []
        body_composition = {}
        
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
        
        try:
            body_composition = client.get_body_composition(today) or {}
        except Exception as e:
            print(f"Error fetching body composition: {e}")
        
        # Extract sleep details from dailySleepDTO
        sleep_dto = {}
        if isinstance(sleep_data, dict):
            sleep_dto = sleep_data.get('dailySleepDTO', {}) or {}
        
        deep_seconds = sleep_dto.get('deepSleepSeconds', 0) or 0
        light_seconds = sleep_dto.get('lightSleepSeconds', 0) or 0
        rem_seconds = sleep_dto.get('remSleepSeconds', 0) or 0
        awake_seconds = sleep_dto.get('awakeSleepSeconds', 0) or 0
        
        sleep_scores = sleep_dto.get('sleepScores', {}) or {}
        overall_score = 0
        if isinstance(sleep_scores, dict):
            overall_obj = sleep_scores.get('overall', {}) or {}
            if isinstance(overall_obj, dict):
                overall_score = overall_obj.get('value', 0) or 0
        
        # Body battery
        bb_current = 0
        bb_highest = 0
        bb_lowest = 100
        bb_charged = 0
        bb_drained = 0
        
        if isinstance(body_battery, list) and len(body_battery) > 0:
            bb_data = body_battery[0] if isinstance(body_battery[0], dict) else {}
            bb_charged = bb_data.get('charged', 0) or 0
            bb_drained = bb_data.get('drained', 0) or 0
            
            values_array = bb_data.get('bodyBatteryValuesArray', []) or []
            if values_array:
                levels = [item[1] for item in values_array if isinstance(item, list) and len(item) > 1 and item[1] is not None]
                if levels:
                    bb_highest = max(levels)
                    bb_lowest = min(levels)
                    bb_current = levels[-1] if levels else 0
        
        if bb_lowest == 100:
            bb_lowest = 0
        
        # Stress data
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
                        if level <= 25:
                            rest_duration += 180
                        elif level <= 50:
                            low_duration += 180
                        elif level <= 75:
                            medium_duration += 180
                        else:
                            high_duration += 180
        
        # Intensity minutes
        intensity_mins = daily_stats.get('intensityMinutes', 0) or 0
        if not intensity_mins:
            mod_mins = daily_stats.get('moderateIntensityMinutes', 0) or 0
            vig_mins = daily_stats.get('vigorousIntensityMinutes', 0) or 0
            intensity_mins = mod_mins + vig_mins
        
        # Body composition - extract from Garmin data
        weight_grams = 0
        body_fat = 0
        body_water = 0
        muscle_mass_grams = 0
        body_comp_date = today
        has_today_body_comp = False
        
        if isinstance(body_composition, dict):
            weight_list = body_composition.get('dateWeightList', []) or []
            if weight_list and len(weight_list) > 0:
                latest = weight_list[-1] if isinstance(weight_list[-1], dict) else {}
                weight_grams = latest.get('weight', 0) or 0
                body_fat = latest.get('bodyFat', 0) or 0
                body_water = latest.get('bodyWater', 0) or 0
                muscle_mass_grams = latest.get('muscleMass', 0) or 0
                body_comp_date = latest.get('calendarDate', today) or today
                has_today_body_comp = weight_grams > 0
            else:
                avg = body_composition.get('totalAverage', {}) or {}
                weight_grams = avg.get('weight', 0) or 0
                body_fat = avg.get('bodyFat', 0) or 0
                body_water = avg.get('bodyWater', 0) or 0
                muscle_mass_grams = avg.get('muscleMass', 0) or 0
                has_today_body_comp = weight_grams > 0
        
        # Convert weights
        weight_kg = round(weight_grams / 1000, 1) if weight_grams else 0
        weight_lbs = round(weight_grams / 453.592, 1) if weight_grams else 0
        muscle_mass_kg = round(muscle_mass_grams / 1000, 1) if muscle_mass_grams else 0
        
        # Use last known body comp if no data today
        if not has_today_body_comp and last_body_comp:
            weight_kg = last_body_comp['weightKg']
            weight_lbs = last_body_comp['weightLbs']
            body_fat = last_body_comp['bodyFatPercent']
            body_water = last_body_comp['bodyWaterPercent']
            muscle_mass_kg = last_body_comp['muscleMassKg']
            body_comp_date = last_body_comp['date']
        
        # Waist - use last known value
        waist_inches = last_waist['inches'] if last_waist else 0
        waist_date = last_waist['date'] if last_waist else ''
        
        # Build response
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
                "current": bb_current,
                "highest": bb_highest,
                "lowest": bb_lowest,
                "charged": bb_charged,
                "drained": bb_drained
            },
            "bodyComposition": {
                "weightKg": weight_kg,
                "weightLbs": weight_lbs,
                "bodyFatPercent": body_fat,
                "bodyWaterPercent": body_water,
                "muscleMassKg": muscle_mass_kg,
                "date": body_comp_date
            },
            "waist": {
                "inches": waist_inches,
                "date": waist_date
            }
        }
        
        # Save to CSV (upsert by date)
        csv_row = {
            'date': today,
            'totalSteps': response['summary']['totalSteps'],
            'restingHeartRate': response['summary']['restingHeartRate'],
            'minHeartRate': response['summary']['minHeartRate'],
            'maxHeartRate': response['summary']['maxHeartRate'],
            'activeKilocalories': response['summary']['activeKilocalories'],
            'totalKilocalories': response['summary']['totalKilocalories'],
            'intensityMinutes': response['summary']['intensityMinutes'],
            'sleepScore': response['sleep']['overallScore'],
            'sleepTotalSeconds': response['sleep']['totalSeconds'],
            'sleepDeep': response['sleep']['deepSeconds'],
            'sleepLight': response['sleep']['lightSeconds'],
            'sleepRem': response['sleep']['remSeconds'],
            'sleepAwake': response['sleep']['awakeSeconds'],
            'sleepStress': response['sleep']['avgStress'],
            'sleepSpO2': response['sleep']['avgSpO2'],
            'sleepRespiration': response['sleep']['avgRespiration'],
            'sleepStart': response['sleep']['startTime'],
            'sleepEnd': response['sleep']['endTime'],
            'stressAvg': response['stress']['averageLevel'],
            'stressMax': response['stress']['maxLevel'],
            'stressRest': response['stress']['restDurationSeconds'],
            'stressLow': response['stress']['lowDurationSeconds'],
            'stressMed': response['stress']['mediumDurationSeconds'],
            'stressHigh': response['stress']['highDurationSeconds'],
            'bbCurrent': response['bodyBattery']['current'],
            'bbHigh': response['bodyBattery']['highest'],
            'bbLow': response['bodyBattery']['lowest'],
            'bbCharged': response['bodyBattery']['charged'],
            'bbDrained': response['bodyBattery']['drained'],
            'weightKg': weight_kg if has_today_body_comp else '',
            'weightLbs': weight_lbs if has_today_body_comp else '',
            'bodyFatPercent': body_fat if has_today_body_comp else '',
            'bodyWaterPercent': body_water if has_today_body_comp else '',
            'muscleMassKg': muscle_mass_kg if has_today_body_comp else '',
            'bodyCompDate': body_comp_date if has_today_body_comp else '',
            'waistInches': waist_inches if waist_date == today else '',
            'waistDate': waist_date if waist_date == today else ''
        }
        
        # Upsert row
        found = False
        for i, row in enumerate(csv_rows):
            if row.get('date') == today:
                # Preserve waist if already set for today
                if csv_rows[i].get('waistInches') and not csv_row['waistInches']:
                    csv_row['waistInches'] = csv_rows[i]['waistInches']
                    csv_row['waistDate'] = csv_rows[i]['waistDate']
                # Preserve body comp if already set for today
                if csv_rows[i].get('weightKg') and not csv_row['weightKg']:
                    csv_row['weightKg'] = csv_rows[i]['weightKg']
                    csv_row['weightLbs'] = csv_rows[i]['weightLbs']
                    csv_row['bodyFatPercent'] = csv_rows[i]['bodyFatPercent']
                    csv_row['bodyWaterPercent'] = csv_rows[i]['bodyWaterPercent']
                    csv_row['muscleMassKg'] = csv_rows[i]['muscleMassKg']
                    csv_row['bodyCompDate'] = csv_rows[i]['bodyCompDate']
                csv_rows[i] = csv_row
                found = True
                break
        
        if not found:
            csv_rows.append(csv_row)
        
        # Sort by date
        csv_rows.sort(key=lambda x: x.get('date', ''))
        
        # Write to blob
        write_csv_to_blob(csv_rows)
        
        return jsonify(response)
    
    except Exception as e:
        error_msg = str(e) if str(e) else type(e).__name__
        traceback_str = traceback.format_exc()
        print(f"Error in get_stats: {error_msg}")
        print(f"Traceback: {traceback_str}")
        return jsonify({"error": error_msg, "details": traceback_str}), 500

@app.route('/api/waist', methods=['POST'])
def save_waist():
    """Save waist measurement."""
    try:
        data = request.get_json()
        waist_inches = float(data.get('inches', 0))
        
        if waist_inches <= 0:
            return jsonify({"error": "Invalid waist measurement"}), 400
        
        today = date.today().isoformat()
        csv_rows = read_csv_from_blob()
        
        # Find or create today's row
        found = False
        for i, row in enumerate(csv_rows):
            if row.get('date') == today:
                csv_rows[i]['waistInches'] = waist_inches
                csv_rows[i]['waistDate'] = today
                found = True
                break
        
        if not found:
            # Create a new row with just the waist data
            new_row = {header: '' for header in CSV_HEADERS}
            new_row['date'] = today
            new_row['waistInches'] = waist_inches
            new_row['waistDate'] = today
            csv_rows.append(new_row)
        
        # Sort by date
        csv_rows.sort(key=lambda x: x.get('date', ''))
        
        # Write to blob
        success = write_csv_to_blob(csv_rows)
        
        if success:
            return jsonify({"success": True, "inches": waist_inches, "date": today})
        else:
            return jsonify({"error": "Failed to save to storage"}), 500
    
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/api/download')
def download_csv():
    """Download the CSV file."""
    try:
        csv_rows = read_csv_from_blob()
        
        if not csv_rows:
            return jsonify({"error": "No data available"}), 404
        
        # Create CSV content with BOM for Excel compatibility
        output = io.StringIO()
        output.write('\ufeff')  # UTF-8 BOM for Excel
        writer = csv.DictWriter(output, fieldnames=CSV_HEADERS)
        writer.writeheader()
        for row in csv_rows:
            writer.writerow(row)
        
        csv_content = output.getvalue()
        
        return Response(
            csv_content,
            mimetype='text/csv',
            headers={'Content-Disposition': 'attachment; filename=garmin-data.csv'}
        )
    
    except Exception as e:
        return jsonify({"error": str(e)}), 500

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
    blob_token = os.environ.get('BLOB_READ_WRITE_TOKEN', '')
    
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
            "password_set": bool(password),
            "tokens_set": bool(tokens),
            "blob_token_set": bool(blob_token),
            "token_load_status": token_load_status,
            "token_error": token_error,
            "profile_name": profile_name
        }
    })

if __name__ == '__main__':
    from dotenv import load_dotenv
    load_dotenv()
    app.run(debug=True, port=5000)
