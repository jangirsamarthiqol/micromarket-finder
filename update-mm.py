import csv
import json
from shapely.geometry import Point, Polygon

# GeoJSON File Path
DATA_FILE_PATH = 'Data/submiromarket_zone.geojson'

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

# Define known areas with bounding boxes for fallback when polygon detection fails
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
        
    if len(coordinates) > 0 and len(coordinates[0]) > 0 and len(coordinates[0][0]) > 2:
        # Convert to 2D by keeping only longitude and latitude
        return [[(point[0], point[1]) for point in ring] for ring in coordinates]
    
    return coordinates

def point_in_polygon_check(point, geometry):
    """Check if a point is inside a polygon or multipolygon."""
    try:
        if geometry['type'] == 'Polygon':
            coordinates = clean_coordinates(geometry['coordinates'])
            polygon = Polygon(coordinates[0])
            if not polygon.is_valid:
                polygon = polygon.buffer(0)
            return polygon.contains(point)
                
        elif geometry['type'] == 'MultiPolygon':
            for poly_coords in geometry['coordinates']:
                cleaned_coords = clean_coordinates(poly_coords)
                try:
                    polygon = Polygon(cleaned_coords[0])
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
    """Determine the micromarket and area (Zone) for given coordinates."""
    point = Point(lon, lat)  # Important: longitude first, latitude second
    
    # First try the GeoJSON polygon approach
    for feature in micromarket_data.get('features', []):
        try:
            properties = feature.get('properties', {})
            area_name = properties.get('Name', '')
            micromarket_name = properties.get('Micromarket', '')
            zone_name = properties.get('Zone', '')  # Extract Zone field
            
            if not area_name and not micromarket_name:
                continue
                
            if point_in_polygon_check(point, feature.get('geometry', {})):
                area = f"{zone_name} Bangalore" if zone_name else "Not Found"
                return area_name, micromarket_name, area
        except Exception as e:
            print(f"Error processing feature: {e}")
    
    # If polygon check fails, try the bounding box approach for known areas
    for area_name, bbox in KNOWN_AREAS.items():
        if point_in_bounding_box(lon, lat, bbox):
            return area_name, area_name, f"{area_name} Bangalore"
    
    return "Unknown", "Not Found", "Not Found"

def process_csv(input_csv):
    """Process the input CSV and add the micromarket and area information in new columns."""
    print(f"Processing CSV: {input_csv}")
    
    try:
        with open(input_csv, mode='r', encoding='utf-8') as infile:
            csv_reader = csv.reader(infile)
            header = next(csv_reader, None)
            
            if not header or len(header) < 2:
                print("Invalid CSV format")
                return
            
            # Add new columns for micromarket and area
            updated_rows = header + ['Micromarket', 'Area']
            
            print("Processing rows...")
            
            # Process each row
            for row in csv_reader:
                print(f"Processing row: {row}")  # Debugging output for each row
                
                if len(row) < 2:
                    updated_rows.append(row + ['Invalid Row', 'Invalid Row'])
                    continue
                
                try:
                    coordinates = row[1]  # coordinates should be in the second column (index 1)
                    lat, lon = map(float, coordinates.split(','))
                    area_name, micromarket_name, area = get_micromarket_info(lat, lon)
                    
                    # Combine area and micromarket info
                    location_name = f"{area_name}, {micromarket_name}" if area_name != "Unknown" else "Not Found"
                    
                    updated_rows.append(row + [location_name, area])
                except ValueError:
                    updated_rows.append(row + ['Invalid Coordinates', 'Invalid Coordinates'])
            
            print(f"Finished processing rows. Writing to file...")

            # Write the updated CSV with micromarket and area information back to the same file
            with open(input_csv, mode='w', encoding='utf-8', newline='') as outfile:
                csv_writer = csv.writer(outfile)
                csv_writer.writerows(updated_rows)
            
            print(f"CSV update completed and saved to {input_csv}")
        
    except Exception as e:
        print(f"Error processing the CSV file: {e}")

# Example Usage:
input_csv_path = 'data.csv'  # Replace with the correct path to your input CSV

process_csv(input_csv_path)
