from flask import Flask, jsonify, request, Response
import os
import json
import traceback
import requests
import csv
import io
from garminconnect import Garmin
from datetime import datetime, date, timedelta

# Try to import zoneinfo (Python 3.9+), fallback to pytz
try:
    from zoneinfo import ZoneInfo
except ImportError:
    # Python < 3.9, use pytz
    import pytz
    def ZoneInfo(tz_name):
        return pytz.timezone(tz_name)

app = Flask(__name__)

# CSV Header columns
CSV_HEADERS = [
    'date', 'totalSteps', 'stepsYesterday', 'distanceMeters', 'floorsClimbed', 
    'restingHeartRate', 'minHeartRate', 'maxHeartRate',
    'activeKilocalories', 'totalKilocalories', 'intensityMinutes', 
    'moderateIntensityMinutes', 'vigorousIntensityMinutes',
    'sleepScore', 'sleepTotalSeconds', 'sleepDeep', 'sleepLight', 'sleepRem', 'sleepAwake',
    'sleepStress', 'sleepSpO2', 'sleepRespiration', 'sleepStart', 'sleepEnd',
    'sleepConsistency', 'sleepAlignment', 'sleepRestfulness',
    'stressAvg', 'stressMax', 'stressRest', 'stressLow', 'stressMed', 'stressHigh',
    'bbCurrent', 'bbHigh', 'bbLow', 'bbCharged', 'bbDrained',
    'hrvAverage', 'hrvStatus', 'hrvBalanced', 'hrvUnbalanced',
    'trainingReadinessScore', 'trainingReadinessStatus',
    'trainingStatusKey', 'trainingStatusLabel', 'vo2MaxValue', 'fitnessAge', 'fitnessTrend',
    'acuteLoad', 'chronicLoad', 'loadRatio', 'loadStatus', 'trainingLoadBalance',
    'aerobicLow', 'aerobicHigh', 'anaerobic',
    'respirationAvg', 'respirationMin', 'respirationMax',
    'spo2Avg', 'spo2Min',
    'skinTempVariance',
    'weightKg', 'weightLbs', 'bodyFatPercent', 'bodyWaterPercent', 'muscleMassKg', 'bodyCompDate',
    'waistInches', 'waistDate'
]

BLOB_TOKEN = os.environ.get('BLOB_READ_WRITE_TOKEN', '')
CSV_FILENAME = 'garmin-data.csv'

def list_blobs():
    """List blobs to find CSV file URL."""
    if not BLOB_TOKEN:
        return []
    
    try:
        headers = {
            'Authorization': f'Bearer {BLOB_TOKEN}'
        }
        response = requests.get('https://blob.vercel-storage.com', headers=headers, timeout=10)
        if response.status_code == 200:
            data = response.json()
            return data.get('blobs', [])
        return []
    except Exception as e:
        print(f"Error listing blobs: {e}")
        return []

def get_blob_url():
    """Get the URL for our CSV blob by listing blobs (no caching to avoid stale data in serverless)."""
    blobs = list_blobs()
    # Find all blobs with our filename and get the most recently uploaded one
    matching_blobs = [b for b in blobs if b.get('pathname') == CSV_FILENAME]
    if matching_blobs:
        # Sort by uploadedAt descending and get the newest one
        matching_blobs.sort(key=lambda x: x.get('uploadedAt', ''), reverse=True)
        return matching_blobs[0].get('url')
    return None

def read_csv_from_blob():
    """Read CSV data from Vercel Blob storage."""
    if not BLOB_TOKEN:
        return []
    
    try:
        blob_url = get_blob_url()
        if not blob_url:
            print("CSV blob not found")
            return []
        
        # Add cache-busting query param to avoid CDN cached content
        cache_bust_url = f"{blob_url}?t={datetime.now().timestamp()}"
        response = requests.get(cache_bust_url, timeout=10, headers={'Cache-Control': 'no-cache'})
        if response.status_code == 200:
            reader = csv.DictReader(io.StringIO(response.text))
            return list(reader)
        print(f"Failed to read CSV: {response.status_code}")
        return []
    except Exception as e:
        print(f"Error reading CSV from blob: {e}")
        return []

def delete_blob(url):
    """Delete a blob by URL."""
    if not BLOB_TOKEN:
        return False
    
    try:
        headers = {
            'Authorization': f'Bearer {BLOB_TOKEN}'
        }
        response = requests.delete(f'https://blob.vercel-storage.com?url={url}', headers=headers, timeout=10)
        return response.status_code in [200, 204]
    except Exception as e:
        print(f"Error deleting blob: {e}")
        return False

def write_csv_to_blob(rows):
    """Write CSV data to Vercel Blob storage."""
    if not BLOB_TOKEN:
        print("BLOB_TOKEN not set, skipping CSV write")
        return False
    
    try:
        # Get existing blobs to delete after upload
        old_blobs = [b for b in list_blobs() if b.get('pathname') == CSV_FILENAME]
        old_urls = [b.get('url') for b in old_blobs if b.get('url')]
        
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
            'x-api-version': '7',
            'x-add-random-suffix': 'false'  # Don't add random suffix, keep same filename
        }
        
        response = requests.put(upload_url, data=csv_content.encode('utf-8'), headers=headers, timeout=30)
        
        if response.status_code in [200, 201]:
            print(f"CSV uploaded successfully")
            # Delete old blobs to avoid confusion
            for old_url in old_urls:
                delete_blob(old_url)
                print(f"Deleted old blob: {old_url}")
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
        
        # Get user's timezone from Garmin
        user_timezone = 'UTC'  # Default fallback
        try:
            user_settings = client.get_userprofile_settings()
            user_timezone = user_settings.get('timeZone', 'UTC') or 'UTC'
            print(f"Using Garmin timezone: {user_timezone}")
        except Exception as e:
            print(f"Error getting timezone, using UTC: {e}")
        
        # Calculate today in user's timezone
        tz = ZoneInfo(user_timezone)
        now_user_tz = datetime.now(tz)
        today = now_user_tz.date().isoformat()
        yesterday = (now_user_tz.date() - timedelta(days=1)).isoformat()
        
        print(f"Date in {user_timezone}: {today}")
        
        # Read existing CSV data
        csv_rows = read_csv_from_blob()
        
        # Get last known values
        last_body_comp = get_last_body_composition(csv_rows)
        last_waist = get_last_waist(csv_rows)
        
        daily_stats = {}
        yesterday_stats = {}
        sleep_data = {}
        stress_data = {}
        body_battery = []
        body_composition = {}
        hrv_data = {}
        training_readiness = {}
        training_status = {}
        respiration_data = {}
        spo2_data = {}

        try:
            daily_stats = client.get_stats(today) or {}
        except Exception as e:
            print(f"Error fetching daily stats: {e}")

        try:
            yesterday_stats = client.get_stats(yesterday) or {}
        except Exception as e:
            print(f"Error fetching yesterday stats: {e}")

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
            # Fetch body composition for last 30 days to get most recent weight
            start_date = (date.today() - timedelta(days=30)).isoformat()
            body_composition = client.get_body_composition(start_date, today) or {}
        except Exception as e:
            print(f"Error fetching body composition: {e}")

        try:
            hrv_data = client.get_hrv_data(today) or {}
        except Exception as e:
            print(f"Error fetching HRV data: {e}")

        try:
            training_readiness = client.get_training_readiness(today) or {}
        except Exception as e:
            print(f"Error fetching training readiness: {e}")

        try:
            training_status = client.get_training_status(today) or {}
        except Exception as e:
            print(f"Error fetching training status: {e}")

        try:
            respiration_data = client.get_respiration_data(today) or {}
        except Exception as e:
            print(f"Error fetching respiration data: {e}")

        try:
            spo2_data = client.get_spo2_data(today) or {}
        except Exception as e:
            print(f"Error fetching SpO2 data: {e}")
        
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
                # API returns list in reverse chronological order (newest first)
                latest = weight_list[0] if isinstance(weight_list[0], dict) else {}
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

        # HRV data extraction (data is nested under hrvSummary)
        hrv_average = 0
        hrv_status = ''
        hrv_balanced = 0
        hrv_unbalanced = 0
        if isinstance(hrv_data, dict):
            # Check for nested hrvSummary first
            hrv_summary = hrv_data.get('hrvSummary', {}) or {}
            if isinstance(hrv_summary, dict) and hrv_summary:
                hrv_average = hrv_summary.get('lastNightAvg', 0) or 0
                hrv_status = hrv_summary.get('status', '') or ''
                weekly_avg = hrv_summary.get('weeklyAvg', 0) or 0
                baseline = hrv_summary.get('baseline', {}) or {}
            else:
                # Fallback to direct access (older API format)
                hrv_average = hrv_data.get('lastNightAvg', 0) or 0
                hrv_status = hrv_data.get('status', '') or ''
                weekly_avg = hrv_data.get('weeklyAvg', 0) or 0
                baseline = hrv_data.get('baseline', {}) or {}
            
            if isinstance(baseline, dict):
                balanced_low = baseline.get('balancedLow', 0) or 0
                balanced_high = baseline.get('balancedHigh', 0) or 0
                if hrv_average >= balanced_low and hrv_average <= balanced_high:
                    hrv_balanced = 1
                else:
                    hrv_unbalanced = 1

        # Training Readiness extraction (API returns a list)
        tr_score = 0
        tr_status = ''
        if isinstance(training_readiness, list) and len(training_readiness) > 0:
            tr_data = training_readiness[0]
            tr_score = tr_data.get('score', 0) or 0
            tr_status = tr_data.get('level', '') or ''
        elif isinstance(training_readiness, dict):
            tr_score = training_readiness.get('score', 0) or 0
            tr_status = training_readiness.get('level', '') or ''

        # Training Status extraction (complex nested structure)
        ts_key = ''
        ts_label = ''
        vo2_max = 0
        fitness_age = 0
        recovery_time = 0
        acute_load = 0
        chronic_load = 0
        load_ratio = 0.0
        load_status = ''
        fitness_trend = ''
        training_load_balance = ''
        aerobic_low = 0
        aerobic_high = 0
        anaerobic = 0
        
        if isinstance(training_status, dict):
            # VO2 Max from mostRecentVO2Max
            vo2_data = training_status.get('mostRecentVO2Max', {}) or {}
            if isinstance(vo2_data, dict):
                generic = vo2_data.get('generic', {}) or {}
                if isinstance(generic, dict):
                    vo2_max = generic.get('vo2MaxPreciseValue', 0) or generic.get('vo2MaxValue', 0) or 0
                    fitness_age = generic.get('fitnessAge', 0) or 0
            
            # Training status from mostRecentTrainingStatus
            recent_status = training_status.get('mostRecentTrainingStatus', {}) or {}
            if isinstance(recent_status, dict):
                latest_data = recent_status.get('latestTrainingStatusData', {}) or {}
                if isinstance(latest_data, dict):
                    # Get first device's data
                    for device_id, device_data in latest_data.items():
                        if isinstance(device_data, dict):
                            ts_key = device_data.get('trainingStatus', 0) or 0
                            ts_label = device_data.get('trainingStatusFeedbackPhrase', '') or ''
                            fitness_trend = device_data.get('fitnessTrend', 0) or 0
                            
                            # Acute/Chronic Training Load
                            acuteDTO = device_data.get('acuteTrainingLoadDTO', {}) or {}
                            if isinstance(acuteDTO, dict):
                                acute_load = acuteDTO.get('dailyTrainingLoadAcute', 0) or 0
                                chronic_load = acuteDTO.get('dailyTrainingLoadChronic', 0) or 0
                                load_ratio = acuteDTO.get('dailyAcuteChronicWorkloadRatio', 0.0) or 0.0
                                load_status = acuteDTO.get('acwrStatus', '') or ''
                            break
            
            # Training Load Balance
            load_balance = training_status.get('mostRecentTrainingLoadBalance', {}) or {}
            if isinstance(load_balance, dict):
                metrics_map = load_balance.get('metricsTrainingLoadBalanceDTOMap', {}) or {}
                if isinstance(metrics_map, dict):
                    for device_id, device_data in metrics_map.items():
                        if isinstance(device_data, dict):
                            aerobic_low = round(device_data.get('monthlyLoadAerobicLow', 0) or 0)
                            aerobic_high = round(device_data.get('monthlyLoadAerobicHigh', 0) or 0)
                            anaerobic = round(device_data.get('monthlyLoadAnaerobic', 0) or 0)
                            training_load_balance = device_data.get('trainingBalanceFeedbackPhrase', '') or ''
                            break

        # All-day Respiration extraction
        resp_avg = 0
        resp_min = 0
        resp_max = 0
        if isinstance(respiration_data, dict):
            resp_avg = respiration_data.get('avgWakingRespirationValue', 0) or respiration_data.get('averageRespirationValue', 0) or 0
            resp_min = respiration_data.get('lowestRespirationValue', 0) or 0
            resp_max = respiration_data.get('highestRespirationValue', 0) or 0

        # All-day SpO2 extraction
        spo2_avg = 0
        spo2_min = 0
        if isinstance(spo2_data, dict):
            spo2_avg = spo2_data.get('averageSPO2', 0) or spo2_data.get('averageSpO2', 0) or 0
            spo2_min = spo2_data.get('lowestSPO2', 0) or spo2_data.get('lowestSpO2', 0) or 0

        # Enhanced sleep metrics from sleep_dto
        sleep_consistency = 0
        sleep_alignment = 0
        sleep_restfulness = 0
        skin_temp_variance = 0

        if isinstance(sleep_dto, dict):
            # Sleep quality metrics
            sleep_scores = sleep_dto.get('sleepScores', {}) or {}
            if isinstance(sleep_scores, dict):
                consistency_obj = sleep_scores.get('consistency', {}) or {}
                if isinstance(consistency_obj, dict):
                    sleep_consistency = consistency_obj.get('value', 0) or 0

                alignment_obj = sleep_scores.get('alignment', {}) or {}
                if isinstance(alignment_obj, dict):
                    sleep_alignment = alignment_obj.get('value', 0) or 0

                restfulness_obj = sleep_scores.get('restfulness', {}) or {}
                if isinstance(restfulness_obj, dict):
                    sleep_restfulness = restfulness_obj.get('value', 0) or 0

            # Skin temperature variance
            skin_temp_variance = sleep_dto.get('skinTempVariance', 0) or 0

        # Build response
        steps_yesterday = yesterday_stats.get('totalSteps', 0) or 0

        response = {
            "date": today,
            "timezone": user_timezone,
            "localTime": now_user_tz.isoformat(),
            "summary": {
                "totalSteps": daily_stats.get('totalSteps', 0) or 0,
                "stepsYesterday": steps_yesterday,
                "distanceMeters": daily_stats.get('totalDistanceMeters', 0) or 0,
                "floorsClimbed": daily_stats.get('floorsAscended', 0) or 0,
                "restingHeartRate": daily_stats.get('restingHeartRate', 0) or 0,
                "minHeartRate": daily_stats.get('minHeartRate', 0) or 0,
                "maxHeartRate": daily_stats.get('maxHeartRate', 0) or 0,
                "activeKilocalories": daily_stats.get('activeKilocalories', 0) or 0,
                "totalKilocalories": daily_stats.get('totalKilocalories', 0) or 0,
                "intensityMinutes": intensity_mins,
                "moderateIntensityMinutes": daily_stats.get('moderateIntensityMinutes', 0) or 0,
                "vigorousIntensityMinutes": daily_stats.get('vigorousIntensityMinutes', 0) or 0
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
                "endTime": sleep_dto.get('sleepEndTimestampGMT', 0) or 0,
                "consistency": sleep_consistency,
                "alignment": sleep_alignment,
                "restfulness": sleep_restfulness
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
            },
            "hrv": {
                "average": hrv_average,
                "status": hrv_status,
                "balanced": hrv_balanced,
                "unbalanced": hrv_unbalanced
            },
            "trainingReadiness": {
                "score": tr_score,
                "status": tr_status
            },
            "trainingStatus": {
                "statusKey": ts_key,
                "statusLabel": ts_label,
                "vo2Max": vo2_max,
                "fitnessAge": fitness_age,
                "fitnessTrend": fitness_trend,
                "acuteLoad": acute_load,
                "chronicLoad": chronic_load,
                "loadRatio": load_ratio,
                "loadStatus": load_status,
                "trainingLoadBalance": training_load_balance,
                "aerobicLow": aerobic_low,
                "aerobicHigh": aerobic_high,
                "anaerobic": anaerobic
            },
            "allDayRespiration": {
                "average": resp_avg,
                "min": resp_min,
                "max": resp_max
            },
            "allDaySpO2": {
                "average": spo2_avg,
                "min": spo2_min
            },
            "skinTemp": {
                "variance": skin_temp_variance
            }
        }
        
        # Save to CSV (upsert by date)
        # Note: We leave waist/body comp empty here - they will be preserved from existing row in upsert
        csv_row = {
            'date': today,
            'totalSteps': response['summary']['totalSteps'],
            'stepsYesterday': response['summary']['stepsYesterday'],
            'distanceMeters': response['summary']['distanceMeters'],
            'floorsClimbed': response['summary']['floorsClimbed'],
            'restingHeartRate': response['summary']['restingHeartRate'],
            'minHeartRate': response['summary']['minHeartRate'],
            'maxHeartRate': response['summary']['maxHeartRate'],
            'activeKilocalories': response['summary']['activeKilocalories'],
            'totalKilocalories': response['summary']['totalKilocalories'],
            'intensityMinutes': response['summary']['intensityMinutes'],
            'moderateIntensityMinutes': response['summary']['moderateIntensityMinutes'],
            'vigorousIntensityMinutes': response['summary']['vigorousIntensityMinutes'],
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
            'sleepConsistency': response['sleep']['consistency'],
            'sleepAlignment': response['sleep']['alignment'],
            'sleepRestfulness': response['sleep']['restfulness'],
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
            'hrvAverage': response['hrv']['average'],
            'hrvStatus': response['hrv']['status'],
            'hrvBalanced': response['hrv']['balanced'],
            'hrvUnbalanced': response['hrv']['unbalanced'],
            'trainingReadinessScore': response['trainingReadiness']['score'],
            'trainingReadinessStatus': response['trainingReadiness']['status'],
            'trainingStatusKey': response['trainingStatus']['statusKey'],
            'trainingStatusLabel': response['trainingStatus']['statusLabel'],
            'vo2MaxValue': response['trainingStatus']['vo2Max'],
            'fitnessAge': response['trainingStatus']['fitnessAge'],
            'fitnessTrend': response['trainingStatus']['fitnessTrend'],
            'acuteLoad': response['trainingStatus']['acuteLoad'],
            'chronicLoad': response['trainingStatus']['chronicLoad'],
            'loadRatio': response['trainingStatus']['loadRatio'],
            'loadStatus': response['trainingStatus']['loadStatus'],
            'trainingLoadBalance': response['trainingStatus']['trainingLoadBalance'],
            'aerobicLow': response['trainingStatus']['aerobicLow'],
            'aerobicHigh': response['trainingStatus']['aerobicHigh'],
            'anaerobic': response['trainingStatus']['anaerobic'],
            'respirationAvg': response['allDayRespiration']['average'],
            'respirationMin': response['allDayRespiration']['min'],
            'respirationMax': response['allDayRespiration']['max'],
            'spo2Avg': response['allDaySpO2']['average'],
            'spo2Min': response['allDaySpO2']['min'],
            'skinTempVariance': response['skinTemp']['variance'],
            'weightKg': weight_kg if has_today_body_comp else '',
            'weightLbs': weight_lbs if has_today_body_comp else '',
            'bodyFatPercent': body_fat if has_today_body_comp else '',
            'bodyWaterPercent': body_water if has_today_body_comp else '',
            'muscleMassKg': muscle_mass_kg if has_today_body_comp else '',
            'bodyCompDate': body_comp_date if has_today_body_comp else '',
            'waistInches': '',  # Preserve from existing row only
            'waistDate': ''     # Preserve from existing row only
        }
        
        # Upsert row
        found = False
        for i, row in enumerate(csv_rows):
            if row.get('date') == today:
                # ALWAYS preserve waist from existing row if it has data
                existing_waist = csv_rows[i].get('waistInches')
                if existing_waist and str(existing_waist).strip():
                    csv_row['waistInches'] = existing_waist
                    csv_row['waistDate'] = csv_rows[i].get('waistDate', today)
                # ALWAYS preserve body comp from existing row if it has data
                existing_weight = csv_rows[i].get('weightKg')
                if existing_weight and str(existing_weight).strip():
                    csv_row['weightKg'] = existing_weight
                    csv_row['weightLbs'] = csv_rows[i].get('weightLbs', '')
                    csv_row['bodyFatPercent'] = csv_rows[i].get('bodyFatPercent', '')
                    csv_row['bodyWaterPercent'] = csv_rows[i].get('bodyWaterPercent', '')
                    csv_row['muscleMassKg'] = csv_rows[i].get('muscleMassKg', '')
                    csv_row['bodyCompDate'] = csv_rows[i].get('bodyCompDate', today)
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
        hrv_data = {}
        training_readiness = {}
        training_status = {}
        respiration_data = {}
        spo2_data = {}

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

        try:
            hrv_data = client.get_hrv_data(today) or {}
        except Exception as e:
            hrv_data = {"error": str(e)}

        try:
            training_readiness = client.get_training_readiness(today) or {}
        except Exception as e:
            training_readiness = {"error": str(e)}

        try:
            training_status = client.get_training_status(today) or {}
        except Exception as e:
            training_status = {"error": str(e)}

        try:
            respiration_data = client.get_respiration_data(today) or {}
        except Exception as e:
            respiration_data = {"error": str(e)}

        try:
            spo2_data = client.get_spo2_data(today) or {}
        except Exception as e:
            spo2_data = {"error": str(e)}

        return jsonify({
            "date": today,
            "sleep_raw": sleep_data,
            "stress_raw": stress_data,
            "body_battery_raw": body_battery,
            "hrv_raw": hrv_data,
            "training_readiness_raw": training_readiness,
            "training_status_raw": training_status,
            "respiration_raw": respiration_data,
            "spo2_raw": spo2_data
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
