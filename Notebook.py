# Ontario 400 Series Highway Traffic Density Map, Build Notebook
# This is the real, executed notebook behind the [interactive map](https://agam2637.github.io/Ontario-400-Series-Highway-Traffic-Density-Map/), not a cleaned-up rewrite. It includes the dead ends and bug fixes as they actually happened: a naive route filter that missed overlapping highway designations, a coordinate reference dead end (LHRS Routes had no LHRS field), a length-calculation bug from splitting lines, a forgotten highway that needed a mid-project rebuild, and, in the historical time-slider section, a `NaN`-in-JSON bug and a sneaky integer/float key mismatch that silently broke every station lookup. This is a more honest picture of the actual GIS/data engineering work than a tidy linear script would be.
# Stack: ArcGIS Pro, Python (arcpy, pandas, numpy), Leaflet.js
# Data sources: Ontario Road Network (ORN) Composite Service, MTO Traffic Volumes 1988-2021, MTO LHRS Base Points
# Features: stretch-level traffic tiers (not one flat value per highway), a Highway Overview panel with per-highway stats, and a historical time slider showing 1988-2021 traffic volume evolve on a fixed color scale.

# Setup. Pointing arcpy at whatever geodatabase this project's using, and telling it to overwrite outputs without complaining since I'll be re-running cells a lot.
import arcpy

aprx = arcpy.mp.ArcGISProject("CURRENT")
arcpy.env.workspace = aprx.defaultGeodatabase
arcpy.env.overwriteOutput = True

# First pass at pulling my 6 highways. Hitting the Ontario Road Network Composite Service directly (it's a live feature service, no static shapefile download available) and filtering on `ROUTE_NUMBER` for an exact match. This turns out to be too naive, fixed a few cells down.
url = "https://services1.arcgis.com/TJH5KDher0W13Kgo/arcgis/rest/services/Ontario_Road_Network_Composite_Service_GeoHub_View_EN/FeatureServer/5"

where_clause = "ROUTE_NUMBER IN ('400', '401', '403', '404', '410', 'QEW')"

arcpy.conversion.FeatureClassToFeatureClass(
    in_features=url,
    out_path=arcpy.env.workspace,
    out_name="highways_filtered",
    where_clause=where_clause
)

# Quick count check, 2003 segments. Reasonable, but I don't know yet that real segments are missing.
count = arcpy.management.GetCount("highways_filtered")
print(count)

# Listing every field on this layer so I know what I'm working with.
fields = arcpy.ListFields("highways_filtered")
for f in fields:
    print(f.name, f.type)

# Noticed a gap in the map near Mississauga on the 403, so checking every distinct value actually stored in `ROUTE_NUMBER` to see if something weird is going on.
with arcpy.da.SearchCursor("highways_filtered", ["ROUTE_NUMBER"]) as cursor:
    unique_values = set(row[0] for row in cursor)

for v in sorted(unique_values, key=str):
    print(v)

# Casting a wider net, searching by street name instead of route number, to see if there are more "403" segments out there than my route number filter caught.
url = "https://services1.arcgis.com/TJH5KDher0W13Kgo/arcgis/rest/services/Ontario_Road_Network_Composite_Service_GeoHub_View_EN/FeatureServer/5"

where_clause = "FULL_STREET_NAME LIKE '%403%' OR ALT_STREET_NAME LIKE '%403%'"

arcpy.conversion.FeatureClassToFeatureClass(
    in_features=url,
    out_path=arcpy.env.workspace,
    out_name="check_403_gap",
    where_clause=where_clause
)

count = arcpy.management.GetCount("check_403_gap")
print(count)

# Comparing the two counts directly: exact-match `ROUTE_NUMBER = '403'` vs. anything mentioning 403 in the street name. The gap here (144 vs 492) is what confirmed something was wrong with my filter.
with arcpy.da.SearchCursor("highways_filtered", ["ROUTE_NUMBER"], where_clause="ROUTE_NUMBER = '403'") as cursor:
    existing_403 = sum(1 for _ in cursor)

print("Existing 403 segments:", existing_403)
print("Segments found by street name search:", count)

# Printing every segment that matched on street name but doesn't have `ROUTE_NUMBER = '403'`, to see what's actually stored there instead.
with arcpy.da.SearchCursor("check_403_gap", ["ROUTE_NUMBER", "FULL_STREET_NAME", "ROAD_CLASS"]) as cursor:
    for row in cursor:
        if row[0] != '403':
            print(row)

# Tallying instead of a wall of text, how often each weird `ROUTE_NUMBER` value and `ROAD_CLASS` shows up. This revealed the real story: combined values like `'QEW; 403'` and a ton of blank-route `Ramp` segments.
from collections import Counter

route_vals = Counter()
road_classes = Counter()

with arcpy.da.SearchCursor("check_403_gap", ["ROUTE_NUMBER", "FULL_STREET_NAME", "ROAD_CLASS"]) as cursor:
    for row in cursor:
        if row[0] != '403':
            route_vals[row[0]] += 1
            road_classes[row[2]] += 1

print("ROUTE_NUMBER values found instead:")
for val, n in route_vals.most_common():
    print(f"  {val!r}: {n}")

print("\nROAD_CLASS values for these segments:")
for val, n in road_classes.most_common():
    print(f"  {val!r}: {n}")

# The actual fix. Using `LIKE` to catch combined route values, restricted to `ROAD_CLASS = 'Freeway'` so I don't pull in unrelated roads that just happen to contain the same digits.
url = "https://services1.arcgis.com/TJH5KDher0W13Kgo/arcgis/rest/services/Ontario_Road_Network_Composite_Service_GeoHub_View_EN/FeatureServer/5"

target_routes = {"400", "401", "403", "404", "410", "QEW"}

like_clause = " OR ".join([f"ROUTE_NUMBER LIKE '%{r}%'" for r in target_routes])
where_clause = f"({like_clause}) AND ROAD_CLASS = 'Freeway'"

arcpy.conversion.FeatureClassToFeatureClass(
    in_features=url,
    out_path=arcpy.env.workspace,
    out_name="highways_mainline",
    where_clause=where_clause
)

print(arcpy.management.GetCount("highways_mainline"))

# Ramps mostly don't carry a route number at all, so matching them separately by street name instead, keeping only `ROAD_CLASS = 'Ramp'`.
street_names = ["HIGHWAY 400", "HIGHWAY 401", "HIGHWAY 403", "HIGHWAY 404", "HIGHWAY 410", "QUEEN ELIZABETH WAY"]

street_clause = " OR ".join([f"FULL_STREET_NAME LIKE '%{s}%'" for s in street_names])
where_clause = f"({street_clause}) AND ROAD_CLASS = 'Ramp'"

arcpy.conversion.FeatureClassToFeatureClass(
    in_features=url,
    out_path=arcpy.env.workspace,
    out_name="highways_ramps",
    where_clause=where_clause
)

print(arcpy.management.GetCount("highways_ramps"))

# Tagging both layers with a `segment_type` field (Mainline vs Ramp) and merging into one layer, my fixed "v2" highway layer.
arcpy.management.AddField("highways_mainline", "segment_type", "TEXT", field_length=20)
arcpy.management.CalculateField("highways_mainline", "segment_type", "'Mainline'")

arcpy.management.AddField("highways_ramps", "segment_type", "TEXT", field_length=20)
arcpy.management.CalculateField("highways_ramps", "segment_type", "'Ramp'")

arcpy.management.Merge(
    inputs=["highways_mainline", "highways_ramps"],
    output="highways_filtered_v2"
)

print(arcpy.management.GetCount("highways_filtered_v2"))

# Sanity check on the merge, nothing unrelated snuck in through the wider `LIKE` filter.
from collections import Counter

with arcpy.da.SearchCursor("highways_filtered_v2", ["ROUTE_NUMBER", "segment_type"]) as cursor:
    tally = Counter((row[0], row[1]) for row in cursor)

for (route, seg_type), n in sorted(tally.items(), key=lambda x: -x[1])[:20]:
    print(route, seg_type, n)

# Starting on the traffic volume side. First look at the MTO AADT CSV, columns, shape, structure.
import pandas as pd

csv_path = r"data raw\Traffic_Volumes_1988-2021.csv"
aadt_df = pd.read_csv(csv_path)

print(aadt_df.shape)
print(aadt_df.columns.tolist())
aadt_df.head()

# Trying to figure out MTO's internal `Hwy No` codes by searching location text for my target highway names. This approach is flawed (it also catches highways just *mentioned* nearby), kept for the record, real fix is next cell.
# Look for rows whose location description mentions our target highways by name,
# and see what Hwy No value those rows actually have
keywords = ["QEW", "401", "400", "403", "404", "410"]

for kw in keywords:
    matches = aadt_df[aadt_df["Location Description"].str.contains(kw, na=False)]
    print(f"--- '{kw}' ---")
    print(matches[["Hwy No", "Hwy No Suffix", "Hwy. Type", "Location Description"]].drop_duplicates().head(10))
    print()

# The real check. Filtering directly by candidate `Hwy No` and reading the location descriptions to see if they trace a believable route. This is how I found the QEW is secretly `Hwy No = 1`.
# Check each candidate Hwy No directly and see if the locations trace a believable route
for hwy in [1, 400, 401, 403, 404, 410]:
    subset = aadt_df[aadt_df["Hwy No"] == hwy]
    print(f"--- Hwy No = {hwy} ({len(subset)} rows) ---")
    print(subset["Location Description"].drop_duplicates().head(8).tolist())
    print()

# Filtering AADT data down to my 6 highways using the confirmed real codes.
target_hwy_codes = [1, 400, 401, 403, 404, 410]  # 1 = QEW

aadt_filtered = aadt_df[aadt_df["Hwy No"].isin(target_hwy_codes)].copy()

print(aadt_filtered.shape)
print(aadt_filtered["Hwy No"].value_counts())

# Checking available years, found no 2020 (COVID gap, probably) and a bogus `9999` placeholder.
print(sorted(aadt_filtered["Year"].unique()))

# Picking 2021 as the most recent real year.
aadt_2021 = aadt_filtered[aadt_filtered["Year"] == 2021].copy()
print(aadt_2021.shape)
aadt_2021[["Hwy No", "Location Description", "AADT", "LHRS", "Offset"]].head(10)

# Checking the AADT column's dtype before doing math on it, turned out to be comma-formatted text, not a clean number.
print(aadt_2021["AADT"].dtype)
print(aadt_2021["AADT"].head(10))

# First attempt at cleaning AADT into a float.
aadt_2021["AADT_clean"] = aadt_2021["AADT"].astype(str).str.replace(",", "").astype(float)

# Redid the cleaning with `9999` explicitly excluded too, plus `.describe()` to sanity check the distribution.
aadt_2021 = aadt_2021[aadt_2021["Year"] != 9999].copy()  # just in case, belt-and-suspenders

aadt_2021["AADT_clean"] = aadt_2021["AADT"].astype(str).str.replace(",", "").astype(float)

print(aadt_2021["AADT_clean"].describe())

# Dead end, but useful. Downloaded MTO's LHRS Routes shapefile hoping to place AADT stations precisely, turned out to have zero LHRS fields, just one line per highway. Not what I needed.
lhrs_routes_path = r"data raw\lhrs_routes_july2015\LHRS_Routes_July2015.shp"

arcpy.management.CopyFeatures(lhrs_routes_path, "lhrs_routes")

fields = arcpy.ListFields("lhrs_routes")
for f in fields:
    print(f.name, f.type)

# Checking what highway codes this Routes file uses, before giving up on it.
with arcpy.da.SearchCursor("lhrs_routes", ["HWY_2015"]) as cursor:
    unique_hwy = sorted(set(row[0] for row in cursor), key=str)

print(unique_hwy[:30])
print(len(unique_hwy))

# Confirmed my 6 highways are present here, but this file still doesn't have what I actually need.
target = ['1', '400', '401', '403', '404', '410']
found = [h for h in unique_hwy if h in target]
print(found)

# The file that actually works. MTO's LHRS Base Points shapefile, has `LHRS`, `OFFSET`, and direct `LATITUDE`/`LONGITUDE`.
base_points_path = r"data raw\LHRS_Base_Points_July2015.shp"

arcpy.management.CopyFeatures(base_points_path, "lhrs_base_points")

fields = arcpy.ListFields("lhrs_base_points")
for f in fields:
    print(f.name, f.type)

# Checking how many of my 327 AADT stations match a `(LHRS, Offset)` pair in Base Points. First run, redone after a notebook reset a few cells down.
with arcpy.da.SearchCursor("lhrs_base_points", ["LHRS", "OFFSET", "HWY"]) as cursor:
    base_keys = set((row[0], row[1]) for row in cursor)

# Build the same key from your AADT 2021 data
aadt_keys = set(zip(aadt_2021["LHRS"], aadt_2021["Offset"]))

matched = aadt_keys & base_keys
print(f"AADT stations: {len(aadt_keys)}")
print(f"Base points: {len(base_keys)}")
print(f"Matched: {len(matched)}")

# Notebook kernel reset (closed ArcGIS Pro, went idle, who knows) and wiped my variables, reloading from scratch to get back to where I was.
import pandas as pd

csv_path = r"data raw\Traffic_Volumes_1988-2021.csv"
aadt_df = pd.read_csv(csv_path)

target_hwy_codes = [1, 400, 401, 403, 404, 410]  # 1 = QEW
aadt_filtered = aadt_df[aadt_df["Hwy No"].isin(target_hwy_codes)].copy()

aadt_2021 = aadt_filtered[aadt_filtered["Year"] == 2021].copy()
aadt_2021["AADT_clean"] = aadt_2021["AADT"].astype(str).str.replace(",", "").astype(float)

print(aadt_2021.shape)

# This reload broke with `FileNotFoundError`, checking what directory Python actually thinks it's in.
import os
print(os.getcwd())

# Fixing the path for real. Building an absolute path off `aprx.homeFolder` instead of a fragile relative one.
import arcpy
import os

aprx = arcpy.mp.ArcGISProject("CURRENT")
project_folder = aprx.homeFolder
print(project_folder)

csv_path = os.path.join(project_folder, "data raw", "Traffic_Volumes_1988-2021.csv")
print(csv_path)
print(os.path.exists(csv_path))  # should print True

# Reloading the AADT CSV with the new reliable path.
import pandas as pd

aadt_df = pd.read_csv(csv_path)

target_hwy_codes = [1, 400, 401, 403, 404, 410]  # 1 = QEW
aadt_filtered = aadt_df[aadt_df["Hwy No"].isin(target_hwy_codes)].copy()

aadt_2021 = aadt_filtered[aadt_filtered["Year"] == 2021].copy()
aadt_2021["AADT_clean"] = aadt_2021["AADT"].astype(str).str.replace(",", "").astype(float)

print(aadt_2021.shape)

# Re-running the join match check, 326 out of 327 matched.
with arcpy.da.SearchCursor("lhrs_base_points", ["LHRS", "OFFSET", "HWY"]) as cursor:
    base_keys = set((row[0], row[1]) for row in cursor)

aadt_keys = set(zip(aadt_2021["LHRS"], aadt_2021["Offset"]))

matched = aadt_keys & base_keys
print(f"AADT stations: {len(aadt_keys)}")
print(f"Base points: {len(base_keys)}")
print(f"Matched: {len(matched)}")

# Curious about the one unmatched station, a single 401 station near Wonderland Rd, probably added after this 2015 Base Points snapshot.
unmatched = aadt_keys - base_keys
print(unmatched)

# Look up that station's details in your AADT data
lhrs_val, offset_val = list(unmatched)[0]
row = aadt_2021[(aadt_2021["LHRS"] == lhrs_val) & (aadt_2021["Offset"] == offset_val)]
print(row[["Hwy No", "Location Description", "AADT_clean", "LHRS", "Offset"]])

# Same as above, re-ran it.
unmatched = aadt_keys - base_keys
print(unmatched)

# Look up that station's details in your AADT data
lhrs_val, offset_val = list(unmatched)[0]
row = aadt_2021[(aadt_2021["LHRS"] == lhrs_val) & (aadt_2021["Offset"] == offset_val)]
print(row[["Hwy No", "Location Description", "AADT_clean", "LHRS", "Offset"]])

# Building a `(LHRS, Offset) -> AADT` lookup and writing it onto the Base Points layer as a new field.
# Build a lookup dict: (LHRS, Offset) -> AADT_clean
aadt_lookup = {
    (row["LHRS"], row["Offset"]): row["AADT_clean"]
    for _, row in aadt_2021.iterrows()
}

# Add a new field to lhrs_base_points and populate it
arcpy.management.AddField("lhrs_base_points", "AADT_2021", "DOUBLE")

with arcpy.da.UpdateCursor("lhrs_base_points", ["LHRS", "OFFSET", "AADT_2021"]) as cursor:
    for row in cursor:
        key = (row[0], row[1])
        if key in aadt_lookup:
            row[2] = aadt_lookup[key]
            cursor.updateRow(row)

# Filtering Base Points to my 6 highways, keeping only ones with an actual AADT value, this becomes `aadt_stations_2021`.
where_clause = "HWY IN ('1','400','401','403','404','410') AND AADT_2021 IS NOT NULL"

arcpy.management.SelectLayerByAttribute("lhrs_base_points", "NEW_SELECTION", where_clause)
arcpy.management.CopyFeatures("lhrs_base_points", "aadt_stations_2021")

count = arcpy.management.GetCount("aadt_stations_2021")
print(count)

# Spot-checking coordinates and AADT values before building anything else on top.
with arcpy.da.SearchCursor("aadt_stations_2021", ["HWY", "LATITUDE", "LONGITUDE", "AADT_2021"]) as cursor:
    for i, row in enumerate(cursor):
        if i < 5:
            print(row)

# Pulling out just the Mainline segments, these are what actually get split into stretches.
where_clause = "segment_type = 'Mainline'"
arcpy.management.SelectLayerByAttribute("highways_filtered_v2", "NEW_SELECTION", where_clause)
arcpy.management.CopyFeatures("highways_filtered_v2", "highways_mainline_only")

# Splitting the highway at each station point so different parts of the same highway can get different colors, instead of one flat value for the whole route.
arcpy.management.SplitLineAtPoint(
    in_features="highways_mainline_only",
    point_features="aadt_stations_2021",
    out_feature_class="highways_split",
    search_radius="100 Meters"
)

count = arcpy.management.GetCount("highways_split")
print(count)

# First attempt joining each stretch to its nearest station, 500m radius. Left 878 unmatched, rural stretches can be way more than 500m from the nearest station.
arcpy.analysis.SpatialJoin(
    target_features="highways_split",
    join_features="aadt_stations_2021",
    out_feature_class="highways_with_aadt",
    join_operation="JOIN_ONE_TO_ONE",
    match_option="CLOSEST",
    search_radius="500 Meters"
)

count = arcpy.management.GetCount("highways_with_aadt")
print(count)

# Quick check: how many got a real AADT value vs came back empty
with arcpy.da.SearchCursor("highways_with_aadt", ["AADT_2021"]) as cursor:
    null_count = sum(1 for row in cursor if row[0] is None)
print(f"Segments with no matched AADT: {null_count}")

# Fixed by widening to 50km. Every stretch matched.
arcpy.analysis.SpatialJoin(
    target_features="highways_split",
    join_features="aadt_stations_2021",
    out_feature_class="highways_with_aadt_v2",
    join_operation="JOIN_ONE_TO_ONE",
    match_option="CLOSEST",
    search_radius="50000 Meters"  # 50 km - should comfortably catch even the sparsest rural gaps
)

count = arcpy.management.GetCount("highways_with_aadt_v2")
print(count)

with arcpy.da.SearchCursor("highways_with_aadt_v2", ["AADT_2021"]) as cursor:
    null_count = sum(1 for row in cursor if row[0] is None)
print(f"Segments with no matched AADT: {null_count}")

# Sanity-checking the AADT distribution on the split data, matched the original station-level stats.
# Add highways_with_aadt_v2 to your map and visually confirm color/value makes sense once symbolized later.
# For now, just check the AADT distribution looks reasonable across the new stretch-level data:

with arcpy.da.SearchCursor("highways_with_aadt_v2", ["AADT_2021"]) as cursor:
    values = [row[0] for row in cursor]

import numpy as np
values = np.array(values)
print(f"Count: {len(values)}")
print(f"Min: {values.min()}, Max: {values.max()}")
print(f"25th pct: {np.percentile(values, 25):.0f}")
print(f"Median: {np.percentile(values, 50):.0f}")
print(f"75th pct: {np.percentile(values, 75):.0f}")

# Calculating tercile break points for Low/Medium/High.
import numpy as np

low_threshold = np.percentile(values, 33.33)
high_threshold = np.percentile(values, 66.67)

print(f"Low/Medium boundary: {low_threshold:.0f}")
print(f"Medium/High boundary: {high_threshold:.0f}")

# Writing the `traffic_tier` label onto every stretch.
arcpy.management.AddField("highways_with_aadt_v2", "traffic_tier", "TEXT", field_length=20)

with arcpy.da.UpdateCursor("highways_with_aadt_v2", ["AADT_2021", "traffic_tier"]) as cursor:
    for row in cursor:
        aadt = row[0]
        if aadt is None:
            row[1] = "No Data"
        elif aadt <= low_threshold:
            row[1] = "Low"
        elif aadt <= high_threshold:
            row[1] = "Medium"
        else:
            row[1] = "High"
        cursor.updateRow(row)

# Tallying tier counts, came out almost perfectly even.
from collections import Counter

with arcpy.da.SearchCursor("highways_with_aadt_v2", ["traffic_tier"]) as cursor:
    tally = Counter(row[0] for row in cursor)

for tier, n in tally.items():
    print(tier, n)

# Pulling Ramp segments back in with a fixed `'Ramp'` tier, merging into `highways_classified`.
where_clause = "segment_type = 'Ramp'"
arcpy.management.SelectLayerByAttribute("highways_filtered_v2", "NEW_SELECTION", where_clause)
arcpy.management.CopyFeatures("highways_filtered_v2", "highways_ramps_only")

arcpy.management.AddField("highways_ramps_only", "traffic_tier", "TEXT", field_length=20)
arcpy.management.CalculateField("highways_ramps_only", "traffic_tier", "'Ramp'")

arcpy.management.Merge(
    inputs=["highways_with_aadt_v2", "highways_ramps_only"],
    output="highways_classified"
)

count = arcpy.management.GetCount("highways_classified")
print(count)

# Symbology in ArcGIS Pro wasn't showing `traffic_tier`, so double-checking the field actually exists.
fields = arcpy.ListFields("highways_classified")
for f in fields:
    print(f.name, f.type)

# First attempt at clearing a stray selection (leftover cyan highlight from all my `SelectLayerByAttribute` calls). Crashed, `SELECTIONSET` isn't a valid property in this arcpy version.
aprx = arcpy.mp.ArcGISProject("CURRENT")
m = aprx.activeMap

for lyr in m.listLayers():
    if lyr.supports("SELECTIONSET"):
        arcpy.management.SelectLayerByAttribute(lyr, "CLEAR_SELECTION")

# Fixed, just try clearing selection on every layer and skip whichever ones don't support it.
aprx = arcpy.mp.ArcGISProject("CURRENT")
m = aprx.activeMap

for lyr in m.listLayers():
    if lyr.isFeatureLayer:
        try:
            arcpy.management.SelectLayerByAttribute(lyr, "CLEAR_SELECTION")
        except Exception as e:
            print(f"Skipped {lyr.name}: {e}")

# Realized I'd forgotten Highway 427 entirely. Checking how it's coded, turned out simple, just `427` directly.
matches = aadt_df[aadt_df["Location Description"].str.contains("427", na=False)]
print(matches[["Hwy No", "Location Description"]].drop_duplicates().head(10))

# Also check directly
subset = aadt_df[aadt_df["Hwy No"] == 427]
print(subset["Location Description"].drop_duplicates().head(8).tolist())

# Rebuilding the highway pull with 427 added.
url = "https://services1.arcgis.com/TJH5KDher0W13Kgo/arcgis/rest/services/Ontario_Road_Network_Composite_Service_GeoHub_View_EN/FeatureServer/5"

target_routes = {"400", "401", "403", "404", "410", "427", "QEW"}

like_clause = " OR ".join([f"ROUTE_NUMBER LIKE '%{r}%'" for r in target_routes])
where_clause = f"({like_clause}) AND ROAD_CLASS = 'Freeway'"
arcpy.conversion.FeatureClassToFeatureClass(url, arcpy.env.workspace, "highways_mainline", where_clause)

street_names = ["HIGHWAY 400", "HIGHWAY 401", "HIGHWAY 403", "HIGHWAY 404", "HIGHWAY 410", "HIGHWAY 427", "QUEEN ELIZABETH WAY"]
street_clause = " OR ".join([f"FULL_STREET_NAME LIKE '%{s}%'" for s in street_names])
where_clause = f"({street_clause}) AND ROAD_CLASS = 'Ramp'"
arcpy.conversion.FeatureClassToFeatureClass(url, arcpy.env.workspace, "highways_ramps", where_clause)

arcpy.management.AddField("highways_mainline", "segment_type", "TEXT", field_length=20)
arcpy.management.CalculateField("highways_mainline", "segment_type", "'Mainline'")
arcpy.management.AddField("highways_ramps", "segment_type", "TEXT", field_length=20)
arcpy.management.CalculateField("highways_ramps", "segment_type", "'Ramp'")

arcpy.management.Merge(["highways_mainline", "highways_ramps"], "highways_filtered_v2")
print(arcpy.management.GetCount("highways_filtered_v2"))

# Rebuilding the AADT filtering with 427's code included.
target_hwy_codes = [1, 400, 401, 403, 404, 410, 427]  # 1 = QEW
aadt_filtered = aadt_df[aadt_df["Hwy No"].isin(target_hwy_codes)].copy()
aadt_2021 = aadt_filtered[aadt_filtered["Year"] == 2021].copy()
aadt_2021["AADT_clean"] = aadt_2021["AADT"].astype(str).str.replace(",", "").astype(float)
print(aadt_2021.shape)

# Re-running the cell above, same rebuild, ran it twice.
url = "https://services1.arcgis.com/TJH5KDher0W13Kgo/arcgis/rest/services/Ontario_Road_Network_Composite_Service_GeoHub_View_EN/FeatureServer/5"

target_routes = {"400", "401", "403", "404", "410", "427", "QEW"}

like_clause = " OR ".join([f"ROUTE_NUMBER LIKE '%{r}%'" for r in target_routes])
where_clause = f"({like_clause}) AND ROAD_CLASS = 'Freeway'"
arcpy.conversion.FeatureClassToFeatureClass(url, arcpy.env.workspace, "highways_mainline", where_clause)

street_names = ["HIGHWAY 400", "HIGHWAY 401", "HIGHWAY 403", "HIGHWAY 404", "HIGHWAY 410", "HIGHWAY 427", "QUEEN ELIZABETH WAY"]
street_clause = " OR ".join([f"FULL_STREET_NAME LIKE '%{s}%'" for s in street_names])
where_clause = f"({street_clause}) AND ROAD_CLASS = 'Ramp'"
arcpy.conversion.FeatureClassToFeatureClass(url, arcpy.env.workspace, "highways_ramps", where_clause)

arcpy.management.AddField("highways_mainline", "segment_type", "TEXT", field_length=20)
arcpy.management.CalculateField("highways_mainline", "segment_type", "'Mainline'")
arcpy.management.AddField("highways_ramps", "segment_type", "TEXT", field_length=20)
arcpy.management.CalculateField("highways_ramps", "segment_type", "'Ramp'")

arcpy.management.Merge(["highways_mainline", "highways_ramps"], "highways_filtered_v2")
print(arcpy.management.GetCount("highways_filtered_v2"))

# Same rebuild again.
target_hwy_codes = [1, 400, 401, 403, 404, 410, 427]  # 1 = QEW
aadt_filtered = aadt_df[aadt_df["Hwy No"].isin(target_hwy_codes)].copy()
aadt_2021 = aadt_filtered[aadt_filtered["Year"] == 2021].copy()
aadt_2021["AADT_clean"] = aadt_2021["AADT"].astype(str).str.replace(",", "").astype(float)
print(aadt_2021.shape)

aadt_lookup = {(row["LHRS"], row["Offset"]): row["AADT_clean"] for _, row in aadt_2021.iterrows()}

# Re-add the field fresh (in case it still has old values from before)
arcpy.management.AddField("lhrs_base_points", "AADT_2021_v2", "DOUBLE")
with arcpy.da.UpdateCursor("lhrs_base_points", ["LHRS", "OFFSET", "AADT_2021_v2"]) as cursor:
    for row in cursor:
        key = (row[0], row[1])
        if key in aadt_lookup:
            row[2] = aadt_lookup[key]
            cursor.updateRow(row)

where_clause = "HWY IN ('1','400','401','403','404','410','427') AND AADT_2021_v2 IS NOT NULL"
arcpy.management.SelectLayerByAttribute("lhrs_base_points", "NEW_SELECTION", where_clause)
arcpy.management.CopyFeatures("lhrs_base_points", "aadt_stations_2021_v2")
print(arcpy.management.GetCount("aadt_stations_2021_v2"))

# Rebuilding the split-at-stations step with the 427-inclusive data.
arcpy.management.SelectLayerByAttribute("highways_filtered_v2", "NEW_SELECTION", "segment_type = 'Mainline'")
arcpy.management.CopyFeatures("highways_filtered_v2", "highways_mainline_only")

arcpy.management.SplitLineAtPoint(
    in_features="highways_mainline_only",
    point_features="aadt_stations_2021_v2",
    out_feature_class="highways_split",
    search_radius="100 Meters"
)
print(arcpy.management.GetCount("highways_split"))

arcpy.analysis.SpatialJoin(
    target_features="highways_split",
    join_features="aadt_stations_2021_v2",
    out_feature_class="highways_with_aadt_v2",
    join_operation="JOIN_ONE_TO_ONE",
    match_option="CLOSEST",
    search_radius="50000 Meters"
)
print(arcpy.management.GetCount("highways_with_aadt_v2"))

with arcpy.da.SearchCursor("highways_with_aadt_v2", ["AADT_2021_v2"]) as cursor:
    null_count = sum(1 for row in cursor if row[0] is None)
print(f"Segments with no matched AADT: {null_count}")

# Recomputing tercile breakpoints now that 427's traffic is in the pool (shifted slightly, as expected), and reclassifying.
with arcpy.da.SearchCursor("highways_with_aadt_v2", ["AADT_2021_v2"]) as cursor:
    values = [row[0] for row in cursor]

import numpy as np
values = np.array(values)

low_threshold = np.percentile(values, 33.33)
high_threshold = np.percentile(values, 66.67)
print(f"Low/Medium boundary: {low_threshold:.0f}")
print(f"Medium/High boundary: {high_threshold:.0f}")

arcpy.management.AddField("highways_with_aadt_v2", "traffic_tier", "TEXT", field_length=20)
with arcpy.da.UpdateCursor("highways_with_aadt_v2", ["AADT_2021_v2", "traffic_tier"]) as cursor:
    for row in cursor:
        aadt = row[0]
        if aadt is None:
            row[1] = "No Data"
        elif aadt <= low_threshold:
            row[1] = "Low"
        elif aadt <= high_threshold:
            row[1] = "Medium"
        else:
            row[1] = "High"
        cursor.updateRow(row)

# Merging the 427-inclusive ramps back in to build the final `highways_classified_v2`.
arcpy.management.SelectLayerByAttribute("highways_filtered_v2", "NEW_SELECTION", "segment_type = 'Ramp'")
arcpy.management.CopyFeatures("highways_filtered_v2", "highways_ramps_only")
arcpy.management.AddField("highways_ramps_only", "traffic_tier", "TEXT", field_length=20)
arcpy.management.CalculateField("highways_ramps_only", "traffic_tier", "'Ramp'")

arcpy.management.Merge(["highways_with_aadt_v2", "highways_ramps_only"], "highways_classified_v2")
print(arcpy.management.GetCount("highways_classified_v2"))

# Clearing selection again before symbolizing.
aprx = arcpy.mp.ArcGISProject("CURRENT")
m = aprx.activeMap
for lyr in m.listLayers():
    if lyr.isFeatureLayer:
        try:
            arcpy.management.SelectLayerByAttribute(lyr, "CLEAR_SELECTION")
        except Exception as e:
            pass

# Listing every layer in the map's Contents pane, about 14 scratch layers had piled up by this point.
import arcpy

aprx = arcpy.mp.ArcGISProject("CURRENT")
m = aprx.activeMap

# Layer names to keep visible - everything else gets removed from the map
keep_layers = ["highways_classified_v2"]

# List what's currently in the map first, so you can see what will be removed
for lyr in m.listLayers():
    print(lyr.name)

# Cleaning up, removing everything except the final classified layer and basemaps. Only touches the map view, not the geodatabase.
keep_layers = ["highways_classified_v2", "World Topographic Map", "World Hillshade"]

for lyr in m.listLayers():
    if lyr.name not in keep_layers:
        m.removeLayer(lyr)

# Confirm what's left
for lyr in m.listLayers():
    print(lyr.name)
    

# Checking the coordinate system before exporting to a web map.
desc = arcpy.Describe("highways_classified_v2")
print(desc.spatialReference.name)

# Reprojecting to WGS84 so the data lines up correctly in Leaflet.
arcpy.management.Project(
    in_dataset="highways_classified_v2",
    out_dataset="highways_classified_wgs84",
    out_coor_system=arcpy.SpatialReference(4326)  # WGS84
)

# Exporting to GeoJSON, the file the web map actually reads. (First export landed in `data raw` by mistake, moved to `data processed` for the real workflow.)
arcpy.conversion.FeaturesToJSON(
    in_features="highways_classified_wgs84",
    out_json_file=r"data raw\highways_classified.geojson",
    geoJSON="GEOJSON"
)

# First attempt merging the GeoJSON into the HTML template as embedded data, so the map works via double-click with no local server.
import json

# Read your GeoJSON
with open(r"data processed\highways_classified.geojson", "r", encoding="utf-8") as f:
    geojson_data = json.load(f)

# Read the HTML template
with open(r"data processed\highways_classified.html", "r", encoding="utf-8") as f:
    html_content = f.read()

# Build the embedded data script tag
embed_script = f"<script>window.EMBEDDED_HIGHWAY_DATA = {json.dumps(geojson_data)};</script>\n"

# Insert it right before the closing </body> tag
merged_html = html_content.replace("</body>", embed_script + "</body>")

# Save as a new standalone file
with open(r"data processed\highways_classified_standalone.html", "w", encoding="utf-8") as f:
    f.write(merged_html)

print("Done - standalone file created")

# Re-running the same merge attempt.
import json

with open(r"data processed\highways_classified.geojson", "r", encoding="utf-8") as f:
    geojson_data = json.load(f)

with open(r"data processed\highways_classified.html", "r", encoding="utf-8") as f:
    html_content = f.read()

embed_script = f"<script>window.EMBEDDED_HIGHWAY_DATA = {json.dumps(geojson_data)};</script>\n"
merged_html = html_content.replace("</body>", embed_script + "</body>")

with open(r"data processed\highways_classified_standalone.html", "w", encoding="utf-8") as f:
    f.write(merged_html)

print("Done - standalone file created")

# Switching to the reliable absolute-path pattern since a plain relative path couldn't find the HTML template.
import json
import arcpy
import os

aprx = arcpy.mp.ArcGISProject("CURRENT")
project_folder = aprx.homeFolder

geojson_path = os.path.join(project_folder, "data processed", "highways_classified.geojson")
html_path = os.path.join(project_folder, "data processed", "highways_classified.html")
output_path = os.path.join(project_folder, "data processed", "highways_classified_standalone.html")

print(os.path.exists(geojson_path))
print(os.path.exists(html_path))

# Re-running the path setup, this is where I found the HTML template genuinely hadn't been moved into the right folder yet.
import json
import arcpy
import os

aprx = arcpy.mp.ArcGISProject("CURRENT")
project_folder = aprx.homeFolder

geojson_path = os.path.join(project_folder, "data processed", "highways_classified.geojson")
html_path = os.path.join(project_folder, "data processed", "highways_classified.html")
output_path = os.path.join(project_folder, "data processed", "highways_classified_standalone.html")

print(os.path.exists(geojson_path))
print(os.path.exists(html_path))

# The actual embedding bug. Inserting embedded data right before `</body>`, but the map's own logic script runs earlier and checks for that data before it exists, the check always failed and fell through to a broken fetch.
with open(geojson_path, "r", encoding="utf-8") as f:
    geojson_data = json.load(f)

with open(html_path, "r", encoding="utf-8") as f:
    html_content = f.read()

embed_script = f"<script>window.EMBEDDED_HIGHWAY_DATA = {json.dumps(geojson_data)};</script>\n"
merged_html = html_content.replace("</body>", embed_script + "</body>")

with open(output_path, "w", encoding="utf-8") as f:
    f.write(merged_html)

print("Done - standalone file created at:", output_path)

# Real fix, inserting the embedded data before the Leaflet script tag instead, so it's defined before anything tries to read it.
with open(geojson_path, "r", encoding="utf-8") as f:
    geojson_data = json.load(f)

with open(html_path, "r", encoding="utf-8") as f:
    html_content = f.read()

embed_script = f"<script>window.EMBEDDED_HIGHWAY_DATA = {json.dumps(geojson_data)};</script>\n"

# Insert BEFORE the Leaflet script tag, not before </body> - order matters!
insertion_point = '<script src="https://cdnjs.cloudflare.com/ajax/libs/leaflet/1.9.4/leaflet.min.js"></script>'
merged_html = html_content.replace(insertion_point, embed_script + insertion_point)

with open(output_path, "w", encoding="utf-8") as f:
    f.write(merged_html)

print("Done - standalone file created at:", output_path)

# Checking every field on `highways_classified_v2` before building the Highway Overview feature, confirming `L_STANDARD_MUNICIPALITY`/`R_STANDARD_MUNICIPALITY` survived the whole pipeline.
fields = arcpy.ListFields("highways_classified_v2")
for f in fields:
    print(f.name, f.type)

# Building the per-highway stats for the overview panel, cities, average AADT, busiest/quietest points, interchange counts, and (buggy at this point) total length using the stale `LENGTH` field.
import json

target_highways = ["400", "401", "403", "404", "410", "427", "QEW"]
highway_stats = {}

with arcpy.da.SearchCursor("highways_classified_v2",
    ["ROUTE_NUMBER", "segment_type", "L_STANDARD_MUNICIPALITY", "R_STANDARD_MUNICIPALITY",
     "LENGTH", "AADT_2021_v2", "DESCRIPTIO", "FULL_STREET_NAME"]) as cursor:
    rows = list(cursor)

for hwy in target_highways:
    cities = set()
    total_length = 0.0
    aadt_values = []
    busiest = {"aadt": -1, "desc": None}
    quietest = {"aadt": float("inf"), "desc": None}
    ramp_count = 0

    for r in rows:
        route_num, seg_type, l_muni, r_muni, length, aadt, desc, street = r

        # Mainline stats: match if this highway appears in the (possibly combined) ROUTE_NUMBER
        if seg_type == "Mainline" and route_num and hwy in [x.strip() for x in route_num.split(";")]:
            if l_muni: cities.add(l_muni)
            if r_muni: cities.add(r_muni)
            if length: total_length += length
            if aadt is not None:
                aadt_values.append(aadt)
                if aadt > busiest["aadt"]:
                    busiest = {"aadt": aadt, "desc": desc}
                if aadt < quietest["aadt"]:
                    quietest = {"aadt": aadt, "desc": desc}

        # Ramp count: match if this highway's name appears in the ramp's street name
        if seg_type == "Ramp" and street:
            street_upper = street.upper()
            hwy_label = "QUEEN ELIZABETH WAY" if hwy == "QEW" else f"HIGHWAY {hwy}"
            if hwy_label in street_upper:
                ramp_count += 1

    highway_stats[hwy] = {
        "cities": sorted(cities),
        "total_length_km": round(total_length, 1),
        "avg_aadt": round(sum(aadt_values) / len(aadt_values)) if aadt_values else None,
        "busiest": busiest,
        "quietest": quietest,
        "interchange_count": ramp_count
    }

for hwy, stats in highway_stats.items():
    print(hwy, "->", stats)

# First attempt fixing the length bug with `CalculateGeometryAttributes`, used the wrong parameter name (`GEODESIC_LENGTH` instead of `LENGTH_GEODESIC`) and it errored immediately.
arcpy.management.CalculateGeometryAttributes(
    in_features="highways_classified_v2",
    geometry_property=[["seg_length_km", "GEODESIC_LENGTH"]],
    length_unit="KILOMETERS"
)

# Corrected parameter name. Recalculates each stretch's real current length from its geometry, instead of the stale pre-split `LENGTH` attribute.
arcpy.management.CalculateGeometryAttributes(
    in_features="highways_classified_v2",
    geometry_property=[["seg_length_km", "LENGTH_GEODESIC"]],
    length_unit="KILOMETERS"
)

# Re-running the length aggregation with the corrected field. Still roughly double real-world figures at this point.
with arcpy.da.SearchCursor("highways_classified_v2",
    ["ROUTE_NUMBER", "segment_type", "seg_length_km"]) as cursor:
    rows = list(cursor)

for hwy in target_highways:
    total_length = 0.0
    for route_num, seg_type, seg_len in rows:
        if seg_type == "Mainline" and route_num and hwy in [x.strip() for x in route_num.split(";")]:
            if seg_len:
                total_length += seg_len
    highway_stats[hwy]["total_length_km"] = round(total_length, 1)

for hwy in target_highways:
    print(hwy, highway_stats[hwy]["total_length_km"])

# Checking `DIRECTION_OF_TRAFFIC_FLOW`, confirmed divided highways are digitized as two separate carriageway lines, explaining the ~2x length inflation.
with arcpy.da.SearchCursor("highways_classified_v2", ["DIRECTION_OF_TRAFFIC_FLOW"]) as cursor:
    from collections import Counter
    tally = Counter(row[0] for row in cursor)

for val, n in tally.items():
    print(repr(val), n)

# Halving the total length to correct for the double-digitized carriageways, landed close to real-world lengths after this.
for hwy in target_highways:
    highway_stats[hwy]["total_length_km"] = round(highway_stats[hwy]["total_length_km"] / 2, 1)

for hwy in target_highways:
    print(hwy, highway_stats[hwy]["total_length_km"])

# Final embed attempt for the single-year version, geojson + highway_stats baked into one standalone file.
import json
import arcpy
import os

aprx = arcpy.mp.ArcGISProject("CURRENT")
project_folder = aprx.homeFolder

geojson_path = os.path.join(project_folder, "data processed", "highways_classified.geojson")
html_path = os.path.join(project_folder, "data processed", "highways_classified.html")  # the NEW download from above
output_path = os.path.join(project_folder, "data processed", "highways_classified_standalone.html")

with open(geojson_path, "r", encoding="utf-8") as f:
    geojson_data = json.load(f)

with open(html_path, "r", encoding="utf-8") as f:
    html_content = f.read()

geojson_embed = f"<script>window.EMBEDDED_HIGHWAY_DATA = {json.dumps(geojson_data)};</script>\n"
stats_embed = f"<script>window.HIGHWAY_STATS = {json.dumps(highway_stats)};</script>\n"

insertion_point = '<script src="https://cdnjs.cloudflare.com/ajax/libs/leaflet/1.9.4/leaflet.min.js"></script>'
merged_html = html_content.replace(insertion_point, geojson_embed + stats_embed + insertion_point)

with open(output_path, "w", encoding="utf-8") as f:
    f.write(merged_html)

print("Done:", output_path)

# Reworked version of the embed script, separated into its own cleaner cell with `data_processed` as its own variable.
import json
import arcpy
import os

aprx = arcpy.mp.ArcGISProject("CURRENT")
project_folder = aprx.homeFolder
data_processed = os.path.join(project_folder, "data processed")

html_path = os.path.join(data_processed, "highways_classified.html")
output_path = os.path.join(data_processed, "index.html")

with open(html_path, "r", encoding="utf-8") as f:
    html_content = f.read()

stats_embed = f"<script>window.HIGHWAY_STATS = {json.dumps(highway_stats)};</script>\n"

insertion_point = '<script src="https://cdnjs.cloudflare.com/ajax/libs/leaflet/1.9.4/leaflet.min.js"></script>'
merged_html = html_content.replace(insertion_point, stats_embed + insertion_point)

with open(output_path, "w", encoding="utf-8") as f:
    f.write(merged_html)

print("Created:", output_path)

# Kernel reset again. Reconnecting to the workspace and rebuilding `highway_stats` from scratch since the variable got wiped.
import arcpy
import os
import json
from collections import Counter

# Reconnect to the workspace
aprx = arcpy.mp.ArcGISProject("CURRENT")
arcpy.env.workspace = aprx.defaultGeodatabase
arcpy.env.overwriteOutput = True
project_folder = aprx.homeFolder
data_processed = os.path.join(project_folder, "data processed")

TARGET_ROUTE_NUMBERS = ["400", "401", "403", "404", "410", "427", "QEW"]
STREET_NAMES = {
    "400": "HIGHWAY 400", "401": "HIGHWAY 401", "403": "HIGHWAY 403",
    "404": "HIGHWAY 404", "410": "HIGHWAY 410", "427": "HIGHWAY 427",
    "QEW": "QUEEN ELIZABETH WAY"
}

# Rebuild highway_stats from your final layer (already saved in the geodatabase)
highway_stats = {}

with arcpy.da.SearchCursor("highways_classified_v2",
    ["ROUTE_NUMBER", "segment_type", "L_STANDARD_MUNICIPALITY", "R_STANDARD_MUNICIPALITY",
     "seg_length_km", "AADT_2021_v2", "DESCRIPTIO", "FULL_STREET_NAME"]) as cursor:
    rows = list(cursor)

for hwy in TARGET_ROUTE_NUMBERS:
    cities = set()
    total_length = 0.0
    aadt_values = []
    busiest = {"aadt": -1, "desc": None}
    quietest = {"aadt": float("inf"), "desc": None}
    ramp_count = 0

    for route_num, seg_type, l_muni, r_muni, seg_len, aadt, desc, street in rows:
        if seg_type == "Mainline" and route_num and hwy in [x.strip() for x in route_num.split(";")]:
            if l_muni: cities.add(l_muni)
            if r_muni: cities.add(r_muni)
            if seg_len: total_length += seg_len
            if aadt is not None:
                aadt_values.append(aadt)
                if aadt > busiest["aadt"]:
                    busiest = {"aadt": aadt, "desc": desc}
                if aadt < quietest["aadt"]:
                    quietest = {"aadt": aadt, "desc": desc}

        if seg_type == "Ramp" and street and STREET_NAMES[hwy] in street.upper():
            ramp_count += 1

    highway_stats[hwy] = {
        "cities": sorted(cities),
        "total_length_km": round(total_length / 2, 1),
        "avg_aadt": round(sum(aadt_values) / len(aadt_values)) if aadt_values else None,
        "busiest": busiest,
        "quietest": quietest,
        "interchange_count": ramp_count
    }

print("Rebuilt highway_stats for:", list(highway_stats.keys()))

# Checking the exact field names for AADT/length on the layer, since I wasn't sure if it was `AADT_2021` or `AADT_2021_v2` after all the rebuilds.
fields = [f.name for f in arcpy.ListFields("highways_classified_v2")]
print([f for f in fields if "AADT" in f.upper() or "LENGTH" in f.upper()])

# Embedding the rebuilt `highway_stats` into a fresh `index.html`.
html_path = os.path.join(data_processed, "highways_classified.html")
output_path = os.path.join(data_processed, "index.html")

with open(html_path, "r", encoding="utf-8") as f:
    html_content = f.read()

stats_embed = f"<script>window.HIGHWAY_STATS = {json.dumps(highway_stats)};</script>\n"

insertion_point = '<script src="https://cdnjs.cloudflare.com/ajax/libs/leaflet/1.9.4/leaflet.min.js"></script>'
merged_html = html_content.replace(insertion_point, stats_embed + insertion_point)

with open(output_path, "w", encoding="utf-8") as f:
    f.write(merged_html)

print("Created:", output_path)

# Empty cell.


# Starting the historical time-slider build. Reloading everything and this time pulling *every* year of AADT data (1988-2021), not just 2021, since I want the slider to show traffic evolving over time.
import arcpy, os, json
import pandas as pd
import numpy as np

aprx = arcpy.mp.ArcGISProject("CURRENT")
arcpy.env.workspace = aprx.defaultGeodatabase
arcpy.env.overwriteOutput = True
project_folder = aprx.homeFolder
data_raw = os.path.join(project_folder, "data raw")
data_processed = os.path.join(project_folder, "data processed")

HWY_CODE_MAP = {"400": 400, "401": 401, "403": 403, "404": 404, "410": 410, "427": 427, "QEW": 1}

# Load ALL years this time, not just 2021
csv_path = os.path.join(data_raw, "Traffic_Volumes_1988-2021.csv")
aadt_df = pd.read_csv(csv_path)

aadt_filtered = aadt_df[
    (aadt_df["Hwy No"].isin(HWY_CODE_MAP.values())) &
    (aadt_df["Year"] != 9999)   # exclude the bogus placeholder year
].copy()

aadt_filtered["AADT_clean"] = aadt_filtered["AADT"].astype(str).str.replace(",", "").astype(float)

print("Years available:", sorted(aadt_filtered["Year"].unique()))
print("Total rows across all years:", len(aadt_filtered))

# Building a station-level lookup: `"LHRS_OFFSET" -> {year: AADT}`, the core data structure the slider will read from client-side in the browser.
# Build a lookup: "LHRS_OFFSET" -> {year: aadt}
yearly_lookup = {}

for _, row in aadt_filtered.iterrows():
    key = f"{row['LHRS']}_{row['Offset']}"
    year = str(int(row['Year']))
    aadt = row['AADT_clean']
    if key not in yearly_lookup:
        yearly_lookup[key] = {}
    yearly_lookup[key][year] = aadt

print("Distinct stations with historical data:", len(yearly_lookup))
# Peek at one station's full history
sample_key = list(yearly_lookup.keys())[0]
print(sample_key, "->", yearly_lookup[sample_key])

# Getting the *full* set of station locations for my 7 highways, regardless of which specific years they have data for, needed since the slider covers all years, not just 2021.
base_points_path = os.path.join(data_raw, "LHRS_Base_Points_July2015.shp")
arcpy.management.CopyFeatures(base_points_path, "lhrs_base_points_all")

# Filter to our 7 highways only - keep ALL of them regardless of which years they have data
where_clause = "HWY IN ('1','400','401','403','404','410','427')"
arcpy.management.SelectLayerByAttribute("lhrs_base_points_all", "NEW_SELECTION", where_clause)
arcpy.management.CopyFeatures("lhrs_base_points_all", "aadt_stations_all_years")

# Add a station_key field matching the lookup dict's key format
arcpy.management.AddField("aadt_stations_all_years", "station_key", "TEXT", field_length=30)
with arcpy.da.UpdateCursor("aadt_stations_all_years", ["LHRS", "OFFSET", "station_key"]) as cursor:
    for row in cursor:
        row[2] = f"{row[0]}_{row[1]}"
        cursor.updateRow(row)

print("Total station locations for these highways:", arcpy.management.GetCount("aadt_stations_all_years")[0])

# Splitting the highway mainline at this fuller station set (384 locations now, vs. 327 before) and joining each stretch to its nearest station.
arcpy.management.SplitLineAtPoint(
    in_features="highways_mainline_only",
    point_features="aadt_stations_all_years",
    out_feature_class="highways_split_historical",
    search_radius="100 Meters"
)
print("Split stretches:", arcpy.management.GetCount("highways_split_historical")[0])

# Join each stretch to its nearest station, carrying over the station_key field
arcpy.analysis.SpatialJoin(
    target_features="highways_split_historical",
    join_features="aadt_stations_all_years",
    out_feature_class="highways_historical_joined",
    join_operation="JOIN_ONE_TO_ONE",
    match_option="CLOSEST",
    search_radius="50000 Meters"
)

with arcpy.da.SearchCursor("highways_historical_joined", ["station_key"]) as cursor:
    null_count = sum(1 for row in cursor if row[0] is None)
print("Unmatched stretches:", null_count)

# Merging ramps back in for the historical version too, ramps get no `station_key`, so they'll just render fixed gray regardless of which year is selected.
arcpy.management.SelectLayerByAttribute("highways_filtered_v2", "NEW_SELECTION", "segment_type = 'Ramp'")
arcpy.management.CopyFeatures("highways_filtered_v2", "highways_ramps_historical")
arcpy.management.AddField("highways_ramps_historical", "station_key", "TEXT", field_length=30)
# Ramps get no station_key (stays null) - handled as fixed gray in the map regardless of year

arcpy.management.Merge(["highways_historical_joined", "highways_ramps_historical"], "highways_historical_final")
print("Final layer:", arcpy.management.GetCount("highways_historical_final")[0])

# Reprojecting to WGS84 and exporting the historical GeoJSON, this one carries a `station_key` per stretch instead of a baked-in AADT/tier, since the tier now gets computed live in the browser based on whatever year the slider is on.
arcpy.management.Project(
    in_dataset="highways_historical_final",
    out_dataset="highways_historical_wgs84",
    out_coor_system=arcpy.SpatialReference(4326)
)

historical_geojson_path = os.path.join(data_processed, "highways_historical.geojson")
arcpy.conversion.FeaturesToJSON(
    in_features="highways_historical_wgs84",
    out_json_file=historical_geojson_path,
    geoJSON="GEOJSON"
)
print("Exported:", historical_geojson_path)

# Saving the year-by-year lookup dictionary as its own small JSON file, separate from the geometry.
lookup_path = os.path.join(data_processed, "yearly_lookup.json")
with open(lookup_path, "w", encoding="utf-8") as f:
    json.dump(yearly_lookup, f)

print("Lookup file size (KB):", os.path.getsize(lookup_path) / 1024)

# First attempt building `index.html` for the historical/slider version - embedding just the highway_stats, keeping the (much larger) historical geojson and lookup as separate fetched files instead of embedding everything, learned from the file-size pain of the single-year version.
import json, os

html_path = os.path.join(data_processed, "highways_classified.html")   # the NEW slider template
output_path = os.path.join(data_processed, "index.html")               # overwrite the old one

with open(html_path, "r", encoding="utf-8") as f:
    html_content = f.read()

stats_embed = f"<script>window.HIGHWAY_STATS = {json.dumps(highway_stats)};</script>\n"

insertion_point = '<script src="https://cdnjs.cloudflare.com/ajax/libs/leaflet/1.9.4/leaflet.min.js"></script>'
merged_html = html_content.replace(insertion_point, stats_embed + insertion_point)

with open(output_path, "w", encoding="utf-8") as f:
    f.write(merged_html)

print("New index.html created (with slider + stats):", output_path)

# Kernel reset yet again, reconnecting and rebuilding `highway_stats` one more time for the slider version.
import arcpy, os, json
from collections import Counter

aprx = arcpy.mp.ArcGISProject("CURRENT")
arcpy.env.workspace = aprx.defaultGeodatabase
arcpy.env.overwriteOutput = True
project_folder = aprx.homeFolder
data_processed = os.path.join(project_folder, "data processed")

TARGET_ROUTE_NUMBERS = ["400", "401", "403", "404", "410", "427", "QEW"]
STREET_NAMES = {
    "400": "HIGHWAY 400", "401": "HIGHWAY 401", "403": "HIGHWAY 403",
    "404": "HIGHWAY 404", "410": "HIGHWAY 410", "427": "HIGHWAY 427",
    "QEW": "QUEEN ELIZABETH WAY"
}

highway_stats = {}

with arcpy.da.SearchCursor("highways_classified_v2",
    ["ROUTE_NUMBER", "segment_type", "L_STANDARD_MUNICIPALITY", "R_STANDARD_MUNICIPALITY",
     "seg_length_km", "AADT_2021_v2", "DESCRIPTIO", "FULL_STREET_NAME"]) as cursor:
    rows = list(cursor)

for hwy in TARGET_ROUTE_NUMBERS:
    cities = set()
    total_length = 0.0
    aadt_values = []
    busiest = {"aadt": -1, "desc": None}
    quietest = {"aadt": float("inf"), "desc": None}
    ramp_count = 0

    for route_num, seg_type, l_muni, r_muni, seg_len, aadt, desc, street in rows:
        if seg_type == "Mainline" and route_num and hwy in [x.strip() for x in route_num.split(";")]:
            if l_muni: cities.add(l_muni)
            if r_muni: cities.add(r_muni)
            if seg_len: total_length += seg_len
            if aadt is not None:
                aadt_values.append(aadt)
                if aadt > busiest["aadt"]:
                    busiest = {"aadt": aadt, "desc": desc}
                if aadt < quietest["aadt"]:
                    quietest = {"aadt": aadt, "desc": desc}

        if seg_type == "Ramp" and street and STREET_NAMES[hwy] in street.upper():
            ramp_count += 1

    highway_stats[hwy] = {
        "cities": sorted(cities),
        "total_length_km": round(total_length / 2, 1),
        "avg_aadt": round(sum(aadt_values) / len(aadt_values)) if aadt_values else None,
        "busiest": busiest,
        "quietest": quietest,
        "interchange_count": ramp_count
    }

print("Rebuilt for:", list(highway_stats.keys()))

# Embedding the rebuilt stats into `index.html` again.
html_path = os.path.join(data_processed, "highways_classified.html")
output_path = os.path.join(data_processed, "index.html")

with open(html_path, "r", encoding="utf-8") as f:
    html_content = f.read()

stats_embed = f"<script>window.HIGHWAY_STATS = {json.dumps(highway_stats)};</script>\n"

insertion_point = '<script src="https://cdnjs.cloudflare.com/ajax/libs/leaflet/1.9.4/leaflet.min.js"></script>'
merged_html = html_content.replace(insertion_point, stats_embed + insertion_point)

with open(output_path, "w", encoding="utf-8") as f:
    f.write(merged_html)

print("Created:", output_path)

# Same embed, but added an `assert` this time to fail loudly if the wrong HTML template (without the slider markup) accidentally gets used again, bit me once already.
html_path = os.path.join(data_processed, "highways_classified.html")
output_path = os.path.join(data_processed, "index.html")

with open(html_path, "r", encoding="utf-8") as f:
    html_content = f.read()

# Sanity check before embedding - confirm we're using the right template
assert "yearSlider" in html_content, "Wrong template - slider markup not found in source file"

stats_embed = f"<script>window.HIGHWAY_STATS = {json.dumps(highway_stats)};</script>\n"
insertion_point = '<script src="https://cdnjs.cloudflare.com/ajax/libs/leaflet/1.9.4/leaflet.min.js"></script>'
merged_html = html_content.replace(insertion_point, stats_embed + insertion_point)

with open(output_path, "w", encoding="utf-8") as f:
    f.write(merged_html)

print("Created:", output_path)

# Found a real bug via the browser console: `json.dump()` happily writes Python's `NaN` for invalid values, but that's not actually valid JSON, browsers reject it outright. Rebuilding the yearly lookup while explicitly skipping any NaN AADT values instead of writing them into the file.
import math

# Rebuild the lookup, skipping any NaN AADT values entirely
yearly_lookup = {}

for _, row in aadt_filtered.iterrows():
    aadt = row['AADT_clean']
    if aadt is None or (isinstance(aadt, float) and math.isnan(aadt)):
        continue  # skip invalid entries instead of writing NaN into the JSON

    key = f"{row['LHRS']}_{row['Offset']}"
    year = str(int(row['Year']))
    if key not in yearly_lookup:
        yearly_lookup[key] = {}
    yearly_lookup[key][year] = aadt

print("Distinct stations:", len(yearly_lookup))

# Save again, overwriting the broken file
lookup_path = os.path.join(data_processed, "yearly_lookup.json")
with open(lookup_path, "w", encoding="utf-8") as f:
    json.dump(yearly_lookup, f)

print("Fixed lookup saved:", os.path.getsize(lookup_path) / 1024, "KB")

# Found a second, sneakier bug. Even after removing NaNs, values were still coming back `undefined` in the browser. Turned out `Offset` is a float in the AADT CSV (`0.0`) but an integer in the shapefile (`0`), so the lookup keys never actually matched even though the data was correct. Casting both to `int()` before building the key fixed it for real.
import math

yearly_lookup = {}

for _, row in aadt_filtered.iterrows():
    aadt = row['AADT_clean']
    if aadt is None or (isinstance(aadt, float) and math.isnan(aadt)):
        continue

    # Cast Offset to int to match the shapefile's Integer field format exactly
    key = f"{int(row['LHRS'])}_{int(row['Offset'])}"
    year = str(int(row['Year']))
    if key not in yearly_lookup:
        yearly_lookup[key] = {}
    yearly_lookup[key][year] = aadt

print("Distinct stations:", len(yearly_lookup))
sample_key = list(yearly_lookup.keys())[0]
print(sample_key, "->", yearly_lookup[sample_key])

lookup_path = os.path.join(data_processed, "yearly_lookup.json")
with open(lookup_path, "w", encoding="utf-8") as f:
    json.dump(yearly_lookup, f)
print("Saved:", os.path.getsize(lookup_path) / 1024, "KB")

# Empty trailing cell.

# Re-running the embed step right after adjusting highway_stats above, just to make sure index.html actually picks up the latest numbers before I move on to anything else.
html_path = os.path.join(data_processed, "highways_classified.html")
output_path = os.path.join(data_processed, "index.html")

with open(html_path, "r", encoding="utf-8") as f:
    html_content = f.read()

assert "yearSlider" in html_content, "Wrong template - slider markup not found"

stats_embed = f"<script>window.HIGHWAY_STATS = {json.dumps(highway_stats)};</script>\n"
insertion_point = '<script src="https://cdnjs.cloudflare.com/ajax/libs/leaflet/1.9.4/leaflet.min.js"></script>'
merged_html = html_content.replace(insertion_point, stats_embed + insertion_point)

with open(output_path, "w", encoding="utf-8") as f:
    f.write(merged_html)

print("Created:", output_path)

# Kernel got restarted at some point and highway_stats was gone from memory, so rebuilding it here straight from the saved highways_classified_v2 layer instead of re-running the entire pipeline from scratch.
import arcpy, os, json
from collections import Counter

aprx = arcpy.mp.ArcGISProject("CURRENT")
arcpy.env.workspace = aprx.defaultGeodatabase
arcpy.env.overwriteOutput = True
project_folder = aprx.homeFolder
data_processed = os.path.join(project_folder, "data processed")

TARGET_ROUTE_NUMBERS = ["400", "401", "403", "404", "410", "427", "QEW"]
STREET_NAMES = {
    "400": "HIGHWAY 400", "401": "HIGHWAY 401", "403": "HIGHWAY 403",
    "404": "HIGHWAY 404", "410": "HIGHWAY 410", "427": "HIGHWAY 427",
    "QEW": "QUEEN ELIZABETH WAY"
}

highway_stats = {}

with arcpy.da.SearchCursor("highways_classified_v2",
    ["ROUTE_NUMBER", "segment_type", "L_STANDARD_MUNICIPALITY", "R_STANDARD_MUNICIPALITY",
     "seg_length_km", "AADT_2021_v2", "DESCRIPTIO", "FULL_STREET_NAME"]) as cursor:
    rows = list(cursor)

for hwy in TARGET_ROUTE_NUMBERS:
    cities = set()
    total_length = 0.0
    aadt_values = []
    busiest = {"aadt": -1, "desc": None}
    quietest = {"aadt": float("inf"), "desc": None}
    ramp_count = 0

    for route_num, seg_type, l_muni, r_muni, seg_len, aadt, desc, street in rows:
        if seg_type == "Mainline" and route_num and hwy in [x.strip() for x in route_num.split(";")]:
            if l_muni: cities.add(l_muni)
            if r_muni: cities.add(r_muni)
            if seg_len: total_length += seg_len
            if aadt is not None:
                aadt_values.append(aadt)
                if aadt > busiest["aadt"]:
                    busiest = {"aadt": aadt, "desc": desc}
                if aadt < quietest["aadt"]:
                    quietest = {"aadt": aadt, "desc": desc}

        if seg_type == "Ramp" and street and STREET_NAMES[hwy] in street.upper():
            ramp_count += 1

    highway_stats[hwy] = {
        "cities": sorted(cities),
        "total_length_km": round(total_length / 2, 1),
        "avg_aadt": round(sum(aadt_values) / len(aadt_values)) if aadt_values else None,
        "busiest": busiest,
        "quietest": quietest,
        "interchange_count": ramp_count
    }

print("Rebuilt for:", list(highway_stats.keys()))

html_path = os.path.join(data_processed, "highways_classified.html")
output_path = os.path.join(data_processed, "index.html")

with open(html_path, "r", encoding="utf-8") as f:
    html_content = f.read()

assert "yearSlider" in html_content, "Wrong template - slider markup not found"

stats_embed = f"<script>window.HIGHWAY_STATS = {json.dumps(highway_stats)};</script>\n"
insertion_point = '<script src="https://cdnjs.cloudflare.com/ajax/libs/leaflet/1.9.4/leaflet.min.js"></script>'
merged_html = html_content.replace(insertion_point, stats_embed + insertion_point)

with open(output_path, "w", encoding="utf-8") as f:
    f.write(merged_html)

print("Created:", output_path)

# Site was still showing the old placeholder colors after a refresh, so before touching anything else here, checking that the template actually has the new green baked in, then re-embedding and checking the written-out file too, not just what was read in.
html_path = os.path.join(data_processed, "highways_classified.html")
output_path = os.path.join(data_processed, "index.html")

with open(html_path, "r", encoding="utf-8") as f:
    html_content = f.read()

# Hard check before doing anything else
assert "4ADE80" in html_content, "STOP - this template still doesn't have the green color"
print("Template confirmed correct, proceeding...")

stats_embed = f"<script>window.HIGHWAY_STATS = {json.dumps(highway_stats)};</script>\n"
insertion_point = '<script src="https://cdnjs.cloudflare.com/ajax/libs/leaflet/1.9.4/leaflet.min.js"></script>'
merged_html = html_content.replace(insertion_point, stats_embed + insertion_point)

with open(output_path, "w", encoding="utf-8") as f:
    f.write(merged_html)

# Verify the OUTPUT is correct too, not just the input
with open(output_path, "r", encoding="utf-8") as f:
    check = f.read()
assert "4ADE80" in check, "STOP - something went wrong, output doesn't have green either"

print("index.html created and verified correct:", output_path)
