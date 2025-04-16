import os
import json
import csv
from flask import Flask, render_template, request, jsonify, send_file, flash, redirect, url_for
from shapely.geometry import Point, Polygon
from werkzeug.utils import secure_filename
from datetime import datetime
from functools import lru_cache

# Flask App Setup
app = Flask(__name__)
app.secret_key = os.urandom(24)
app.jinja_env.auto_reload = True
app.config['TEMPLATES_AUTO_RELOAD'] = True

# Configuration
UPLOAD_FOLDER = 'uploads'
ALLOWED_EXTENSIONS = {'csv'}
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024  # 16MB max file size

# GeoJSON File Path
DATA_FILE_PATH = os.path.join(os.path.dirname(__file__), 'Data', 'coordinate2.json')

# Load GeoJSON File
try:
    with open(DATA_FILE_PATH, encoding='utf-8') as f:
        micromarket_data = json.load(f)
except FileNotFoundError:
    print(f"Error: GeoJSON file not found at {DATA_FILE_PATH}")
    micromarket_data = {"features": []}

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

@lru_cache(maxsize=1024)
def get_micromarket(lat, lon):
    point = Point(lon, lat)
    for feature in micromarket_data.get('features', []):
        micromarket_name = feature['properties'].get('Micromarket', 'Unknown')
        try:
            geometry = feature['geometry']
            if geometry['type'] == "Polygon":
                if any(Polygon(ring).contains(point) for ring in geometry['coordinates']):
                    return micromarket_name
            elif geometry['type'] == "MultiPolygon":
                if any(Polygon(ring).contains(point) 
                      for poly in geometry['coordinates'] 
                      for ring in poly):
                    return micromarket_name
        except Exception as e:
            print(f"Error processing {micromarket_name}: {e}")
    return "No matching micromarket"

@app.route('/')
def home():
    """Render the modern home page with dynamic features."""
    recent_searches = request.cookies.get('recent_searches', '[]')
    recent_searches = json.loads(recent_searches)
    return render_template(
        'index.html',
        recent_searches=recent_searches,
        google_maps_api_key=os.getenv('GOOGLE_MAPS_API_KEY', '')
    )

@app.route('/find_micromarket', methods=['POST'])
def find_micromarket():
    try:
        data = request.get_json() if request.is_json else request.form
        lat = float(data.get('latitude'))
        lon = float(data.get('longitude'))
        
        if not (-90 <= lat <= 90) or not (-180 <= lon <= 180):
            return jsonify({
                "status": "error",
                "message": "Coordinates out of valid range",
                "type": "validation_error"
            }), 400
            
        micromarket_name = get_micromarket(lat, lon)
        
        response_data = {
            "status": "success",
            "data": {
                "latitude": lat,
                "longitude": lon,
                "micromarket_name": micromarket_name,
                "timestamp": datetime.now().isoformat()
            }
        }
        
        return jsonify(response_data)
    
    except (TypeError, ValueError) as e:
        return jsonify({
            "status": "error",
            "message": "Invalid coordinates format",
            "type": "validation_error",
            "details": str(e)
        }), 400

@app.route('/upload_csv', methods=['POST'])
def upload_csv():
    if 'file' not in request.files:
        return jsonify({
            "status": "error",
            "message": "No file provided",
            "type": "file_error"
        }), 400

    file = request.files['file']
    if not file or not file.filename:
        return jsonify({
            "status": "error",
            "message": "No file selected",
            "type": "file_error"
        }), 400

    if not allowed_file(file.filename):
        return jsonify({
            "status": "error",
            "message": "Invalid file type. Please upload a CSV file.",
            "type": "file_error"
        }), 400

    try:
        filename = secure_filename(file.filename)
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        file_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
        file.save(file_path)

        stats = {
            "total_processed": 0,
            "invalid_rows": 0,
            "successful_rows": 0
        }

        updated_rows = []
        
        with open(file_path, 'r', encoding='utf-8') as csv_file:
            csv_reader = csv.reader(csv_file)
            header = next(csv_reader, None)
            
            if not header or len(header) < 3:
                os.remove(file_path)
                return jsonify({
                    "status": "error",
                    "message": "Invalid CSV format",
                    "type": "format_error"
                }), 400

            updated_rows.append(header + ["Micromarket Name", "Processing Status"])
            
            for row in csv_reader:
                stats["total_processed"] += 1
                status = "Success"
                
                if len(row) < 3:
                    stats["invalid_rows"] += 1
                    updated_rows.append(row + ["Invalid Row", "Error: Insufficient columns"])
                    continue
                    
                try:
                    lat = float(row[1])
                    lon = float(row[2])
                    if not (-90 <= lat <= 90) or not (-180 <= lon <= 180):
                        stats["invalid_rows"] += 1
                        status = "Error: Invalid coordinate range"
                        micromarket_name = "Invalid Coordinates Range"
                    else:
                        micromarket_name = get_micromarket(lat, lon)
                        stats["successful_rows"] += 1
                except ValueError:
                    stats["invalid_rows"] += 1
                    status = "Error: Invalid coordinate format"
                    micromarket_name = "Invalid Coordinates"
                
                updated_rows.append(row + [micromarket_name, status])

        updated_filename = f"processed_{timestamp}_{filename}"
        updated_file_path = os.path.join(app.config['UPLOAD_FOLDER'], updated_filename)
        
        with open(updated_file_path, 'w', newline='', encoding='utf-8') as updated_csv:
            csv.writer(updated_csv).writerows(updated_rows)

        os.remove(file_path)  # Clean up original file

        return jsonify({
            "status": "success",
            "message": "File processed successfully",
            "stats": stats,
            "download_url": url_for('download_file', filename=updated_filename)
        })

    except Exception as e:
        if os.path.exists(file_path):
            os.remove(file_path)
        return jsonify({
            "status": "error",
            "message": f"An error occurred: {str(e)}",
            "type": "processing_error"
        }), 500

@app.route('/download/<filename>')
def download_file(filename):
    try:
        return send_file(
            os.path.join(app.config['UPLOAD_FOLDER'], filename),
            as_attachment=True,
            download_name=filename
        )
    except Exception as e:
        return jsonify({
            "status": "error",
            "message": f"Download failed: {str(e)}",
            "type": "download_error"
        }), 500

@app.route('/api/micromarkets')
def get_micromarkets():
    """API endpoint to get all available micromarkets"""
    try:
        micromarkets = set()
        for feature in micromarket_data.get('features', []):
            micromarket = feature['properties'].get('Micromarket')
            if micromarket:
                micromarkets.add(micromarket)
        return jsonify({
            "status": "success",
            "data": sorted(list(micromarkets))
        })
    except Exception as e:
        return jsonify({
            "status": "error",
            "message": str(e)
        }), 500

if __name__ == '__main__':
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port, debug=False)
