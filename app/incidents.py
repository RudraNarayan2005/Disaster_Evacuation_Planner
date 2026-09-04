"""
SOS and incident reporting — lets a user report a blocked road, flooding,
a fallen tree, or send an SOS with their location. These feed into
incident_reports (already in your schema) and can later influence
routing (e.g. a reported road closure should raise that edge's risk).
"""
import uuid

from sqlalchemy import text
from sqlalchemy.orm import Session


def create_incident_report(
    db: Session,
    report_type: str,
    lat: float,
    lng: float,
    description: str = "",
) -> dict:
    """
    report_type: one of 'road_blocked', 'flooding', 'fallen_tree', 'sos', 'other'
    Matches the CHECK constraint already defined in incident_reports.
    """
    valid_types = {"road_blocked", "flooding", "fallen_tree", "sos", "other"}
    if report_type not in valid_types:
        return {"error": f"Invalid report_type. Choose one of: {sorted(valid_types)}"}

    result = db.execute(text("""
        INSERT INTO incident_reports (report_type, reporter_location, description)
        VALUES (:report_type, ST_SetSRID(ST_MakePoint(:lng, :lat), 4326)::geography, :description)
        RETURNING id, created_at
    """), {
        "report_type": report_type,
        "lat": lat,
        "lng": lng,
        "description": description,
    })
    db.commit()

    row = result.mappings().first()
    return {
        "id": row["id"],
        "report_type": report_type,
        "lat": lat,
        "lng": lng,
        "description": description,
        "status": "open",
        "created_at": str(row["created_at"]),
    }


def create_sos(db: Session, lat: float, lng: float, description: str = "") -> dict:
    """
    Dedicated SOS helper — same underlying table, but generates a
    distinct emergency ID the user can reference/quote to responders,
    per the original spec ('generate emergency ID').
    """
    emergency_id = f"SOS-{uuid.uuid4().hex[:8].upper()}"
    full_description = f"[{emergency_id}] {description}".strip()

    report = create_incident_report(db, "sos", lat, lng, full_description)
    if "error" in report:
        return report

    report["emergency_id"] = emergency_id
    return report


def get_open_incidents(db: Session, bbox: dict | None = None) -> list[dict]:
    """
    Returns all open incident reports, optionally filtered to a bounding
    box (bbox = {"min_lat", "max_lat", "min_lng", "max_lng"}) so a
    frontend map only pulls incidents currently in view.
    """
    if bbox:
        query = text("""
            SELECT id, report_type, description, status, created_at,
                   ST_Y(reporter_location::geometry) AS lat,
                   ST_X(reporter_location::geometry) AS lng
            FROM incident_reports
            WHERE status = 'open'
              AND ST_Y(reporter_location::geometry) BETWEEN :min_lat AND :max_lat
              AND ST_X(reporter_location::geometry) BETWEEN :min_lng AND :max_lng
            ORDER BY created_at DESC
        """)
        rows = db.execute(query, bbox).mappings().all()
    else:
        query = text("""
            SELECT id, report_type, description, status, created_at,
                   ST_Y(reporter_location::geometry) AS lat,
                   ST_X(reporter_location::geometry) AS lng
            FROM incident_reports
            WHERE status = 'open'
            ORDER BY created_at DESC
        """)
        rows = db.execute(query).mappings().all()

    return [
        {
            "id": r["id"],
            "report_type": r["report_type"],
            "description": r["description"],
            "status": r["status"],
            "lat": r["lat"],
            "lng": r["lng"],
            "created_at": str(r["created_at"]),
        }
        for r in rows
    ]


def resolve_incident(db: Session, incident_id: int) -> dict:
    """Marks an incident as resolved (e.g. once a road is cleared)."""
    result = db.execute(text("""
        UPDATE incident_reports SET status = 'resolved'
        WHERE id = :id
        RETURNING id, status
    """), {"id": incident_id})
    db.commit()

    row = result.mappings().first()
    if row is None:
        return {"error": f"No incident found with id {incident_id}"}
    return {"id": row["id"], "status": row["status"]}