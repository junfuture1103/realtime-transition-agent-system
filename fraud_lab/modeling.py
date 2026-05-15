from __future__ import annotations

import json
import math
from collections import Counter
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

import joblib
from sklearn.ensemble import IsolationForest, RandomForestClassifier
from sklearn.feature_extraction import DictVectorizer
from sklearn.metrics import accuracy_score, f1_score, precision_score, recall_score, roc_auc_score
from sklearn.model_selection import train_test_split
from sklearn.pipeline import Pipeline


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass(frozen=True)
class ScoreResult:
    score: float
    risk_label: str
    predicted_label: int
    model_version: int
    model_kind: str
    reasons: list[str]
    thresholds: dict[str, float]

    def as_decision(self) -> dict[str, Any]:
        return {
            "score": round(self.score, 6),
            "risk_label": self.risk_label,
            "predicted_label": self.predicted_label,
            "model_version": self.model_version,
            "model_kind": self.model_kind,
            "reasons": self.reasons,
            "thresholds": self.thresholds,
        }


class FeatureSchema:
    def __init__(self, raw: dict[str, Any]):
        self.raw = raw
        self.schema_id = raw["schema_id"]
        self.target = raw.get("target", "label")
        self.fields = raw.get("fields", [])
        self.field_map = {field["name"]: field for field in self.fields}
        self.feature_fields = [
            field
            for field in self.fields
            if field.get("role", "feature") == "feature" and field.get("train", True)
        ]
        self.entity_fields = [
            field for field in self.fields if field.get("role") == "entity" or not field.get("train", True)
        ]
        self.allow_unknown_features = bool(raw.get("allow_unknown_features", False))

    @classmethod
    def load(cls, path: Path) -> "FeatureSchema":
        with Path(path).open("r", encoding="utf-8") as handle:
            return cls(json.load(handle))

    @property
    def decision_thresholds(self) -> dict[str, float]:
        decision = self.raw.get("decision", {})
        return {
            "review": float(decision.get("review_threshold", 0.6)),
            "block": float(decision.get("block_threshold", 0.85)),
        }

    @property
    def retrain_config(self) -> dict[str, Any]:
        return self.raw.get("retrain", {})

    def normalize_payload(self, payload: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
        normalized: dict[str, Any] = {}
        warnings: list[str] = []
        for field in self.fields:
            name = field["name"]
            if name in payload and payload[name] not in ("", None):
                value = payload[name]
            else:
                value = field.get("default")
                if field.get("required"):
                    warnings.append(f"{name} was missing; default applied")
            normalized[name] = self._coerce_value(value, field, warnings)

        if self.allow_unknown_features:
            known = set(self.field_map)
            for key, value in payload.items():
                if key not in known and isinstance(value, (str, int, float, bool)):
                    normalized[key] = value
        else:
            unknown = [key for key in payload if key not in self.field_map]
            if unknown:
                warnings.append(f"unknown fields ignored: {', '.join(sorted(unknown))}")

        return normalized, warnings

    def feature_dict(self, payload: dict[str, Any]) -> dict[str, Any]:
        normalized, _ = self.normalize_payload(payload)
        features = {}
        for field in self.feature_fields:
            name = field["name"]
            value = normalized.get(name, field.get("default"))
            derived = self._derived_temporal_features(name, value, field, normalized)
            features.update(derived)
            if not derived or field.get("include_raw", True):
                features[name] = value
        if self.allow_unknown_features:
            for key, value in normalized.items():
                if key not in self.field_map and isinstance(value, (str, int, float, bool)):
                    features[key] = value
        features.update(self._schema_derived_features(normalized))
        return features

    def extract_label(self, payload: dict[str, Any], explicit_label: int | bool | None = None) -> int | None:
        if explicit_label is not None:
            return int(bool(explicit_label))
        if self.target in payload and payload[self.target] not in ("", None):
            return int(bool(payload[self.target]))
        return None

    def account_id(self, payload: dict[str, Any]) -> str:
        display = self.raw.get("display", {})
        account_field = display.get("account_field")
        value = (
            payload.get(account_field) if account_field else None
        ) or payload.get("account_id") or payload.get("customer_id") or payload.get("cc_num") or payload.get("nameOrig") or "acct-demo-001"
        return str(value)

    def _coerce_value(self, value: Any, field: dict[str, Any], warnings: list[str]) -> Any:
        field_type = field.get("type", "text")
        name = field["name"]
        try:
            if field_type == "number":
                number = float(value)
                if "min" in field:
                    number = max(number, float(field["min"]))
                if "max" in field:
                    number = min(number, float(field["max"]))
                return number
            if field_type == "integer":
                number = int(float(value))
                if "min" in field:
                    number = max(number, int(field["min"]))
                if "max" in field:
                    number = min(number, int(field["max"]))
                return number
            if field_type == "boolean":
                if isinstance(value, str):
                    return value.strip().lower() in {"true", "1", "yes", "y", "on", "fraud"}
                return bool(value)
            if field_type == "datetime":
                return self._parse_datetime(value).strftime("%Y-%m-%d %H:%M:%S")
            if field_type == "date":
                return self._parse_date(value).isoformat()
            if field_type == "categorical":
                text = str(value)
                allowed = field.get("allowed")
                if allowed and text not in allowed:
                    warnings.append(f"{name} has unseen category '{text}'")
                return text
            return str(value)
        except (TypeError, ValueError):
            warnings.append(f"{name} could not be parsed; default applied")
            return field.get("default")

    def _derived_temporal_features(
        self, name: str, value: Any, field: dict[str, Any], normalized: dict[str, Any]
    ) -> dict[str, Any]:
        derived: dict[str, Any] = {}
        for item in field.get("derive", []):
            try:
                if item in {"hour", "day_of_week", "month", "is_weekend"}:
                    dt = self._parse_datetime(value)
                    if item == "hour":
                        derived[f"{name}__hour"] = dt.hour
                    elif item == "day_of_week":
                        derived[f"{name}__day_of_week"] = dt.weekday()
                    elif item == "month":
                        derived[f"{name}__month"] = dt.month
                    elif item == "is_weekend":
                        derived[f"{name}__is_weekend"] = dt.weekday() >= 5
                elif item == "age_years":
                    born = self._parse_date(value)
                    reference_name = field.get("reference_datetime_field")
                    reference = (
                        self._parse_datetime(normalized.get(reference_name))
                        if reference_name
                        else datetime.now()
                    )
                    age = reference.date().year - born.year
                    if (reference.date().month, reference.date().day) < (born.month, born.day):
                        age -= 1
                    derived[f"{name}__age_years"] = max(0, age)
            except (TypeError, ValueError):
                continue
        return derived

    def _schema_derived_features(self, normalized: dict[str, Any]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for feature in self.raw.get("derived_features", []):
            try:
                if feature.get("type") == "geo_distance":
                    result[feature["name"]] = self._haversine_km(
                        float(normalized[feature["lat"]]),
                        float(normalized[feature["long"]]),
                        float(normalized[feature["other_lat"]]),
                        float(normalized[feature["other_long"]]),
                    )
                elif feature.get("type") == "difference":
                    result[feature["name"]] = float(normalized[feature["left"]]) - float(
                        normalized[feature["right"]]
                    )
                elif feature.get("type") == "ratio":
                    denominator = float(normalized[feature["denominator"]])
                    result[feature["name"]] = (
                        float(normalized[feature["numerator"]]) / denominator
                        if denominator
                        else 0
                    )
            except (KeyError, TypeError, ValueError):
                continue
        return result

    def _parse_datetime(self, value: Any) -> datetime:
        if isinstance(value, datetime):
            return value
        text = str(value)
        for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S", "%m/%d/%Y %H:%M"):
            try:
                return datetime.strptime(text, fmt)
            except ValueError:
                pass
        return datetime.fromisoformat(text)

    def _parse_date(self, value: Any) -> date:
        if isinstance(value, date) and not isinstance(value, datetime):
            return value
        if isinstance(value, datetime):
            return value.date()
        text = str(value)
        for fmt in ("%Y-%m-%d", "%m/%d/%Y"):
            try:
                return datetime.strptime(text, fmt).date()
            except ValueError:
                pass
        return datetime.fromisoformat(text).date()

    def _haversine_km(self, lat1: float, lon1: float, lat2: float, lon2: float) -> float:
        radius = 6371.0
        phi1 = math.radians(lat1)
        phi2 = math.radians(lat2)
        delta_phi = math.radians(lat2 - lat1)
        delta_lambda = math.radians(lon2 - lon1)
        a = (
            math.sin(delta_phi / 2) ** 2
            + math.cos(phi1) * math.cos(phi2) * math.sin(delta_lambda / 2) ** 2
        )
        return radius * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


class FraudModelManager:
    def __init__(self, schema_path: Path, model_dir: Path):
        self.schema_path = Path(schema_path)
        self.model_dir = Path(model_dir)
        self.schema = FeatureSchema.load(self.schema_path)
        self.pipeline: Pipeline | None = None
        self.metadata: dict[str, Any] = {
            "version": 0,
            "model_kind": "heuristic",
            "created_at": utc_now(),
            "metrics": {},
        }

    @property
    def current_version(self) -> int:
        return int(self.metadata.get("version", 0))

    @property
    def model_kind(self) -> str:
        return str(self.metadata.get("model_kind", "heuristic"))

    def load_artifact(self, artifact_path: str | Path) -> bool:
        path = Path(artifact_path)
        if not path.exists():
            return False
        artifact = joblib.load(path)
        self.pipeline = artifact["pipeline"]
        self.metadata = artifact["metadata"]
        self.schema = FeatureSchema(artifact.get("schema", self.schema.raw))
        return True

    def score(self, payload: dict[str, Any]) -> tuple[dict[str, Any], ScoreResult]:
        normalized, warnings = self.schema.normalize_payload(payload)
        features = self.schema.feature_dict(normalized)
        if self.pipeline is None:
            score = self._heuristic_score(normalized)
        elif self.model_kind in {"supervised_random_forest", "schema_driven_random_forest"}:
            proba = self.pipeline.predict_proba([features])[0]
            classes = list(self.pipeline.named_steps["model"].classes_)
            score = float(proba[classes.index(1)]) if 1 in classes else float(max(proba))
        else:
            raw = float(-self.pipeline.decision_function([features])[0])
            score = 1 / (1 + math.exp(-12 * raw))

        score = max(0.0, min(0.999999, score))
        thresholds = self.schema.decision_thresholds
        risk_label = "blocked" if score >= thresholds["block"] else "review" if score >= thresholds["review"] else "normal"
        reasons = self._explain(normalized, score, warnings)
        result = ScoreResult(
            score=score,
            risk_label=risk_label,
            predicted_label=int(score >= thresholds["review"]),
            model_version=self.current_version,
            model_kind=self.model_kind,
            reasons=reasons,
            thresholds=thresholds,
        )
        return normalized, result

    def train(self, rows: list[dict[str, Any]], reason: str) -> dict[str, Any]:
        config = self.schema.retrain_config
        max_recent = int(config.get("max_recent_samples", 5000))
        rows = rows[:max_recent]
        prepared = self._prepare_rows(rows)
        all_features = [item["features"] for item in prepared if item["features"]]
        labeled = [item for item in prepared if item["label"] is not None]
        labels = [int(item["label"]) for item in labeled]

        supervised_min = int(config.get("supervised_min_labeled", 30))
        can_supervise = len(labeled) >= supervised_min and len(set(labels)) >= 2

        if can_supervise:
            pipeline, metrics, feature_importance = self._train_supervised(labeled)
            model_kind = "schema_driven_random_forest"
            training_rows = len(labeled)
        else:
            pipeline, metrics, feature_importance = self._train_unsupervised(all_features)
            model_kind = "isolation_forest"
            training_rows = len(all_features)

        version = self.current_version + 1
        robustness = self._robustness_report(
            model_kind=model_kind,
            feature_importance=feature_importance,
            pseudo_labeled_rows=sum(1 for item in labeled if item["label_source"] == "pseudo_high_confidence"),
        )
        metadata = {
            "version": version,
            "schema_id": self.schema.schema_id,
            "created_at": utc_now(),
            "model_kind": model_kind,
            "metrics": metrics,
            "feature_importance": feature_importance,
            "reason": reason,
        }
        artifact_path = self.model_dir / f"fraud_model_v{version}.joblib"
        artifact_path.parent.mkdir(parents=True, exist_ok=True)
        joblib.dump({"pipeline": pipeline, "metadata": metadata, "schema": self.schema.raw}, artifact_path)

        self.pipeline = pipeline
        self.metadata = metadata
        return {
            "version": version,
            "created_at": metadata["created_at"],
            "schema_id": self.schema.schema_id,
            "training_rows": training_rows,
            "labeled_rows": len(labeled),
            "metrics": metrics,
            "robustness": robustness,
            "artifact_path": str(artifact_path),
            "notes": reason,
            "used_transaction_ids": [item["transaction_id"] for item in labeled[:250]],
        }

    def schema_for_ui(self) -> dict[str, Any]:
        return self.schema.raw

    def _prepare_rows(self, rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
        config = self.schema.retrain_config
        allow_pseudo = bool(config.get("allow_high_confidence_pseudo_labels", False))
        pseudo_min = float(config.get("pseudo_label_min_confidence", 0.94))
        prepared = []

        for row in rows:
            payload = row.get("payload", {})
            features = self.schema.feature_dict(payload)
            label = row.get("label")
            label_source = row.get("label_source")
            if label is None and allow_pseudo:
                decision = row.get("decision", {})
                score = float(decision.get("score", row.get("anomaly_score") or 0))
                predicted = int(decision.get("predicted_label", score >= self.schema.decision_thresholds["review"]))
                confidence = score if predicted else 1 - score
                if confidence >= pseudo_min:
                    label = predicted
                    label_source = "pseudo_high_confidence"
            prepared.append(
                {
                    "transaction_id": row.get("transaction_id"),
                    "features": features,
                    "label": int(label) if label is not None else None,
                    "label_source": label_source,
                }
            )
        return prepared

    def _train_supervised(
        self, labeled: list[dict[str, Any]]
    ) -> tuple[Pipeline, dict[str, Any], list[dict[str, Any]]]:
        x = [item["features"] for item in labeled]
        y = [int(item["label"]) for item in labeled]
        pipeline = Pipeline(
            [
                ("features", DictVectorizer(sparse=False)),
                (
                    "model",
                    RandomForestClassifier(
                        n_estimators=180,
                        max_depth=10,
                        min_samples_leaf=2,
                        class_weight="balanced_subsample",
                        random_state=42,
                    ),
                ),
            ]
        )
        metrics: dict[str, Any] = {"mode": "supervised", "class_balance": dict(Counter(y))}
        counts = Counter(y)
        if len(y) >= 60 and min(counts.values()) >= 6:
            x_train, x_test, y_train, y_test = train_test_split(
                x, y, test_size=0.25, random_state=42, stratify=y
            )
            pipeline.fit(x_train, y_train)
            predictions = pipeline.predict(x_test)
            probabilities = pipeline.predict_proba(x_test)[:, list(pipeline.named_steps["model"].classes_).index(1)]
            metrics.update(
                {
                    "accuracy": round(float(accuracy_score(y_test, predictions)), 4),
                    "precision": round(float(precision_score(y_test, predictions, zero_division=0)), 4),
                    "recall": round(float(recall_score(y_test, predictions, zero_division=0)), 4),
                    "f1": round(float(f1_score(y_test, predictions, zero_division=0)), 4),
                    "roc_auc": round(float(roc_auc_score(y_test, probabilities)), 4),
                    "validation_rows": len(y_test),
                }
            )

        pipeline.fit(x, y)
        return pipeline, metrics, self._feature_importance(pipeline)

    def _train_unsupervised(
        self, all_features: list[dict[str, Any]]
    ) -> tuple[Pipeline, dict[str, Any], list[dict[str, Any]]]:
        if not all_features:
            all_features = [self.schema.feature_dict({})]
        contamination = float(self.schema.retrain_config.get("isolation_contamination", 0.08))
        pipeline = Pipeline(
            [
                ("features", DictVectorizer(sparse=False)),
                (
                    "model",
                    IsolationForest(
                        contamination=contamination,
                        random_state=42,
                        n_estimators=160,
                    ),
                ),
            ]
        )
        pipeline.fit(all_features)
        metrics = {
            "mode": "unsupervised",
            "training_rows": len(all_features),
            "contamination": contamination,
        }
        return pipeline, metrics, []

    def _feature_importance(self, pipeline: Pipeline) -> list[dict[str, Any]]:
        model = pipeline.named_steps["model"]
        if not hasattr(model, "feature_importances_"):
            return []
        feature_names = pipeline.named_steps["features"].get_feature_names_out()
        importances = model.feature_importances_
        ranked = sorted(
            zip(feature_names, importances, strict=False),
            key=lambda item: float(item[1]),
            reverse=True,
        )
        return [
            {"feature": str(name), "importance": round(float(value), 6)}
            for name, value in ranked[:12]
        ]

    def _robustness_report(
        self, model_kind: str, feature_importance: list[dict[str, Any]], pseudo_labeled_rows: int
    ) -> dict[str, Any]:
        config = self.schema.retrain_config
        return {
            "model_kind": model_kind,
            "schema_id": self.schema.schema_id,
            "feature_contract": {
                "features": [field["name"] for field in self.schema.feature_fields],
                "target": self.schema.target,
                "unknown_features": "accepted" if self.schema.allow_unknown_features else "ignored",
            },
            "thresholds": self.schema.decision_thresholds,
            "defense_controls": [
                "schema validation with type coercion and unseen-category logging",
                "schema-driven derived features for timestamp, age, balance deltas, and geo distance",
                "class-balanced supervised model when labels are available",
                "isolation fallback for sparse or unlabeled streams",
                "high-confidence pseudo labels are explicitly marked in training logs",
                "agent actions are separated behind a local MCP-style connector",
            ],
            "training_policy": {
                "supervised_min_labeled": int(config.get("supervised_min_labeled", 30)),
                "pseudo_labels_enabled": bool(config.get("allow_high_confidence_pseudo_labels", False)),
                "pseudo_label_min_confidence": float(config.get("pseudo_label_min_confidence", 0.94)),
                "pseudo_labeled_rows": pseudo_labeled_rows,
            },
            "top_features": feature_importance,
        }

    def _heuristic_score(self, payload: dict[str, Any]) -> float:
        amount = float(payload.get("amount") or payload.get("amt") or 0)
        velocity = float(payload.get("velocity_10m") or 0)
        failed = float(payload.get("prior_failed_attempts") or 0)
        device = float(payload.get("device_trust_score") or 0.65)
        recipient = float(payload.get("recipient_risk_score") or 0)
        age = float(payload.get("account_age_days") or 0)
        category = str(payload.get("merchant_category") or payload.get("category") or "")
        international = bool(payload.get("is_international"))
        feature_values = self.schema.feature_dict(payload)
        hour = int(payload.get("transaction_hour") or feature_values.get("trans_date_trans_time__hour", 12))
        distance = float(feature_values.get("customer_merchant_distance_km", 0))

        score = 0.04
        score += min(amount / 1200, 1) * 0.2
        score += min(velocity / 20, 1) * 0.16
        score += min(failed / 8, 1) * 0.12
        score += max(0, 0.75 - device) * 0.25
        score += recipient * 0.2
        score += 0.08 if international else 0
        score += 0.08 if category in {"shopping_net", "misc_net", "travel", "gift_card", "crypto", "cash_out"} else 0
        score += 0.08 if age < 21 else 0
        score += 0.04 if hour <= 5 else 0
        score += min(distance / 500, 1) * 0.1
        return score

    def _explain(self, payload: dict[str, Any], score: float, warnings: list[str]) -> list[str]:
        reasons = list(warnings[:3])
        amount = float(payload.get("amount") or payload.get("amt") or 0)
        feature_values = self.schema.feature_dict(payload)
        if amount > 700:
            reasons.append("large amount")
        if float(payload.get("device_trust_score") or 1) < 0.35:
            reasons.append("low device trust")
        if float(payload.get("recipient_risk_score") or 0) > 0.7:
            reasons.append("high recipient risk")
        if int(payload.get("velocity_10m") or 0) >= 8:
            reasons.append("high transaction velocity")
        if int(payload.get("prior_failed_attempts") or 0) >= 3:
            reasons.append("recent failed attempts")
        if payload.get("is_international"):
            reasons.append("international transaction")
        if float(feature_values.get("customer_merchant_distance_km", 0)) > 300:
            reasons.append("distant merchant location")
        if int(feature_values.get("trans_date_trans_time__hour", payload.get("transaction_hour") or 12)) <= 5:
            reasons.append("late-night transaction")
        if not reasons:
            reasons.append("within learned baseline" if score < self.schema.decision_thresholds["review"] else "model score exceeded threshold")
        return reasons[:6]


def attacker_intel_from_updates(updates: list[dict[str, Any]]) -> dict[str, Any]:
    latest = updates[0] if updates else {}
    robustness = latest.get("robustness", {})
    top_features = robustness.get("top_features", [])
    return {
        "latest_version": latest.get("version"),
        "updated_at": latest.get("created_at"),
        "model_kind": robustness.get("model_kind"),
        "thresholds": robustness.get("thresholds", {}),
        "top_features": top_features,
        "robustness_controls": robustness.get("defense_controls", []),
        "sandbox_attack_cards": [
            {
                "name": "low-and-slow transaction splitting",
                "objective": "Probe how amount and velocity interact inside this sandbox stream.",
                "learning_goal": "Understand why velocity features and aggregation windows matter.",
            },
            {
                "name": "schema drift probe",
                "objective": "Send unseen categories or shifted country/channel combinations and observe validation logs.",
                "learning_goal": "Compare strict schema handling with permissive feature ingestion.",
            },
            {
                "name": "label-noise exercise",
                "objective": "Mark a small set of transactions with wrong labels and watch retraining metrics.",
                "learning_goal": "See how poisoning pressure appears in class balance and validation recall.",
            },
            {
                "name": "policy boundary test",
                "objective": "Create transactions near review and block thresholds, then inspect MCP actions.",
                "learning_goal": "Separate model confidence from automated account actions.",
            },
        ],
    }
