import requests
import folium
from shapely.geometry import shape, Polygon, MultiPolygon, LineString
from datetime import datetime, timedelta, timezone
from folium.plugins import MarkerCluster
from collections import defaultdict
import pandas as pd
import ast 
import json
from branca.element import Template, MacroElement 
from folium.plugins import Draw
from folium.plugins import HeatMap
from folium.plugins import MarkerCluster
from branca.colormap import LinearColormap
from jinja2 import Template
import geopandas as gpd


# -------------------------
# HELPER FUNCTION
# -------------------------
def fetch_geojson(url, params, timeout=60):
    try:
        r = requests.get(url, params=params, timeout=timeout)
        r.raise_for_status()
        data = r.json()
        if "features" in data:
            return data
        else:
            print(f"⚠️ No 'features' in response from {url}. Keys: {list(data.keys())}")
            return {"type": "FeatureCollection", "features": []}
    except Exception as e:
        print(f"❌ Error fetching {url}: {e}")
        return {"type": "FeatureCollection", "features": []}

# -------------------------
# HELPER: Get bounds from geometry
# -------------------------
def get_bounds(geom):
    """Return [[south, west], [north, east]] bounds for a GeoJSON geometry."""
    try:
        shp = shape(geom)
        bounds = shp.bounds  # (minx, miny, maxx, maxy)
        return [[bounds[1], bounds[0]], [bounds[3], bounds[2]]]
    except Exception as e:
        print(f"Could not get bounds: {e}")
        return None

# Dictionary to store bounds for quick zoom
layer_bounds = {}

def add_auto_refresh(layer_name, url, map_object):
    refresh_template = """
    <script>
    function refreshLayer_{{layer_name}}() {
        fetch("{{url}}")
        .then(response => response.json())
        .then(data => {
            if (window.{{layer_name}}) {
                window.{{layer_name}}.clearLayers();
                window.{{layer_name}}.addData(data);
            }
        });
    }
    // Refresh every 5 minutes
    setInterval(refreshLayer_{{layer_name}}, 300000);
    </script>
    """
    macro = MacroElement()
    macro._template = Template(refresh_template.replace("{{layer_name}}", layer_name).replace("{{url}}", url))
    map_object.get_root().add_child(macro)

# -------------------------
# TIME FILTER (last 7 days)
# -------------------------
now = datetime.now(timezone.utc)
seven_days_ago = now - timedelta(days=7)
time_filter = seven_days_ago.strftime("%Y-%m-%d %H:%M:%S")

# -------------------------
# MAP INIT
# -------------------------

import folium

# Create the map with zoom limits
m = folium.Map(
    location=[20, 0],
    zoom_start=3,
    min_zoom=3,   # smallest zoom allowed
    max_zoom=9,   # largest zoom allowed
    max_bounds=True
)

# Save or display the map
m.save("map_with_native_zoom_limits.html")

# -------------------------
# BASEMAPS
# -------------------------
basemaps = {
    "Dark": folium.TileLayer(
        "CartoDB dark_matter",
        name="Dark",
        control=True,
        no_wrap=True,
        attr="© OpenStreetMap contributors © CartoDB",
        overlay=False
    ),
    "Light": folium.TileLayer(
        "CartoDB positron",
        name="Light",
        control=True,
        no_wrap=True,
        attr="© OpenStreetMap contributors © CartoDB",
        overlay=False
    ),
    "OSM": folium.TileLayer(
        "OpenStreetMap",
        name="OSM",
        control=True,
        no_wrap=True,
        attr="© OpenStreetMap contributors",
        overlay=False
    ),
    "Satellite": folium.TileLayer(
        tiles="https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}",
        attr="© ESRI & OpenStreetMap contributors",
        name="Satellite",
        control=True,
        no_wrap=True,
        overlay=False
    )
}
# Default Dark layer
basemaps["Dark"].add_to(m)
for k, b in basemaps.items():
    if k != "Dark":
        b.add_to(m)

# -------------------------
# DRAWING TOOL (lines only)
# -------------------------

draw = Draw(
    draw_options={
        'polyline': False,        # Disable lines
        'polygon': True,          # Enable freeform polygon
        'circle': True,           # Enable circles
        'rectangle': False,       # Disable rectangles
        'marker': False,          # Disable markers
        'circlemarker': False     # Disable circle markers
    },
    edit_options={
        'edit': True,
        'remove': True
    }
)
draw.add_to(m)

# -------------------------
# FETCH DATA
# -------------------------
print("Fetching hurricane data...")
hurr_data = fetch_geojson(
    "https://services9.arcgis.com/RHVPKKiFTONKtxq3/arcgis/rest/services/Active_Hurricanes_v1/FeatureServer/0/query",
    {"where": "1=1", "outFields": "*", "f": "geojson"}
)

print("Fetching hurricane danger area...")
danger_area_data = fetch_geojson(
    "https://services9.arcgis.com/RHVPKKiFTONKtxq3/arcgis/rest/services/Active_Hurricanes_v1/FeatureServer/3/query",
    {"where":"1=1","outFields":"*","f":"geojson"}
)

print("Fetching earthquake points...")
eq_points_data = fetch_geojson(
    "https://services9.arcgis.com/RHVPKKiFTONKtxq3/arcgis/rest/services/USGS_Seismic_Data_v1/FeatureServer/0/query",
    {"where": f"eventTime >= TIMESTAMP '{time_filter}'", "outFields": "*", "f": "geojson"}
)

print("Fetching shake intensity polygons...")
eq_intensity_data = fetch_geojson(
    "https://services9.arcgis.com/RHVPKKiFTONKtxq3/arcgis/rest/services/USGS_Seismic_Data_v1/FeatureServer/1/query",
    {"where": f"eventTime >= TIMESTAMP '{time_filter}'", "outFields": "*", "f": "geojson"}
)

print("Fetching USA Wildfires...")
wildfire_data = fetch_geojson(
    "https://services9.arcgis.com/RHVPKKiFTONKtxq3/arcgis/rest/services/USA_Wildfires_v1/FeatureServer/0/query",
    {"where": f"ModifiedOnDateTime >= TIMESTAMP '{time_filter}'", "outFields": "*", "f": "geojson"}
)

# Fetch FeatureServer/1 (the new hurricane location polygons)
location_data = fetch_geojson(
    "https://services9.arcgis.com/RHVPKKiFTONKtxq3/arcgis/rest/services/Active_Hurricanes_v1/FeatureServer/1/query",
    {"where":"1=1","outFields":"*","f":"geojson"}
)

# --- Add auto-refresh for each hazard layer ---
add_auto_refresh("hurr_layer", 
                 "https://services9.arcgis.com/RHVPKKiFTONKtxq3/arcgis/rest/services/Active_Hurricanes_v1/FeatureServer/0/query", 
                 m)

add_auto_refresh("danger_area_layer", 
                 "https://services9.arcgis.com/RHVPKKiFTONKtxq3/arcgis/rest/services/Active_Hurricanes_v1/FeatureServer/3/query",
                 m)

add_auto_refresh("eq_points_layer", 
                 "https://services9.arcgis.com/RHVPKKiFTONKtxq3/arcgis/rest/services/USGS_Seismic_Data_v1/FeatureServer/0/query",
                 m)

add_auto_refresh("eq_intensity_layer", 
                 "https://services9.arcgis.com/RHVPKKiFTONKtxq3/arcgis/rest/services/USGS_Seismic_Data_v1/FeatureServer/1/query", 
                 m)

add_auto_refresh("wildfire_layer", 
                 "https://services9.arcgis.com/RHVPKKiFTONKtxq3/arcgis/rest/services/USA_Wildfires_v1/FeatureServer/0/query", 
                 m)

add_auto_refresh("location_layer", 
                 "https://services9.arcgis.com/RHVPKKiFTONKtxq3/arcgis/rest/services/Active_Hurricanes_v1/FeatureServer/1/query", 
                 m)

# Convert hurricane polygons to GeoDataFrame
storm_polys = []
for feature in location_data['features']:
    storm_name = feature['properties'].get('STORMNAME', 'Unknown')
    geom = shape(feature['geometry'])
    storm_polys.append({"storm": storm_name, "geometry": geom})

storms_gdf = gpd.GeoDataFrame(storm_polys, crs="EPSG:4326")

# Dictionary to store bounds for quick zoom
from shapely.geometry import shape

def get_bounds_safe(geom):
    """Return [[south, west], [north, east]] for Polygon/MultiPolygon."""
    try:
        shp = shape(geom)
        minx, miny, maxx, maxy = shp.bounds
        return [[miny, minx], [maxy, maxx]]
    except Exception as e:
        print(f"Error computing bounds: {e}")
        return None

hurricane_location_bounds = {}

for feature in location_data.get("features", []):
    geom_data = feature.get("geometry")
    if not geom_data:
        print(f"Skipping {feature.get('properties', {}).get('STORMNAME','Unknown')} with no geometry in FeatureServer/1")
        continue

    bounds = get_bounds_safe(geom_data)
    if bounds:
        storm_name = feature.get("properties", {}).get("STORMNAME", "Unknown")
        hurricane_location_bounds[storm_name] = bounds

# -------------------------
# FEATURE LAYERS
# -------------------------
hurricane_layer = folium.FeatureGroup(name="Hurricanes", show=True)
eq_layer = folium.FeatureGroup(name="Earthquakes", show=False)
shake_layer= folium.FeatureGroup(name="Shake Intensity", show=False)
wildfire_layer = folium.FeatureGroup(name="USA Wildfires", show=False)

# -------------------------
# HURRICANES
# -------------------------
layers_ordered = [
    ("Forecast Track", "https://services9.arcgis.com/RHVPKKiFTONKtxq3/arcgis/rest/services/Active_Hurricanes_v1/FeatureServer/0/query"),
    ("Forecast Cone", "https://services9.arcgis.com/RHVPKKiFTONKtxq3/arcgis/rest/services/Active_Hurricanes_v1/FeatureServer/2/query"),
    ("Tropical Storm Prob", "https://services9.arcgis.com/RHVPKKiFTONKtxq3/arcgis/rest/services/Active_Hurricanes_v1/FeatureServer/4/query"),
    ("Hurricane Force Prob", "https://services9.arcgis.com/RHVPKKiFTONKtxq3/arcgis/rest/services/Active_Hurricanes_v1/FeatureServer/9/query"),
    ("Danger Area", "https://services9.arcgis.com/RHVPKKiFTONKtxq3/arcgis/rest/services/Active_Hurricanes_v1/FeatureServer/3/query")
]

cat_colors = {1:"#66ff66",2:"#ffff66",3:"#ffcc66",4:"#ff9966",5:"#ff6666"}
def get_color(prob, layer_name):
    if layer_name == "Hurricane Force Prob":
        if prob <= 20: return "#7CFC0070"
        elif prob <= 40: return "#FFFF0070"
        elif prob <= 60: return "#FFA50070"
        elif prob <= 80: return "#FF000070"
        else: return "#80008070"
    elif layer_name == "Tropical Storm Prob":
        return "#f1e6e6b4"  # transparent fill for white hashing
    elif layer_name == "Forecast Cone":
        return "#87CEFA50"
    elif layer_name == "Danger Area":
        return "#FF450060"
    elif layer_name == "Forecast Track":
        return "#000000"
    elif layer_name == "Forecast Cone":
        return "#87CEFA50"
    elif layer_name == "Danger Area":
        return "#FF450060"
    elif layer_name == "Forecast Track":
        return "#000000"

for layer_name, url in layers_ordered:
    data = fetch_geojson(url, {"where":"1=1","outFields":"*","f":"geojson"})

    # Sort Hurricane Force Prob polygons by probability
    if layer_name == "Hurricane Force Prob":
        data['features'] = sorted(
            data['features'],
            key=lambda f: f['properties'].get('PWIND120', 0)
        )

    for feature in data['features']:
        geom_data = feature.get('geometry')
        if not geom_data:
            print(f"Skipping {feature.get('properties', {}).get('STORMNAME','Unknown')} with no geometry in {layer_name}")
            continue  # Skip features without geometry

        geom = shape(geom_data)
        prob = feature['properties'].get('PWIND120', 0)
        storm_name = feature['properties'].get('STORMNAME', 'Unknown')
        
        # Set popup text
        if layer_name == "Hurricane Force Prob":
            popup_text = f"{layer_name} Probability: {prob}%"
        elif layer_name.endswith("Prob"):
            popup_text = f"{storm_name}<br>{layer_name} Probability: {prob}%"
        else:
            popup_text = f"{storm_name}<br>{layer_name}"
        
        # Set style (same as your existing code)
        if layer_name == "Hurricane Force Prob":
            color = None
            weight = 0
            fill_opacity = 0.35
            dash_array = None
        elif layer_name == "Tropical Storm Prob":
            color = "white"
            weight = 1
            fill_opacity = 0.3
            dash_array = "5,5"
        elif layer_name == "Forecast Cone":
            color = "#87CEFA"
            weight = 1
            fill_opacity = 0.3
            dash_array = None
        elif layer_name == "Danger Area":
            color = "#FF4500"
            weight = 1
            fill_opacity = 0.6
            dash_array = None
        else:
            color = get_color(prob, layer_name)
            weight = 3 if layer_name=="Forecast Track" else 2
            fill_opacity = 0.35
            dash_array = None

        # Draw polygons or lines
        if isinstance(geom, (Polygon, MultiPolygon)):
            polygons = [geom] if isinstance(geom, Polygon) else geom.geoms
            for poly in polygons:
                folium.Polygon(
                    locations=[[(y, x) for x, y in poly.exterior.coords]],
                    color=color,
                    weight=weight,
                    fill=True,
                    fill_color=get_color(prob, layer_name),
                    fill_opacity=fill_opacity,
                    dash_array=dash_array,
                    popup=popup_text
                ).add_to(hurricane_layer)
        elif isinstance(geom, LineString):
            folium.PolyLine(
                locations=[(y, x) for x, y in geom.coords],
                color=color,
                weight=weight,
                opacity=0.7,
                popup=popup_text
            ).add_to(hurricane_layer)

# Collect probability polygons for TIV calculation
prob_polys = []

for layer_name, url in layers_ordered:
    if layer_name not in ["Hurricane Force Prob", "Tropical Storm Prob"]:
        continue  # only probability cones

    data = fetch_geojson(url, {"where":"1=1","outFields":"*","f":"geojson"})
    for feature in data['features']:
        geom_data = feature.get('geometry')
        if not geom_data:
            continue
        geom = shape(geom_data)
        storm_name = feature['properties'].get('STORMNAME', 'Unknown')
        prob = feature['properties'].get('PWIND120', 0)
        prob_polys.append({"storm": storm_name, "prob": prob, "geometry": geom})

# Convert to GeoDataFrame
prob_gdf = gpd.GeoDataFrame(prob_polys, crs="EPSG:4326")

# -------------------------
# EARTHQUAKES
# -------------------------
def mag_color(mag):
    if mag < 5.0: return "#ffff66"
    elif mag < 6.0: return "#ce4823"
    elif mag < 7.0: return "#ff3333"
    else: return "#9900cc"

for feat in eq_points_data.get("features", []):
    props = feat.get("properties", {})
    geom = feat.get("geometry", {})
    coords = geom.get("coordinates", [])
    if len(coords) < 2: continue
    lon, lat = coords[:2]
    mag = props.get("mag")
    depth = props.get("depth") or props.get("depth_km") or props.get("z") or "?"
    if mag is None or mag < 5: continue
    col = mag_color(mag)
    radius = 1 + mag * 1.5
    folium.CircleMarker(
        (lat, lon),
        radius=radius,
        color=col,
        fill=True,
        fill_color=col,
        fill_opacity=0.8,
        tooltip=f"M{mag}, Depth: {depth} km"
    ).add_to(eq_layer)

# Shake intensity polygons
from branca.colormap import linear

# Shake intensity colors: 1-3 clear, 4-10 specific colors
intensity_colors = {
    4: "#ADD8FF",  # light blue
    5: "#00FF00",  # green
    6: "#FFFF00",  # yellow
    7: "#FFA500",  # light orange
    8: "#FF8C00",  # dark orange
    9: "#FF6666",  # light red
    10:"#8B0000",  # dark red
}

def intensity_color(intensity):
    if intensity < 4:
        return "#00000000"  # transparent
    return intensity_colors.get(int(intensity), "#000000")  # fallback black

# Add shake intensity polygons
folium.GeoJson(
    eq_intensity_data,
    style_function=lambda f: {
        "fillColor": intensity_color(f["properties"].get("grid_value", 0)),
        "color": "none",
        "fillOpacity": 0.6 if f["properties"].get("grid_value",0) >= 4 else 0,
        "weight": 0
    },
    tooltip=folium.GeoJsonTooltip(fields=["grid_value"], aliases=["Intensity"])
).add_to(shake_layer)

# -------------------------
# USA WILDFIRES (polygons only)
# -------------------------
print("Fetching USA Wildfires (polygons only)...")
wildfire_url = "https://services9.arcgis.com/RHVPKKiFTONKtxq3/arcgis/rest/services/USA_Wildfires_v1/FeatureServer/1/query"
wildfire_params = {
    "where": f"CreateDate >= TIMESTAMP '{time_filter}'",
    "outFields": "*",
    "f": "geojson",
    "resultRecordCount": 4000
}
wildfire_response = requests.get(wildfire_url, params=wildfire_params)
wildfire_data = wildfire_response.json()
features = wildfire_data.get("features", [])
if not features:
    print("⚠️ No wildfire polygons returned for the last 7 days.")
    
# Fix coordinates for WGS84
def fix_coordinates(feature):
    geom_type = feature['geometry']['type']
    coords = feature['geometry']['coordinates']
    if geom_type == 'Polygon':
        if abs(coords[0][0][0]) > 180:
            feature['geometry']['coordinates'] = [[[y, x] for x, y in ring] for ring in coords]
    elif geom_type == 'MultiPolygon':
        if abs(coords[0][0][0][0]) > 180:
            feature['geometry']['coordinates'] = [[[[y, x] for x, y in ring] for ring in poly] for poly in coords]
    return feature

wildfire_data['features'] = [fix_coordinates(f) for f in features]

# Convert timestamps & set popup/tooltip
for feature in wildfire_data['features']:
    props = feature['properties']
    incident = props.get('IncidentName','')
    category = props.get('FeatureCategory','')
    timestamp = props.get('DateCurrent','')
    try:
        if timestamp:
            dt = datetime.utcfromtimestamp(int(timestamp)/1000)
            formatted_date = dt.strftime("%d/%m/%Y, %H:%M")
        else:
            formatted_date = ''
    except:
        formatted_date = str(timestamp)
    feature['properties']['popup_text'] = f"Incident: {incident}<br>Category: {category}<br>Date: {formatted_date}"
    feature['properties']['tooltip_date'] = formatted_date

# Style function
def wildfire_style(feature):
    category = feature['properties'].get('FeatureCategory','')
    color = 'red' if category == 'Wildfire Daily Fire Perimeter' else 'orange'
    return {'fillColor': color, 'color': color, 'weight': 2, 'fillOpacity': 0.4}

# Create wildfire layer
wildfire_layer = folium.FeatureGroup(name="USA Wildfires", show=False)
folium.GeoJson(
    wildfire_data,
    style_function=wildfire_style,
    tooltip=folium.GeoJsonTooltip(
        fields=['IncidentName','FeatureCategory','tooltip_date'],
        aliases=['Incident:','Category:','Date:'],
        labels=True,
        sticky=True
    ),
    popup=folium.GeoJsonPopup(fields=['popup_text'])
).add_to(wildfire_layer)

# Add to map
wildfire_layer.add_to(m)

# -------------------------
# NWS FLOOD EVENTS (shades of blue)
# -------------------------
print("Fetching NWS flood events...")
flood_url = "https://services9.arcgis.com/RHVPKKiFTONKtxq3/arcgis/rest/services/NWS_Watches_Warnings_v1/FeatureServer/6/query"
flood_data = fetch_geojson(flood_url, {"where": "1=1", "outFields": "*", "f": "geojson"})

# Detect event field
event_field = None
if flood_data['features']:
    sample_props = flood_data['features'][0]['properties']
    if 'Event' in sample_props:
        event_field = 'Event'
    elif 'EVENT' in sample_props:
        event_field = 'EVENT'
    else:
        event_field = list(sample_props.keys())[0]  # fallback
else:
    flood_data['features'] = []

# Filter only flood-related features (case-insensitive)
flood_features = {
    "type": "FeatureCollection",
    "features": [f for f in flood_data['features'] if 'flood' in f['properties'].get(event_field,'').lower()]
}
print(f"Total flood-related features: {len(flood_features['features'])}")

# Color function
def get_blue_shade(event_name):
    event_name = event_name.lower()
    if "flash flood warning" in event_name:
        return "#08306b"  # darkest
    elif "flood warning" in event_name:
        return "#2171b5"
    elif "flood watch" in event_name:
        return "#6baed6"
    else:
        return "#c6dbef"  # lightest

# Add as FeatureGroup
flood_layer = folium.FeatureGroup(name="Flood Events", show=False)
folium.GeoJson(
    flood_features,
    style_function=lambda feature: {
        "fillColor": get_blue_shade(feature['properties'][event_field]),
        "color": get_blue_shade(feature['properties'][event_field]),
        "weight": 2,
        "fillOpacity": 0.5,
    },
    tooltip=folium.GeoJsonTooltip(
        fields=[event_field],
        aliases=["Event:"]
    )
).add_to(flood_layer)
flood_layer.add_to(m)

# -------------------------
# CSV EXPOSURE POLYGONS
# -------------------------
csv_path = r"C:\Users\AngusJohnston\Documents\Projects\Exposure Viewer Mk2\Data\exposure_geography_zone_202509291239.csv"
df = pd.read_csv(csv_path)

polygon_col = "Geometry"
id_col = "ExposureGeographyId"
name_col = "Name"

selected_ids = [1, 2, 3, 4, 7]

df_filtered = df[df[id_col].isin(selected_ids)]

layer_names = {1: "Countries", 2: "US States", 3: "Canadian States", 4: "CRESTA Zones", 7: "US Peril Zones"}
layer_colors = {1: "clear", 2: "green", 3: "purple", 4: "orange", 7: "red"}

def add_polygons_to_layer(df_filtered, id_value):
    layer_name = layer_names.get(id_value, f"Geography {id_value}")
    color = layer_colors.get(id_value, "gray")
    layer = folium.FeatureGroup(
    name=layer_name, 
    show=True if id_value == 1 else False  # Only countries visible at start
)

    for _, row in df_filtered[df_filtered[id_col] == id_value].iterrows():
        geom_data = row.get(polygon_col)
        if pd.isna(geom_data):
            continue
        try:
            geom_str = str(geom_data).strip()
            geom = json.loads(geom_str)
            folium.GeoJson(
                geom,
                style_function=lambda x, col=color: {
                    "fillColor": col,
                    "color": "black",
                    "weight": 1,
                    "fillOpacity": 0.3,
                },
            tooltip=folium.Tooltip(f"{row[name_col]}", sticky=False),  # hover only
            ).add_to(layer)
        except Exception as e:
            print(f"Skipping row due to error: {e}")
    return layer

# Add exposure layers to main map
for i in selected_ids:
    layer = add_polygons_to_layer(df_filtered, i)
    layer.add_to(m)

# -------------------------
# LOAD TIV CSV
# -------------------------
tiv_file_path = r"C:\Users\AngusJohnston\Documents\Projects\Exposure Viewer Mk2\Data\TIV_Peril_Locs.csv"
print("Loading TIV CSV (may take a few seconds)...")
tiv_df = pd.read_csv(tiv_file_path)

# Ensure numeric columns
numeric_cols = ['latitude','longitude','total_tiv_usd','eq_total_usd','ws_total_usd',
                'to_total_usd','fl_total_usd','fr_total_usd']
for col in numeric_cols:
    tiv_df[col] = pd.to_numeric(tiv_df[col], errors='coerce')

# GeoDataFrame for all points
points_gdf = gpd.GeoDataFrame(
    tiv_df,
    geometry=gpd.points_from_xy(tiv_df.longitude, tiv_df.latitude),
    crs="EPSG:4326"
)

# ------------------------------------------------------
# WILDFIRE EXPOSURE CALCULATION (run AFTER points_gdf)
# ------------------------------------------------------
print("🔹 Calculating total wf_total_usd exposure per wildfire polygon...")

import geopandas as gpd

try:
    # Convert wildfire polygons to GeoDataFrame
    wf_poly_gdf = gpd.GeoDataFrame.from_features(wildfire_data["features"], crs="EPSG:4326")

    # Create unique ID for each wildfire polygon
    wf_poly_gdf["wf_poly_id"] = wf_poly_gdf.index.astype(str)

    # Spatial join points to wildfire polygons
    wf_join = gpd.sjoin(points_gdf, wf_poly_gdf, how="inner", predicate="intersects")

    # Sum exposure per wildfire polygon
    tiv_by_wf = wf_join.groupby(["wf_poly_id", "IncidentName"])["fr_total_usd"].sum().reset_index()

    # Merge results back into polygons
    wf_poly_gdf = wf_poly_gdf.merge(tiv_by_wf, on=["wf_poly_id", "IncidentName"], how="left")
    wf_poly_gdf["fr_total_usd"] = wf_poly_gdf["fr_total_usd"].fillna(0)

    print(f"✅ Added wildfire exposure data to {len(wf_poly_gdf)} polygons")

except Exception as e:
    print(f"⚠️ Wildfire exposure calculation failed: {e}")

# -------------------------
# Add wf_total_usd per wildfire polygon
# -------------------------
print("🔹 Calculating total fr_total_usd exposure per wildfire polygon...")

# Convert wildfire polygons to GeoDataFrame
from shapely.geometry import shape

wf_polys = []
for i, f in enumerate(wildfire_data.get("features", [])):
    geom = shape(f.get("geometry", {}))
    wf_polys.append({
        "wf_id": f"wf{i}",
        "geometry": geom,
        "IncidentName": f["properties"].get("IncidentName", f"Wildfire {i}")
    })

if wf_polys:
    wf_poly_gdf = gpd.GeoDataFrame(wf_polys, crs="EPSG:4326")
    wf_poly_gdf["geometry"] = wf_poly_gdf.geometry.apply(lambda g: g.buffer(0) if not g.is_valid else g)

    # Spatial join with exposure points to sum wf_total_usd
    join_wf = gpd.sjoin(points_gdf, wf_poly_gdf, how="inner", predicate='intersects')
    tiv_by_wf = join_wf.groupby(["wf_id", "IncidentName"])['fr_total_usd'].sum().reset_index()

    # Merge totals back into polygons
    wf_poly_gdf = wf_poly_gdf.merge(tiv_by_wf, on=["wf_id", "IncidentName"], how="left").fillna(0)

    # Create a labeled GeoJson layer showing wf_total_usd
    wildfire_value_layer = folium.FeatureGroup(name="Wildfire Exposure ('fr_total_usd')", show=False)
    folium.GeoJson(
        wf_poly_gdf,
        style_function=lambda f: {
            'fillColor': 'red',
            'color': 'darkred',
            'weight': 1,
            'fillOpacity': 0.4
        },
        tooltip=folium.GeoJsonTooltip(
            fields=["IncidentName", 'fr_total_usd'],
            aliases=["Incident:", "Exposure ('fr_total_usd'): $"],
            localize=True
        )
    ).add_to(wildfire_value_layer)

    wildfire_value_layer.add_to(m)

# -------------------------
# HURRICANE / PROBABILISTIC EXPOSURE
# -------------------------
if points_gdf.crs != prob_gdf.crs:
    prob_gdf = prob_gdf.to_crs(points_gdf.crs)

prob_gdf["geometry"] = prob_gdf.geometry.apply(lambda g: g.buffer(0) if not g.is_valid else g)
join_prob = gpd.sjoin(points_gdf, prob_gdf, how="inner", predicate='intersects').copy()

# Sum ws_total_usd for hurricanes
tiv_per_storm_prob = join_prob.groupby(["storm", "prob"])['ws_total_usd'].sum().reset_index()

# -------------------------
# EARTHQUAKES ≥6 & SHAKE POLYGONS
# -------------------------
shake_features = eq_intensity_data.get("features", [])
shake_polys = []
for i, f in enumerate(shake_features):
    geom = shape(f.get("geometry", {}))
    intensity = f["properties"].get("grid_value", 0)
    shake_polys.append({
        "shake_id": f"shake{i}",
        "geometry": geom,
        "intensity": intensity
    })

shake_gdf = gpd.GeoDataFrame(shake_polys, crs="EPSG:4326")
shake_gdf["geometry"] = shake_gdf.geometry.apply(lambda g: g.buffer(0) if not g.is_valid else g)

# Correct shake_bounds format for JS zoom
shake_bounds = {
    row['shake_id']: [[row.geometry.bounds[1], row.geometry.bounds[0]],  # [miny, minx]
                      [row.geometry.bounds[3], row.geometry.bounds[2]]]  # [maxy, maxx]
    for idx, row in shake_gdf.iterrows()
}

# Join points to shake polygons
join_shake = gpd.sjoin(points_gdf, shake_gdf, how="inner", predicate='intersects')

# Sum eq_total_usd per shake polygon
tiv_by_shake = join_shake.groupby(["shake_id", "intensity"])['eq_total_usd'].sum().reset_index()

# Filter shake polygons that intersect ≥6 earthquakes
eq_features = [
    f for f in eq_points_data.get("features", [])
    if f["properties"].get("mag") is not None and f["properties"]["mag"] >= 6
]

eq_gdf = gpd.GeoDataFrame([
    {
        "eq_id": f["properties"].get("id", f"eq{i}"),
        "geometry": shape(f["geometry"]),
        "mag": f["properties"].get("mag"),
        "place": f["properties"].get("place", "Unknown")
    } for i, f in enumerate(eq_features)
], crs="EPSG:4326")

eq_coords = eq_gdf.set_index("eq_id")["geometry"].apply(lambda g: [g.y, g.x]).to_dict()

def zoom_to_eq(eq_id):
    if eq_id in eq_coords:
        lat, lon = eq_coords[eq_id]
        m.fit_bounds([[lat-0.5, lon-0.5], [lat+0.5, lon+0.5]])  # or appropriate zoom delta

eq_shake_join = gpd.sjoin(eq_gdf, shake_gdf, how="inner", predicate='intersects')
shake_ids_for_eq6 = eq_shake_join["shake_id"].unique()
shake_points_eq6 = join_shake[join_shake["shake_id"].isin(shake_ids_for_eq6)]

tiv_per_eq = shake_points_eq6.groupby("shake_id")['eq_total_usd'].sum().reset_index()
shake_to_eq = eq_shake_join.set_index("shake_id")[["eq_id","mag","place"]].to_dict(orient="index")
tiv_per_eq["eq_id"] = tiv_per_eq["shake_id"].map(lambda x: shake_to_eq.get(x, {}).get("eq_id"))
tiv_per_eq["mag"] = tiv_per_eq["shake_id"].map(lambda x: shake_to_eq.get(x, {}).get("mag"))
tiv_per_eq["place"] = tiv_per_eq["shake_id"].map(lambda x: shake_to_eq.get(x, {}).get("place"))

# -------------------------
# HEATMAP (total_tiv_usd)
# -------------------------
df_heat = tiv_df.dropna(subset=["latitude","longitude","total_tiv_usd"]).copy()

# Ensure numeric
df_heat['latitude'] = pd.to_numeric(df_heat['latitude'], errors='coerce')
df_heat['longitude'] = pd.to_numeric(df_heat['longitude'], errors='coerce')
df_heat['weight'] = pd.to_numeric(df_heat['total_tiv_usd'], errors='coerce')

# Drop rows with invalid coords or weight
df_heat = df_heat.dropna(subset=['latitude','longitude','weight'])

# Clamp coordinates to valid ranges
df_heat = df_heat[(df_heat.latitude >= -90) & (df_heat.latitude <= 90)]
df_heat = df_heat[(df_heat.longitude >= -180) & (df_heat.longitude <= 180)]

# Normalize weight
max_tiv = df_heat['weight'].max()
df_heat['weight'] = df_heat['weight'] / max_tiv if max_tiv else 1

# Downsample for performance (increase fraction to preserve global coverage)
sample_frac = 0.2 if len(df_heat) > 500_000 else 1.0
df_sample = df_heat.sample(frac=sample_frac, random_state=42)

# Prepare heatmap points
heat_points = df_sample[["latitude","longitude","weight"]].values.tolist()

# Add heatmap layer
heat_layer = folium.FeatureGroup(name="Exposure Heatmap (TIV)", show=False)
HeatMap(
    data=heat_points,
    radius=10,
    blur=15,
    min_opacity=0.3,
    max_opacity=0.8
).add_to(heat_layer)
heat_layer.add_to(m)
print(f"✅ Exposure heatmap layer added (weighted by total_tiv_usd, {len(df_sample):,} points)")

# -------------------------
# WILDFIRE TIV IN POLYGONS
# -------------------------

# Ensure numeric column exists
tiv_df['fr_total_usd'] = pd.to_numeric(tiv_df.get('fr_total_usd', 0), errors='coerce')

# Spatial join: points inside wildfire polygons
wf_join = gpd.sjoin(points_gdf, wf_poly_gdf, how="inner", predicate="intersects")

# Sum wf_total_usd per wildfire polygon
tiv_by_wildfire = wf_join.groupby("fr_poly_id")['fr_total_usd'].sum().reset_index()

# Optional: map polygon info back
wf_info = wf_poly_gdf.set_index("wf_poly_id")[["name", "date"]].to_dict(orient="index")
tiv_by_wildfire["name"] = tiv_by_wildfire["wf_poly_id"].map(lambda x: wf_info.get(x, {}).get("name"))
tiv_by_wildfire["date"] = tiv_by_wildfire["wf_poly_id"].map(lambda x: wf_info.get(x, {}).get("date"))

# Example: print summary
print(tiv_by_wildfire.head())

# -------------------------
# ADD LAYERS & CONTROL
# -------------------------
hurricane_layer.add_to(m)
eq_layer.add_to(m)
shake_layer.add_to(m)
wildfire_layer.add_to(m)
flood_layer.add_to(m)
heat_layer.add_to(m)  

folium.LayerControl(collapsed=True).add_to(m)

# -------------------------
# LEGEND + HURRICANE SUMMARY HTML
# -------------------------
legend_html = """
<div id="legend" style="position: fixed; bottom: 30px; left: 30px; width: 380px; max-height: 400px; overflow-y: auto; background-color: white; border:2px solid grey; z-index:9999; font-size:14px; border-radius: 8px; padding:10px; box-shadow:2px 2px 6px rgba(0,0,0,0.3);">
  <div onclick="toggleLegend()" style="background:#f2f2f2;cursor:pointer;padding:5px;font-weight:bold;">
    Legend + Quick Zoom (click to expand/collapse)
  </div>
  <div id="legend-content" style="display:none; padding:5px;">

     <b>Hurricanes</b><br>
    <i style="background:#87CEFA50;width:15px;height:15px;float:left;margin-right:5px;border:1px solid #003366;"></i> Forecast Cone<br>
    <i style="background:#000000;width:15px;height:2px;float:left;margin-right:5px;"></i> Forecast / Historic Track<br><br>

    <b>Hurricane Force Probability</b><br>
    <div style="position: relative; width: 150px; height: 15px; background: linear-gradient(to right, 
    #7CFC0070 0%, 
    #FFFF0070 20%, 
    #FFA50070 40%, 
    #FF000070 60%, 
    #80008070 80%, 
    #80008070 100%); border:1px solid #000; margin:5px 0;"></div>
    <div style="display: flex; justify-content: space-between; font-size: 12px; width: 150px; margin-top: 2px;">
    <span>0%</span>
    <span>100%</span>
    </div>
    <br>

    <b>Earthquakes (last 7 days)</b><br>
    <i style="background:#ce4823;width:15px;height:15px;float:left;margin-right:5px;"></i> M6.0–7.0<br>
    <i style="background:#ff3333;width:15px;height:15px;float:left;margin-right:5px;"></i> M≥7.0<br>
    <b>Shake Intensity</b><br>
    <i style="background:#ADD8FF;width:15px;height:15px;float:left;margin-right:5px;"></i> 4<br>
    <i style="background:#00FF00;width:15px;height:15px;float:left;margin-right:5px;"></i> 5<br>
    <i style="background:#FFFF00;width:15px;height:15px;float:left;margin-right:5px;"></i> 6<br>
    <i style="background:#FFA500;width:15px;height:15px;float:left;margin-right:5px;"></i> 7<br>
    <i style="background:#FF8C00;width:15px;height:15px;float:left;margin-right:5px;"></i> 8<br>
    <i style="background:#FF6666;width:15px;height:15px;float:left;margin-right:5px;"></i> 9<br>
    <i style="background:#8B0000;width:15px;height:15px;float:left;margin-right:5px;"></i> 10<br><br>


    <b>Wildfires</b><br>
    <i style="background:red;width:15px;height:15px;float:left;margin-right:5px;"></i> Wildfire Daily Fire Perimeter<br>
    <i style="background:orange;width:15px;height:15px;float:left;margin-right:5px;"></i> Other Fire<br><br>

    <b>Flood Events</b><br>
    <i style="background:#08306b;width:15px;height:15px;float:left;margin-right:5px;"></i> Flash Flood Warning<br>
    <i style="background:#2171b5;width:15px;height:15px;float:left;margin-right:5px;"></i> Flood Warning<br>
    <i style="background:#6baed6;width:15px;height:15px;float:left;margin-right:5px;"></i> Flood Watch<br>
    <i style="background:#c6dbef;width:15px;height:15px;float:left;margin-right:5px;"></i> Other Flood Events<br><br>

    <b>Quick Zoom</b><br>
    <div style="margin-top:5px;">
        <div onclick="zoomTo('usa')" style="display:inline-block; padding:3px 6px; margin:2px; background:#007bff; color:white; border-radius:4px; cursor:pointer;">USA</div>
        <div onclick="zoomTo('europe')" style="display:inline-block; padding:3px 6px; margin:2px; background:#007bff; color:white; border-radius:4px; cursor:pointer;">Europe</div>
        <div onclick="zoomTo('japan')" style="display:inline-block; padding:3px 6px; margin:2px; background:#007bff; color:white; border-radius:4px; cursor:pointer;">Japan</div>
        <div onclick="zoomTo('world')" style="display:inline-block; padding:3px 6px; margin:2px; background:#007bff; color:white; border-radius:4px; cursor:pointer;">World</div>
    </div>

  </div>
</div>

<script>
function toggleLegend() {
  var x = document.getElementById("legend-content");
  x.style.display = (x.style.display === "none") ? "block" : "none";
}

function getMap() {
    if (window._leaflet_map) return window._leaflet_map;
    for (var key in window) {
        if (window[key] instanceof L.Map) {
            window._leaflet_map = window[key];
            return window._leaflet_map;
        }
    }
    return null;
}

function zoomTo(region) {
    var map = getMap();
    if (!map) return;
    if (region === 'usa') { map.setView([37.8, -96], 4); }
    else if (region === 'europe') { map.setView([54, 15], 4); }
    else if (region === 'japan') { map.setView([36, 138], 5); }
    else if (region === 'world') { map.setView([20, 0], 2); }
}

// Pre-cache map reference after Leaflet initializes
setTimeout(getMap, 1000);
</script>
"""

# Add legend to the map
m.get_root().html.add_child(folium.Element(legend_html))

# -------------------------
# HURRICANE SUMMARY PANEL (simplified)
# -------------------------
latest_storms = defaultdict(dict)
for feature in hurr_data.get("features", []):
    props = feature.get("properties", {})
    name = props.get("STORMNAME", "Unknown")
    storm_type = props.get("STORMTYPE", "Unknown")
    date_str = props.get("DATE", "")
    try:
        dt = datetime.fromisoformat(date_str) if date_str else now
    except:
        dt = now
    if name not in latest_storms or dt > latest_storms[name]["datetime"]:
        latest_storms[name] = {"name": name, "type": storm_type, "datetime": dt}

today = datetime.now(timezone.utc).date()
storms_today = [s for s in latest_storms.values() if s["datetime"].date() == today]
storms_today = sorted(storms_today, key=lambda x: x["datetime"], reverse=True)

hurricane_bounds_js = json.dumps(hurricane_location_bounds)

from collections import defaultdict
import json

# -------------------------
# Prepare latest storms (one per name)
# -------------------------
latest_storms = {}
for feature in hurr_data.get("features", []):
    props = feature.get("properties", {})
    name = props.get("STORMNAME", "Unknown")
    storm_type = props.get("STORMTYPE", "Unknown")
    date_str = props.get("DATE", "")
    try:
        dt = datetime.fromisoformat(date_str) if date_str else now
    except:
        dt = now
    if name not in latest_storms or dt > latest_storms[name]["datetime"]:
        latest_storms[name] = {"name": name, "type": storm_type, "datetime": dt}

# Only storms today
today = datetime.now(timezone.utc).date()
storms_today = sorted(
    [s for s in latest_storms.values() if s["datetime"].date() == today],
    key=lambda x: x["datetime"],
    reverse=True
)

# -------------------------
# Unified disaster panel HTML + JS
# -------------------------
shake_bounds_json = json.dumps(shake_bounds)
hurricane_bounds_json = json.dumps(hurricane_location_bounds)
'TIV'
summary_html = f"""
<div id="disaster-panel" style="
    position: fixed; 
    bottom: 30px; 
    right: 30px; 
    width: 380px; 
    max-height: 450px; 
    overflow-y: auto;
    background-color: white; 
    border:2px solid grey; 
    z-index:9999; 
    font-size:14px; 
    border-radius: 8px; 
    padding:10px;
    box-shadow:2px 2px 6px rgba(0,0,0,0.3);">

    <div style="font-weight:bold; cursor:pointer;" onclick="togglePanel('disaster-content')">
        Active Hurricanes & Shake Intensity TIV (click to expand/collapse)
    </div>

    <div id="disaster-content" style="padding-top:5px; display:block;">

        <div style="margin-bottom:10px;">
            <b>Hurricanes / Tropical Storms</b><br>
"""

# Hurricane section
for s in storms_today:
    storm_name = s['name']
    summary_html += f"""
        <div style="margin-bottom:6px; display:flex; flex-direction:column;">
            <div>
                <b style="color:blue; cursor:pointer;" onclick="zoomToHurricane('{storm_name}')">{storm_name}</b> ({s['type']})
            </div>
    """
    storm_probs = tiv_per_storm_prob[tiv_per_storm_prob['storm']==storm_name]
    for _, row in storm_probs.sort_values("prob").iterrows():
        summary_html += f"""
            <div style="margin-left:10px; font-size:12px;">
                Capital currently at risk: ${row['ws_total_usd']:,.0f}
            </div>
        """
    summary_html += "</div>"

# Shake intensity section
summary_html += """
        </div>
        <div style="margin-bottom:10px;">
            <b>Shake Intensity Polygons (Earthquakes ≥6)</b><br>
"""
for _, row in tiv_per_eq.sort_values("mag", ascending=False).iterrows():
    shake_id = row['shake_id']
    summary_html += f"""
        <div style="margin-bottom:4px;">
            <b style="color:red; cursor:pointer;" onclick="zoomToShake('{shake_id}')">
                M{row['mag']} – {row['place']}: ${row['eq_total_usd']:,.0f}
            </b>
        </div>
    """

summary_html += """
        </div>
    </div>
</div>

<script>
function togglePanel(contentId) {
    var content = document.getElementById(contentId);
    if (!content) return;
    content.style.display = (content.style.display === "none") ? "block" : "none";
}

// Cache map reference
function getMap() {
    if (window._leaflet_map) return window._leaflet_map;
    for (var key in window) {
        if (window[key] instanceof L.Map) {
            window._leaflet_map = window[key];
            return window._leaflet_map;
        }
    }
    return null;
}

// Hurricane and Shake bounds
var hurricane_bounds = """ + hurricane_bounds_json + """;
var shake_bounds = """ + shake_bounds_json + """;

// Zoom functions
function zoomToHurricane(name) {
    var map = getMap();
    if (!map) return;
    var bounds = hurricane_bounds[name];
    if (bounds) {
        var southWest = bounds[0];
        var northEast = bounds[1];
        var centerLat = (southWest[0] + northEast[0]) / 2;
        var centerLng = (southWest[1] + northEast[1]) / 2;
        map.setView([centerLat, centerLng], 7);
    }
}

function zoomToShake(shake_id) {
    var map = getMap();
    if (!map) return;
    var bounds = shake_bounds[shake_id];
    if (bounds) {
        var southWest = bounds[0];
        var northEast = bounds[1];
        var centerLat = (southWest[0] + northEast[0]) / 2;
        var centerLng = (southWest[1] + northEast[1]) / 2;
        map.setView([centerLat, centerLng], 7);
    }
}
</script>

"""

# Add panel to map

# Add disaster panel to map
m.get_root().html.add_child(folium.Element(summary_html))

# Add auto-refresh JS
refresh_js = """
<script>
function refreshLayer(layerName, url) {
    var map = getMap();
    if (!map) return;

    // Remove existing layer
    map.eachLayer(function(l) {
        if (l.options && l.options.name === layerName) {
            map.removeLayer(l);
        }
    });

    // Fetch new GeoJSON
    fetch(url)
        .then(response => response.json())
        .then(data => {
            var newLayer = L.geoJSON(data).addTo(map);
            newLayer.options.name = layerName;
        });
}

</script>
"""

m.get_root().html.add_child(folium.Element(refresh_js))

# -------------------------
# TOP BANNER (text only) + LARGE LENS TEXT + SHIFTED UI CONTROLS
# -------------------------
banner_html = """
<div id="top-banner" style="
    position: fixed;
    top: 0;
    left: 0;
    width: 100%;
    background: rgba(0, 0, 0, 0.85);
    color: white;
    z-index: 9999;
    display: flex;
    align-items: center;
    justify-content: flex-start;
    padding: 5px 20px;
    font-family: Arial, sans-serif;
    box-shadow: 0 2px 6px rgba(0,0,0,0.5);
    height: 50px;
    box-sizing: border-box;
    white-space: nowrap;
">
    <span style="font-size: 36px; font-weight: bold;">LENS</span>
    <span style="font-size: 12px; font-weight: normal; margin-left: 10px;"> Loss Exposure & Natural-hazard Scanner</span>
</div>

<style>
    /* Push map down so top controls aren't hidden */
    .folium-map {
        position: relative;
        top: 50px;  /* matches banner height */
    }

    /* Popups appear below banner */
    .leaflet-popup-content-wrapper {
        margin-top: 50px;
    }

    /* Shift Leaflet controls below banner */
    .leaflet-top.leaflet-left, .leaflet-top.leaflet-right {
        top: 50px;  /* matches banner height */
    }

    /* Responsive adjustments */
    @media (max-width: 768px) {
        #top-banner {
            height: 60px;
            padding: 5px 10px;
        }
        #top-banner span:first-child { font-size: 28px; }
        #top-banner span:last-child { font-size: 10px; margin-left: 5px; }
        .leaflet-top.leaflet-left, .leaflet-top.leaflet-right {
            top: 60px;
        }
        .leaflet-popup-content-wrapper {
            margin-top: 60px;
        }
    }

    @media (max-width: 480px) {
        #top-banner {
            height: 50px;
            padding: 5px 8px;
        }
        #top-banner span:first-child { font-size: 22px; }
        #top-banner span:last-child { font-size: 9px; margin-left: 4px; }
        .leaflet-top.leaflet-left, .leaflet-top.leaflet-right {
            top: 50px;
        }
        .leaflet-popup-content-wrapper {
            margin-top: 50px;
        }
    }
</style>
"""

m.get_root().html.add_child(folium.Element(banner_html))

# -------------------------
# SAVE MAP
# -------------------------
m.save("full_disaster_map_test.html")
print("✅ Map saved as full_disaster_map_test.html")
