# Spotter fuel route API

A Django REST API that plans US road journeys and fuel purchases from a prepared
station price catalogue. It routes through selected facilities, calculates
partial purchases using the final road distances, and returns a map of the same
saved itinerary.

The fuel model assumes a **50 US gallon** full starting tank, **10 MPG**,
divisible purchases and zero destination reserve. Purchase cost excludes the
initial tank. The purchase calculation is optimal for the selected fixed
itinerary; route and station selection are heuristic.

## Quick start

Docker runs the application and PostgreSQL on Windows, macOS and Linux. No host
Python or PostgreSQL installation is required.

| Platform | Prerequisites |
| --- | --- |
| Windows | [Docker Desktop](https://docs.docker.com/desktop/setup/install/windows-install/) running Linux containers. |
| macOS | [Docker Desktop](https://docs.docker.com/desktop/setup/install/mac-install/) for Apple silicon or Intel, matching your Mac. |
| Linux | [Docker Engine](https://docs.docker.com/engine/install/) with the [Compose plugin](https://docs.docker.com/compose/install/linux/), or Docker Desktop. |

Start Docker and confirm `docker info` and `docker compose version` work in your
terminal. Run the following commands from the repository root.

**Windows — PowerShell**

```powershell
Copy-Item .env.example .env
```

**macOS / Linux — Terminal**

```sh
cp .env.example .env
```

Set `DB_PASSWORD` to a private local password in `.env`. The remaining local
defaults support the offline demo. Start the application on any platform:

```sh
docker compose up --build -d
docker compose exec web python manage.py demo_plan
```

Startup waits for PostgreSQL, applies migrations and creates the shared cache
table. [GET /health/](http://127.0.0.1:8000/health/) checks web-process liveness.
Live planning also needs the data and ORS credential described below.

The offline demo makes no provider requests. Its synthetic 900-mile itinerary
has a $4 station at mile 400: 40 gallons purchased, $160 cost and zero remaining
fuel. It rolls back its database changes and uses a temporary cache; its geometry
is illustrative and its map URL is not served by the web process.

| Task | Command |
| --- | --- |
| View logs | `docker compose logs web` |
| Stop | `docker compose stop` |
| Restart | `docker compose up -d` |
| Rebuild after source changes | `docker compose up --build -d web` |

PostgreSQL persists in a named volume. Source is built into the image; private
data is mounted from `data/`. The local web server binds to `127.0.0.1:8000` and
uses Django's development server.

## Live planning setup

Synthetic fixtures and the benchmark route manifest are included in Git. The
assessment CSV and prepared coordinates are supplied separately in a private
data package. Without that package, tests and the offline demo are available.

Merge the package's `data/` directory into the repository root:

```text
data/
  raw/fuel-prices.csv
  enriched/stations.json
  boundaries/us.wkb
  boundaries/territories.wkb
  boundaries/us.json
```

The package manifest contains SHA-256 hashes. Preserve file bytes: the importer
uses content hashes for dataset identity. The catalogue contains 8,151 source
observations, 6,626 US station identities and 1,400 accepted coordinates.

Set `ORS_API_KEY` in `.env` to an openrouteservice credential with access to
`driving-hgv`. `GEOAPIFY_API_KEY` enables optional background map tiles. Reload the
environment and import the catalogue using the same commands on every platform:

```sh
docker compose up -d --force-recreate web
docker compose exec web python manage.py import_fuel_data data/raw/fuel-prices.csv data/enriched/stations.json
```

Identical imports are no-ops. A new dataset activates atomically after validation;
each request retains one captured dataset version. Startup does not acquire or
import station data. Contact the repository owner for the private data package.

To prepare boundaries separately, download the official
[Census TIGER2025 state archive](https://www2.census.gov/geo/tiger/TIGER2025/STATE/tl_2025_us_state.zip)
to `data/raw/tl_2025_us_state.zip` and run:

```sh
docker compose exec web python manage.py prepare_us_boundaries data/raw/tl_2025_us_state.zip
```

### Configuration

| Setting | Purpose |
| --- | --- |
| `DB_PASSWORD` | Required local PostgreSQL password. |
| `DJANGO_DEBUG` | `1` in the example for local development. |
| `DJANGO_SECRET_KEY` | Required when debug is disabled; local debug has a development fallback. |
| `DJANGO_ALLOWED_HOSTS` | Comma-separated hostnames; defaults include localhost and 127.0.0.1. |
| `ORS_API_KEY` | Server-side live routing credential. |
| `GEOAPIFY_API_KEY` | Server-side background tile credential. |
| `US_BOUNDARY_PATH` | Defaults to `data/boundaries/us.wkb`. |
| `DB_NAME`, `DB_USER`, `DB_HOST`, `DB_PORT` | Native database connection. Compose overrides name/user/host with `spotter`/`spotter`/`db`; port defaults to 5432. |

`.env`, private data, local Compose overrides and generated outputs are excluded
from Git and the Docker build context. Choose the database password before first
startup; changing it later also requires changing the existing PostgreSQL login.

## API

Send `POST /api/v1/route-plan/` with `Content-Type: application/json`:

```json
{
  "start": {"latitude": 32.7555, "longitude": -97.3308},
  "finish": {"latitude": 33.749, "longitude": -84.388}
}
```

Only these named numeric fields are accepted. Strings, booleans, non-finite or
out-of-range values and extra fields are rejected. Endpoints must be within the
50 US states or DC.

| Response field | Contents |
| --- | --- |
| `plan_id`, `map_url`, `map_expires_at` | Saved plan identifier and one-hour map snapshot. |
| `route` | Final GeoJSON, road distance, legs, endpoint snaps and additional itinerary distance. |
| `visited_stations` | All selected waypoints, including facilities requiring no purchase after final routing. |
| `fuel_stops` | Positive purchases, prices, quantities, costs and tank balances. |
| `fuel` | Initial, consumed, purchased and remaining gallons; total purchase cost. |
| `assumptions`, `provenance` | Fuel model and dataset, price, algorithm, boundary and provider versions. |
| `diagnostics`, `warnings` | Routing attempts, cache hits, repair status and limitations. |

The synthetic demo returns this `fuel` object:

```json
{
  "initial_gallons": "50",
  "capacity_gallons": "50",
  "mpg": "10",
  "consumed_gallons": "90.000000000000",
  "purchased_gallons": "40.000000000000",
  "remaining_gallons": "0.000000000000",
  "total_cost_usd": "160.00"
}
```

This example belongs to the synthetic itinerary, rather than the live request
above. Quantities are decimal strings. Purchase costs round half-up to cents;
the total sums the displayed line items.

### Map and Postman

Open `http://127.0.0.1:8000` followed by the response's `map_url`. The Leaflet viewer
displays saved geometry and purchases without rerouting. It loads Leaflet from a
CDN. Background tiles have a separate 24-hour cache and may consume Geoapify
credits; a tile failure leaves the itinerary visible. Expired snapshots return 404.

Import the collection and environment from `postman/`, then select **Spotter local**.
Run the long-route request, repeat it to inspect `plan_cache_hit`, and open
**Saved exact map**. Invalid-input and zero-distance requests are also included.
Zero-distance requests need prepared boundaries and an active dataset, but make
no routing call. Provider credentials are configured on the server, not in Postman.

### Errors

Errors contain `error.code`, `error.message`, optional safe details and `request_id`.

| HTTP status | Representative codes |
| --- | --- |
| 400 / 415 | `INVALID_INPUT`: invalid fields, JSON or content type. |
| 422 | `OUTSIDE_US`, `UNSUPPORTED_US_JURISDICTION`: unsupported endpoint. |
| 422 | `INSUFFICIENT_STATION_COVERAGE`: accepted facilities cannot bridge the projected route. |
| 422 | `NO_VERIFIED_PLAN`: final itinerary is infeasible within the repair budget. |
| 422 | `ROUTE_GEOGRAPHY_UNVERIFIED`, `STATION_ACCESS_UNVERIFIED`: geography or snap check failed. |
| 503 | `DATA_NOT_READY`, `PROVIDER_UNAVAILABLE`, `PROVIDER_QUOTA_EXCEEDED`. |
| 504 | `PROVIDER_TIMEOUT`. |

## Architecture

`stations` handles ingestion, coordinate matching, provenance and versioned
catalogues. `planning` contains the Decimal fuel solver, independent validator,
ORS adapter, station projection, orchestration, caches and map. `config` holds
the Django settings and URL configuration. The runtime uses Django REST Framework
and PostgreSQL.

1. Validate endpoints, capture the active dataset and check the saved-plan cache.
2. Request an ORS `driving-hgv` base route with `vehicle_type: hgv` and
   `avoid_borders: all`; validate its complete geometry against the US boundary.
3. Project accepted facilities within one mile of the route, retain distinct
   occurrences on loops, and calculate purchases on projected distances.
4. Route through the selected facilities and recompute purchases using actual
   road legs. Endpoint snaps are limited to 350 metres; facility snaps to 100 metres.
5. Attempt one bridge repair for a final fuel gap if budget remains. Independently
   validate capacity, fuel conservation and serialised quantities, then save the plan.

A fuel itinerary normally needs two routing attempts; retries and repair share
a maximum of three actual attempts per request. A journey requiring no purchase
usually needs one. Successful plans are cached for one hour; a saved-plan hit
makes zero routing calls. Cache keys include relevant dataset, boundary and
routing-policy versions. See [the algorithm](docs/algorithm.md) for the greedy
rule, worked examples and optimality scope.

The importer preserves all source observations, including duplicates and 620
Canadian rows. Canadian rows do not become routing candidates. US OPIS identities
use the **median of distinct positive prices**, so duplicate rows cannot
overweight a price. The catalogue retains source observations and coordinate
evidence for each dataset version.

The prepared catalogue has 1,400 accepted facilities across 43 states: 1,398 from
published All the Places operator-derived records and two from validated operator
directory records. Supported reference namespaces include Love's, Pilot/Flying J,
Kwik Trip/Star and Sheetz. Acceptance requires compatible branch reference,
operator, state, locality, physical address, fuel-facility evidence, supported-US
coordinates and provenance. Unproven renames, conflicting identities and shared
coordinates remain unresolved or review-required.

## Benchmarks and limitations

The reference benchmark uses `fixtures/coverage-benchmark-routes.json`, the
1,400-coordinate catalogue and the explicit HGV policy above. Each case has two
requests to distinguish initial planning from cached repeats.

| Fuel-purchase journey | Final miles | Purchase cost |
| --- | ---: | ---: |
| Fort Worth → Atlanta | 815.95 | $94.47 |
| Chicago → New York | 797.19 | $98.40 |
| Los Angeles → Denver | 1,017.91 | $178.74 |
| Miami → Atlanta | 664.06 | $52.87 |
| Atlanta → Fort Worth | 816.61 | $94.67 |
| Minneapolis → Dallas | 942.51 | $138.39 |
| Detroit → New York | 618.53 | $39.20 |
| Seattle → Denver | No verified plan | Accepted-station coverage gap |

Seven of eight fuel-purchase cases succeed. Seattle–Denver has a 525.20-mile gap
between eligible accepted facilities. The separate zero-purchase controls are
Seattle–Boise (499.63 miles) and Dallas–Fort Worth (32.14 miles), both at $0.

In the reference run, successful purchase cases used two actual routing calls
initially and controls used one; successful repeats used zero. The failed
Seattle–Denver repeat reused cached base geometry and made zero calls. Results
depend on the catalogue, provider responses and cache state; a local miss does
not establish an upstream provider-cold request.

- **Coverage:** 1,400 of 6,626 US identities (21.1%) have accepted coordinates.
  This benchmark does not establish nationwide coverage, accuracy or an SLA.
- **Prices:** the supplied snapshot has unknown grade and observation date.
- **Coordinate evidence:** source rules and limited documentary inspection
  establish acceptance, not a field survey. Source addresses do not prove a match
  to CSV highway-exit text, and some fuel tags originate in collector logic.
- **Access:** provider waypoints do not verify individual pumps. HGV routing does
  not establish legal clearance for a particular truck's dimensions or weight.
- **Optimisation:** purchase quantities are optimal on the selected fixed itinerary.
  Route/stop selection is heuristic; additional facilities can increase road distance
  and cost.

## Development

Run checks on any platform with Docker:

```sh
docker compose exec web pytest -q
docker compose exec web ruff check .
docker compose exec web ruff format --check .
docker compose exec web python manage.py check
docker compose exec web python manage.py makemigrations --check --dry-run
```

Tests use synthetic data and mocked providers. They cover a seeded exhaustive
solver oracle, range edges, route loops, road-distance repair, import atomicity,
source conflicts, input validation and saved maps.

Preview the benchmark with `docker compose exec web python manage.py benchmark_routes`.
Add `--live` to run it against the routing provider; this consumes provider allowance.
The command retains caches and writes timings, query counts, attempts and failures
to ignored `data/cache/benchmark.json`.

<details>
<summary>Optional native setup</summary>

Install Python 3.13 and PostgreSQL. Create a `spotter` database with a login able
to create test databases. Create a virtual environment from the repository root:

**Windows — PowerShell**

```powershell
py -3.13 -m venv .venv
.\.venv\Scripts\Activate.ps1
Copy-Item .env.example .env
```

**macOS / Linux — Terminal**

```sh
python3.13 -m venv .venv
. .venv/bin/activate
cp .env.example .env
```

Configure the database credentials in `.env`, then use the same commands on all
platforms from the activated environment:

```sh
python -m pip install -r requirements.txt
python manage.py migrate
python manage.py createcachetable
python manage.py runserver 127.0.0.1:8000
```

For import, demo and checks, omit `docker compose exec web` from the commands above.

</details>

Attribution: routes © openrouteservice / HeiGIT; basemap © Geoapify and
OpenStreetMap contributors; boundaries from the US Census Bureau. Leaflet uses
BSD-2-Clause. Operator-derived coordinates retain All the Places source provenance.
The assessment CSV and prepared data package are privately supplied.
