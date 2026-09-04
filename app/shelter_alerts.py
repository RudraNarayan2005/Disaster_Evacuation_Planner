"""
The user-facing half of the loop: given someone's live location, check
whether their district is currently at High/Severe risk, and if so,
find their nearest real shelter (from your 158-shelter dataset already
seeded into the DB).

This is what app/main.py's future /api/check-my-risk endpoint will call.
"""
from sqlalchemy import text
from sqlalchemy.orm import Session


def find_nearest_shelters(db: Session, lat: float, lng: float, limit: int = 3) -> list[dict]:
    """
    Uses PostGIS's <-> distance operator to find the closest real shelters
    to a given point — pulls straight from your 158-shelter table.
    """
    query = text("""
        SELECT
            name, district, block, shelter_type, is_open,
            ST_Y(location::geometry) AS lat,
            ST_X(location::geometry) AS lng,
            ST_Distance(location, ST_SetSRID(ST_MakePoint(:lng, :lat), 4326)::geography) AS distance_m
        FROM shelters
        WHERE is_open = true
        ORDER BY location <-> ST_SetSRID(ST_MakePoint(:lng, :lat), 4326)::geography
        LIMIT :limit
    """)
    rows = db.execute(query, {"lat": lat, "lng": lng, "limit": limit}).mappings().all()

    return [
        {
            "name": r["name"],
            "district": r["district"],
            "block": r["block"],
            "shelter_type": r["shelter_type"],
            "lat": r["lat"],
            "lng": r["lng"],
            "distance_km": round(r["distance_m"] / 1000, 2),
        }
        for r in rows
    ]


def check_user_risk_and_notify(db: Session, lat: float, lng: float, district_risk: dict) -> dict:
    """
    Combines the live district risk score (from weather_service) with
    nearest-shelter lookup, to build the actual notification payload
    your frontend/SOS flow would show the user.

    district_risk is one entry from weather_service.update_all_districts(),
    e.g. {"district": "Puri", "impact_level": "High", "flood_probability": 0.63, ...}
    """
    impact_level = district_risk.get("impact_level", "Low")
    should_evacuate = impact_level in ("High", "Severe")

    result = {
        "district": district_risk.get("district"),
        "impact_level": impact_level,
        "flood_probability": district_risk.get("flood_probability"),
        "should_evacuate": should_evacuate,
        "nearest_shelters": [],
        "message": None,
    }

    if should_evacuate:
        result["nearest_shelters"] = find_nearest_shelters(db, lat, lng, limit=3)
        if result["nearest_shelters"]:
            nearest = result["nearest_shelters"][0]
            result["message"] = (
                f"{impact_level} flood risk in {district_risk.get('district')}. "
                f"Nearest shelter: {nearest['name']} ({nearest['distance_km']} km away)."
            )
        else:
            result["message"] = (
                f"{impact_level} flood risk in {district_risk.get('district')}, "
                f"but no open shelter found nearby — contact local authorities."
            )
    else:
        result["message"] = f"{impact_level} flood risk in {district_risk.get('district')}. No evacuation needed."

    return result


def check_user_combined_risk_and_notify(db: Session, lat: float, lng: float, combined_risk: dict) -> dict:
    """
    Same as check_user_risk_and_notify(), but takes the combined
    flood+cyclone result from weather_service.update_district_combined_risk()
    and evacuates based on whichever hazard is currently worse.

    combined_risk shape:
    {
        "district": "Puri",
        "flood": {...impact_level, flood_probability...},
        "cyclone": {...impact_level, cyclone_probability...},
        "overall_impact_level": "High",
        "overall_hazard": "cyclone",
    }
    """
    district = combined_risk.get("district")
    impact_level = combined_risk.get("overall_impact_level", "Low")
    hazard = combined_risk.get("overall_hazard", "flood")
    should_evacuate = impact_level in ("High", "Severe")

    result = {
        "district": district,
        "impact_level": impact_level,
        "driving_hazard": hazard,
        "flood_probability": combined_risk.get("flood", {}).get("flood_probability"),
        "cyclone_probability": combined_risk.get("cyclone", {}).get("cyclone_probability"),
        "should_evacuate": should_evacuate,
        "nearest_shelters": [],
        "message": None,
    }

    if should_evacuate:
        result["nearest_shelters"] = find_nearest_shelters(db, lat, lng, limit=3)
        if result["nearest_shelters"]:
            nearest = result["nearest_shelters"][0]
            result["message"] = (
                f"{impact_level} {hazard} risk in {district}. "
                f"Nearest shelter: {nearest['name']} ({nearest['distance_km']} km away)."
            )
        else:
            result["message"] = (
                f"{impact_level} {hazard} risk in {district}, "
                f"but no open shelter found nearby — contact local authorities."
            )
    else:
        result["message"] = f"{impact_level} risk in {district} (flood and cyclone). No evacuation needed."

    return result
