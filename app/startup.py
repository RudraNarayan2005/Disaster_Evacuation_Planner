"""
Ensures trained ML models exist before the app starts serving requests.
On Render (fresh deploy), the .pkl files aren't in Git, so we train
them once here if missing. Locally, if you already have them, this
does nothing (fast).
"""
import os


def ensure_models_exist():
    flood_model_path = os.path.join("ml", "flood_risk_model.pkl")
    cyclone_model_path = os.path.join("ml", "cyclone_risk_model.pkl")

    if not os.path.exists(flood_model_path):
        print("Flood risk model not found — training now...")
        from ml.train_flood_model import train_and_compare
        train_and_compare()

    if not os.path.exists(cyclone_model_path):
        print("Cyclone risk model not found — training now...")
        from ml.train_cyclone_model import train_and_compare as train_cyclone_model
        train_cyclone_model()