# Runtime catalogue

These prepared inputs support local route planning without data acquisition or
geocoding. `manifest.json` identifies the five files by SHA-256 and byte size.
Git preserves their source bytes; do not reformat them in place.

| Input | Source and purpose |
| --- | --- |
| `raw/fuel-prices.csv` | Supplied assessment prices and station identities. Price grade and observation date are unknown. |
| `enriched/stations.json` | Coordinate statuses, accepted locations and source-specific identity evidence linked to the CSV. |
| `boundaries/us.wkb` | Prepared WGS84 union of the 50 states and DC for endpoint and complete-route checks. |
| `boundaries/territories.wkb` | Prepared territory polygons for distinguishing unsupported US jurisdictions. |
| `boundaries/us.json` | Census source, CRS and boundary checksum metadata. |

The coordinate artifact preserves all 6,626 US identities, including 1,400
accepted, 94 review-required and 5,132 unresolved. Only accepted coordinates
participate in planning. It uses 1,398 accepted All the Places operator-derived
records and two source-linked operator-directory records. Source URLs, retrieval
metadata and matching evidence remain in the artifact.

All the Places publishes its generated data under
[CC0](https://github.com/alltheplaces/alltheplaces/blob/master/LICENSE). That notice
applies to its data component; it is not a blanket licence for the supplied price
CSV or the separate operator-directory records.

Boundaries are derived from the US Census Bureau's
[TIGER2025 state shapefiles](https://www2.census.gov/geo/tiger/TIGER2025/STATE/tl_2025_us_state.zip).
This application repackages those polygons; it is not a Census Bureau product
and is not endorsed by the Census Bureau. Original geographic files are available
free from the Census Bureau.

Raw operator exports, matching reports, acquisition state, provider response
caches and credentials are excluded. Docker mounts `data/` at runtime rather
than copying these inputs into the image. See the root README for setup and
catalogue limitations.
