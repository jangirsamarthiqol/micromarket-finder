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
DATA_FILE_PATH = os.path.join(os.path.dirname(__file__), 'Data', 'new.geojson')

# Load GeoJSON File
try:
    with open(DATA_FILE_PATH, encoding='utf-8') as f:
        micromarket_data = json.load(f)
        print(f"Successfully loaded GeoJSON from {DATA_FILE_PATH}")
except FileNotFoundError:
    print(f"ERROR: GeoJSON file not found at {DATA_FILE_PATH}")
    micromarket_data = {"features": []}
except json.JSONDecodeError as e:
    print(f"ERROR: Invalid JSON in GeoJSON file: {e}")
    micromarket_data = {"features": []}
except Exception as e:
    print(f"ERROR: Unexpected error loading GeoJSON: {e}")
    micromarket_data = {"features": []}

# Define known areas with bounding boxes for fallback
KNOWN_AREAS = {
    "BTM Layout": [77.60, 12.90, 77.63, 12.94],
    "Koramangala": [77.61, 12.93, 77.65, 12.98],
    "Hebbal": [77.58, 13.04, 77.62, 13.06],
    "Yelahanka": [77.57, 13.09, 77.62, 13.14],
}

def clean_coordinates(coordinates):
    """Clean coordinate data to handle 3D coordinates (with elevation)."""
    if not coordinates:
        return coordinates
        
    # Handle different coordinate structures
    if isinstance(coordinates, list) and len(coordinates) > 0:
        if isinstance(coordinates[0], list):
            # This is a ring of coordinates
            if len(coordinates[0]) > 0 and isinstance(coordinates[0][0], list):
                # This is a polygon with multiple rings
                return [[(point[0], point[1]) for point in ring if len(point) >= 2] for ring in coordinates]
            else:
                # This is a single ring
                return [(point[0], point[1]) for point in coordinates if len(point) >= 2]
    
    return coordinates

def point_in_polygon_check(point, geometry):
    """Check if a point is inside a polygon or multipolygon."""
    try:
        if geometry['type'] == 'Polygon':
            coordinates = geometry['coordinates']
            if not coordinates:
                return False
                
            # Clean coordinates to 2D
            cleaned_coords = clean_coordinates(coordinates)
            if not cleaned_coords or len(cleaned_coords) == 0:
                return False
                
            # Create polygon from exterior ring (first ring)
            exterior_ring = cleaned_coords[0] if isinstance(cleaned_coords[0], list) else cleaned_coords
            if len(exterior_ring) < 3:  # Need at least 3 points for a polygon
                return False
                
            polygon = Polygon(exterior_ring)
            if not polygon.is_valid:
                polygon = polygon.buffer(0)
            return polygon.contains(point)
                
        elif geometry['type'] == 'MultiPolygon':
            for poly_coords in geometry['coordinates']:
                if not poly_coords:
                    continue
                    
                cleaned_coords = clean_coordinates(poly_coords)
                if not cleaned_coords or len(cleaned_coords) == 0:
                    continue
                    
                try:
                    exterior_ring = cleaned_coords[0] if isinstance(cleaned_coords[0], list) else cleaned_coords
                    if len(exterior_ring) < 3:
                        continue
                        
                    polygon = Polygon(exterior_ring)
                    if not polygon.is_valid:
                        polygon = polygon.buffer(0)
                    if polygon.contains(point):
                        return True
                except Exception as inner_e:
                    print(f"Error with individual polygon in MultiPolygon: {inner_e}")
                    continue
            return False
            
    except Exception as e:
        print(f"Error in point_in_polygon_check: {e}")
        return False

def point_in_bounding_box(lon, lat, bbox):
    """Check if a point is inside a bounding box."""
    try:
        min_lon, min_lat, max_lon, max_lat = bbox
        return min_lon <= lon <= max_lon and min_lat <= lat <= max_lat
    except Exception as e:
        print(f"Error in bounding box check: {e}")
        return False

def get_micromarket_info(lat, lon):
    """Determine the micromarket and zone for given coordinates."""
    try:
        point = Point(lon, lat)  # Important: longitude first, latitude second
        print(f"Searching for point: ({lat}, {lon})")
        # First try the GeoJSON polygon approach
        for i, feature in enumerate(micromarket_data.get('features', [])):
            try:
                properties = feature.get('properties', {})
                micromarket_name = properties.get('Micromarket', '')
                zone_name = properties.get('Zone', '')
                if not micromarket_name:
                    continue
                geometry = feature.get('geometry', {})
                if not geometry:
                    continue
                if point_in_polygon_check(point, geometry):
                    print(f"MATCH FOUND: Micromarket: {micromarket_name}, Zone: {zone_name}")
                    return micromarket_name, zone_name
            except Exception as e:
                print(f"Error processing feature {i+1}: {e}")
                continue
        # If polygon check fails, try the bounding box approach for known areas
        print("No polygon match found, trying bounding box approach...")
        for area_name, bbox in KNOWN_AREAS.items():
            if point_in_bounding_box(lon, lat, bbox):
                print(f"BOUNDING BOX MATCH: {area_name}")
                return area_name, ""
        print("No match found in any polygon or bounding box")
        return "Unknown", ""
    except Exception as e:
        print(f"Error in get_micromarket_info: {e}")
        return "Unknown", ""

@app.route('/')
def home():
    return render_template('index.html')

@app.route('/find_micromarket', methods=['POST'])
def find_micromarket():
    try:
        lat = float(request.form.get('latitude', ''))
        lon = float(request.form.get('longitude', ''))
        micromarket_name, zone_name = get_micromarket_info(lat, lon)
        return jsonify({
            "latitude": lat,
            "longitude": lon,
            "micromarket_name": micromarket_name,
            "zone_name": zone_name
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
        updated.append(header + ["Micromarket", "Zone"])
        for row in reader:
            if len(row) < 3:
                updated.append(row + ["Invalid Row", ""])
                continue
            try:
                lat, lon = float(row[1]), float(row[2])
                micromarket_name, zone_name = get_micromarket_info(lat, lon)
            except ValueError:
                micromarket_name, zone_name = "Invalid Coordinates", ""
            updated.append(row + [micromarket_name, zone_name])

    out_name = f"updated_{filename}"
    out_path = os.path.join(app.config['UPLOAD_FOLDER'], out_name)
    with open(out_path, 'w', newline='', encoding='utf-8') as out_csv:
        csv.writer(out_csv).writerows(updated)

    return send_file(out_path, as_attachment=True)

if __name__ == '__main__':
    print(f"Starting Flask app with GeoJSON: {DATA_FILE_PATH}")
    app.run(host='0.0.0.0', port=5000, debug=True)
