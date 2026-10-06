"""Small, dependency-light feature drift report using PSI."""
from pathlib import Path
import numpy as np
import pandas as pd


def psi(expected: pd.Series, actual: pd.Series, bins=10) -> float:
    expected = pd.to_numeric(expected, errors="coerce").dropna()
    actual = pd.to_numeric(actual, errors="coerce").dropna()
    if expected.empty or actual.empty:
        return float("nan")
    edges = np.unique(np.quantile(expected, np.linspace(0, 1, bins + 1)))
    if len(edges) < 3:
        return 0.0
    e = np.histogram(expected, bins=edges)[0] / len(expected)
    a = np.histogram(actual, bins=edges)[0] / len(actual)
    e = np.clip(e, 1e-6, None)
    a = np.clip(a, 1e-6, None)
    return float(np.sum((a - e) * np.log(a / e)))


def compare(reference_path: str, current_path: str, output_path: str):
    ref = pd.read_csv(reference_path)
    cur = pd.read_csv(current_path)
    rows = []
    for col in ref.select_dtypes(include="number").columns:
        if col in cur:
            rows.append({"feature": col, "psi": psi(ref[col], cur[col])})
    out = pd.DataFrame(rows).sort_values("psi", ascending=False)
    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    out.to_csv(output_path, index=False)
    return out
