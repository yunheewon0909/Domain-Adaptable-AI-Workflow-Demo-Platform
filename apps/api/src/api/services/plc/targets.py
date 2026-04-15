from __future__ import annotations

from typing import Any


def _normalize_text(value: Any) -> str | None:
    text = str(value or "").strip()
    return text or None


def _normalize_tags(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    if isinstance(value, str):
        normalized = value.strip()
        if not normalized:
            return []
        return [item.strip() for item in normalized.split(",") if item.strip()]
    return []


def normalize_target_metadata(raw_metadata: Any) -> dict[str, Any]:
    if raw_metadata in (None, ""):
        raw_metadata = {}
    if not isinstance(raw_metadata, dict):
        raise ValueError("PLC target metadata_json must be a JSON object")

    normalized = {
        "schema_version": "plc-target.v1",
        "environment_label": _normalize_text(
            raw_metadata.get("environment_label") or raw_metadata.get("environment")
        ),
        "line": _normalize_text(raw_metadata.get("line")),
        "bench": _normalize_text(raw_metadata.get("bench")),
        "tags": _normalize_tags(raw_metadata.get("tags")),
    }
    attributes = {
        str(key): value
        for key, value in raw_metadata.items()
        if key
        not in {
            "schema_version",
            "environment_label",
            "environment",
            "line",
            "bench",
            "tags",
        }
    }
    normalized["attributes_json"] = attributes
    return normalized


def normalize_target_payload(target: dict[str, Any]) -> dict[str, Any]:
    metadata_json = normalize_target_metadata(target.get("metadata_json"))
    return {
        **target,
        "metadata_json": metadata_json,
        "environment_label": metadata_json.get("environment_label"),
        "tags": metadata_json.get("tags") or [],
        "line": metadata_json.get("line"),
        "bench": metadata_json.get("bench"),
    }
