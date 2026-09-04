"""
Loads the trained cyclone risk model and exposes predict_cyclone_risk() —
called by app/weather_service.py to get a live cyclone risk score per
district, alongside the existing flood risk score.

Quick manual test:
    python -m ml.predict_cyclone_risk
"""
import os
import pickle

MODEL_PATH = os.path.join(os.path.dirname(__file__), "cyclone_risk_model.pkl")

_model_cache = None  # loaded once, reused across calls (avoids re-reading disk every request)


def _load_model():
    global _model_cache
    if _model_cache is None:
        if not os.path.exists(MODEL_PATH):
            raise FileNotFoundError(
                "cyclone_risk_model.pkl not found. Run `python -m ml.train_cyclone_model` first."
            )
        with open(MODEL_PATH, "rb") as f:
            _model_cache = pickle.load(f)
    return _model_cache


def predict_cyclone_risk(
    wind_speed_kmph: float,
    pressure_hpa: float,
    distance_from_coast_km: float,
    storm_surge_exposure: float,
    historical_cyclone_freq: float,
    mangrove_cover_index: float,
    building_density_index: float,
) -> float:
    """
    Returns a cyclone risk probability between 0.0 (safe) and 1.0
    (severe/certain impact). Same shape and calling convention as
    predict_flood_risk(), so the two can be combined by the caller.
    """
    bundle = _load_model()
    model = bundle["model"]
    features = [[
        wind_speed_kmph, pressure_hpa, distance_from_coast_km,
        storm_surge_exposure, historical_cyclone_freq,
        mangrove_cover_index, building_density_index,
    ]]
    probability = model.predict(features)[0]
    return float(max(0.0, min(1.0, probability)))  # clamp to valid [0,1] range


def risk_probability_to_weight(probability: float) -> float:
    """
    Converts a raw cyclone probability into a road-edge cost multiplier —
    same bucket scheme as the flood model, for consistency in the
    routing engine:
      0.0-0.25 Safe     -> x1.0
      0.25-0.5 Moderate -> x1.5
      0.5-0.75 High     -> x3.0
      0.75-1.0 Severe   -> x10.0
    """
    if probability < 0.25:
        return 1.0
    elif probability < 0.5:
        return 1.5
    elif probability < 0.75:
        return 3.0
    else:
        return 10.0


def cyclone_impact_level(probability: float) -> str:
    if probability < 0.25:
        return "Low"
    elif probability < 0.5:
        return "Moderate"
    elif probability < 0.75:
        return "High"
    else:
        return "Severe"


if __name__ == "__main__":
    # Example: intense storm near the coast, exposed low-lying area — should score HIGH/SEVERE
    risk = predict_cyclone_risk(
        wind_speed_kmph=140,
        pressure_hpa=955,
        distance_from_coast_km=3,
        storm_surge_exposure=0.85,
        historical_cyclone_freq=3,
        mangrove_cover_index=0.1,
        building_density_index=0.6,
    )
    print(f"Cyclone probability: {risk:.3f} ({cyclone_impact_level(risk)})")
    print(f"Road risk weight:    x{risk_probability_to_weight(risk)}")

    # Example: calm conditions, inland, protected — should score LOW risk
    risk2 = predict_cyclone_risk(
        wind_speed_kmph=15,
        pressure_hpa=1012,
        distance_from_coast_km=40,
        storm_surge_exposure=0.1,
        historical_cyclone_freq=0,
        mangrove_cover_index=0.6,
        building_density_index=0.2,
    )
    print(f"\nCyclone probability: {risk2:.3f} ({cyclone_impact_level(risk2)})")
    print(f"Road risk weight:    x{risk_probability_to_weight(risk2)}")
