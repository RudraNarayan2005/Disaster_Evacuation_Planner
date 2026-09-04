"""
One-time (or re-runnable) seed script: loads data/odisha_shelters_geocoded.csv
into the `shelters` table.

Run from the project root:
    python -m db.seed_shelters
"""
import csv
import os
import sys

# allow running this as a script from project root
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import text
from app.database import engine

CSV_PATH = os.path.join(os.path.dirname(__file__), "..", "data", "odisha_shelters_geocoded.csv")

INSERT_SQL = text("""
    INSERT INTO shelters
        (name, district, block, gp, village, location_desc, shelter_type,
         location, geocode_level)
    VALUES
        (:name, :district, :block, :gp, :village, :location_desc, :shelter_type,
         ST_SetSRID(ST_MakePoint(:lng, :lat), 4326)::geography, :geocode_level)
""")


def build_shelter_name(row: dict) -> str:
    """
    The source CSV doesn't have a clean 'name' column — it has
    Location + Village + Shelter Type. Build something readable.
    """
    loc = row["Location"].strip().rstrip(",")
    village = row["Village"].strip()
    return f"{loc} ({village})" if village and village.lower() not in loc.lower() else loc


def seed():
    with open(CSV_PATH, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        rows = list(reader)

    print(f"Loaded {len(rows)} rows from {CSV_PATH}")

    with engine.begin() as conn:
        # Clear existing seed data so this script is safely re-runnable
        conn.execute(text("DELETE FROM shelters"))

        for row in rows:
            conn.execute(INSERT_SQL, {
                "name": build_shelter_name(row),
                "district": row["District"].strip(),
                "block": row["Block"].strip(),
                "gp": row["GP"].strip(),
                "village": row["Village"].strip(),
                "location_desc": row["Location"].strip(),
                "shelter_type": row["Shelter Type"].strip(),
                "lat": float(row["Latitude"]),
                "lng": float(row["Longitude"]),
                "geocode_level": row["Geocode_Level"].strip(),
            })

    print(f"Seeded {len(rows)} shelters into the database.")


if __name__ == "__main__":
    seed()
