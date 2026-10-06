from pathlib import Path
import joblib
import pandas as pd
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

ROOT = Path(__file__).resolve().parents[2]
MODEL_PATH = ROOT / "mlops" / "models" / "rockettwin_xgb.joblib"
app = FastAPI(title="RocketTwin Health Inference API", version="0.1.0")

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

@app.get("/health")
def health():
    return {"status": "ok", "model_loaded": MODEL_PATH.exists()}


def make_features(payload: Telemetry):
    d = payload.model_dump()
    phase = d.pop("flight_phase")
    row = pd.DataFrame([d])
    # Single-observation API uses zero for unavailable temporal derivatives/rolling stats.
    for col in ["mpre104p", "mrtd104t", "mpre105p", "mrtd105t", "mmsw203x", "mmsw205x", "mmsw301x"]:
        row[f"{col}_diff"] = 0.0
        row[f"{col}_roll_mean_3"] = row[col]
        row[f"{col}_roll_std_3"] = 0.0
    for phase_name in ["LOCKUP", "ASCENT", "LOX_CONDITIONING", "PRESSURIZATION", "RP1_BLEED", "LOX_CHILLDOWN_BLEED", "FREE_FLIGHT"]:
        row[f"phase_{phase_name}"] = float(phase == phase_name)
    return row

@app.post("/predict")
def predict(payload: Telemetry):
    if not MODEL_PATH.exists():
        raise HTTPException(503, "Model not trained. Run the training pipeline first.")
    bundle = joblib.load(MODEL_PATH)
    X = make_features(payload).reindex(columns=bundle["features"], fill_value=0.0)
    pred_num = int(bundle["model"].predict(X)[0])
    label = bundle["inv_mapping"][pred_num]
    fault_present = label != "nominal"
    severity = 0 if not fault_present else (3 if label in {"vr01_stuck_closed", "vr06_stuck_closed", "pv02_stuck_closed", "pv03_stuck_closed"} else 2)
    subsystem = "none" if not fault_present else ("lox" if label.startswith(("vr01", "pv03")) else "rp1")
    return {"fault_present": fault_present, "fault": label, "subsystem": subsystem, "severity": severity}
