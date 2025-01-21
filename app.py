import os
import json
import csv
from flask import Flask, render_template, request, jsonify, send_file
from shapely.geometry import Point, Polygon
from werkzeug.utils import secure_filename

app = Flask(__name__)

# Ensure the 'uploads' directory exists to save the uploaded files
UPLOAD_FOLDER = 'uploads'
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

# Define the path to the 'coordinate2.json' file relative to the current file
data_file_path = os.path.join(os.path.dirname(__file__), 'Data', 'coordinate2.json')

# Load the GeoJSON file containing the micromarkets
try:
    with open(data_file_path, encoding='utf-8') as f:
        micromarket_data = json.load(f)
except FileNotFoundError:
    print(f"Error: GeoJSON file not found at {data_file_path}")
    micromarket_data = {"features": []}

# Function to check if a point is within any micromarket polygon
def get_micromarket(lat, lon):
    point = Point(lon, lat)  # Create a point with longitude and latitude
    for feature in micromarket_data['features']:
        micromarket_name = feature['properties'].get('Micromarket', 'Unknown')
        polygon_coords = feature['geometry']['coordinates']

        try:
            if feature['geometry']['type'] == "Polygon":
                for ring in polygon_coords:
                    if isinstance(ring[0], list):  # Ensure it's a list of coordinates
                        polygon = Polygon(ring)
                        if polygon.contains(point):
                            return micromarket_name
            elif feature['geometry']['type'] == "MultiPolygon":
                for poly in polygon_coords:
                    for ring in poly:  # Each ring in the polygon
                        if isinstance(ring[0], list):  # Ensure it's a list of coordinates
                            polygon = Polygon(ring)
                            if polygon.contains(point):
                                return micromarket_name
        except Exception as e:
            print(f"Error processing micromarket '{micromarket_name}': {e}")
            continue

    return "No matching micromarket"


# Route for the homepage
@app.route('/')
def home():
    return render_template('index.html')


# Route to handle manual lat/long input and return micromarket
@app.route('/find_micromarket', methods=['POST'])
def find_micromarket():
    try:
        lat = float(request.form['latitude'])
        lon = float(request.form['longitude'])
        micromarket_name = get_micromarket(lat, lon)
        return jsonify({
            "latitude": lat,
            "longitude": lon,
            "micromarket_name": micromarket_name
        })
    except ValueError:
        return jsonify({"error": "Invalid input. Please enter valid latitude and longitude."}), 400


# Route to handle CSV file upload
@app.route('/upload_csv', methods=['POST'])
def upload_csv():
    if 'file' not in request.files:
        return jsonify({"error": "No file part"}), 400

    file = request.files['file']
    if file.filename == '':
        return jsonify({"error": "No selected file"}), 400

    try:
        filename = secure_filename(file.filename)
        file_path = os.path.join(UPLOAD_FOLDER, filename)
        file.save(file_path)

        # Read the CSV and process the file
        updated_rows = []
        with open(file_path, mode='r', encoding='utf-8') as csv_file:
            csv_reader = csv.reader(csv_file)
            header = next(csv_reader)
            if len(header) < 3:
                return jsonify({"error": "CSV must contain at least three columns: Project Name, Latitude, Longitude"}), 400
            updated_rows.append(header + ["Micromarket Name"])  # Add new column for micromarket

            for row in csv_reader:
                if len(row) < 3:
                    updated_rows.append(row + ["Invalid Row"])
                    continue
                try:
                    lat = float(row[1])  # Ensure lat and lon are converted to float
                    lon = float(row[2])
                    micromarket_name = get_micromarket(lat, lon)
                except ValueError:
                    micromarket_name = "Invalid Coordinates"
                updated_rows.append(row + [micromarket_name])

        # Create a new CSV file with the updated data
        updated_filename = f"updated_{filename}"
        updated_file_path = os.path.join(UPLOAD_FOLDER, updated_filename)

        with open(updated_file_path, mode='w', newline='', encoding='utf-8') as updated_csv_file:
            csv_writer = csv.writer(updated_csv_file)
            csv_writer.writerows(updated_rows)

        return send_file(updated_file_path, as_attachment=True)

    except Exception as e:
        return jsonify({"error": f"An error occurred while processing the file: {str(e)}"}), 500


if __name__ == '__main__':
    # Use the PORT environment variable for deployment compatibility
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port, debug=True)
