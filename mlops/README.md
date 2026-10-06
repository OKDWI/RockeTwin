# RocketTwin MLOps Pipeline

MLOps layer for the RocketTwin digital-twin project. It follows the project presentation: data validation, versioned/reproducible dataset construction, ML training, experiment tracking, API serving, containerization and monitoring foundations.

## 1. Install

From the project root:

```bash
pip install -r requirements-mlops.txt
```

## 2. Validate the telemetry

```bash
python -m mlops.src.data.validate --dataset dataset
```

## 3. Build the ML dataset

```bash
python -m mlops.src.features.build_dataset --dataset dataset --output mlops/data/processed/training.csv
```

This creates row-level labels from the event onset time. The simulator's valve-state columns are intentionally excluded from features because they directly expose injected faults and would cause target leakage.

## 4. Train

```bash
python -m mlops.src.models.train
```

Outputs:

- `mlops/models/rockettwin_xgb.joblib`
- `mlops/reports/metrics.json`
- MLflow run data when MLflow is installed

The split is **mission-level**, so telemetry from a mission cannot appear in both train and test sets.

## 5. Serve

```bash
uvicorn mlops.api.main:app --reload
```

Open `http://127.0.0.1:8000/docs` for Swagger UI.

## 6. Docker

From the project root:

```bash
docker build -t rockettwin-mlops .
docker run --rm -p 8000:8000 rockettwin-mlops
```

## MLOps stages still to complete

- DVC remote/data versioning
- MLflow model registry
- Automated drift/performance monitoring
- CI/CD
- AWS SageMaker deployment
