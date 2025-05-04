import os
import json
import csv
from flask import Flask, render_template, request, jsonify, send_file
from shapely.geometry import Point, Polygon, MultiPolygon, shape
from shapely import ops
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
        
        # Log first feature structure for debugging
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

# Define known areas with bounding boxes for fallback when polygon detection fails
# Format: "AreaName": [min_lon, min_lat, max_lon, max_lat]
KNOWN_AREAS = {
    "BTM Layout": [77.60, 12.90, 77.63, 12.94],
    "Koramangala": [77.61, 12.93, 77.65, 12.98],
    "Hebbal": [77.58, 13.04, 77.62, 13.06],
    "Yelahanka": [77.57, 13.09, 77.62, 13.14],
    # Add more areas as needed
}

def clean_coordinates(coordinates):
    """Clean coordinate data to handle 3D coordinates (with elevation)."""
    if not coordinates:
        return coordinates
        
    # Check if we have 3D coordinates (with elevation)
    if len(coordinates) > 0 and len(coordinates[0]) > 0 and len(coordinates[0][0]) > 2:
        # Convert to 2D by keeping only longitude and latitude
        return [[(point[0], point[1]) for point in ring] for ring in coordinates]
    
    return coordinates

def point_in_polygon_check(point, geometry):
    """Check if a point is inside a polygon or multipolygon."""
    try:
        if geometry['type'] == 'Polygon':
            coordinates = clean_coordinates(geometry['coordinates'])
            # Use only the exterior ring (first ring) for containment check
            polygon = Polygon(coordinates[0])
            # Try to fix any invalid polygons
            if not polygon.is_valid:
                polygon = polygon.buffer(0)
            return polygon.contains(point)
                
        elif geometry['type'] == 'MultiPolygon':
            for poly_coords in geometry['coordinates']:
                cleaned_coords = clean_coordinates(poly_coords)
                # Use only the exterior ring (first ring) of each polygon
                try:
                    polygon = Polygon(cleaned_coords[0])
                    # Try to fix any invalid polygons
                    if not polygon.is_valid:
                        polygon = polygon.buffer(0)
                    if polygon.contains(point):
                        return True
                except Exception as inner_e:
                    print(f"Error with polygon: {inner_e}")
            return False
    except Exception as e:
        print(f"Error in point_in_polygon_check: {e}")
        return False

def point_in_bounding_box(lon, lat, bbox):
    """Check if a point is inside a bounding box."""
    min_lon, min_lat, max_lon, max_lat = bbox
    return min_lon <= lon <= max_lon and min_lat <= lat <= max_lat

def get_micromarket_info(lat, lon):
    """Determine the micromarket for given coordinates."""
    point = Point(lon, lat)  # Important: longitude first, latitude second
    print(f"Checking point ({lon}, {lat})")
    
    # First try the GeoJSON polygon approach
    for feature in micromarket_data.get('features', []):
        try:
            properties = feature.get('properties', {})
            area_name = properties.get('Name', '')
            micromarket_name = properties.get('Micromarket', '')
            
            if not area_name and not micromarket_name:
                continue
                
            if point_in_polygon_check(point, feature.get('geometry', {})):
                print(f"Found match in GeoJSON: {area_name}, {micromarket_name}")
                return area_name, micromarket_name
        except Exception as e:
            print(f"Error processing feature: {e}")
    
    # If polygon check fails, try the bounding box approach for known areas
    for area_name, bbox in KNOWN_AREAS.items():
        if point_in_bounding_box(lon, lat, bbox):
            print(f"Found match in bounding box: {area_name}")
            return area_name, area_name
    
    # If no match is found
    return "Unknown", "Not Found"

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
        
        area_name, micromarket_name = get_micromarket_info(lat, lon)
        
        # Create a user-friendly formatted name
        if area_name == "Unknown" or not area_name or area_name == micromarket_name:
            formatted_name = micromarket_name
        else:
            formatted_name = f"{area_name}, {micromarket_name}"
            
        # Don't return "Unknown, Not Found" to the user
        if formatted_name == "Unknown, Not Found":
            formatted_name = "Location not found in any micromarket"
        
        return jsonify({
            "latitude": lat, 
            "longitude": lon, 
            "area_name": area_name,
            "micromarket_name": micromarket_name,
            "formatted_name": formatted_name
        })
    except (TypeError, ValueError) as e:
        return jsonify({"error": f"Invalid coordinates: {e}"}), 400
    except Exception as e:
        return jsonify({"error": f"An error occurred: {e}"}), 500

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

            # Add new column for location
            updated_rows.append(header + ["Location"])
            
            for row in csv_reader:
                if len(row) < 3:
                    updated_rows.append(row + ["Invalid Row"])
                    continue
                
                try:
                    lat = float(row[1])
                    lon = float(row[2])
                    area_name, micromarket_name = get_micromarket_info(lat, lon)
                    
                    # Format location name
                    if area_name == "Unknown" or not area_name or area_name == micromarket_name:
                        location_name = micromarket_name
                    else:
                        location_name = f"{area_name}, {micromarket_name}"
                    
                    # Don't include "Unknown, Not Found"
                    if location_name == "Unknown, Not Found":
                        location_name = "Not Found"
                        
                except ValueError:
                    location_name = "Invalid Coordinates"
                
                updated_rows.append(row + [location_name])

        # Write updated CSV
        updated_filename = f"updated_{filename}"
        updated_file_path = os.path.join(app.config['UPLOAD_FOLDER'], updated_filename)
        with open(updated_file_path, 'w', newline='', encoding='utf-8') as updated_csv:
            csv.writer(updated_csv).writerows(updated_rows)

        return send_file(updated_file_path, as_attachment=True)
    except Exception as e:
        return jsonify({"error": f"An error occurred: {e}"}), 500


if __name__ == '__main__':
    # Print diagnostic info on startup
    print(f"Starting Flask app with GeoJSON: {DATA_FILE_PATH}")
    print(f"File exists: {os.path.exists(DATA_FILE_PATH)}")
    
    # Enable debug mode for development
    app.run(host='0.0.0.0', port=5000, debug=True)