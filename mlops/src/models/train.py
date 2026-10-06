from pathlib import Path
import json
import joblib
import pandas as pd
from sklearn.metrics import classification_report, accuracy_score, f1_score, confusion_matrix
from sklearn.model_selection import train_test_split
from xgboost import XGBClassifier

TARGET = "target"
META = ["mission_id", "mission_time_s", TARGET, "fault_present"]


def main(data_path="mlops/data/processed/training.csv", model_dir="mlops/models", report_path="mlops/reports/metrics.json"):
    try:
        import mlflow
        mlflow_available = True
    except ImportError:
        mlflow_available = False
    df = pd.read_csv(data_path)
    mission_labels = df.groupby("mission_id")[TARGET].agg(lambda s: "nominal" if (s == "nominal").all() else s[s != "nominal"].iloc[0])
    train_missions, test_missions = train_test_split(
        mission_labels.index, test_size=0.2, random_state=42, stratify=mission_labels.values
    )
    train = df[df.mission_id.isin(train_missions)]
    test = df[df.mission_id.isin(test_missions)]
    X_train = train.drop(columns=META)
    X_test = test.drop(columns=META)
    y_train = train[TARGET]
    y_test = test[TARGET]
    classes = sorted(y_train.unique())
    mapping = {label: i for i, label in enumerate(classes)}
    inv = {i: label for label, i in mapping.items()}
    model = XGBClassifier(
        n_estimators=250, max_depth=6, learning_rate=0.08,
        subsample=0.85, colsample_bytree=0.85,
        objective="multi:softprob", num_class=len(classes),
        eval_metric="mlogloss", random_state=42, n_jobs=4,
    )
    if mlflow_available:
        mlflow.set_experiment("RocketTwin-Fault-Detection")
        run_ctx = mlflow.start_run(run_name="xgboost-baseline")
        mlflow.log_params({"n_estimators": 250, "max_depth": 6, "learning_rate": 0.08, "test_size": 0.2, "split_unit": "mission"})
    else:
        run_ctx = None
    model.fit(X_train, y_train.map(mapping))
    pred_num = model.predict(X_test).astype(int)
    pred = pd.Series([inv[int(x)] for x in pred_num], index=y_test.index)
    report = classification_report(y_test, pred, output_dict=True, zero_division=0)
    metrics = {
        "accuracy": accuracy_score(y_test, pred),
        "macro_f1": f1_score(y_test, pred, average="macro"),
        "weighted_f1": f1_score(y_test, pred, average="weighted"),
        "classification_report": report,
        "confusion_matrix": confusion_matrix(y_test, pred, labels=classes).tolist(),
        "classes": classes,
        "train_missions": len(train_missions),
        "test_missions": len(test_missions),
        "train_rows": len(train),
        "test_rows": len(test),
        "feature_columns": list(X_train.columns),
    }
    Path(model_dir).mkdir(parents=True, exist_ok=True)
    Path(report_path).parent.mkdir(parents=True, exist_ok=True)
    joblib.dump({"model": model, "mapping": mapping, "inv_mapping": inv, "features": list(X_train.columns)}, Path(model_dir) / "rockettwin_xgb.joblib")
    Path(report_path).write_text(json.dumps(metrics, indent=2))
    if mlflow_available:
        mlflow.log_metrics({"accuracy": metrics["accuracy"], "macro_f1": metrics["macro_f1"], "weighted_f1": metrics["weighted_f1"]})
        mlflow.log_artifact(str(report_path))
        mlflow.log_artifact(str(Path(model_dir) / "rockettwin_xgb.joblib"))
        mlflow.end_run()
    print(json.dumps({k: metrics[k] for k in ["accuracy", "macro_f1", "weighted_f1", "train_missions", "test_missions"]}, indent=2))


if __name__ == "__main__":
    main()
