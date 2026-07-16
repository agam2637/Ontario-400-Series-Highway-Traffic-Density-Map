# Ontario 400 Series Highway Traffic Density Map

An interactive map of 2021 average annual daily traffic (AADT) across Ontario's busiest highway corridors — Highways 400, 401, 403, 404, 410, 427, and the QEW — built with ArcGIS Pro, Python, and Leaflet.js.

**[View the live map →](https://yourusername.github.io/ontario-400-series-highway-traffic-density-map/)**

---

## What it shows

Each highway is broken into stretches and colored by traffic volume tier:

| Tier | AADT (2021) | Color |
|---|---|---|
| High | 143,200+ | Red |
| Medium | 41,200 – 143,200 | Orange |
| Low | < 41,200 | Yellow |
| Interchange ramp | — | Gray |

Traffic volume varies *along* each highway rather than being one flat value per route — clicking any stretch shows its specific tier and AADT. A **Highway Overview** panel lets you select any of the seven highways to see:

- Every city/municipality it runs through
- Total length (km)
- Number of interchanges
- Average AADT
- Its busiest and quietest monitored points

---

## Data sources

- **Traffic volume**: [MTO Traffic Volumes 1988–2021](https://www.library.mto.gov.on.ca/SydneyPLUS/TechPubs/Portal/tp/tvSplash.aspx) — Ontario Ministry of Transportation
- **Highway geometry**: [Ontario Road Network (ORN) Composite Service](https://geohub.lio.gov.on.ca/) — Ontario GeoHub
- **Station geolocation**: [MTO LHRS Base Points](https://data.ontario.ca/dataset/16a8d195-087b-461e-b6b2-69506dd7feaa) (Linear Highway Referencing System), July 2015

## Methodology

1. **Highway geometry** was pulled live from the ORN Composite Service's REST endpoint, filtered to the 7 target highways. This required matching combined/overlapping route designations (e.g. a shared QEW/403 stretch is stored as `"QEW; 403"` in the source data) rather than a simple exact match, plus a separate pass to catch interchange ramps, which mostly carry no route number at all.
2. **Traffic volume** came from MTO's AADT dataset, keyed by an internal Linear Highway Referencing System (`LHRS` + `Offset`) rather than coordinates. MTO's LHRS Base Points dataset was used to translate those codes into real latitude/longitude for each monitoring station (one useful discovery along the way: the QEW is coded internally as `Hwy No = 1`, not "QEW").
3. Each highway's mainline was **split into stretches at every station location**, so that traffic volume can vary along a highway instead of being one flat value for the whole route. Each stretch was then matched to its nearest monitoring station's AADT.
4. Stretches were classified into Low/Medium/High tiers using tercile breakpoints on 2021 AADT.
5. The final layer was exported to GeoJSON and embedded directly into a single self-contained HTML file (Leaflet.js), along with pre-computed per-highway summary statistics — no server or database required to view it.

The full, real analysis — including the debugging and dead ends — is documented in [`notebook/traffic_volume_analysis.ipynb`](notebook/traffic_volume_analysis.ipynb).

## Known limitations

- **Interpolated, not measured, between stations.** Traffic volume for any given stretch is assigned from its *nearest* monitoring station, not independently measured at every point — a reasonable approximation, but not a direct reading everywhere.
- **Highway lengths are approximate.** Divided highways are digitized in the source data as two separate lines (one per direction of travel); total length is estimated by halving the summed length of all stretches, which is close but not exact.
- **Highway 407 is excluded.** It's privately operated by 407 ETR Concession Company Ltd. and has no public MTO/OPP traffic or collision data.
- **LHRS Base Points data is dated July 2015.** Highway geometry itself rarely changes, so this is unlikely to matter in practice, but it's not a live-updated source.
- **2020 has no AADT data** in the source dataset, likely due to pandemic-era data collection disruption.

## Tech stack

- **ArcGIS Pro + Python (arcpy, pandas, numpy)** — data acquisition, spatial joins, classification
- **Leaflet.js** — interactive web map rendering
- Vanilla HTML/CSS/JS — no build step, no framework, no server required

## Repo structure

```
├── docs/
│   └── index.html              # the interactive map (GitHub Pages serves from here)
└── notebook/
    └── traffic_volume_analysis.ipynb   # full build process, as it actually happened
```
