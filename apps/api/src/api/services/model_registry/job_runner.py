from __future__ import annotations

import argparse
import json
import sys
from typing import Any

from sqlalchemy.orm import Session

from api.db import get_engine
from api.models import FTTrainingJobRecord
from api.services.model_registry.service import complete_training_job


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="ft-train-model-runner",
        description="Run the fine-tuning scaffold job and emit structured JSON",
    )
    parser.add_argument("--payload-json", default=None)
    return parser


def _resolve_payload(payload_json_raw: str | None) -> dict[str, Any]:
    if payload_json_raw is None:
        return {}
    parsed = json.loads(payload_json_raw)
    if not isinstance(parsed, dict):
        raise ValueError("payload_json must be a JSON object")
    return parsed


def execute_training_job(
    payload: dict[str, Any], *, session: Session
) -> dict[str, Any]:
    training_job_id = str(payload.get("training_job_id") or "").strip()
    if not training_job_id:
        raise RuntimeError("training_job_id is required")
    training_job = session.get(FTTrainingJobRecord, training_job_id)
    if training_job is None:
        raise RuntimeError("training job not found")
    training_job.status = "preparing_data"
    session.commit()
    result = complete_training_job(session, training_job_id=training_job_id)
    return {
        "training_job_id": training_job_id,
        "status": result.get("status"),
        "artifacts": result.get("artifacts", []),
        "registered_models": result.get("registered_models", []),
    }


def main() -> None:
    parser = _build_parser()
    args = parser.parse_args()
    try:
        payload = _resolve_payload(args.payload_json)
        with Session(get_engine()) as session:
            result = execute_training_job(payload, session=session)
    except Exception as exc:
        print(f"[ft-train-model-runner] failed: {exc}", file=sys.stderr, flush=True)
        raise SystemExit(1) from exc
    print(json.dumps(result), flush=True)


if __name__ == "__main__":
    main()
