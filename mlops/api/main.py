
from pathlib import Path
from threading import Lock

import joblib
import pandas as pd
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from mlops.src.features.streaming import StreamingFeatureCalculator

ROOT = Path(__file__).resolve().parents[2]
MODEL_PATH = ROOT / "mlops" / "models" / "rockettwin_xgb.joblib"

app = FastAPI(
    title="RocketTwin Health Inference API",
    version="0.2.0",
)

MODEL_BUNDLE = None
MODEL_LOCK = Lock()

# In-memory state: one independent calculator per mission.
MISSION_STATES = {}
STATE_LOCK = Lock()


class Telemetry(BaseModel):
    mission_time_s: float = Field(ge=0)
    mpre104p: float
    mrtd104t: float
    mpre105p: float
    mrtd105t: float
    mmsw203x: float
    mmsw205x: float
    mmsw301x: float
    flight_phase: str = "UNKNOWN"


def get_model_bundle():
    """Load the model once and reuse it for subsequent requests."""
    global MODEL_BUNDLE

    if not MODEL_PATH.exists():
        raise HTTPException(
            status_code=503,
            detail="Model not trained. Run the training pipeline first.",
        )

    if MODEL_BUNDLE is None:
        with MODEL_LOCK:
            if MODEL_BUNDLE is None:
                MODEL_BUNDLE = joblib.load(MODEL_PATH)

    return MODEL_BUNDLE


def classify_features(features: dict, bundle: dict) -> dict:
    """Run the trained classifier and format the existing API response."""
    X = pd.DataFrame([features]).reindex(
        columns=bundle["features"],
        fill_value=0.0,
    )

    pred_num = int(bundle["model"].predict(X)[0])
    label = bundle["inv_mapping"][pred_num]

    fault_present = label != "nominal"

    severity = (
        0
        if not fault_present
        else (
            3
            if label in {
                "vr01_stuck_closed",
                "vr06_stuck_closed",
                "pv02_stuck_closed",
                "pv03_stuck_closed",
            }
            else 2
        )
    )

    subsystem = (
        "none"
        if not fault_present
        else ("lox" if label.startswith(("vr01", "pv03")) else "rp1")
    )

    return {
        "fault_present": fault_present,
        "fault": label,
        "subsystem": subsystem,
        "severity": severity,
    }


def make_features(payload: Telemetry) -> dict:
    """Build features for a single, stateless reading."""
    calculator = StreamingFeatureCalculator()
    return calculator.update(payload.model_dump())


@app.get("/health")
def health():
    return {
        "status": "ok",
        "model_available": MODEL_PATH.exists(),
        "model_loaded": MODEL_BUNDLE is not None,
    }


@app.post("/predict")
def predict(payload: Telemetry):
    """
    Backwards-compatible stateless prediction.

    This endpoint has no previous telemetry context. Use the mission
    endpoint for sequential inference with rolling temporal features.
    """
    bundle = get_model_bundle()
    features = make_features(payload)
    return classify_features(features, bundle)


@app.post("/missions/{mission_id}/predict")
def predict_stream(mission_id: str, payload: Telemetry):
    """Process one reading using only current and previous mission readings."""
    bundle = get_model_bundle()

    with STATE_LOCK:
        state = MISSION_STATES.get(mission_id)

        if state is None:
            state = {
                "calculator": StreamingFeatureCalculator(),
                "last_time": None,
                "readings_processed": 0,
            }

        last_time = state["last_time"]

        if last_time is not None and payload.mission_time_s <= last_time:
            raise HTTPException(
                status_code=409,
                detail=(
                    "mission_time_s must be strictly greater than the "
                    f"previous reading ({last_time}). Reset the mission "
                    "if you intend to start a new sequence."
                ),
            )

        # Work on a copy so failed predictions do not advance stored history.
        import copy
        candidate = copy.deepcopy(state["calculator"])

        features = candidate.update(payload.model_dump())
        prediction = classify_features(features, bundle)

        state["calculator"] = candidate
        state["last_time"] = payload.mission_time_s
        state["readings_processed"] += 1
        MISSION_STATES[mission_id] = state

        return {
            **prediction,
            "mission_id": mission_id,
            "mission_time_s": payload.mission_time_s,
            "readings_processed": state["readings_processed"],
            "mode": "streaming",
        }


@app.post("/missions/{mission_id}/reset")
def reset_mission(mission_id: str):
    """Clear rolling history for a mission."""
    with STATE_LOCK:
        existed = MISSION_STATES.pop(mission_id, None) is not None

    return {
        "mission_id": mission_id,
        "reset": True,
        "previous_state_existed": existed,
    }
