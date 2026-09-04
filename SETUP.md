# Setup Guide — Odisha Disaster Evacuation Planner

This project is now feature-complete end to end: live weather → flood + cyclone
risk models → risk-aware A*/Dijkstra routing across a real (synthetic but
data-grounded) multi-district road network → a full interactive map frontend
→ an admin dashboard for managing shelters and incidents → WebSocket live
updates, with a background job that keeps road risk current automatically.

Everything below has been verified by actually standing up a local
PostgreSQL+PostGIS instance, running every seed/train step, and exercising
every API route (including the WebSocket) end to end.

## Prerequisites
1. **PostgreSQL 14+** with the **PostGIS** extension available (Stack Builder →
   Spatial Extensions on Windows, or `postgresql-*-postgis-3` on Linux)
2. **Python 3.10+**
3. Free **OpenWeatherMap API key** (openweathermap.org/api → sign up → API keys
   tab) — optional to get the app running, required for real live weather data
   instead of graceful "no data" fallbacks

## Setup steps

### 1. Create the database
```bash
psql -U postgres -c "CREATE DATABASE disaster_evac_planner;"
```

### 2. Set up your virtual environment
```bash
python -m venv venv
source venv/bin/activate        # venv\Scripts\activate on Windows
pip install -r requirements.txt
```

### 3. Configure environment variables
```bash
cp .env.example .env
```
Edit `.env`:
- `DB_PASSWORD` → your real PostgreSQL password
- `OPENWEATHER_API_KEY` → your real OpenWeatherMap key (leave blank to run
  without live weather — risk checks and road-risk refresh will report a
  clear "no data" error per district instead of crashing)
- `ADMIN_USERNAME` / `ADMIN_PASSWORD` → the admin dashboard login this project
  will create in step 7. **Change the password from the default before
  deploying this anywhere reachable by others.**

### 4. Run the schema
```bash
psql -U postgres -d disaster_evac_planner -f db/schema.sql
```
Should stream `CREATE EXTENSION` / `CREATE TABLE` / `CREATE INDEX` with no
errors — 7 tables total.

### 5. Seed the real shelter data
```bash
python -m db.seed_shelters
```
→ `Seeded 158 shelters into the database.`

### 6. Seed the road network
```bash
python -m db.seed_road_network
```
→ `Seeded 33 road nodes and 36 road edges across 9 districts.`

**Important note on this data:** this environment has no network access to
OpenStreetMap/Overpass, so this is **not** a real road import. It's a
transparent synthetic network: one hub node per tracked district (at the
same coordinates the weather/ML pipeline already uses), a handful of access
nodes at real shelter coordinates wired to their district's hub, and
hub-to-hub backbone edges connecting each district to its nearest neighbors.
It's genuinely connected and good enough for realistic routing/demo
purposes, but if this ever needs real road geometry, swap this script for an
Overpass API import — nothing else in the app cares how `road_nodes`/
`road_edges` got populated.

### 7. Create the admin account
```bash
python -m db.seed_admin
```
→ `Admin user 'admin' is ready.` Re-runnable (it upserts), and reads
`ADMIN_USERNAME`/`ADMIN_PASSWORD` from `.env` if you set them.

### 8. Train the ML models
```bash
python -m ml.train_flood_model
python -m ml.train_cyclone_model
```
Pre-trained models are already included at `ml/flood_risk_model.pkl` and
`ml/cyclone_risk_model.pkl` — these steps just retrain them fresh if you
want to. Both fall back to synthetic training data if no real Kaggle
dataset is present, so they work with zero extra setup.

### 9. Start the API
```bash
uvicorn app.main:app --reload
```
On startup this also starts a background scheduler (interval set by
`WEATHER_POLL_INTERVAL_MINUTES`, default 15) that periodically refreshes
live risk for every district and re-scores road segment risk accordingly —
no manual action needed once it's running, though you can also trigger it
manually from the admin dashboard.

### 10. Open it
| URL | What it is |
|---|---|
| `http://127.0.0.1:8000/` | Main map — set your location, check risk, get routed to a shelter, report incidents/SOS |
| `http://127.0.0.1:8000/admin` | Admin dashboard — log in with the account from step 7 |
| `http://127.0.0.1:8000/health/db` | Quick DB + PostGIS + shelter-count sanity check |
| `http://127.0.0.1:8000/docs` | Auto-generated interactive API docs (FastAPI/Swagger) |

If `/health/db` returns `postgis_version` and `"shelters_seeded": 158`, and
the map at `/` shows shelter markers and a colored road network, everything
is wired up correctly.

---

## What's in this project

```
disaster-evac-planner/
├── app/
│   ├── main.py              # FastAPI app + all HTTP/WebSocket routes
│   ├── config.py            # loads .env into a typed Settings object
│   ├── database.py          # SQLAlchemy engine + session
│   ├── weather_service.py   # live weather -> flood/cyclone models -> risk score, per district or all
│   ├── shelter_alerts.py    # risk check -> nearest real shelter(s)
│   ├── routing_engine.py    # loads road_nodes/road_edges into a graph, runs A*/Dijkstra
│   ├── routing_astar.py     # A* implementation
│   ├── routing_dijkstra.py  # Dijkstra implementation
│   ├── incidents.py         # incident/SOS report creation + resolution
│   ├── websocket_manager.py # broadcast hub for connected frontend clients
│   ├── risk_sync.py         # ties live district risk to road_edges.risk_weight + WS broadcast
│   ├── scheduler.py         # background job that runs risk_sync on a timer
│   ├── admin_auth.py        # PBKDF2 password hashing + session tokens
│   ├── admin_routes.py      # /api/admin/* — login, shelter mgmt, incident resolution, overview
│   ├── geo_utils.py         # haversine distance, point-in-polygon helpers
│   └── startup.py           # ensures ML models exist before the app serves traffic
├── db/
│   ├── schema.sql              # PostGIS schema (7 tables)
│   ├── seed_shelters.py        # loads the real shelter CSV into the DB
│   ├── seed_road_network.py    # builds the synthetic multi-district road graph (see step 6)
│   └── seed_admin.py           # creates/updates the admin dashboard login
├── data/
│   ├── odisha_shelters_geocoded.csv   # 158 real shelters, 9 tracked districts (primary)
│   └── kendrapara_shelters.csv        # 117 shelters, Kendrapara only (richer detail)
├── ml/
│   ├── generate_synthetic_flood_data.py / generate_synthetic_cyclone_data.py
│   ├── train_flood_model.py / train_cyclone_model.py   # train RF + XGBoost, save the winner
│   ├── predict_flood_risk.py / predict_cyclone_risk.py # used by the live API
│   └── flood_risk_model.pkl / cyclone_risk_model.pkl   # pre-trained models (already included)
├── frontend/
│   ├── index.html / app.js     # main interactive map — risk check, routing, incidents, live updates
│   └── admin.html / admin.js   # admin dashboard
├── requirements.txt
├── .env.example
└── SETUP.md                    # this file
```

## What each piece actually does, end to end

1. **Check my risk**: click the map (or use browser geolocation) to set your
   location, pick a district, hit "Check my risk." The backend pulls live
   weather for that district, runs it through both the flood and cyclone ML
   models, takes whichever hazard is worse, and returns an impact level plus
   the nearest real shelters.
2. **Route me there**: click "Route" next to any shelter — the backend runs
   A*/Dijkstra over the road graph, weighting each edge by its *current* risk
   (not just distance), and the frontend draws the resulting path.
3. **Live risk feeds routing automatically**: every `WEATHER_POLL_INTERVAL_MINUTES`,
   the background scheduler re-checks every district and updates
   `road_edges.risk_weight` accordingly — so routes computed later
   automatically avoid roads through worse-hit districts, with zero manual
   intervention. The admin dashboard can also trigger this immediately.
4. **Report / SOS**: both broadcast over WebSocket to every connected client
   immediately, appearing as map markers and in the live log without a page
   refresh.
5. **Admin dashboard**: open/close shelters, edit capacity, resolve
   incidents, see district risk + road risk stats at a glance, and manually
   force a risk refresh.

## Known limitations / honest caveats
- The road network is synthetic (see step 6) — real OSM road geometry would
  be a drop-in improvement later, not a rewrite.
- Admin sessions are held in memory (see `app/admin_auth.py`) — fine for a
  single local/dev process, but won't survive a server restart or work
  across multiple worker processes. Swap in Redis-backed sessions or a real
  JWT library before any multi-instance production deployment.
- Without an `OPENWEATHER_API_KEY`, risk checks and the road-risk refresh
  return a clear per-district error rather than fabricated data — this is
  intentional, not a bug.
