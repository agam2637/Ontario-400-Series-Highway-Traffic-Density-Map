# Ontario 400 Series Highway Traffic Density Map

An interactive map of average annual daily traffic (AADT) across Ontario's busiest highway corridors — Highways 400, 401, 403, 404, 410, 427, and the QEW — built with ArcGIS Pro, Python, and Leaflet.js.

**[View the live map →](https://agam2637.github.io/Ontario-400-Series-Highway-Traffic-Density-Map/)**

---

## What it shows

Each highway is broken into individual stretches — not one flat value per route — and colored by traffic volume tier:

| Tier | AADT | Color |
|---|---|---|
| High | 143,200+ | Red |
| Medium | 41,200 – 143,200 | Orange |
| Low | < 41,200 | Green |
| Interchange ramp | — | Gray |

### 🕐 Historical time slider (1988–2021)
Drag the slider — or hit play — to watch traffic volume evolve across three decades. Every stretch recolors live using a **fixed color scale**, so what you're watching is real traffic growth over time, not a rescaled legend on every frame. Any station missing data for a given year shows as a dim "No Data" stretch rather than guessing.

### 📍 Highway Overview panel
Select any of the seven highways to see:
- Every city/municipality it runs through
- Total length (km)
- Number of interchanges
- Average AADT (2021)
- Its busiest and quietest monitored points

---

## Data sources

- **Traffic volume**: [MTO Traffic Volumes 1988–2021](https://www.library.mto.gov.on.ca/SydneyPLUS/TechPubs/Portal/tp/tvSplash.aspx) — Ontario Ministry of Transportation
- **Highway geometry**: [Ontario Road Network (ORN) Composite Service](https://geohub.lio.gov.on.ca/) — Ontario GeoHub
- **Station geolocation**: [MTO LHRS Base Points](https://data.ontario.ca/dataset/16a8d195-087b-461e-b6b2-69506dd7feaa) (Linear Highway Referencing System), July 2015

## Methodology

1. **Highway geometry** was pulled live from the ORN Composite Service's REST endpoint, filtered to the 7 target highways. This required matching combined/overlapping route designations (e.g. a shared QEW/403 stretch is stored as `"QEW; 403"` in the source data) rather than a simple exact match, plus a separate pass to catch interchange ramps, which mostly carry no route number at all.
2. **Traffic volume** came from MTO's AADT dataset, keyed by an internal Linear Highway Referencing System (`LHRS` + `Offset`) rather than coordinates. MTO's LHRS Base Points dataset was used to translate those codes into real latitude/longitude for each monitoring station (one useful discovery along the way: the QEW is coded internally as `Hwy No = 1`, not "QEW").
3. Each highway's mainline was **split into stretches at every station location**, so traffic volume can vary along a highway instead of being one flat value for the whole route. Each stretch was matched to its nearest monitoring station via spatial join.
4. Stretches were classified into Low/Medium/High tiers using tercile breakpoints on 2021 AADT — the same fixed thresholds are reused for the historical slider, so color changes across years reflect real growth rather than a shifting scale.
5. For the historical view, every available year (1988–2021, excluding a missing 2020) was pulled per station and exported as a lightweight year → AADT lookup table, kept separate from the map geometry so the browser can recolor stretches instantly on slider input without reloading any data.
6. The final layers were exported to GeoJSON and paired with a small self-contained HTML/Leaflet.js page — no server, database, or GIS software required to view it.

The full, real analysis — including the debugging and dead ends — is documented in [`traffic_volume_analysis.ipynb`](traffic_volume_analysis.ipynb).

## Known limitations

- **Interpolated, not measured, between stations.** Traffic volume for any given stretch is assigned from its *nearest* monitoring station, not independently measured at every point.
- **Highway lengths are approximate.** Divided highways are digitized in the source data as two separate lines (one per direction of travel); total length is estimated by halving the summed length of all stretches.
- **Highway 407 is excluded.** It's privately operated by 407 ETR Concession Company Ltd. and has no public MTO/OPP traffic or collision data.
- **LHRS Base Points data is dated July 2015.** Highway geometry itself rarely changes, so this is unlikely to matter in practice, but it's not a live-updated source.
- **2020 has no AADT data** in the source dataset, likely due to pandemic-era data collection disruption — the slider skips straight from 2019 to 2021.
- **Color tiers are fixed to 2021 thresholds.** This is intentional (it's what makes the historical growth visible), but it means very old years will show mostly green/low even on roads that were relatively busy for their era.

## Tech stack

- **ArcGIS Pro + Python (arcpy, pandas, numpy)** — data acquisition, spatial joins, classification
- **Leaflet.js** — interactive web map rendering
- Vanilla HTML/CSS/JS — no build step, no framework, no server required

## Repo structure

```
├── docs/
│   ├── index.html                    # the interactive map
│   ├── highways_historical.geojson   # highway geometry with station references
│   └── yearly_lookup.json            # per-station AADT by year (1988-2021)
├── README.md
└── traffic_volume_analysis.ipynb     # full build process, as it actually happened
```
