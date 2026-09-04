"""
Admin-only API surface: login, shelter management (open/close, edit
capacity), incident resolution, district risk overview, and a manual
"refresh risk now" trigger. Mounted under /api/admin in app/main.py.

Every route except /api/admin/login depends on require_admin, which
checks the Bearer token issued at login against the in-memory session
store in app/admin_auth.py.
"""
from fastapi import APIRouter, Depends, Header, HTTPException
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.admin_auth import authenticate_admin, resolve_session, revoke_session
from app.database import get_db
from app.incidents import get_open_incidents, resolve_incident
from app.risk_sync import refresh_all_risk_and_broadcast
from app.weather_service import DISTRICT_PROFILES

router = APIRouter(prefix="/api/admin", tags=["admin"])


def require_admin(authorization: str = Header(default="")) -> str:
    """
    Expects `Authorization: Bearer <token>`. Returns the admin username
    on success, or raises 401 — use as a route dependency.
    """
    if not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing or malformed Authorization header")
    token = authorization.removeprefix("Bearer ").strip()
    username = resolve_session(token)
    if username is None:
        raise HTTPException(status_code=401, detail="Invalid or expired admin session")
    return username


@router.post("/login")
def admin_login(username: str, password: str, db: Session = Depends(get_db)):
    token = authenticate_admin(db, username, password)
    if token is None:
        raise HTTPException(status_code=401, detail="Invalid username or password")
    return {"token": token, "username": username}


@router.post("/logout")
def admin_logout(authorization: str = Header(default="")):
    if authorization.startswith("Bearer "):
        revoke_session(authorization.removeprefix("Bearer ").strip())
    return {"status": "logged out"}


@router.get("/shelters")
def list_all_shelters(_admin: str = Depends(require_admin), db: Session = Depends(get_db)):
    """All shelters (including closed ones) — the public /api/nearest-shelters only shows open ones."""
    rows = db.execute(text("""
        SELECT id, name, district, block, shelter_type, capacity, is_open,
               wheelchair_accessible, medical_support, contact_number,
               ST_Y(location::geometry) AS lat, ST_X(location::geometry) AS lng
        FROM shelters
        ORDER BY district, name
    """)).mappings().all()
    return [dict(r) for r in rows]


@router.put("/shelters/{shelter_id}")
def update_shelter(
    shelter_id: int,
    is_open: bool | None = None,
    capacity: int | None = None,
    _admin: str = Depends(require_admin),
    db: Session = Depends(get_db),
):
    fields, params = [], {"id": shelter_id}
    if is_open is not None:
        fields.append("is_open = :is_open")
        params["is_open"] = is_open
    if capacity is not None:
        fields.append("capacity = :capacity")
        params["capacity"] = capacity

    if not fields:
        raise HTTPException(status_code=400, detail="Provide at least one of is_open, capacity")

    result = db.execute(text(f"""
        UPDATE shelters SET {", ".join(fields)} WHERE id = :id
        RETURNING id, name, is_open, capacity
    """), params)
    db.commit()

    row = result.mappings().first()
    if row is None:
        raise HTTPException(status_code=404, detail=f"No shelter with id {shelter_id}")
    return dict(row)


@router.get("/incidents")
def list_incidents_admin(_admin: str = Depends(require_admin), db: Session = Depends(get_db)):
    return get_open_incidents(db)


@router.put("/incidents/{incident_id}/resolve")
def resolve_incident_admin(incident_id: int, _admin: str = Depends(require_admin), db: Session = Depends(get_db)):
    return resolve_incident(db, incident_id)


@router.get("/overview")
def admin_overview(_admin: str = Depends(require_admin), db: Session = Depends(get_db)):
    shelter_stats = db.execute(text("""
        SELECT COUNT(*) AS total,
               COUNT(*) FILTER (WHERE is_open) AS open_count,
               COUNT(*) FILTER (WHERE NOT is_open) AS closed_count
        FROM shelters
    """)).mappings().first()

    incident_stats = db.execute(text("""
        SELECT COUNT(*) FILTER (WHERE status = 'open') AS open_incidents,
               COUNT(*) FILTER (WHERE report_type = 'sos' AND status = 'open') AS open_sos
        FROM incident_reports
    """)).mappings().first()

    road_stats = db.execute(text("""
        SELECT COUNT(*) AS total_edges,
               COUNT(*) FILTER (WHERE risk_weight >= 5.0) AS high_risk_edges,
               COUNT(*) FILTER (WHERE is_closed) AS closed_edges
        FROM road_edges
    """)).mappings().first()

    return {
        "tracked_districts": list(DISTRICT_PROFILES.keys()),
        "shelters": dict(shelter_stats),
        "incidents": dict(incident_stats),
        "roads": dict(road_stats),
    }


@router.post("/refresh-risk")
async def admin_refresh_risk(_admin: str = Depends(require_admin)):
    """Manually pulls live weather for every tracked district and re-scores road risk immediately."""
    return await refresh_all_risk_and_broadcast()
