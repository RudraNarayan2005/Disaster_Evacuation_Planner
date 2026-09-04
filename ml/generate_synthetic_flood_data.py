"""
Generates a synthetic flood-risk dataset when the real Kaggle CSV isn't
present yet. This is NOT random noise — each feature relationship is
based on real hydrology logic (e.g. low elevation + high rainfall +
close to a river = high flood probability), so the model trained on it
behaves sensibly even before you swap in the real dataset.

To use the REAL Kaggle dataset instead:
  1. Download it from kaggle.com/datasets/naiyakhalid/flood-prediction-dataset
  2. Save it as data/kaggle_flood_dataset.csv
  3. train_flood_model.py will detect it automatically and use it instead
     of calling this generator.

Run standalone to preview the generated data:
    python -m ml.generate_synthetic_flood_data
"""
import numpy as np
import pandas as pd

RNG = np.random.default_rng(42)  # fixed seed -> reproducible dataset


def generate_synthetic_flood_data(n_rows: int = 3000) -> pd.DataFrame:
    rainfall_mm = RNG.gamma(shape=2.0, scale=40, size=n_rows)          # skewed, mostly moderate, occasional heavy
    elevation_m = RNG.uniform(0, 200, size=n_rows)                      # Odisha coastal belt is mostly low-lying
    distance_from_river_km = RNG.exponential(scale=3.0, size=n_rows)    # many points cluster near rivers
    historical_flood_freq = RNG.poisson(lam=2.0, size=n_rows)           # floods-in-last-10-years, per location
    drainage_quality = RNG.uniform(0, 1, size=n_rows)                   # 0 = poor drainage, 1 = excellent
    urbanization_index = RNG.uniform(0, 1, size=n_rows)                 # 0 = rural, 1 = dense urban
    deforestation_index = RNG.uniform(0, 1, size=n_rows)                # 0 = forested, 1 = fully cleared

    # --- Domain-logic flood probability (this is the "ground truth" the model learns to approximate) ---
    risk_score = (
        0.35 * (rainfall_mm / rainfall_mm.max())
        + 0.20 * (1 - elevation_m / elevation_m.max())            # lower elevation -> higher risk
        + 0.15 * (1 - np.clip(distance_from_river_km, 0, 15) / 15)  # closer to river -> higher risk
        + 0.15 * (historical_flood_freq / historical_flood_freq.max())
        + 0.10 * (1 - drainage_quality)                            # poor drainage -> higher risk
        + 0.05 * deforestation_index
    )
    noise = RNG.normal(0, 0.05, size=n_rows)
    flood_probability = np.clip(risk_score + noise, 0, 1)

    df = pd.DataFrame({
        "rainfall_mm": rainfall_mm,
        "elevation_m": elevation_m,
        "distance_from_river_km": distance_from_river_km,
        "historical_flood_freq": historical_flood_freq,
        "drainage_quality": drainage_quality,
        "urbanization_index": urbanization_index,
        "deforestation_index": deforestation_index,
        "flood_probability": flood_probability,
    })

    # Also derive a 4-class label, matching your original spec
    # (Safe / Moderate / High / Flooded), in case you want classification
    # metrics alongside the regression output.
    df["flood_class"] = pd.cut(
        df["flood_probability"],
        bins=[-0.01, 0.25, 0.5, 0.75, 1.0],
        labels=["Safe", "Moderate", "High", "Flooded"],
    )

    return df


if __name__ == "__main__":
    data = generate_synthetic_flood_data()
    print(data.head(10))
    print("\nClass distribution:")
    print(data["flood_class"].value_counts())
    data.to_csv("data/synthetic_flood_data.csv", index=False)
    print("\nSaved to data/synthetic_flood_data.csv")
