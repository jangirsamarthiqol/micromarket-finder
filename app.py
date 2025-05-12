import os
import json
import csv
from flask import Flask, render_template, request, jsonify, send_file
from shapely.geometry import Point, Polygon, MultiPolygon
from werkzeug.utils import secure_filename

# Flask App Setup
app = Flask(__name__)

# Configuration
UPLOAD_FOLDER = 'uploads'
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER

# GeoJSON File Path
DATA_FILE_PATH = os.path.join(os.path.dirname(__file__), 'Data', 'submiromarket_zone.geojson')

# Load GeoJSON File
try:
    with open(DATA_FILE_PATH, encoding='utf-8') as f:
        micromarket_data = json.load(f)
        print(f"Successfully loaded GeoJSON from {DATA_FILE_PATH}")
        print(f"GeoJSON type: {micromarket_data.get('type', 'Not specified')}")
        print(f"Number of features: {len(micromarket_data.get('features', []))}")
        if micromarket_data.get('features'):
            first_feature = micromarket_data['features'][0]
            print(f"First feature properties: {first_feature.get('properties', {})}")
            print(f"First feature geometry type: {first_feature.get('geometry', {}).get('type', 'Unknown')}")
except FileNotFoundError:
    print(f"ERROR: GeoJSON file not found at {DATA_FILE_PATH}")
    micromarket_data = {"features": []}
except json.JSONDecodeError as e:
    print(f"ERROR: Invalid JSON in GeoJSON file: {e}")
    micromarket_data = {"features": []}
except Exception as e:
    print(f"ERROR: Unexpected error loading GeoJSON: {e}")
    micromarket_data = {"features": []}

# Known areas for bounding-box fallback
KNOWN_AREAS = {
    "BTM Layout": [77.60, 12.90, 77.63, 12.94],
    "Koramangala": [77.61, 12.93, 77.65, 12.98],
    "Hebbal": [77.58, 13.04, 77.62, 13.06],
    "Yelahanka": [77.57, 13.09, 77.62, 13.14],
}

def clean_coordinates(coords):
    if not coords:
        return coords
    # Detect 3D coords
    if isinstance(coords[0][0], (list, tuple)) and len(coords[0][0]) > 2:
        return [[(pt[0], pt[1]) for pt in ring] for ring in coords]
    return coords


def point_in_polygon_check(point, geometry):
    try:
        gtype = geometry.get('type')
        coords = geometry.get('coordinates')
        if gtype == 'Polygon':
            rings = clean_coordinates(coords)
            poly = Polygon(rings[0])
            if not poly.is_valid:
                poly = poly.buffer(0)
            return poly.contains(point)
        elif gtype == 'MultiPolygon':
            for poly_coords in coords:
                rings = clean_coordinates(poly_coords)
                try:
                    poly = Polygon(rings[0])
                    if not poly.is_valid:
                        poly = poly.buffer(0)
                    if poly.contains(point):
                        return True
                except Exception as e:
                    print(f"Polygon error: {e}")
            return False
    except Exception as e:
        print(f"Error in point_in_polygon_check: {e}")
        return False


def point_in_bounding_box(lon, lat, bbox):
    min_lon, min_lat, max_lon, max_lat = bbox
    return min_lon <= lon <= max_lon and min_lat <= lat <= max_lat


def get_micromarket_info(lat, lon):
    point = Point(lon, lat)
    print(f"Checking point ({lon}, {lat}) for micromarket and zone")
    # GeoJSON polygons
    for feat in micromarket_data.get('features', []):
        props = feat.get('properties', {})
        area = props.get('Name', '')
        micro = props.get('Micromarket', '')
        raw_zone = props.get('Zone', '')
        # Build zone with suffix
        zone = raw_zone if 'Bangalore' in raw_zone else f"{raw_zone} Bangalore" if raw_zone else "Unknown"
        if not (area or micro):
            continue
        if point_in_polygon_check(point, feat.get('geometry', {})):
            print(f"Matched in GeoJSON: {area}, {micro}, zone={zone}")
            return area, micro, zone
    # Bounding boxes
    for area, bbox in KNOWN_AREAS.items():
        if point_in_bounding_box(lon, lat, bbox):
            zone = f"{area} Bangalore"
            print(f"Matched bbox: {area}, zone={zone}")
            return area, area, zone
    return "Unknown", "Not Found", "Unknown"


@app.route('/')
def home():
    return render_template('index.html')


@app.route('/find_micromarket', methods=['POST'])
def find_micromarket():
    try:
        lat = float(request.form.get('latitude', ''))
        lon = float(request.form.get('longitude', ''))
        area, micro, zone = get_micromarket_info(lat, lon)
        if area and area != "Unknown" and area != micro:
            formatted = f"{area}, {micro}"
        else:
            formatted = micro or "Not Found"
        return jsonify({
            "latitude": lat,
            "longitude": lon,
            "area_name": area,
            "micromarket_name": micro,
            "formatted_name": formatted,
            "zone": zone
        })
    except (ValueError, TypeError) as e:
        return jsonify({"error": f"Invalid coordinates: {e}"}), 400
    except Exception as e:
        return jsonify({"error": f"An error occurred: {e}"}), 500


@app.route('/upload_csv', methods=['POST'])
def upload_csv():
    file = request.files.get('file')
    if not file or not file.filename:
        return jsonify({"error": "No file provided"}), 400
    filename = secure_filename(file.filename)
    path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
    file.save(path)

    updated = []
    with open(path, newline='', encoding='utf-8') as csvfile:
        reader = csv.reader(csvfile)
        header = next(reader, [])
        updated.append(header + ["Location", "Zone"])
        for row in reader:
            if len(row) < 3:
                updated.append(row + ["Invalid Row", ""])
                continue
            try:
                lat, lon = float(row[1]), float(row[2])
                area, micro, zone = get_micromarket_info(lat, lon)
                if area and area != "Unknown" and area != micro:
                    loc = f"{area}, {micro}"
                else:
                    loc = micro or "Not Found"
            except ValueError:
                loc, zone = "Invalid Coordinates", "Unknown"
            updated.append(row + [loc, zone])

    out_name = f"updated_{filename}"
    out_path = os.path.join(app.config['UPLOAD_FOLDER'], out_name)
    with open(out_path, 'w', newline='', encoding='utf-8') as out_csv:
        csv.writer(out_csv).writerows(updated)

    return send_file(out_path, as_attachment=True)


if __name__ == '__main__':
    print(f"Starting Flask app with GeoJSON: {DATA_FILE_PATH}")
    print(f"File exists: {os.path.exists(DATA_FILE_PATH)}")
    app.run(host='0.0.0.0', port=5000, debug=True)
