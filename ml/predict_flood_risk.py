"""
Loads the trained flood risk model and exposes predict_flood_risk() —
this is the function app/routing.py will call later to get a live risk
score for a road segment or zone.

Quick manual test:
    python -m ml.predict_flood_risk
"""
import os
import pickle

MODEL_PATH = os.path.join(os.path.dirname(__file__), "flood_risk_model.pkl")

_model_cache = None  # loaded once, reused across calls (avoids re-reading disk every request)


def _load_model():
    global _model_cache
    if _model_cache is None:
        if not os.path.exists(MODEL_PATH):
            raise FileNotFoundError(
                "flood_risk_model.pkl not found. Run `python -m ml.train_flood_model` first."
            )
        with open(MODEL_PATH, "rb") as f:
            _model_cache = pickle.load(f)
    return _model_cache


def predict_flood_risk(
    rainfall_mm: float,
    elevation_m: float,
    distance_from_river_km: float,
    historical_flood_freq: float,
    drainage_quality: float,
    urbanization_index: float,
    deforestation_index: float,
) -> float:
    """
    Returns a flood probability between 0.0 (safe) and 1.0 (certain flooding).
    This is the number that becomes a road's risk_weight in the routing engine.
    """
    bundle = _load_model()
    model = bundle["model"]
    features = [[
        rainfall_mm, elevation_m, distance_from_river_km,
        historical_flood_freq, drainage_quality,
        urbanization_index, deforestation_index,
    ]]
    probability = model.predict(features)[0]
    return float(max(0.0, min(1.0, probability)))  # clamp to valid [0,1] range


def risk_probability_to_weight(probability: float) -> float:
    """
    Converts a raw flood probability into a road-edge cost multiplier,
    per the bucket scheme decided earlier:
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


if __name__ == "__main__":
    # Example: a low-lying, high-rainfall spot near a river — should score HIGH risk
    risk = predict_flood_risk(
        rainfall_mm=180,
        elevation_m=5,
        distance_from_river_km=0.5,
        historical_flood_freq=4,
        drainage_quality=0.2,
        urbanization_index=0.6,
        deforestation_index=0.5,
    )
    print(f"Flood probability: {risk:.3f}")
    print(f"Road risk weight:  x{risk_probability_to_weight(risk)}")

    # Example: elevated, low-rainfall, far from river — should score LOW risk
    risk2 = predict_flood_risk(
        rainfall_mm=20,
        elevation_m=150,
        distance_from_river_km=8,
        historical_flood_freq=0,
        drainage_quality=0.9,
        urbanization_index=0.3,
        deforestation_index=0.1,
    )
    print(f"\nFlood probability: {risk2:.3f}")
    print(f"Road risk weight:  x{risk_probability_to_weight(risk2)}")
