"""
Entry point. Run with:
    uvicorn app.main:app --reload
"""
from fastapi import FastAPI, Depends, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.database import get_db
from app.weather_service import (
    update_district_risk,
    update_all_districts,
    update_district_cyclone_risk,
    update_all_districts_cyclone,
    update_district_combined_risk,
    nearest_district,
    DISTRICT_PROFILES,
)
from app.shelter_alerts import check_user_risk_and_notify, check_user_combined_risk_and_notify, find_nearest_shelters
from app.routing_engine import compute_safest_route
from app.incidents import create_incident_report, create_sos, get_open_incidents, resolve_incident
from app.websocket_manager import manager
from app.startup import ensure_models_exist
from app.admin_routes import router as admin_router
from app.scheduler import start_scheduler, stop_scheduler
ensure_models_exist()

app = FastAPI(
    title="Disaster Evacuation Planner API",
    description="ML-driven flood/cyclone evacuation routing for Odisha",
    version="0.1.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # For local dev only — restrict this in production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(admin_router)
app.mount("/static", StaticFiles(directory="frontend"), name="static")


@app.on_event("startup")
def on_startup():
    start_scheduler()


@app.on_event("shutdown")
def on_shutdown():
    stop_scheduler()


@app.get("/")
def root():
    return FileResponse("frontend/index.html")


@app.get("/admin")
def admin_page():
    return FileResponse("frontend/admin.html")


@app.get("/health/db")
def db_health_check(db: Session = Depends(get_db)):
    result = db.execute(text("SELECT PostGIS_Version();")).scalar()
    shelter_count = db.execute(text("SELECT COUNT(*) FROM shelters;")).scalar()
    return {
        "database": "connected",
        "postgis_version": result,
        "shelters_seeded": shelter_count,
    }


@app.get("/api/districts")
def list_tracked_districts():
    """District names + centroid coords — lets the frontend build a selector without hardcoding the list."""
    return [
        {"district": d, "lat": p["lat"], "lng": p["lng"]}
        for d, p in DISTRICT_PROFILES.items()
    ]


@app.get("/api/weather/{district}")
async def get_district_risk(district: str):
    if district not in DISTRICT_PROFILES:
        return {"error": f"Unknown district. Choose one of: {list(DISTRICT_PROFILES.keys())}"}
    return await update_district_risk(district)


@app.get("/api/weather/all")
async def get_all_district_risk():
    return await update_all_districts()


@app.get("/api/cyclone/{district}")
async def get_district_cyclone_risk(district: str):
    if district not in DISTRICT_PROFILES:
        return {"error": f"Unknown district. Choose one of: {list(DISTRICT_PROFILES.keys())}"}
    return await update_district_cyclone_risk(district)


@app.get("/api/cyclone/all")
async def get_all_district_cyclone_risk():
    return await update_all_districts_cyclone()


@app.get("/api/nearest-shelters")
def get_nearest_shelters(lat: float, lng: float, limit: int = 3, db: Session = Depends(get_db)):
    return find_nearest_shelters(db, lat, lng, limit=limit)


@app.get("/api/nearest-district")
def get_nearest_district(lat: float, lng: float):
    """Return the nearest tracked district and centroid distance for browser geolocation."""
    return nearest_district(lat, lng)


@app.get("/api/check-my-risk")
async def check_my_risk(lat: float, lng: float, district: str, db: Session = Depends(get_db)):
    """
    Flood-only risk check, kept for backward compatibility with the
    original SETUP.md walkthrough. For the combined flood+cyclone
    picture, use /api/check-my-risk/combined instead.
    """
    if district not in DISTRICT_PROFILES:
        return {"error": f"Unknown district. Choose one of: {list(DISTRICT_PROFILES.keys())}"}
    district_risk = await update_district_risk(district)
    return check_user_risk_and_notify(db, lat, lng, district_risk)


@app.get("/api/check-my-risk/combined")
async def check_my_combined_risk(lat: float, lng: float, district: str, db: Session = Depends(get_db)):
    """
    The full loop across BOTH hazards: live weather -> flood model AND
    cyclone model -> whichever is worse -> evacuate? -> nearest real shelter.
    """
    if district not in DISTRICT_PROFILES:
        return {"error": f"Unknown district. Choose one of: {list(DISTRICT_PROFILES.keys())}"}
    combined_risk = await update_district_combined_risk(district)
    return check_user_combined_risk_and_notify(db, lat, lng, combined_risk)


@app.get("/api/road-network")
def get_road_network(db: Session = Depends(get_db)):
    """
    Nodes + edges with their current risk_weight, for the frontend to
    draw the road graph and color-code it by live risk (green = safe,
    red = severe). Small enough (a few dozen nodes/edges) to send whole.
    """
    nodes = db.execute(text("""
        SELECT id, label, district,
               ST_Y(location::geometry) AS lat, ST_X(location::geometry) AS lng
        FROM road_nodes
    """)).mappings().all()

    edges = db.execute(text("""
        SELECT id, from_node, to_node, distance_m, risk_weight, is_closed
        FROM road_edges
    """)).mappings().all()

    return {
        "nodes": [dict(n) for n in nodes],
        "edges": [dict(e) for e in edges],
    }


@app.get("/api/route")
def get_safest_route(
    user_lat: float, user_lng: float,
    shelter_lat: float, shelter_lng: float,
    db: Session = Depends(get_db),
):
    return compute_safest_route(db, user_lat, user_lng, shelter_lat, shelter_lng)


@app.post("/api/incidents")
async def report_incident(
    report_type: str, lat: float, lng: float, description: str = "",
    db: Session = Depends(get_db),
):
    result = create_incident_report(db, report_type, lat, lng, description)
    if "error" not in result:
        await manager.broadcast({"type": "new_incident", "data": result})
    return result


@app.post("/api/sos")
async def send_sos(lat: float, lng: float, description: str = "", db: Session = Depends(get_db)):
    result = create_sos(db, lat, lng, description)
    if "error" not in result:
        await manager.broadcast({"type": "sos_alert", "data": result})
    return result


@app.get("/api/incidents")
def list_incidents(db: Session = Depends(get_db)):
    return get_open_incidents(db)


@app.put("/api/incidents/{incident_id}/resolve")
def mark_incident_resolved(incident_id: int, db: Session = Depends(get_db)):
    return resolve_incident(db, incident_id)


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await manager.connect(websocket)
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        manager.disconnect(websocket)


@app.get("/ws-test")
def websocket_test_page():
    html_content = """
    <!DOCTYPE html>
    <html>
    <body>
    <h3>WebSocket Test</h3>
    <div id="log"></div>
    <script>
      const ws = new WebSocket("ws://127.0.0.1:8000/ws");
      ws.onopen = () => document.getElementById("log").innerHTML += "<p>Connected!</p>";
      ws.onmessage = (event) => document.getElementById("log").innerHTML += "<p>Received: " + event.data + "</p>";
      ws.onerror = (e) => document.getElementById("log").innerHTML += "<p>Error occurred</p>";
    </script>
    </body>
    </html>
    """
    return HTMLResponse(content=html_content)