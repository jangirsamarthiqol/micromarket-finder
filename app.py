import os
import json
import csv
from flask import Flask, render_template, request, jsonify, send_file
from shapely.geometry import Point, Polygon
from werkzeug.utils import secure_filename

# Flask App Setup
app = Flask(__name__)

# Configuration
UPLOAD_FOLDER = 'uploads'
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER

# GeoJSON File Path
DATA_FILE_PATH = os.path.join(os.path.dirname(__file__), 'Data', 'coordinate2.json')

# Load GeoJSON File
try:
    with open(DATA_FILE_PATH, encoding='utf-8') as f:
        micromarket_data = json.load(f)
except FileNotFoundError:
    print(f"Error: GeoJSON file not found at {DATA_FILE_PATH}")
    micromarket_data = {"features": []}


def get_micromarket(lat, lon):
    """Determine the micromarket name for given coordinates."""
    point = Point(lon, lat)
    for feature in micromarket_data.get('features', []):
        micromarket_name = feature['properties'].get('Micromarket', 'Unknown')
        try:
            if feature['geometry']['type'] == "Polygon":
                for ring in feature['geometry']['coordinates']:
                    if Polygon(ring).contains(point):
                        return micromarket_name
            elif feature['geometry']['type'] == "MultiPolygon":
                for poly in feature['geometry']['coordinates']:
                    for ring in poly:
                        if Polygon(ring).contains(point):
                            return micromarket_name
        except Exception as e:
            print(f"Error processing {micromarket_name}: {e}")
    return "No matching micromarket"


@app.route('/')
def home():
    """Render the home page."""
    return render_template('index.html')


@app.route('/find_micromarket', methods=['POST'])
def find_micromarket():
    """Find micromarket by coordinates."""
    try:
        lat = float(request.form.get('latitude'))
        lon = float(request.form.get('longitude'))
        micromarket_name = get_micromarket(lat, lon)
        return jsonify({"latitude": lat, "longitude": lon, "micromarket_name": micromarket_name})
    except (TypeError, ValueError):
        return jsonify({"error": "Invalid latitude or longitude"}), 400


@app.route('/upload_csv', methods=['POST'])
def upload_csv():
    """Handle CSV file upload."""
    file = request.files.get('file')
    if not file or not file.filename:
        return jsonify({"error": "No file provided"}), 400

    try:
        filename = secure_filename(file.filename)
        file_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
        file.save(file_path)

        # Process the CSV file
        updated_rows = []
        with open(file_path, 'r', encoding='utf-8') as csv_file:
            csv_reader = csv.reader(csv_file)
            header = next(csv_reader, None)
            if not header or len(header) < 3:
                return jsonify({"error": "Invalid CSV format"}), 400

            updated_rows.append(header + ["Micromarket Name"])
            for row in csv_reader:
                if len(row) < 3:
                    updated_rows.append(row + ["Invalid Row"])
                    continue
                try:
                    lat = float(row[1])
                    lon = float(row[2])
                    micromarket_name = get_micromarket(lat, lon)
                except ValueError:
                    micromarket_name = "Invalid Coordinates"
                updated_rows.append(row + [micromarket_name])

        # Write updated CSV file
        updated_filename = f"updated_{filename}"
        updated_file_path = os.path.join(app.config['UPLOAD_FOLDER'], updated_filename)
        with open(updated_file_path, 'w', newline='', encoding='utf-8') as updated_csv:
            csv.writer(updated_csv).writerows(updated_rows)

        return send_file(updated_file_path, as_attachment=True)
    except Exception as e:
        return jsonify({"error": f"An error occurred: {e}"}), 500


if __name__ == '__main__':
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port, debug=False)  # Debug False for production
