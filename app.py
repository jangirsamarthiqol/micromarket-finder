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
DATA_FILE_PATH = os.path.join(os.path.dirname(__file__), 'Data', 'submicromarket_zone_micromarket_190525.geojson')

# Load GeoJSON File
print(f"Attempting to load GeoJSON from: {DATA_FILE_PATH}")
print(f"File exists: {os.path.exists(DATA_FILE_PATH)}")
print(f"File size: {os.path.getsize(DATA_FILE_PATH) if os.path.exists(DATA_FILE_PATH) else 'N/A'} bytes")

try:
    with open(DATA_FILE_PATH, encoding='utf-8') as f:
        print("Starting to load GeoJSON file...")
        micromarket_data = json.load(f)
        print(f"Successfully loaded GeoJSON from {DATA_FILE_PATH}")
        print(f"GeoJSON type: {micromarket_data.get('type', 'Not specified')}")
        features = micromarket_data.get('features', [])
        print(f"Number of features: {len(features)}")
        if features:
            print(f"First feature properties: {features[0].get('properties', {})}")
            print(f"Last feature properties: {features[-1].get('properties', {})}")
            print(f"Total features processed: {len(features)}")
            first_feature = features[0]
            print(f"First feature geometry type: {first_feature.get('geometry', {}).get('type', 'Unknown')}")
            print(f"First feature coordinates sample: {str(first_feature.get('geometry', {}).get('coordinates', []))[:200]}...")
            # Verify feature count
            if len(features) != 1294:
                print(f"WARNING: Expected 1294 features but found {len(features)}")
except FileNotFoundError:
    print(f"ERROR: GeoJSON file not found at {DATA_FILE_PATH}")
    print("Please ensure the file exists in the Data directory")
    micromarket_data = {"features": []}
except json.JSONDecodeError as e:
    print(f"ERROR: Invalid JSON in GeoJSON file: {e}")
    print("Please check if the GeoJSON file is properly formatted")
    micromarket_data = {"features": []}
except Exception as e:
    print(f"ERROR: Unexpected error loading GeoJSON: {str(e)}")
    print(f"Error type: {type(e).__name__}")
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
    try:
        # Handle 3D coordinates by dropping the Z coordinate
        if isinstance(coords[0][0], (list, tuple)):
            if len(coords[0][0]) > 2:
                print(f"Converting 3D coordinates to 2D. First coordinate: {coords[0][0]}")
                return [[(pt[0], pt[1]) for pt in ring] for ring in coords]
            return coords
        return coords
    except Exception as e:
        print(f"Error in clean_coordinates: {str(e)}")
        return coords


def point_in_polygon_check(point, geometry):
    try:
        gtype = geometry.get('type')
        coords = geometry.get('coordinates')
        print(f"\nChecking point {point} against geometry type: {gtype}")
        
        if not coords:
            print("No coordinates found in geometry")
            return False
            
        if gtype == 'Polygon':
            rings = clean_coordinates(coords)
            if not rings or not rings[0]:
                print("Invalid polygon rings")
                return False
            # Log the first few coordinates of the polygon
            print(f"Polygon first few coordinates: {rings[0][:5]}")
            poly = Polygon(rings[0])
            if not poly.is_valid:
                print("Invalid polygon, attempting to fix with buffer")
                poly = poly.buffer(0)
            result = poly.covers(point)
            print(f"Point containment result: {result}")
            if result:
                print(f"Found match! Point is inside polygon with coordinates: {rings[0][:5]}")
            return result
        elif gtype == 'MultiPolygon':
            for i, poly_coords in enumerate(coords):
                rings = clean_coordinates(poly_coords)
                try:
                    if not rings or not rings[0]:
                        print(f"Invalid rings in polygon {i}")
                        continue
                    # Log the first few coordinates of each polygon
                    print(f"MultiPolygon {i} first few coordinates: {rings[0][:5]}")
                    poly = Polygon(rings[0])
                    if not poly.is_valid:
                        print(f"Invalid polygon {i}, attempting to fix with buffer")
                        poly = poly.buffer(0)
                    result = poly.covers(point)
                    print(f"Point containment result for polygon {i}: {result}")
                    if result:
                        print(f"Found match! Point is inside polygon {i} with coordinates: {rings[0][:5]}")
                        return True
                except Exception as e:
                    print(f"Error processing polygon {i}: {str(e)}")
            return False
        else:
            print(f"Unsupported geometry type: {gtype}")
            return False
    except Exception as e:
        print(f"Error in point_in_polygon_check: {str(e)}")
        print(f"Error type: {type(e).__name__}")
        return False


def point_in_bounding_box(lon, lat, bbox):
    min_lon, min_lat, max_lon, max_lat = bbox
    return min_lon <= lon <= max_lon and min_lat <= lat <= max_lat


def get_micromarket_info(lat, lon):
    point = Point(lon, lat)
    print(f"\nChecking point ({lon}, {lat}) for micromarket and zone")
    print(f"Point coordinates: {point.x}, {point.y}")
    
    features = micromarket_data.get('features', [])
    total_features = len(features)
    print(f"Total features to check: {total_features}")
    
    if total_features != 1294:
        print(f"WARNING: Expected 1294 features but found {total_features}")
    
    # GeoJSON polygons
    features_checked = 0
    features_skipped = 0
    try:
        for i, feat in enumerate(features):
            try:
                props = feat.get('properties', {})
                area = props.get('Name', '')
                micro = props.get('Micromarket', '')
                raw_zone = props.get('Zone', '')
                # Build zone with suffix
                zone = raw_zone if 'Bangalore' in raw_zone else f"{raw_zone} Bangalore" if raw_zone else "Unknown"
                
                # Skip features without area or micro name
                if not (area or micro):
                    print(f"Skipping feature {i+1} - No area or micro name")
                    features_skipped += 1
                    continue
                    
                # Log progress every 100 features
                if i % 100 == 0:
                    print(f"Progress: Checking feature {i+1}/{total_features} ({(i+1)/total_features*100:.1f}%)")
                    
                print(f"\nChecking feature {i+1}/{total_features}: {area}, {micro}, {zone}")
                if point_in_polygon_check(point, feat.get('geometry', {})):
                    print(f"Matched in GeoJSON: {area}, {micro}, zone={zone}")
                    return area, micro, zone
                    
                features_checked += 1
            except Exception as e:
                print(f"Error processing feature {i+1}: {str(e)}")
                continue
                
        print(f"\nTotal features checked: {features_checked}/{total_features}")
        print(f"Total features skipped: {features_skipped}")
        
    except Exception as e:
        print(f"Error during feature processing: {str(e)}")
        print(f"Error type: {type(e).__name__}")
    
    # Bounding boxes
    for area, bbox in KNOWN_AREAS.items():
        if point_in_bounding_box(lon, lat, bbox):
            zone = f"{area} Bangalore"
            print(f"Matched bbox: {area}, zone={zone}")
            return area, area, zone
            
    print("No match found in any polygon or bounding box")
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
