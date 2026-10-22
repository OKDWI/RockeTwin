# RocketTwin Mission Control — React prototype

A dark aerospace-style React + Vite + TypeScript dashboard for replaying the project's existing synthetic mission telemetry through the existing FastAPI/XGBoost streaming inference API.

## What it includes

- Load multiple recorded telemetry CSVs in the browser (the original dataset files are not copied into this frontend).
- Sequential replay with pause/resume, reset, and selectable replay intervals.
- Posts one telemetry sample at a time to `POST /missions/{mission_id}/predict`; it waits for each API response before advancing so the server-side rolling feature state remains ordered.
- Live pressure/temperature or switch-signal plots, sensor snapshots, CSV valve-state snapshot, mission progress, classifier output, severity/subsystem labels, and event log.
- Optional `manifest.csv` upload for ground-truth fault label and onset reference. The manifest is used only for display/visual evaluation; its labels are never sent to the model.
- API/model availability indicators and visible errors when backend calls fail.
- Vite development proxy from `/api/*` to `http://127.0.0.1:8000/*`, avoiding the need to alter the existing API or enable CORS for local development.

## Requirements

- Node.js 20.19+ or 22.12+ recommended (current Vite releases require a modern Node version).
- The RocketTwin Python environment, trained model artifact at `mlops/models/rockettwin_xgb.joblib`, and existing FastAPI code.

## Run it

Open two PowerShell terminals at the RocketTwin project root (`rocketwin_work`). Keep the frontend folder at `rocketwin_work/rockettwin-dashboard`.

### Terminal 1 — Existing backend

```powershell
.venv\Scripts\Activate.ps1
uvicorn mlops.api.main:app --reload
```

Check `http://127.0.0.1:8000/health`.

### Terminal 2 — Frontend

```powershell
cd rockettwin-dashboard
npm install
npm run dev
```

Open the local URL printed by Vite (normally `http://127.0.0.1:5173`).

## Load data

1. Click **Load mission** and select one or more CSVs from the project's `dataset/telemetry/` directory, such as `mission_0002.csv`.
2. Optionally click **Manifest** and select `dataset/manifest.csv` to show the known class and onset reference.
3. Ensure the left sidebar reports that the inference API is connected and the model artifact is available.
4. Select a mission and press **Start replay**. Samples are sent in timestamp order. Use Pause/Resume or Reset as needed.

The CSV parser checks required telemetry columns and rejects duplicate/non-increasing timestamps. Valve state columns are shown from the source CSV but are not sent to the model. The frontend sends only `mission_time_s`, the seven numeric sensor channels, and `flight_phase`.

## Existing backend contract used

- `GET /health`
- `POST /missions/{mission_id}/predict`
- `POST /missions/{mission_id}/reset`

The frontend uses the exact seven model sensor columns present in the existing `Telemetry` Pydantic model and supplies `flight_phase` (or `UNKNOWN` when absent). It does not change model loading, feature engineering, training, or API routes.

## Notes / known prototype boundaries

- This is recorded synthetic mission replay, not live rocket telemetry or a live simulator feed.
- Each mission has in-memory streaming state on the backend. Reset before replaying the same mission from its beginning. Restarting the API clears server state.
- The UI displays the backend's existing severity heuristic; it is not a calibrated probability or certified flight-safety decision.
- Ground-truth onset is an optional reference from `manifest.csv`; it is not part of inference input.
- Vite's proxy is configured for local development. If deploying the frontend separately, configure the API base URL and production CORS/reverse proxy deliberately.
