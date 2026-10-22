from pathlib import Path

import pandas as pd
from pandas.testing import assert_frame_equal

from mlops.src.features.build_dataset import add_features
from mlops.src.features.streaming import (
    StreamingFeatureCalculator,
    SENSOR_COLUMNS,
    FLIGHT_PHASES,
    WINDOWS,
)

DATASET_DIR = Path("dataset")
MISSION_LIMIT = None  # Start small; expand to all missions after this passes.


def expected_feature_columns():
    columns = list(SENSOR_COLUMNS)

    for col in SENSOR_COLUMNS:
        columns.append(f"{col}_diff")
        for window in WINDOWS:
            columns.append(f"{col}_roll_mean_{window}")
            columns.append(f"{col}_roll_std_{window}")

    columns.extend(f"phase_{phase}" for phase in FLIGHT_PHASES)
    return columns


def main():
    paths = sorted(
        (DATASET_DIR / "telemetry").glob("mission_*.csv")
    )

    if MISSION_LIMIT is not None:
        paths = paths[:MISSION_LIMIT]

    if not paths:
        raise FileNotFoundError(
            f"No mission CSV files found under {DATASET_DIR / 'telemetry'}"
        )

    feature_columns = expected_feature_columns()
    calculator = StreamingFeatureCalculator()
    checked_rows = 0

    for path in paths:
        raw = pd.read_csv(path).sort_values("mission_time_s")
        raw["mission_id"] = path.stem

        # Batch reference: the existing implementation.
        batch = add_features(raw.copy())
        expected = batch[feature_columns].reset_index(drop=True)

        # Streaming implementation: one reading at a time.
        calculator.reset()
        streamed = pd.DataFrame([
            calculator.update(row)
            for row in raw.to_dict(orient="records")
        ])[feature_columns]

        assert_frame_equal(
            expected,
            streamed,
            check_dtype=False,
            check_exact=False,
            rtol=1e-7,
            atol=1e-8,
        )

        checked_rows += len(raw)
        print(f"PASS {path.stem}: {len(raw):,} rows")

    print(
        f"\nStreaming parity passed: {checked_rows:,} rows, "
        f"{len(feature_columns)} features, {len(paths)} missions."
    )


if __name__ == "__main__":
    main()
