from __future__ import annotations

import argparse
import csv
import gzip
import json
import random
import sys
import time
from collections import Counter
from pathlib import Path
from typing import Any, TextIO

import joblib
import pandas as pd
from imblearn.over_sampling import SMOTE
from imblearn.pipeline import Pipeline
from sklearn.ensemble import ExtraTreesClassifier, HistGradientBoostingClassifier, RandomForestClassifier
from sklearn.feature_extraction import DictVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import (
    accuracy_score,
    average_precision_score,
    classification_report,
    f1_score,
    precision_recall_curve,
    precision_score,
    recall_score,
    roc_auc_score,
)
from sklearn.model_selection import train_test_split
from sklearn.preprocessing import RobustScaler


ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from fraud_lab.modeling import FeatureSchema, utc_now  # noqa: E402
from fraud_lab.simulator import generate_transaction  # noqa: E402


RF_PORTED_PARAMS = {
    "n_estimators": 495,
    "max_depth": 9,
    "min_samples_split": 5,
    "min_samples_leaf": 6,
    "criterion": "entropy",
    "n_jobs": -1,
    "random_state": 42,
    "class_weight": "balanced_subsample",
}

XGB_PORTED_PARAMS = {
    "n_estimators": 455,
    "max_depth": 9,
    "learning_rate": 0.08903150630423762,
    "subsample": 0.7754599867108974,
    "colsample_bytree": 0.5996549945015783,
    "scale_pos_weight": 3.4735511118988494,
    "random_state": 42,
    "eval_metric": "logloss",
}

DEFAULT_CANDIDATES = ["random_forest", "extra_trees", "hist_gradient_boosting", "logistic_regression"]


def build_synthetic_dataset(rows: int, fraud_rate: float, seed: int) -> pd.DataFrame:
    rng = random.Random(seed)
    rows = max(200, rows)
    remaining_fraud = max(1, min(rows - 1, round(rows * fraud_rate)))
    records: list[dict[str, Any]] = []

    for index in range(rows):
        remaining_rows = rows - index
        fraud = rng.random() < (remaining_fraud / remaining_rows)
        if fraud:
            remaining_fraud -= 1
        payload, label = generate_transaction(rng, fraud=fraud)
        record = dict(payload)
        record["is_fraud"] = label
        records.append(record)

    frame = pd.DataFrame(records)
    return frame.sample(frac=1.0, random_state=seed).reset_index(drop=True)


def payloads_from_frame(frame: pd.DataFrame, schema: FeatureSchema) -> list[dict[str, Any]]:
    payload_columns = [
        field["name"]
        for field in schema.fields
        if field.get("role") != "target" and field["name"] in frame.columns
    ]
    return frame[payload_columns].to_dict(orient="records")


def features_from_payloads(payloads: list[dict[str, Any]], schema: FeatureSchema) -> list[dict[str, Any]]:
    return [schema.feature_dict(payload) for payload in payloads]


def open_dataset_file(path: Path) -> TextIO:
    if path.suffix == ".gz":
        return gzip.open(path, "rt", newline="", encoding="utf-8")
    return path.open("r", newline="", encoding="utf-8")


def dataset_paths(input_dir: Path | None, input_csv: Path | None) -> list[Path]:
    if input_csv:
        return [input_csv]
    if input_dir:
        paths = [path for path in sorted(input_dir.glob("part-*.csv.gz")) if path.is_file()]
        paths.extend(path for path in sorted(input_dir.glob("part-*.csv")) if path.is_file())
        if paths:
            return paths
    return []


def load_sampled_frame(
    *,
    paths: list[Path],
    sample_rows: int,
    max_scan_rows: int,
    seed: int,
    target: str,
) -> pd.DataFrame:
    rng = random.Random(seed)
    sample_rows = max(1, sample_rows)
    max_scan_rows = max(sample_rows, max_scan_rows)
    reservoir: list[dict[str, Any]] = []
    seen = 0

    for path in paths:
        with open_dataset_file(path) as handle:
            reader = csv.DictReader(handle)
            for row in reader:
                seen += 1
                if len(reservoir) < sample_rows:
                    reservoir.append(row)
                else:
                    index = rng.randint(1, seen)
                    if index <= sample_rows:
                        reservoir[index - 1] = row
                if seen >= max_scan_rows:
                    break
        if seen >= max_scan_rows:
            break

    if len(reservoir) < sample_rows:
        raise RuntimeError(f"only sampled {len(reservoir)} rows from input dataset")

    frame = pd.DataFrame(reservoir)
    frame[target] = frame[target].astype(int)
    return frame.sample(frac=1.0, random_state=seed).reset_index(drop=True)


def dataset_columns(schema: FeatureSchema) -> list[str]:
    payload_columns = [
        field["name"]
        for field in schema.fields
        if field.get("role") != "target"
    ]
    return payload_columns + [schema.target]


def open_shard(path: Path, compress: bool) -> TextIO:
    path.parent.mkdir(parents=True, exist_ok=True)
    if compress:
        return gzip.open(path, "wt", newline="", encoding="utf-8")
    return path.open("w", newline="", encoding="utf-8")


def stream_synthetic_dataset(
    *,
    rows: int,
    fraud_rate: float,
    seed: int,
    schema: FeatureSchema,
    shard_dir: Path,
    shard_rows: int,
    compress: bool,
    progress_every: int,
) -> dict[str, Any]:
    rng = random.Random(seed)
    rows = max(1, rows)
    shard_rows = max(1, shard_rows)
    progress_every = max(1, progress_every)
    remaining_fraud = max(0, min(rows, round(rows * fraud_rate)))
    columns = dataset_columns(schema)
    suffix = ".csv.gz" if compress else ".csv"
    started = time.time()
    class_balance = Counter()
    shard_paths: list[str] = []
    current_file: TextIO | None = None
    writer: csv.writer | None = None

    shard_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = shard_dir / "manifest.json"

    try:
        for index in range(rows):
            if index % shard_rows == 0:
                if current_file:
                    current_file.close()
                shard_index = index // shard_rows
                shard_path = shard_dir / f"part-{shard_index:05d}{suffix}"
                shard_paths.append(str(shard_path))
                current_file = open_shard(shard_path, compress)
                writer = csv.writer(current_file)
                writer.writerow(columns)

            remaining_rows = rows - index
            fraud = rng.random() < (remaining_fraud / remaining_rows) if remaining_rows else False
            if fraud:
                remaining_fraud -= 1
            payload, label = generate_transaction(rng, fraud=fraud)
            class_balance[label] += 1
            assert writer is not None
            writer.writerow([payload.get(column, label if column == schema.target else "") for column in columns])

            written = index + 1
            if written % progress_every == 0:
                elapsed = max(time.time() - started, 0.001)
                print(
                    json.dumps(
                        {
                            "event": "progress",
                            "rows": written,
                            "rows_per_second": round(written / elapsed, 2),
                            "shards": len(shard_paths),
                            "elapsed_seconds": round(elapsed, 2),
                        },
                        ensure_ascii=False,
                    ),
                    file=sys.stderr,
                    flush=True,
                )
    finally:
        if current_file:
            current_file.close()

    total_bytes = sum(Path(path).stat().st_size for path in shard_paths)
    elapsed = time.time() - started
    manifest = {
        "schema_id": schema.schema_id,
        "target": schema.target,
        "rows": rows,
        "class_balance": {str(key): int(value) for key, value in sorted(class_balance.items())},
        "fraud_rate": fraud_rate,
        "seed": seed,
        "shard_rows": shard_rows,
        "compression": "gzip" if compress else "none",
        "columns": columns,
        "shard_count": len(shard_paths),
        "total_bytes": total_bytes,
        "elapsed_seconds": round(elapsed, 2),
        "rows_per_second": round(rows / max(elapsed, 0.001), 2),
        "label_policy": "Labels exist only in this offline training dataset; operational stream data remains unlabeled.",
        "created_at": utc_now(),
        "shards": shard_paths,
    }
    manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
    manifest["manifest_path"] = str(manifest_path)
    return manifest


def make_pipeline(model_name: str, y_train: list[int]) -> Pipeline:
    counts = Counter(y_train)
    min_class = min(counts.values())
    steps: list[tuple[str, Any]] = [
        ("features", DictVectorizer(sparse=False)),
        ("scale", RobustScaler()),
    ]
    if min_class >= 6:
        steps.append(("sampler", SMOTE(random_state=42, k_neighbors=min(5, min_class - 1))))

    if model_name == "xgboost":
        try:
            from xgboost import XGBClassifier
        except ImportError as exc:  # pragma: no cover - optional dependency.
            raise RuntimeError("xgboost is not installed; omit --include-xgboost or install xgboost") from exc
        model = XGBClassifier(**XGB_PORTED_PARAMS)
    elif model_name == "extra_trees":
        model = ExtraTreesClassifier(
            n_estimators=520,
            max_depth=None,
            min_samples_split=4,
            min_samples_leaf=2,
            class_weight="balanced",
            n_jobs=-1,
            random_state=42,
        )
    elif model_name == "hist_gradient_boosting":
        model = HistGradientBoostingClassifier(
            max_iter=360,
            learning_rate=0.045,
            max_leaf_nodes=31,
            l2_regularization=0.025,
            random_state=42,
            class_weight="balanced",
        )
    elif model_name == "logistic_regression":
        model = LogisticRegression(
            max_iter=1500,
            class_weight="balanced",
            solver="lbfgs",
            random_state=42,
        )
    else:
        model = RandomForestClassifier(**RF_PORTED_PARAMS)

    steps.append(("model", model))
    return Pipeline(steps)


def evaluate_model(pipeline: Pipeline, x_test: list[dict[str, Any]], y_test: list[int]) -> dict[str, Any]:
    probabilities = pipeline.predict_proba(x_test)[:, list(pipeline.named_steps["model"].classes_).index(1)]
    precision_curve, recall_curve, thresholds = precision_recall_curve(y_test, probabilities)
    if len(thresholds):
        f1_curve = (2 * precision_curve[:-1] * recall_curve[:-1]) / (
            precision_curve[:-1] + recall_curve[:-1] + 1e-12
        )
        best_index = int(f1_curve.argmax())
        threshold = float(thresholds[best_index])
    else:
        threshold = 0.5
    predictions = [int(value >= threshold) for value in probabilities]
    return {
        "accuracy": round(float(accuracy_score(y_test, predictions)), 4),
        "precision": round(float(precision_score(y_test, predictions, zero_division=0)), 4),
        "recall": round(float(recall_score(y_test, predictions, zero_division=0)), 4),
        "f1": round(float(f1_score(y_test, predictions, zero_division=0)), 4),
        "roc_auc": round(float(roc_auc_score(y_test, probabilities)), 4),
        "average_precision": round(float(average_precision_score(y_test, probabilities)), 4),
        "decision_threshold": round(threshold, 6),
        "classification_report": classification_report(
            y_test,
            predictions,
            output_dict=True,
            zero_division=0,
        ),
    }


def top_features(pipeline: Pipeline, limit: int = 16) -> list[dict[str, Any]]:
    model = pipeline.named_steps["model"]
    if not hasattr(model, "feature_importances_"):
        return []
    feature_names = pipeline.named_steps["features"].get_feature_names_out()
    ranked = sorted(
        zip(feature_names, model.feature_importances_, strict=False),
        key=lambda item: float(item[1]),
        reverse=True,
    )
    return [
        {"feature": str(name), "importance": round(float(value), 6)}
        for name, value in ranked[:limit]
    ]


def train_ported_model(
    frame: pd.DataFrame,
    schema: FeatureSchema,
    include_xgboost: bool,
    seed: int,
    candidate_names: list[str] | None = None,
) -> tuple[str, Pipeline, dict[str, Any], list[dict[str, Any]]]:
    payloads = payloads_from_frame(frame, schema)
    x = features_from_payloads(payloads, schema)
    y = [int(value) for value in frame[schema.target].tolist()]
    x_train, x_test, y_train, y_test = train_test_split(
        x,
        y,
        test_size=0.25,
        random_state=seed,
        stratify=y,
    )

    candidate_names = list(candidate_names or DEFAULT_CANDIDATES)
    if include_xgboost:
        candidate_names.append("xgboost")

    results: dict[str, dict[str, Any]] = {}
    pipelines: dict[str, Pipeline] = {}
    for name in candidate_names:
        pipeline = make_pipeline(name, y_train)
        pipeline.fit(x_train, y_train)
        metrics = evaluate_model(pipeline, x_test, y_test)
        metrics["train_rows"] = len(y_train)
        metrics["validation_rows"] = len(y_test)
        metrics["class_balance"] = dict(Counter(y))
        metrics["sampler"] = "smote" if "sampler" in pipeline.named_steps else "none"
        results[name] = metrics
        pipelines[name] = pipeline

    best_name = max(results, key=lambda name: (results[name]["average_precision"], results[name]["f1"]))
    best_pipeline = pipelines[best_name]
    best_pipeline.fit(x, y)
    metrics = {
        "selected_model": best_name,
        "candidates": results,
        "class_balance": dict(Counter(y)),
        "schema_id": schema.schema_id,
        "ported_from": "seonhak123/Credit-Card-Fraud-Detection",
        "sample_rows": len(frame),
    }
    return best_name, best_pipeline, metrics, top_features(best_pipeline)


def save_outputs(
    frame: pd.DataFrame,
    schema: FeatureSchema,
    pipeline: Pipeline,
    metrics: dict[str, Any],
    feature_importance: list[dict[str, Any]],
    dataset_path: Path,
    metrics_path: Path,
    artifact_path: Path,
) -> None:
    dataset_path.parent.mkdir(parents=True, exist_ok=True)
    metrics_path.parent.mkdir(parents=True, exist_ok=True)
    artifact_path.parent.mkdir(parents=True, exist_ok=True)

    frame.to_csv(dataset_path, index=False)
    metrics_path.write_text(
        json.dumps(metrics | {"top_features": feature_importance}, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    joblib.dump(
        {
            "pipeline": pipeline,
            "schema": schema.raw,
            "metadata": {
                "version": 0,
                "model_kind": f"ported_{metrics['selected_model']}",
                "schema_id": schema.schema_id,
                "created_at": utc_now(),
                "metrics": metrics,
                "feature_importance": feature_importance,
                "reason": "offline_synthetic_dataset_port",
                "source_model_repo": "https://github.com/seonhak123/Credit-Card-Fraud-Detection",
            },
        },
        artifact_path,
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Port the Credit-Card-Fraud-Detection training recipe to this lab's transaction schema."
    )
    parser.add_argument("--rows", type=int, default=5000)
    parser.add_argument("--fraud-rate", type=float, default=0.08)
    parser.add_argument("--seed", type=int, default=20260519)
    parser.add_argument("--input-csv", type=Path, default=None)
    parser.add_argument("--input-dir", type=Path, default=None)
    parser.add_argument(
        "--sample-rows",
        type=int,
        default=None,
        help="Rows to train from input data. Defaults to --rows.",
    )
    parser.add_argument(
        "--sample-scan-rows",
        type=int,
        default=1_000_000,
        help="Maximum rows to scan when reservoir-sampling from input shards.",
    )
    parser.add_argument(
        "--candidates",
        default=",".join(DEFAULT_CANDIDATES),
        help="Comma-separated sklearn candidate models to train and compare.",
    )
    parser.add_argument(
        "--generate-only",
        action="store_true",
        help="Only generate a synthetic training dataset. Uses streaming shards and does not train a model.",
    )
    parser.add_argument(
        "--shard-rows",
        type=int,
        default=1_000_000,
        help="Rows per output shard when --generate-only is used.",
    )
    parser.add_argument(
        "--shard-dir",
        type=Path,
        default=None,
        help="Directory for generated dataset shards. Defaults to data/generated/synthetic_financial_transactions_<rows>.",
    )
    parser.add_argument(
        "--no-compress",
        action="store_true",
        help="Write plain CSV shards instead of csv.gz shards.",
    )
    parser.add_argument(
        "--progress-every",
        type=int,
        default=1_000_000,
        help="Progress log interval for streaming generation.",
    )
    parser.add_argument(
        "--schema",
        type=Path,
        default=ROOT_DIR / "configs" / "schemas" / "kaggle_fraud_transactions.json",
    )
    parser.add_argument("--output-dir", type=Path, default=ROOT_DIR / "data" / "generated")
    parser.add_argument(
        "--artifact-path",
        type=Path,
        default=ROOT_DIR / "data" / "models" / "ported_transaction_fraud_model.joblib",
    )
    parser.add_argument("--include-xgboost", action="store_true")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    schema = FeatureSchema.load(args.schema)
    if args.generate_only:
        shard_dir = args.shard_dir or args.output_dir / f"synthetic_financial_transactions_{args.rows}"
        manifest = stream_synthetic_dataset(
            rows=args.rows,
            fraud_rate=args.fraud_rate,
            seed=args.seed,
            schema=schema,
            shard_dir=shard_dir,
            shard_rows=args.shard_rows,
            compress=not args.no_compress,
            progress_every=args.progress_every,
        )
        print(
            json.dumps(
                {
                    "rows": manifest["rows"],
                    "class_balance": manifest["class_balance"],
                    "shard_count": manifest["shard_count"],
                    "total_bytes": manifest["total_bytes"],
                    "elapsed_seconds": manifest["elapsed_seconds"],
                    "rows_per_second": manifest["rows_per_second"],
                    "manifest_path": manifest["manifest_path"],
                },
                indent=2,
                ensure_ascii=False,
            )
        )
        return

    paths = dataset_paths(args.input_dir, args.input_csv)
    if paths:
        frame = load_sampled_frame(
            paths=paths,
            sample_rows=args.sample_rows or args.rows,
            max_scan_rows=args.sample_scan_rows,
            seed=args.seed,
            target=schema.target,
        )
        dataset_source = {
            "mode": "sampled_input_dataset",
            "input_dir": str(args.input_dir) if args.input_dir else None,
            "input_csv": str(args.input_csv) if args.input_csv else None,
            "input_files_seen": len(paths),
            "sample_scan_rows": args.sample_scan_rows,
        }
    else:
        frame = build_synthetic_dataset(args.rows, args.fraud_rate, args.seed)
        dataset_source = {"mode": "fresh_synthetic_generation"}
    candidates = [item.strip() for item in args.candidates.split(",") if item.strip()]
    selected, pipeline, metrics, feature_importance = train_ported_model(
        frame,
        schema,
        include_xgboost=args.include_xgboost,
        seed=args.seed,
        candidate_names=candidates,
    )
    metrics["dataset_source"] = dataset_source
    dataset_path = args.output_dir / "synthetic_financial_transactions.csv"
    metrics_path = args.output_dir / "transaction_fraud_model_metrics.json"
    save_outputs(
        frame,
        schema,
        pipeline,
        metrics,
        feature_importance,
        dataset_path,
        metrics_path,
        args.artifact_path,
    )
    selected_metrics = metrics["candidates"][selected]
    print(
        json.dumps(
            {
                "selected_model": selected,
                "rows": len(frame),
                "class_balance": metrics["class_balance"],
                "dataset_path": str(dataset_path),
                "metrics_path": str(metrics_path),
                "artifact_path": str(args.artifact_path),
                "average_precision": selected_metrics["average_precision"],
                "precision": selected_metrics["precision"],
                "recall": selected_metrics["recall"],
                "f1": selected_metrics["f1"],
                "roc_auc": selected_metrics["roc_auc"],
                "top_features": feature_importance[:8],
            },
            indent=2,
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
