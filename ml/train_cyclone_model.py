"""
Trains the Cyclone Risk Prediction model.

Automatically uses a REAL dataset if present at
data/real_cyclone_dataset.csv, otherwise falls back to the synthetic
domain-logic dataset (ml/generate_synthetic_cyclone_data.py) so you're
never blocked waiting on a manual download — same pattern as
train_flood_model.py.

Trains both Random Forest and XGBoost, compares them on held-out test
data, and saves the better-performing model to ml/cyclone_risk_model.pkl.
This is the file app/startup.py imports when the .pkl is missing
(e.g. on a fresh Render deploy, since .pkl files are gitignored).

Run from the project root:
    python -m ml.train_cyclone_model
"""
import os
import pickle

import numpy as np
import pandas as pd
from sklearn.ensemble import RandomForestRegressor
from sklearn.metrics import mean_absolute_error, r2_score
from sklearn.model_selection import train_test_split
from xgboost import XGBRegressor

from ml.generate_synthetic_cyclone_data import generate_synthetic_cyclone_data

REAL_CSV_PATH = os.path.join("data", "real_cyclone_dataset.csv")
MODEL_OUTPUT_PATH = os.path.join("ml", "cyclone_risk_model.pkl")

FEATURE_COLUMNS = [
    "wind_speed_kmph",
    "pressure_hpa",
    "distance_from_coast_km",
    "storm_surge_exposure",
    "historical_cyclone_freq",
    "mangrove_cover_index",
    "building_density_index",
]
TARGET_COLUMN = "cyclone_probability"


def load_training_data() -> pd.DataFrame:
    if os.path.exists(REAL_CSV_PATH):
        print(f"Found real dataset at {REAL_CSV_PATH} — using it.")
        df = pd.read_csv(REAL_CSV_PATH)
        # NOTE: if the real CSV's column names differ from FEATURE_COLUMNS,
        # rename them here to match, e.g.:
        # df = df.rename(columns={"WindSpeed": "wind_speed_kmph", ...})
        missing = [c for c in FEATURE_COLUMNS + [TARGET_COLUMN] if c not in df.columns]
        if missing:
            raise ValueError(
                f"Real dataset is missing expected columns {missing}. "
                f"Open the CSV, check its actual column names, and add a "
                f".rename(columns={{...}}) mapping in load_training_data()."
            )
        return df
    else:
        print("No real cyclone dataset found — generating synthetic training data instead.")
        return generate_synthetic_cyclone_data(n_rows=3000)


def train_and_compare():
    df = load_training_data()
    X = df[FEATURE_COLUMNS]
    y = df[TARGET_COLUMN]

    X_train, X_test, y_train, y_test = train_test_split(
        X, y, test_size=0.2, random_state=42
    )

    # --- Random Forest ---
    rf = RandomForestRegressor(n_estimators=200, max_depth=10, random_state=42)
    rf.fit(X_train, y_train)
    rf_pred = rf.predict(X_test)
    rf_mae = mean_absolute_error(y_test, rf_pred)
    rf_r2 = r2_score(y_test, rf_pred)

    # --- XGBoost ---
    xgb = XGBRegressor(n_estimators=200, max_depth=6, learning_rate=0.1, random_state=42)
    xgb.fit(X_train, y_train)
    xgb_pred = xgb.predict(X_test)
    xgb_mae = mean_absolute_error(y_test, xgb_pred)
    xgb_r2 = r2_score(y_test, xgb_pred)

    print("\n--- Model comparison ---")
    print(f"Random Forest -> MAE: {rf_mae:.4f}  R²: {rf_r2:.4f}")
    print(f"XGBoost       -> MAE: {xgb_mae:.4f}  R²: {xgb_r2:.4f}")

    # Pick the better model by R² (higher = better fit)
    if xgb_r2 >= rf_r2:
        best_model, best_name = xgb, "XGBoost"
    else:
        best_model, best_name = rf, "Random Forest"

    print(f"\nBest model: {best_name} — saving to {MODEL_OUTPUT_PATH}")

    with open(MODEL_OUTPUT_PATH, "wb") as f:
        pickle.dump({
            "model": best_model,
            "model_name": best_name,
            "feature_columns": FEATURE_COLUMNS,
        }, f)

    # Feature importance — useful for your report ("what drives cyclone risk")
    importances = best_model.feature_importances_
    print("\nFeature importance:")
    for name, imp in sorted(zip(FEATURE_COLUMNS, importances), key=lambda x: -x[1]):
        print(f"  {name}: {imp:.3f}")

    return best_model, best_name


if __name__ == "__main__":
    train_and_compare()
