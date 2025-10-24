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
import matplotlib.pyplot as plt
import matplotlib.cm as cm
import matplotlib.colors as colors
from branca.colormap import StepColormap
import numpy as np
from urllib.parse import urlparse
from datetime import timezone  


# HELPER FUNCTION

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


# HELPER: Get bounds from geometry

def get_bounds(geom):
    """Return [[south, west], [north, east]] bounds for a GeoJSON geometry."""
    try:
        shp = shape(geom)
        bounds = shp.bounds  
        return [[bounds[1], bounds[0]], [bounds[3], bounds[2]]]
    except Exception as e:
        print(f"Could not get bounds: {e}")
        return None

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


# TIME FILTER (last 7 days)

now = datetime.now(timezone.utc)
seven_days_ago = now - timedelta(days=7)
time_filter = seven_days_ago.strftime("%Y-%m-%d %H:%M:%S")


# MAP INIT

import folium

m = folium.Map(
    location=[20, 0],
    zoom_start=3,
    min_zoom=3,   
    max_zoom=9,   
    max_bounds=True
)

m.save("map_with_native_zoom_limits.html")

# BASEMAPS

basemaps = {
    "OpenStreetMap": folium.TileLayer(
        "OpenStreetMap",
        name="OpenStreetMap",
        control=True,
        no_wrap=True,
        attr="© OpenStreetMap contributors",
        overlay=False
    ),
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
    "Satellite": folium.TileLayer(
        tiles="https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}",
        attr="© ESRI & OpenStreetMap contributors",
        name="Satellite",
        control=True,
        no_wrap=True,
        overlay=False
    )
}
basemaps["OpenStreetMap"].add_to(m)

for k, b in basemaps.items():
    if k != "OpenStreetMap":
        b.add_to(m)

def safe_geodataframe(data_list, crs="EPSG:4326"):
    import geopandas as gpd
    if not data_list:
        return gpd.GeoDataFrame(columns=['geometry'], geometry='geometry', crs=crs)
    filtered_data = [item for item in data_list if item.get('geometry') is not None]
    if not filtered_data:
        return gpd.GeoDataFrame(columns=['geometry'], geometry='geometry', crs=crs)
    return gpd.GeoDataFrame(filtered_data, geometry='geometry', crs=crs)

# FETCH DATA

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

location_data = fetch_geojson(
    "https://services9.arcgis.com/RHVPKKiFTONKtxq3/arcgis/rest/services/Active_Hurricanes_v1/FeatureServer/1/query",
    {"where":"1=1","outFields":"*","f":"geojson"}
)

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

storm_polys = []

for feature in location_data.get('features', []):
    storm_name = feature.get('properties', {}).get('STORMNAME', 'Unknown')
    geom_data = feature.get('geometry')
    if geom_data is None:
        continue
    try:
        geom = shape(geom_data)
    except Exception as e:
        print(f"Skipping storm {storm_name} due to invalid geometry: {e}")
        continue
    storm_polys.append({"storm": storm_name, "geometry": geom})

storms_gdf = safe_geodataframe(storm_polys)

if storms_gdf.empty:
    print("No storm data available to display on the map.")
else:
    folium.GeoJson(
        storms_gdf,
        style_function=lambda feature: {
            'fillColor': 'red',
            'color': 'red',
            'weight': 2,
            'fillOpacity': 0.4
        },
        tooltip=folium.GeoJsonTooltip(fields=[], aliases=[], localize=True)
    ).add_to(m)

    print("No storm data available to display on the map.")

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

# FEATURE LAYERS

hurricane_layer = folium.FeatureGroup(name="Hurricanes", show=True)
eq_layer = folium.FeatureGroup(name="Earthquakes", show=False)
shake_layer= folium.FeatureGroup(name="Shake Intensity", show=False)
wildfire_layer = folium.FeatureGroup(name="USA Wildfires", show=False)

# HURRICANES

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
        return "#f1e6e6b4"  
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

    if layer_name == "Hurricane Force Prob":
        data['features'] = sorted(
            data['features'],
            key=lambda f: f['properties'].get('PWIND120', 0)
        )

    for feature in data['features']:
        geom_data = feature.get('geometry')
        if not geom_data:
            print(f"Skipping {feature.get('properties', {}).get('STORMNAME','Unknown')} with no geometry in {layer_name}")
            continue  

        geom = shape(geom_data)
        prob = feature['properties'].get('PWIND120', 0)
        storm_name = feature['properties'].get('STORMNAME', 'Unknown')
        
        if layer_name == "Hurricane Force Prob":
            popup_text = f"{layer_name} Probability: {prob}%"
        elif layer_name.endswith("Prob"):
            popup_text = f"{storm_name}<br>{layer_name} Probability: {prob}%"
        else:
            popup_text = f"{storm_name}<br>{layer_name}"
        
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

# HURRICANE PROBABILITY POLYGONS

prob_polys = []

for layer_name, url in layers_ordered:
    if layer_name not in ["Hurricane Force Prob", "Tropical Storm Prob"]:
        continue  
    
    data = fetch_geojson(url, {"where":"1=1","outFields":"*","f":"geojson"})
    
    for feature in data.get('features', []):
        geom_data = feature.get('geometry')
        if not geom_data:
            print(f"Skipping {feature.get('properties', {}).get('STORMNAME', 'Unknown')} in {layer_name} (no geometry)")
            continue
        try:
            geom = shape(geom_data)
        except Exception as e:
            print(f"Skipping {feature.get('properties', {}).get('STORMNAME','Unknown')} in {layer_name} due to invalid geometry: {e}")
            continue
        
        storm_name = feature['properties'].get('STORMNAME', 'Unknown')
        prob = feature['properties'].get('PWIND120', 0)
        prob_polys.append({"storm": storm_name, "prob": prob, "geometry": geom})

prob_gdf = safe_geodataframe(prob_polys)

print("prob_gdf columns:", prob_gdf.columns)

if prob_gdf.empty:
    print("No probability polygons to display on the map.")
else:
    for idx, row in prob_gdf.iterrows():
        geom = row['geometry']
        storm_name = row['storm']
        prob = row['prob']
        layer_name = "Hurricane Force Prob" if prob > 0 else "Tropical Storm Prob"  

        color = get_color(prob, layer_name)

        polygons = [geom] if isinstance(geom, Polygon) else geom.geoms
        for poly in polygons:
            folium.Polygon(
                locations=[[(y, x) for x, y in poly.exterior.coords]],
                color=color,
                weight=2,
                fill=True,
                fill_color=color,
                fill_opacity=0.35,
                popup=f"{storm_name} - {layer_name} Probability: {prob}%",
            ).add_to(hurricane_layer)

# EARTHQUAKES

def mag_color(mag):
    if mag < 5.0: return "#ffff66"
    elif mag < 6.0: return "#ce4823"
    elif mag < 7.0: return "#c01e1e"
    else: return "#fa0303"

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

from branca.colormap import linear

intensity_colors = {
    4: "#ADD8FF",  
    5: "#00FF00",  
    6: "#FFFF00",  
    7: "#FFA500",  
    8: "#FF8C00",  
    9: "#FF6666",  
    10:"#8B0000",  
}

def intensity_color(intensity):
    if intensity < 4:
        return "#00000000"  
    return intensity_colors.get(int(intensity), "#000000")  

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

# USA WILDFIRES (polygons only)

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

for feature in wildfire_data['features']:
    props = feature['properties']
    incident = props.get('IncidentName','')
    category = props.get('FeatureCategory','')
    timestamp = props.get('DateCurrent','')
    try:
        if timestamp:

            dt = datetime.fromtimestamp(int(timestamp)/1000, tz=timezone.utc)

            formatted_date = dt.strftime("%d/%m/%Y, %H:%M")
        else:
            formatted_date = ''
    except:
        formatted_date = str(timestamp)
    feature['properties']['popup_text'] = f"Incident: {incident}<br>Category: {category}<br>Date: {formatted_date}"
    feature['properties']['tooltip_date'] = formatted_date

def wildfire_style(feature):
    category = feature['properties'].get('FeatureCategory','')
    color = 'red' if category == 'Wildfire Daily Fire Perimeter' else 'orange'
    return {'fillColor': color, 'color': color, 'weight': 2, 'fillOpacity': 0.4}

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
popup=folium.GeoJsonPopup(
    fields=['popup_text',],
    aliases=['Details:'],
    localize=True
)
).add_to(wildfire_layer)

wildfire_layer.add_to(m)

# NWS FLOOD EVENTS 

print("Fetching NWS flood events...")
flood_url = "https://services9.arcgis.com/RHVPKKiFTONKtxq3/arcgis/rest/services/NWS_Watches_Warnings_v1/FeatureServer/6/query"
flood_data = fetch_geojson(flood_url, {"where": "1=1", "outFields": "*", "f": "geojson"})

event_field = None
if flood_data['features']:
    sample_props = flood_data['features'][0]['properties']
    if 'Event' in sample_props:
        event_field = 'Event'
    elif 'EVENT' in sample_props:
        event_field = 'EVENT'
    else:
        event_field = list(sample_props.keys())[0]  
else:
    flood_data['features'] = []

flood_features = {
    "type": "FeatureCollection",
    "features": [f for f in flood_data['features'] if 'flood' in f['properties'].get(event_field,'').lower()]
}
print(f"Total flood-related features: {len(flood_features['features'])}")

def get_blue_shade(event_name):
    event_name = event_name.lower()
    if "flash flood warning" in event_name:
        return "#08306b"  
    elif "flood warning" in event_name:
        return "#2171b5"
    elif "flood watch" in event_name:
        return "#6baed6"
    else:
        return "#c6dbef"  

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

# POSTGRES Data Call 

import os
import getpass
from sqlalchemy import create_engine
import geopandas as gpd
import pandas as pd
from shapely import wkb
from shapely.geometry import shape
from shapely.errors import TopologicalError
import folium
from folium.plugins import HeatMap

db_url = os.environ.get("DB_URL")

if not db_url:
    pg_user = os.environ.get("PGUSER") or input("Postgres user: ")
    pg_host = os.environ.get("PGHOST") or input("Postgres host: ")
    pg_port = os.environ.get("PGPORT") or input("Postgres port (default 5432): ") or "5432"
    pg_db = os.environ.get("PGDATABASE") or input("Postgres database: ")
    pg_password = getpass.getpass("Postgres password (hidden): ")

    db_url = f"postgresql+psycopg2://{pg_user}:{pg_password}@{pg_host}:{pg_port}/{pg_db}"
    del pg_password  

engine = create_engine(db_url)

country_codes = {
    "Afghanistan": "AF",	
    "Åland Islands": "AX",	
    "Albania": "AL",	
    "Algeria": "DZ",	
    "American Samoa": "AS",	
    "Andorra": "AD",	
    "Angola": "AO",	
    "Anguilla": "AI",	
    "Antarctica": "AQ",	
    "Antigua and Barbuda": "AG",	
    "Argentina": "AR",	
    "Armenia": "AM",	
    "Aruba": "AW",	
    "Australia": "AU",	
    "Austria": "AT",	
    "Azerbaijan": "AZ",	
    "Bahamas": "BS",	
    "Bahrain": "BH",	
    "Bangladesh": "BD",	
    "Barbados": "BB",	
    "Belarus": "BY",	
    "Belgium": "BE",	
    "Belize": "BZ",	
    "Benin": "BJ",	
    "Bermuda": "BM",	
    "Bhutan": "BT",	
    "Bolivia": "BO",	
    "Bosnia and Herzegovina": "BA",	
    "Botswana": "BW",	
    "Bouvet Island": "BV",	
    "Brazil": "BR",	
    "British Indian Ocean Territory": "IO",	
    "Brunei": "BN",	
    "Bulgaria": "BG",	
    "Burkina Faso": "BF",	
    "Burundi": "BI",	
    "Cambodia": "KH",	
    "Cameroon": "CM",	
    "Canada": "CA",	
    "Cape Verde": "CV",	
    "Cayman Islands": "KY",	
    "Central African Republic": "CF",	
    "Chad": "TD",	
    "Chile": "CL",	
    "China": "CN",	
    "Christmas Island": "CX",	
    "Cocos (Keeling) Islands": "CC",	
    "Colombia": "CO",	
    "Comoros": "KM",	
    "Congo (Congo-Brazzaville)": "CG",	
    "Cook Islands": "CK",	
    "Costa Rica": "CR",	
    "Côte d'Ivoire": "CI",	
    "Croatia": "HR",	
    "Cuba": "CU",	
    "Cyprus": "CY",	
    "Czech Republic": "CZ",	
    "Denmark": "DK",	
    "Djibouti": "DJ",	
    "Dominica": "DM",	
    "Dominican Republic": "DO",	
    "East Timor": "TL",	
    "Ecuador": "EC",	
    "Egypt": "EG",	
    "El Salvador": "SV",	
    "Equatorial Guinea": "GQ",	
    "Eritrea": "ER",	
    "Estonia": "EE",	
    "Ethiopia": "ET",	
    "Falkland Islands (Malvinas)": "FK",	
    "Faroe Islands": "FO",	
    "Fiji": "FJ",	
    "Finland": "FI",	
    "France": "FR",	
    "French Guiana": "GF",	
    "French Polynesia": "PF",	
    "French Southern Territories": "TF",	
    "Gabon": "GA",	
    "Gambia": "GM",	
    "Georgia": "GE",	
    "Germany": "DE",	
    "Ghana": "GH",	
    "Gibraltar": "GI",	
    "Greece": "GR",	
    "Greenland": "GL",	
    "Grenada": "GD",	
    "Guadeloupe": "GP",	
    "Guam": "GU",	
    "Guatemala": "GT",	
    "Guinea": "GN",	
    "Guinea-Bissau": "GW",	
    "Guyana": "GY",	
    "Haiti": "HT",	
    "Heard and McDonald Islands": "HM",	
    "Honduras": "HN",	
    "Hong Kong": "HK",	
    "Hungary": "HU",	
    "Iceland": "IS",	
    "India": "IN",	
    "Indonesia": "ID",	
    "Iran": "IR",	
    "Iraq": "IQ",	
    "Ireland": "IE",	
    "Israel": "IL",	
    "Italy": "IT",	
    "Jamaica": "JM",	
    "Japan": "JP",	
    "Jordan": "JO",	
    "Kazakhstan": "KZ",	
    "Kenya": "KE",	
    "Kiribati": "KI",	
    "North Korea": "KP",	
    "South Korea": "KR",	
    "Kuwait": "KW",	
    "Kyrgyzstan": "KG",	
    "Laos": "LA",	
    "Latvia": "LV",	
    "Lebanon": "LB",	
    "Lesotho": "LS",	
    "Liberia": "LR",	
    "Libya": "LY",	
    "Liechtenstein": "LI",	
    "Lithuania": "LT",	
    "Luxembourg": "LU",	
    "North Macedonia": "MK",	
    "Madagascar": "MG",	
    "Malawi": "MW",	
    "Malaysia": "MY",	
    "Maldives": "MV",	
    "Mali": "ML",	
    "Malta": "MT",	
    "Marshall Islands": "MH",	
    "Martinique": "MQ",	
    "Mauritania": "MR",	
    "Mauritius": "MU",	
    "Mayotte": "YT",	
    "Mexico": "MX",	
    "Micronesia, Federated States of": "FM",	
    "Moldova": "MD",	
    "Monaco": "MC",	
    "Mongolia": "MN",	
    "Montenegro": "ME",	
    "Montserrat": "MS",	
    "Morocco": "MA",	
    "Mozambique": "MZ",	
    "Myanmar": "MM",	
    "Namibia": "NA",	
    "Nauru": "NR",	
    "Nepal": "NP",	
    "Netherlands": "NL",	
    "New Caledonia": "NC",	
    "New Zealand": "NZ",	
    "Nicaragua": "NI",	
    "Niger": "NE",	
    "Nigeria": "NG",	
    "Niue": "NU",	
    "Norfolk Island": "NF",	
    "Northern Mariana Islands": "MP",	
    "Norway": "NO",	
    "Oman": "OM",	
    "Pakistan": "PK",	
    "Palau": "PW",	
    "Panama": "PA",	
    "Papua New Guinea": "PG",	
    "Paraguay": "PY",	
    "Peru": "PE",	
    "Philippines": "PH",	
    "Pitcairn": "PN",	
    "Poland": "PL",	
    "Portugal": "PT",	
    "Puerto Rico": "PR",	
    "Qatar": "QA",	
    "Réunion": "RE",	
    "Romania": "RO",	
    "Russia": "RU",	
    "Rwanda": "RW",	
    "Saint Kitts and Nevis": "KN",	
    "Saint Lucia": "LC",	
    "Saint Vincent and the Grenadines": "VC",	
    "Samoa": "WS",	
    "San Marino": "SM",	
    "Sao Tome and Principe": "ST",	
    "Saudi Arabia": "SA",	
    "Senegal": "SN",	
    "Serbia": "RS",	
    "Seychelles": "SC",	
    "Sierra Leone": "SL",	
    "Singapore": "SG",	
    "Slovakia": "SK",	
    "Slovenia": "SI",	
    "Solomon Islands": "SB",	
    "Somalia": "SO",	
    "South Africa": "ZA",	
    "South Georgia and the South Sandwich Islands": "GS",	
    "Spain": "ES",	
    "Sri Lanka": "LK",	
    "St. Helena": "SH",	
    "St. Pierre and Miquelon": "PM",	
    "Sudan": "SD",	
    "Suriname": "SR",	
    "Svalbard and Jan Mayen Islands": "SJ",	
    "Swaziland": "SZ",	
    "Sweden": "SE",	
    "Switzerland": "CH",	
    "Syria": "SY",	
    "Taiwan": "TW",	
    "Tajikistan": "TJ",	
    "Tanzania": "TZ",	
    "Thailand": "TH",	
    "Togo": "TG",	
    "Tokelau": "TK",	
    "Tonga": "TO",	
    "Trinidad and Tobago": "TT",	
    "Tunisia": "TN",	
    "Turkey": "TR",	
    "Turkmenistan": "TM",	
    "Turks and Caicos Islands": "TC",	
    "Tuvalu": "TV",	
    "Uganda": "UG",	
    "Ukraine": "UA",	
    "United Arab Emirates": "AE",	
    "United Kingdom": "GB",	
    "United States of America": "US",	
    "Uruguay": "UY",	
    "Uzbekistan": "UZ",	
    "Vanuatu": "VU",	
    "Vatican City": "VA",	
    "Venezuela": "VE",	
    "Vietnam": "VN",	
    "Virgin Islands (British)": "VG",	
    "Virgin Islands (U.S.)": "VI",	
    "Wallis and Futuna": "WF",	
    "Western Sahara": "EH",	
    "Yemen": "YE",	
    "Zambia": "ZM",	
    "Zimbabwe": "ZW"	
}

code_to_country = {v: k for k, v in country_codes.items()}

# LOAD EXPOSURE POLYGONS

exposure_table = "raw_smint.exposure_geography_zone"
geom_column = "Geometry"

try:
    exposure_df = pd.read_sql(f"SELECT * FROM {exposure_table};", engine)
    print(f"✅ Loaded exposure table: {len(exposure_df):,} rows")

    from shapely import wkb
    from shapely.errors import WKBReadingError
    import json

    def safe_geom(val):
        try:
            if val is None:
                return None
            if isinstance(val, bytes):
                return wkb.loads(val)
            if isinstance(val, str):
                try:
                    return wkb.loads(val, hex=True)
                except WKBReadingError:
                    return shape(json.loads(val))
        except Exception as e:
            print(f"Skipping invalid Geometry: {e}")
            return None

    exposure_df['Geometry'] = exposure_df[geom_column].apply(safe_geom)
    exposure_df = exposure_df[exposure_df['Geometry'].notna()].copy()
    exposure_gdf = gpd.GeoDataFrame(exposure_df, geometry='Geometry', crs="EPSG:4326")
except Exception as e:
    print("❌ Failed to load exposure polygons:", e)
    exposure_gdf = gpd.GeoDataFrame(columns=['Geometry'], geometry='Geometry', crs="EPSG:4326")

for col in ['ExposureGeographyId','Name']:
    if col not in exposure_gdf.columns:
        print(f"⚠️ exposure_gdf missing {col} column — adjust mapping if needed.")

selected_ids = ['1','2']
layer_names = {'1': "Countries", '2': "US States"}
layer_colors = {'1': "clear", '2': "green"}
df_filtered = exposure_gdf.copy()

# IMPORTS

import pandas as pd
import geopandas as gpd
import numpy as np
from shapely.geometry import shape
from folium import FeatureGroup, GeoJson, Tooltip
from folium.plugins import HeatMap
from branca.colormap import StepColormap
from sqlalchemy import text
import pandas as pd
import geopandas as gpd
import numpy as np

tiv_cols = [
    'latitude', 'longitude', 'total_insurable_value', 'value_currency',
    'account_number', 'location_number', 'country_code',
    'attachment_point_usd', 'policy_limit_usd', 'exposure_above_att',
    'trapped_exposure_usd', 'participant_name'
]

ded_cols = {
    'eq': ['eqcv1ded','eqcv2ded','eqcv3ded'],
    'ws': ['wscv1ded','wscv2ded','wscv3ded'],
    'to': ['tocv1ded','tocv2ded','tocv3ded'],
    'fl': ['flcv1ded','flcv2ded','flcv3ded'],
    'fr': ['frcv1ded','frcv2ded','frcv3ded']
}

tiv_df = pd.DataFrame(columns=tiv_cols)

# -------------------------
# PARTICIPANT LIST
# -------------------------
participants = sorted(tiv_df['participant_name'].dropna().unique().tolist())

# LOAD TIV DATA WITH PARTICIPANTS, EXCHANGE RATES, AND GEO COORDINATES

tiv_df = pd.DataFrame()

tiv_sql = """

WITH loc_dedup AS (
    SELECT DISTINCT
        accntnum AS account_number,
        cntrycode AS country_code,
        latitude,
        longitude,
        "100% tiv" AS total_insurable_value,
        eqsitelcur AS value_currency,
        rule AS participant_name
    FROM g_exposure_reporting.g_loc_incremental_latest_no_endorsements
    WHERE cntrycode IS NOT NULL
      AND latitude IS NOT NULL
      AND longitude IS NOT NULL
),
acc_dedup AS (
    SELECT DISTINCT
        account_number,
        attachment_point,
        policy_limit_currency
    FROM s_core_reporting.s_acc_incremental
    WHERE account_number IS NOT NULL
),
trapped_per_location AS (
    SELECT
        l.account_number,
        l.country_code,
        l.latitude,
        l.longitude,
        COALESCE(l.participant_name, 'Unassigned') AS participant_name,
        l.total_insurable_value,
        a.attachment_point,
        l.value_currency AS location_currency,
        a.policy_limit_currency AS policy_currency
    FROM loc_dedup l
    LEFT JOIN acc_dedup a
        ON l.account_number = a.account_number
),
trapped_with_usd AS (
    SELECT
        tpl.*,
        GREATEST(
            COALESCE((tpl.total_insurable_value / NULLIF(er_l.conversion_rate, 0)), 0)
            - COALESCE((tpl.attachment_point / NULLIF(er_a.conversion_rate, 0)), 0),
            0
        ) AS trapped_exposure_usd
    FROM trapped_per_location tpl
    LEFT JOIN s_misc.exchange_rates_monthend er_l
        ON tpl.location_currency = er_l.converted_currency 
       AND er_l.monthyear = 202510
    LEFT JOIN s_misc.exchange_rates_monthend er_a
        ON tpl.policy_currency = er_a.converted_currency 
       AND er_a.monthyear = 202510
),
with_all_rows AS (
    -- individual participants
    SELECT 
        country_code,
        latitude,
        longitude,
        participant_name,
        trapped_exposure_usd
    FROM trapped_with_usd
    WHERE trapped_exposure_usd > 0

    UNION ALL

    -- summed "All" row per location
    SELECT 
        country_code,
        latitude,
        longitude,
        'All' AS participant_name,
        SUM(trapped_exposure_usd) AS trapped_exposure_usd
    FROM (
        SELECT DISTINCT country_code, latitude, longitude, participant_name, trapped_exposure_usd
        FROM trapped_with_usd
        WHERE trapped_exposure_usd > 0
    ) unique_participants
    GROUP BY country_code, latitude, longitude
)
SELECT
    country_code,
    latitude,
    longitude,
    participant_name,
    trapped_exposure_usd
FROM with_all_rows
ORDER BY 
    country_code,
    latitude,
    longitude,
    CASE WHEN participant_name = 'All' THEN 0 ELSE 1 END,
    participant_name;
"""

tiv_df = pd.read_sql(text(tiv_sql), con=engine)

if tiv_df.empty:
    print("⚠️ No data returned from SQL query.")
else:
    print(f"✅ Loaded {len(tiv_df)} rows of exposure data.")
    print(tiv_df.head())

points_gdf = gpd.GeoDataFrame(columns=list(tiv_df.columns) + ['geometry'], crs="EPSG:4326")

if tiv_df.empty:
    print("⚠️ No data returned from SQL query.")
else:
    missing = [c for c in ["latitude", "longitude", "trapped_exposure_usd"] if c not in tiv_df.columns]
    if missing:
        print(f"⚠️ Missing columns in TIV results: {missing}")
    else:
        print(f"✅ Columns loaded: {list(tiv_df.columns)}")

if not tiv_df.empty:
    for col in ['trapped_exposure_usd','latitude','longitude']:
        tiv_df[col] = tiv_df[col].astype(float)

if not tiv_df.empty and 'country_code' in tiv_df.columns:
    tiv_df['country_name'] = tiv_df['country_code'].map(code_to_country)
    tiv_df = tiv_df.dropna(subset=['country_name'])

if not tiv_df.empty and {'latitude','longitude'}.issubset(tiv_df.columns):
    points_gdf = gpd.GeoDataFrame(
        tiv_df,
        geometry=gpd.points_from_xy(tiv_df.longitude, tiv_df.latitude),
        crs="EPSG:4326"
    )
else:
    points_gdf = gpd.GeoDataFrame(columns=tiv_df.columns+['geometry'], crs="EPSG:4326")

if not tiv_df.empty and 'country_name' in tiv_df.columns:
    trapped_agg = tiv_df.groupby('country_name')['trapped_exposure_usd'].sum().reset_index()
else:
    trapped_agg = pd.DataFrame(columns=['country_name','trapped_exposure_usd'])


from folium import FeatureGroup, GeoJson, Tooltip
import geopandas as gpd
import numpy as np
import matplotlib.cm as cm
import matplotlib.colors as mcolors
from branca.colormap import StepColormap

def add_trapped_polygons(exposure_gdf, points_gdf, layer_names, id_value, n_breaks=5):
    layer_name = layer_names.get(id_value, f"Geography {id_value}")
    sub = exposure_gdf[exposure_gdf["ExposureGeographyId"] == id_value].copy()
    if sub.empty or sub.geometry.notnull().sum() == 0:
        return None

    layer = FeatureGroup(name=layer_name, show=True if id_value == '1' else False)

    values = sub['trapped_exposure_usd']
    if values.max() > 0:
        quantiles = np.unique(np.quantile(values, np.linspace(0, 1, n_breaks + 1)))
        num_bins = len(quantiles) - 1
        base_colors = ["#deebf7", "#9ecae1", "#6baed6", "#3182bd", "#08519c"]
        colors = base_colors[:num_bins] if num_bins <= len(base_colors) else [mcolors.rgb2hex(cm.Blues(i)) for i in range(num_bins)]
        colormap = StepColormap(colors=colors, index=quantiles, vmin=values.min(), vmax=values.max())
    else:
        colormap = None

    # ---- LOOP OVER POLYGONS ----
    for idx, row in sub.iterrows():
        geom = row['Geometry']
        if geom is None or geom.is_empty:
            continue

        fill_color = colormap(row['trapped_exposure_usd']) if colormap else "#3182bd"

        gj = GeoJson(
            geom.__geo_interface__,
            style_function=lambda x, col=fill_color: {
                "fillColor": col,
                "color": "black",
                "weight": 1,
                "fillOpacity": 0.8
            },
            tooltip=Tooltip(
                f"{row.get('Name','')}<br>Trapped Exposure: ${row['trapped_exposure_usd']:,.0f}",
                sticky=False
            )
        )

        # Attach participant_names for JS filtering
        participant_str = row.get('participant_name', '')
        gj.add_child(folium.Element(
            f"<div style='display:none;' data-participants='{participant_str}'></div>"
        ))

        gj.add_to(layer)

    return layer

# ADD POLYGONS TO MAP

layer_names = {'1':"Countries",'2':"US States"}

if not trapped_agg.empty and not exposure_gdf.empty:
    exposure_gdf = exposure_gdf.merge(trapped_agg, left_on='Name', right_on='country_name', how='left')
    exposure_gdf['trapped_exposure_usd'] = exposure_gdf['trapped_exposure_usd'].fillna(0)
    exposure_gdf = gpd.GeoDataFrame(exposure_gdf, geometry='Geometry', crs="EPSG:4326")


if 'participant_name' in points_gdf.columns and 'Name' in exposure_gdf.columns:
    participant_map = (
        points_gdf.groupby('country_name')['participant_name']
        .apply(lambda x: ', '.join(sorted(x.unique())))
    )

    exposure_gdf = exposure_gdf.reset_index(drop=True)

    exposure_gdf['participant_name'] = exposure_gdf['Name'].map(participant_map).fillna('')
else:
    exposure_gdf['participant_name'] = ''


for id_value in ['1','2']:
    poly_layer = add_trapped_polygons(exposure_gdf, points_gdf, layer_names, id_value)
    if poly_layer:
        poly_layer.add_to(m)
        print(f"✅ Added polygon layer: {layer_names.get(id_value)}")
    else:
        print(f"⚠️ No valid polygons for layer: {layer_names.get(id_value)}")

# HEATMAP (TRAPPED EXPOSURE)

if not tiv_df.empty:
    df_heat = tiv_df.dropna(subset=['latitude','longitude','trapped_exposure_usd']).copy()
    if not df_heat.empty:
        df_heat['weight'] = df_heat['trapped_exposure_usd'] / df_heat['trapped_exposure_usd'].max()
        heat_points = df_heat[['latitude','longitude','weight']].values.tolist()
        heat_layer = FeatureGroup(name="Exposure Heatmap (Trapped Exposure)", show=False)
        HeatMap(data=heat_points, radius=10, blur=15, min_opacity=0.3, max_opacity=0.8).add_to(heat_layer)
        heat_layer.add_to(m)
        print(f"✅ Heatmap added (weighted by trapped exposure, {len(df_heat):,} points)")
    else:
        print("⚠️ No valid trapped exposure points for heatmap")
else:
    print("⚠️ No trapped exposure points available")

# PROBABILISTIC HURRICANE / STORM EXPOSURE

if 'prob_gdf' in locals() and not prob_gdf.empty and not points_gdf.empty:
    # Ensure CRS alignment
    prob_gdf = prob_gdf.to_crs(points_gdf.crs)

    # Clean geometries
    prob_gdf = prob_gdf[prob_gdf.geometry.notnull()].copy()
    prob_gdf['geometry'] = prob_gdf['geometry'].apply(lambda g: g if g.is_valid else g.buffer(0))

    # Spatial join
    join_prob = gpd.sjoin(points_gdf, prob_gdf, how="inner", predicate="within")

    if not join_prob.empty:
        trapped_per_storm_prob = (
            join_prob.groupby(["storm","prob"], as_index=False)
            .apply(lambda df: pd.Series({
                "trapped_exposure_usd": (df["trapped_exposure_usd"] * df["prob"]).sum()
            }))
        )
        trapped_per_storm_prob['trapped_exposure_usd'] = trapped_per_storm_prob['trapped_exposure_usd'].fillna(0)
    else:
        trapped_per_storm_prob = pd.DataFrame(columns=["storm","prob","trapped_exposure_usd"])
        print("⚠️ No points joined to hurricane polygons — check CRS and geometry validity.")
else:
    trapped_per_storm_prob = pd.DataFrame(columns=["storm","prob","trapped_exposure_usd"])
    print("⚠️ prob_gdf or points_gdf is empty")

# EARTHQUAKES ≥6

if 'eq_points_data' in locals():
    eq_features = [f for f in eq_points_data.get("features", []) if isinstance(f.get("properties", {}).get("mag"), (int,float)) and f["properties"]["mag"] >= 6]
    eq_records = []
    for i,f in enumerate(eq_features):
        try:
            geom = shape(f["geometry"])
            eq_records.append({
                "eq_id": f["properties"].get("id", f"eq{i}"),
                "geometry": geom,
                "mag": f["properties"].get("mag"),
                "place": f["properties"].get("place","Unknown")
            })
        except Exception as e:
            print(f"⚠️ Skipping invalid earthquake feature {i}: {e}")
    eq_gdf = gpd.GeoDataFrame(eq_records, geometry="geometry", crs="EPSG:3857") if eq_records else gpd.GeoDataFrame(columns=["eq_id","geometry","mag","place"], geometry="geometry", crs="EPSG:3857")
else:
    eq_gdf = gpd.GeoDataFrame(columns=["eq_id","geometry","mag","place"], geometry="geometry", crs="EPSG:3857")

# SHAKE POLYGONS

shake_features = eq_intensity_data.get("features", []) if 'eq_intensity_data' in locals() else []
shake_polys = []
for i,f in enumerate(shake_features):
    try:
        geom = shape(f.get("geometry",{}))
        if geom.is_empty:
            continue
        intensity = f.get("properties",{}).get("grid_value",0)
        shake_polys.append({"shake_id":f"shake{i}","geometry":geom,"intensity":intensity})
    except Exception as e:
        print(f"⚠️ Skipping invalid shake polygon {i}: {e}")
shake_gdf = gpd.GeoDataFrame(shake_polys, geometry="geometry", crs="EPSG:3857") if shake_polys else gpd.GeoDataFrame(columns=["shake_id","geometry","intensity"], geometry="geometry", crs="EPSG:3857")

# LINK SHAKE POLYGONS TO NEAREST EARTHQUAKE

if not shake_gdf.empty and not eq_gdf.empty:
    shake_proj = shake_gdf.to_crs(3857)
    eq_proj = eq_gdf.to_crs(3857)

    shake_with_eq = gpd.sjoin_nearest(
        shake_proj, eq_proj[['eq_id', 'geometry']], how='left', distance_col='dist'
    )

    shake_with_eq = shake_with_eq.to_crs(4326)
else:
    shake_with_eq = shake_gdf.copy()
    shake_with_eq["eq_id"] = None

# JOIN EXPOSURE POINTS WITH SHAKE POLYGONS

if not shake_with_eq.empty and not points_gdf.empty:
    for col in ['index_left', 'index_right']:
        if col in shake_with_eq.columns:
            shake_with_eq = shake_with_eq.drop(columns=[col])
        if col in points_gdf.columns:
            points_gdf = points_gdf.drop(columns=[col])

    join_shake = gpd.sjoin(points_gdf, shake_with_eq, how="inner", predicate="intersects")

    if 'unique_point_id' not in join_shake.columns:
        print("⚠️ 'unique_point_id' missing after join — re-adding from index.")
        join_shake = join_shake.reset_index().rename(columns={'index': 'unique_point_id'})

    join_shake = (
        join_shake.sort_values('intensity', ascending=False)
        .drop_duplicates(subset=['unique_point_id', 'eq_id'])
    )

    trapped_by_shake_eq = (
        join_shake.groupby(['eq_id', 'shake_id', 'intensity'], as_index=False)['trapped_exposure_usd']
        .sum()
    )

else:
    trapped_by_shake_eq = pd.DataFrame(columns=['eq_id', 'shake_id', 'intensity', 'trapped_exposure_usd'])

# TRAPPED EXPOSURE PER EARTHQUAKE

if not eq_gdf.empty and not points_gdf.empty:
    join_eq = gpd.sjoin(points_gdf, eq_gdf, how="inner", predicate="intersects")
    trapped_per_eq = join_eq.groupby(["eq_id","mag","place"], as_index=False)["trapped_exposure_usd"].sum()
else:
    trapped_per_eq = pd.DataFrame(columns=["eq_id","mag","place","trapped_exposure_usd"])
    print("⚠️ No trapped exposure data for earthquakes ≥6")

# CONVERT BACK TO EPSG:4326 FOR MAPPING

for gdf_name in ["points_gdf","shake_with_eq","prob_gdf","eq_gdf"]:
    if gdf_name in locals() and not locals()[gdf_name].empty:
        locals()[gdf_name] = locals()[gdf_name].to_crs("EPSG:4326")

# -------------------------
# PARTICIPANT-SPECIFIC LAYERS
# -------------------------
participant_layers = {}

for participant in participants:
    participant_points = points_gdf[points_gdf["participant_name"] == participant]

    for id_value in ['1', '2']:  
        poly_layer = add_trapped_polygons(exposure_gdf, participant_points, layer_names, id_value)
        if poly_layer:
            poly_layer.add_to(m)
            participant_layers[f"{participant}_{id_value}"] = poly_layer

    df_heat = participant_points.dropna(subset=['latitude','longitude','trapped_exposure_usd']).copy()
    if not df_heat.empty:
        df_heat['weight'] = df_heat['trapped_exposure_usd'] / df_heat['trapped_exposure_usd'].max()
        heat_layer = FeatureGroup(name=f"Heatmap - {participant}", show=False)
        HeatMap(data=df_heat[['latitude','longitude','weight']].values.tolist(), radius=10, blur=15, min_opacity=0.3, max_opacity=0.8).add_to(heat_layer)
        heat_layer.add_to(m)
        participant_layers[f"{participant}_heat"] = heat_layer

# ADD LAYERS & CONTROL

hurricane_layer.add_to(m)
eq_layer.add_to(m)
shake_layer.add_to(m)
wildfire_layer.add_to(m)
flood_layer.add_to(m)
heat_layer.add_to(m)  

folium.LayerControl(collapsed=True).add_to(m)

# LEGEND + HURRICANE SUMMARY HTML

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

m.get_root().html.add_child(folium.Element(legend_html))

# HURRICANE SUMMARY PANEL 

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


# Prepare latest storms

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

today = datetime.now(timezone.utc).date()
storms_today = sorted(
    [s for s in latest_storms.values() if s["datetime"].date() == today],
    key=lambda x: x["datetime"],
    reverse=True
)

# EARTHQUAKES ≥6 & SHAKE POLYGONS 

shake_features = eq_intensity_data.get("features", [])
shake_polys = []

for i, f in enumerate(shake_features):
    try:
        geom = shape(f.get("geometry", {}))
        if geom.is_empty:
            continue
        intensity = f.get("properties", {}).get("grid_value", 0)
        shake_polys.append({
            "shake_id": f"shake{i}",
            "geometry": geom,
            "intensity": intensity
        })
    except Exception as e:
        print(f"⚠️ Skipping invalid shake polygon {i}: {e}")
        continue

if shake_polys:
    shake_gdf = gpd.GeoDataFrame(shake_polys, geometry="geometry", crs="EPSG:4326")
    shake_gdf["geometry"] = shake_gdf.geometry.apply(lambda g: g if g.is_valid else g.buffer(0))
    eq_gdf["geometry"] = eq_gdf.geometry.apply(lambda g: g if g.is_valid else g.buffer(0))

else:
    print("⚠️ No valid shake polygons found — creating empty GeoDataFrame.")
    shake_gdf = gpd.GeoDataFrame(columns=["shake_id", "geometry", "intensity"], geometry="geometry", crs="EPSG:4326")

# Earthquake points ≥6

eq_features = [
    f for f in eq_points_data.get("features", [])
    if isinstance(f.get("properties", {}).get("mag"), (int, float)) and f.get("properties", {}).get("mag") >= 6
]
eq_records = []
for i, f in enumerate(eq_features):
    try:
        geom = shape(f["geometry"])
        eq_records.append({
            "eq_id": f["properties"].get("id", f"eq{i}"),
            "geometry": geom,
            "mag": f["properties"].get("mag"),
            "place": f["properties"].get("place", "Unknown")
        })
    except Exception as e:
        print(f"⚠️ Skipping invalid earthquake feature {i}: {e}")
        continue

if eq_records:
    eq_gdf = gpd.GeoDataFrame(eq_records, geometry="geometry", crs="EPSG:4326")
else:
    eq_gdf = gpd.GeoDataFrame(columns=["eq_id", "geometry", "mag", "place"], geometry="geometry", crs="EPSG:4326")

# LINK SHAKE POLYGONS TO NEAREST EARTHQUAKE 

if not shake_gdf.empty and not eq_gdf.empty:
    shake_proj = shake_gdf.to_crs(3857)
    eq_proj = eq_gdf.to_crs(3857)

    shake_with_eq = gpd.sjoin_nearest(
        shake_proj, eq_proj[['eq_id', 'geometry']], how='left', distance_col='dist'
    )

    shake_with_eq = shake_with_eq.to_crs(4326)
else:
    shake_with_eq = shake_gdf.copy()
    shake_with_eq["eq_id"] = None

# LINK POINTS TO SHAKE POLYGONS 

if not shake_with_eq.empty and not points_gdf.empty:

    for col in ['index_left', 'index_right']:
        if col in shake_with_eq.columns:
            shake_with_eq = shake_with_eq.drop(columns=[col])
        if col in points_gdf.columns:
            points_gdf = points_gdf.drop(columns=[col])

    join_shake = gpd.sjoin(points_gdf, shake_with_eq, how="inner", predicate="intersects")

    if 'unique_point_id' not in join_shake.columns:
        print("⚠️ 'unique_point_id' missing after join — re-adding from index.")
        join_shake = join_shake.reset_index().rename(columns={'index': 'unique_point_id'})

    join_shake = (
        join_shake.sort_values('intensity', ascending=False)
        .drop_duplicates(subset=['unique_point_id', 'eq_id'])
    )

    trapped_by_shake_eq = (
        join_shake.groupby(['eq_id', 'shake_id', 'intensity'], as_index=False)['trapped_exposure_usd']
        .sum()
    )

else:
    trapped_by_shake_eq = pd.DataFrame(columns=['eq_id', 'shake_id', 'intensity', 'trapped_exposure_usd'])

# SHAKE BOUNDS (for map zoom)

shake_bounds = {}
if not shake_with_eq.empty:
    for _, row in shake_with_eq.iterrows():
        if row.geometry and not row.geometry.is_empty:
            minx, miny, maxx, maxy = row.geometry.bounds
            shake_bounds[row["shake_id"]] = [[miny, minx], [maxy, maxx]]

else:
    trapped_by_shake_eq = pd.DataFrame(columns=['eq_id', 'shake_id', 'intensity', 'trapped_exposure_usd'])

# EARTHQUAKE EXPOSURE (aggregated from shake polygons)

if not shake_with_eq.empty and not points_gdf.empty:
    if points_gdf.crs != shake_with_eq.crs:
        points_proj = points_gdf.to_crs(shake_with_eq.crs)
    else:
        points_proj = points_gdf.copy()

    if 'unique_point_id' not in points_proj.columns:
        points_proj = points_proj.reset_index(drop=True)
        points_proj['unique_point_id'] = points_proj.index

    join_eq = gpd.sjoin(points_proj, shake_with_eq[['eq_id', 'geometry', 'intensity']], how="inner", predicate="intersects")

    join_eq = (
        join_eq.sort_values('intensity', ascending=False)
        .drop_duplicates(subset=['unique_point_id', 'eq_id'])
    )

    trapped_per_eq = (
        join_eq.groupby(['eq_id'], as_index=False)['trapped_exposure_usd'].sum()
    )

    trapped_per_eq = trapped_per_eq.merge(eq_gdf[['eq_id', 'mag', 'place']], on='eq_id', how='left')

else:
    trapped_per_eq = pd.DataFrame(columns=["eq_id", "mag", "place", "trapped_exposure_usd"])
    print("⚠️ No trapped exposure data for earthquakes ≥6.")

# UNIFIED DISASTER PANEL HTML (hurricanes + earthquakes; shake exposure ≥ intensity 4)

# Assuming `prob_gdf` has polygons for hurricane probability and `points_gdf` has TIV points

# -------------------------
# PROBABILISTIC HURRICANE / STORM EXPOSURE
# -------------------------

if 'prob_gdf' in locals() and not prob_gdf.empty and not points_gdf.empty:
    # Ensure CRS alignment
    points_proj = points_gdf.to_crs(prob_gdf.crs)
    
    # Clean geometries
    prob_gdf = prob_gdf[prob_gdf.geometry.notnull()].copy()
    prob_gdf['geometry'] = prob_gdf['geometry'].apply(lambda g: g if g.is_valid else g.buffer(0))

    # Spatial join: points inside each polygon
    join_hurr = gpd.sjoin(points_proj, prob_gdf[['storm','prob','geometry']], how='inner', predicate='intersects')

    if not join_hurr.empty:
        # Sum trapped exposure per polygon (use index_right from sjoin)
        trapped_per_polygon = (
            join_hurr.groupby('index_right', as_index=False)['trapped_exposure_usd'].sum()
        )
        trapped_per_polygon.rename(columns={'trapped_exposure_usd':'trapped_exposure_usd_polygon'}, inplace=True)

        # Merge back into prob_gdf
        prob_gdf = prob_gdf.reset_index()
        prob_gdf = prob_gdf.merge(trapped_per_polygon, left_on='index', right_on='index_right', how='left')
        prob_gdf['trapped_exposure_usd_polygon'] = prob_gdf['trapped_exposure_usd_polygon'].fillna(0)
    else:
        prob_gdf['trapped_exposure_usd_polygon'] = 0
else:
    prob_gdf['trapped_exposure_usd_polygon'] = 0
    print("⚠️ prob_gdf or points_gdf is empty — no hurricane trapped exposure calculated")

shakes_filtered = trapped_by_shake_eq[trapped_by_shake_eq['intensity'] >= 4]

eq_trapped_summary = (
    trapped_by_shake_eq.groupby('eq_id', as_index=False)['trapped_exposure_usd']
    .sum()
)

eq_trapped_summary = eq_trapped_summary.merge(
    trapped_per_eq[['eq_id', 'mag', 'place']],
    on='eq_id',
    how='left'
)

eq_trapped_summary = eq_trapped_summary[eq_trapped_summary['mag'] >= 6]


shake_bounds_json = json.dumps({
    row["shake_id"]: [[row.geometry.centroid.y, row.geometry.centroid.x]] 
    for _, row in shake_with_eq[shake_with_eq['intensity'] >= 4].iterrows()
})

eq_bounds_json = json.dumps({
    row["eq_id"]: [[row.geometry.y, row.geometry.x]] 
    for _, row in eq_gdf.iterrows()
})

hurricane_bounds_json = json.dumps({str(k): v for k, v in hurricane_location_bounds.items()})

disaster_panel_html = """
<div id="disaster-panel" style="position: fixed; bottom: 30px; right: 30px; width: 380px; max-height: 500px; overflow-y: auto; background-color: white; border:2px solid grey; z-index:9999; font-size:14px; border-radius: 8px; padding:10px; box-shadow:2px 2px 6px rgba(0,0,0,0.3);">
<div style="font-weight:bold; cursor:pointer;" onclick="togglePanel('disaster-content')">
Active Disasters & Trapped Exposure (click to expand/collapse)
</div>
<div id="disaster-content" style="padding-top:5px; display:block;">
<b>Hurricanes (Trapped Exposure)</b><br>
"""

if not trapped_per_storm_prob.empty:
    for _, row in trapped_per_storm_prob.iterrows():
        prob_text = (
            f"Prob {row['prob']:.0f}%"
            if row['prob'] > 0
            else "Cone of Uncertainty"
        )
        disaster_panel_html += f"""
        <div style="margin-bottom:4px;">
            <span style="color:#1E90FF; cursor:pointer;" onclick="zoomToHurricane('{row['storm']}')">
                {row['storm']} ({prob_text}): ${row['trapped_exposure_usd']:,.0f}
            </span>
        </div>
        """

else:
    disaster_panel_html += "<i>No active hurricanes detected.</i>"

disaster_panel_html += "<br><b>Earthquakes ≥6 (Trapped Exposure)</b><br>"

if not eq_trapped_summary.empty:
    for _, eq_row in eq_trapped_summary.iterrows():
        disaster_panel_html += f"""
        <div style="margin-bottom:4px;">
            <div style="margin-left:5px; margin-bottom:2px; font-size:13px; color:#ce4823; cursor:pointer;" onclick="zoomToEarthquake('{eq_row['eq_id']}')">
                M{eq_row['mag']:.1f} – {eq_row['place']}: ${eq_row['trapped_exposure_usd']:,.0f}
            </div>
        </div>
        """

else:
    disaster_panel_html += "<i>No earthquakes ≥ M6 detected in the last 7 days.</i>"

disaster_panel_html += "</div></div>"

disaster_panel_html += f"""
<script>
function togglePanel(contentId) {{
    var content = document.getElementById(contentId);
    if (!content) return;
    content.style.display = (content.style.display==='none')?'block':'none';
}}

function getMap() {{
    if(window._leaflet_map) return window._leaflet_map;
    for(var k in window) if(window[k] instanceof L.Map) {{window._leaflet_map=window[k]; return window._leaflet_map;}}
    return null;
}}

var hurricane_bounds = {hurricane_bounds_json};
var eq_bounds = {eq_bounds_json};
var shake_bounds = {shake_bounds_json};

function zoomToHurricane(name) {{
    if(!name) return;
    var map = getMap();
    if(!map) return;
    var bounds = hurricane_bounds[name];
    if(bounds) {{
        map.fitBounds(bounds, {{padding:[50,50]}});
    }}
}}

function zoomToEarthquake(eq_id) {{
    if(!eq_id) return;
    var map = getMap();
    if(!map) return;
    var coords = eq_bounds[eq_id];
    if(coords) map.setView(coords[0],7);
}}

function zoomToShake(shake_id) {{
    if(!shake_id) return;
    var map = getMap();
    if(!map) return;
    var bounds = shake_bounds[shake_id];
    if(bounds) map.fitBounds(bounds, {{padding:[30,30]}});
}}
</script>
"""

m.get_root().html.add_child(folium.Element(disaster_panel_html))

# TOP BANNER (text only) + LARGE LENS TEXT + SHIFTED UI CONTROLS

import json

participants = sorted(tiv_df['participant_name'].dropna().unique().tolist())
participant_json = json.dumps(participants)

banner_html = f"""
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

    <select id="participantSelect" multiple style="margin-left:20px; padding:2px; font-size:12px;" onchange="filterByParticipant()">
    </select>
</div>

<script>
// --- Map reference ---
var map = null;
function getMap() {{
    if(window._leaflet_map) return window._leaflet_map;
    for(var k in window) {{
        if(window[k] instanceof L.Map) {{
            window._leaflet_map = window[k]; 
            return window._leaflet_map;
        }}
    }}
    return null;
}}
map = getMap();

<script>
// ==========================================
// PARTICIPANT DROPDOWN + MAP FILTERING
// ==========================================

// Initialize dropdown from Python dictionary
var participants = Object.keys(window.participantTrapped || {{}});
var select = document.getElementById('participantSelect');

// Populate dropdown options
participants.forEach(function(p) {{
    var opt = document.createElement('option');
    opt.value = p;
    opt.innerText = p;
    select.appendChild(opt);
}});

// Main update function
function updateParticipantView() {{
    var selected = Array.from(select.selectedOptions).map(opt => opt.value);
    var map = window._leaflet_map || Object.values(window).find(v => v instanceof L.Map);

    // -------------------------------
    // Filter polygons + heatmaps
    // -------------------------------
    participants.forEach(function(p) {{
        ['1','2'].forEach(function(id) {{
            var layerKey = p + '_' + id;
            var layer = window.participant_layers[layerKey];
            if(layer) {{
                if(selected.includes(p)) map.addLayer(layer);
                else map.removeLayer(layer);
            }}
        }});

        var heatKey = 'heat_' + p.replace(/\\s+/g,'_');
        var heatLayer = window[heatKey] ? window[heatKey].layer : null;
        if(heatLayer) {{
            if(selected.includes(p)) map.addLayer(heatLayer);
            else map.removeLayer(heatLayer);
        }}
    }});

    // -------------------------------
    // Filter TIV points dynamically
    // -------------------------------
    if(window.tivPointsLayer) map.removeLayer(window.tivPointsLayer);

    var points = window.allTivPoints || [];
    var filteredPoints = selected.length
        ? points.filter(pt => selected.includes(pt.participant))
        : points;

    window.tivPointsLayer = L.layerGroup(filteredPoints.map(function(pt) {{
        return L.circleMarker([pt.lat, pt.lon], {{
            radius: 4,
            color: '#007bff',
            fillColor: '#007bff',
            fillOpacity: 0.7
        }}).bindTooltip(`${{pt.participant}}<br>$${{pt.value.toLocaleString()}}`);
    }})).addTo(map);

    // -------------------------------
    // Live totals from filtered points
    // -------------------------------
    var total = 0, hurricane = 0, eq = 0;

    filteredPoints.forEach(pt => {{
        total += pt.value || 0;
        if(pt.hazard === 'hurricane') hurricane += pt.value || 0;
        if(pt.hazard === 'earthquake') eq += pt.value || 0;
    }});

    // Update summary boxes
    document.getElementById('total-trapped').innerText = total.toLocaleString();
    document.getElementById('hurricane-trapped').innerText = hurricane > 0 ? hurricane.toLocaleString() : '';
    document.getElementById('eq-trapped').innerText = eq > 0 ? eq.toLocaleString() : '';

    // Show/hide sections dynamically
    document.getElementById('total-trapped').parentElement.style.display = total > 0 ? 'block' : 'none';
    document.getElementById('hurricane-trapped').parentElement.style.display = hurricane > 0 ? 'block' : 'none';
    document.getElementById('eq-trapped').parentElement.style.display = eq > 0 ? 'block' : 'none';
}}

// Hook up listener
select.addEventListener('change', updateParticipantView);
updateParticipantView();  // Initialize on load
</script>

<style>
/* Ensure dropdown appears above banner and map */
#participantSelect {{
    position: relative;
    z-index: 1200;
}}
.folium-map {{ position: relative; top: 50px; }}
.leaflet-top.leaflet-left, .leaflet-top.leaflet-right {{ top: 50px; }}
</style>
"""
m.get_root().html.add_child(folium.Element(banner_html))

# SAVE MAP

m.save("full_disaster_map_test.html")
print("✅ Map saved as full_disaster_map_test.html")

