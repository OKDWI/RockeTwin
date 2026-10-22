from collections import deque
from math import sqrt
import pandas as pd

SENSOR_COLUMNS = [
    "mpre104p",
    "mrtd104t",
    "mpre105p",
    "mrtd105t",
    "mmsw203x",
    "mmsw205x",
    "mmsw301x",
]

WINDOWS = [3, 10, 30]

FLIGHT_PHASES = [
    "ASCENT",
    "FREE_FLIGHT",
    "LOCKUP",
    "LOX_CHILLDOWN_BLEED",
    "LOX_CONDITIONING",
    "PRESSURIZATION",
    "RP1_BLEED",
]


class StreamingFeatureCalculator:
    """Calculate batch-compatible features from one telemetry row at a time."""

    def __init__(self):
        self.previous = {}
        self.history = {
            col: deque(maxlen=max(WINDOWS))
            for col in SENSOR_COLUMNS
        }

    def reset(self):
        """Reset state before processing a new mission."""
        self.previous.clear()
        for values in self.history.values():
            values.clear()

    def update(self, telemetry: dict) -> dict:
        """Return the 63 model features for the current telemetry row."""
        features = {}

        # Raw sensor values
        for col in SENSOR_COLUMNS:
            features[col] = float(telemetry[col])

        # Differences and rolling statistics use only past/current readings.
        for col in SENSOR_COLUMNS:
            value = float(telemetry[col])
            history = self.history[col]

            features[f"{col}_diff"] = (
                value - self.previous[col]
                if col in self.previous
                else 0.0
            )

            history.append(value)

            for window in WINDOWS:
                values = list(history)[-window:]
                features[f"{col}_roll_mean_{window}"] = (
                    sum(values) / len(values)
                )

                # Match pandas rolling().std(): sample standard deviation,
                # with ddof=1. A single observation produces 0 after fillna.
                if len(values) < 2:
                    std = 0.0
                else:
                    mean = sum(values) / len(values)
                    variance = sum(
                        (x - mean) ** 2 for x in values
                    ) / (len(values) - 1)
                    std = sqrt(max(variance, 0.0))

                features[f"{col}_roll_std_{window}"] = std

            self.previous[col] = value

        # Match pd.get_dummies(..., prefix="phase", dtype=float).
        phase = telemetry["flight_phase"]
        for name in FLIGHT_PHASES:
            features[f"phase_{name}"] = float(phase == name)

        return features
