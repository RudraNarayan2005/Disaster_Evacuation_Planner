"""
Generates a synthetic cyclone-risk dataset when a real historical cyclone
dataset isn't present yet. Like the flood generator, this is NOT random
noise — each feature relationship is based on real cyclone-impact logic
(e.g. high wind speed + low central pressure + close to coast + high
storm surge exposure = high cyclone risk; mangrove cover reduces it),
so the model trained on it behaves sensibly even before you swap in a
real IMD/NOAA historical dataset.

To use a REAL dataset instead:
  1. Get historical cyclone track/impact data (e.g. IMD best-track data,
     or a Kaggle cyclone dataset).
  2. Save it as data/real_cyclone_dataset.csv with columns matching
     FEATURE_COLUMNS + cyclone_probability (or add a rename mapping in
     train_cyclone_model.py's load_training_data(), same pattern as
     the flood model).

Run standalone to preview the generated data:
    python -m ml.generate_synthetic_cyclone_data
"""
import numpy as np
import pandas as pd

RNG = np.random.default_rng(42)  # fixed seed -> reproducible dataset


def generate_synthetic_cyclone_data(n_rows: int = 3000) -> pd.DataFrame:
    # Wind speed at the location, km/h. Most readings are calm/background
    # wind; occasional rows simulate an active cyclone system nearby.
    wind_speed_kmph = RNG.gamma(shape=2.0, scale=25, size=n_rows)

    # Central/local pressure, hPa. Normal ~1013 hPa; deep cyclones drop
    # well below 950 hPa. Correlate loosely with wind speed like real storms
    # (higher wind -> lower pressure), plus noise.
    pressure_hpa = 1013 - (wind_speed_kmph / 250) * 100 + RNG.normal(0, 8, size=n_rows)
    pressure_hpa = np.clip(pressure_hpa, 890, 1015)

    distance_from_coast_km = RNG.exponential(scale=15.0, size=n_rows)     # coastal Odisha: many points close to shore
    storm_surge_exposure = RNG.uniform(0, 1, size=n_rows)                  # 0 = sheltered/high ground, 1 = fully exposed low coast
    historical_cyclone_freq = RNG.poisson(lam=1.5, size=n_rows)            # landfalling cyclones affecting this area in last 10 years
    mangrove_cover_index = RNG.uniform(0, 1, size=n_rows)                  # 0 = none, 1 = dense mangrove buffer (protective)
    building_density_index = RNG.uniform(0, 1, size=n_rows)                # 0 = open/rural, 1 = dense construction (higher damage exposure)

    # --- Domain-logic cyclone risk (the "ground truth" the model learns to approximate) ---
    risk_score = (
        0.30 * (wind_speed_kmph / wind_speed_kmph.max())
        + 0.20 * (1 - (pressure_hpa - 890) / (1015 - 890))         # lower pressure -> higher risk
        + 0.20 * (1 - np.clip(distance_from_coast_km, 0, 60) / 60)  # closer to coast -> higher risk
        + 0.15 * storm_surge_exposure
        + 0.10 * (historical_cyclone_freq / max(historical_cyclone_freq.max(), 1))
        + 0.05 * building_density_index
        - 0.10 * mangrove_cover_index                                # protective factor -> lowers risk
    )
    noise = RNG.normal(0, 0.05, size=n_rows)
    cyclone_probability = np.clip(risk_score + noise, 0, 1)

    df = pd.DataFrame({
        "wind_speed_kmph": wind_speed_kmph,
        "pressure_hpa": pressure_hpa,
        "distance_from_coast_km": distance_from_coast_km,
        "storm_surge_exposure": storm_surge_exposure,
        "historical_cyclone_freq": historical_cyclone_freq,
        "mangrove_cover_index": mangrove_cover_index,
        "building_density_index": building_density_index,
        "cyclone_probability": cyclone_probability,
    })

    # Also derive a 4-class label, matching the flood model's convention
    # (Safe / Moderate / High / Severe)
    df["cyclone_class"] = pd.cut(
        df["cyclone_probability"],
        bins=[-0.01, 0.25, 0.5, 0.75, 1.0],
        labels=["Safe", "Moderate", "High", "Severe"],
    )

    return df


if __name__ == "__main__":
    data = generate_synthetic_cyclone_data()
    print(data.head(10))
    print("\nClass distribution:")
    print(data["cyclone_class"].value_counts())
    data.to_csv("data/synthetic_cyclone_data.csv", index=False)
    print("\nSaved to data/synthetic_cyclone_data.csv")
