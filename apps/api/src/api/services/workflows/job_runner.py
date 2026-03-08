from __future__ import annotations

import argparse
import json
import sys
from typing import Any

from sqlalchemy.orm import Session

from api.db import get_engine
from api.dependencies import get_embedding_client, get_llm_client
from api.services.datasets.registry import ensure_default_datasets
from api.services.workflows.service import execute_workflow


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="workflow-job-runner",
        description="Run a retrieval-first workflow job and emit structured JSON",
    )
    parser.add_argument(
        "--payload-json",
        default=None,
        help="JSON object payload containing workflow_key, dataset_key, prompt, and optional k",
    )
    return parser


def _resolve_payload(payload_json_raw: str | None) -> dict[str, Any]:
    if payload_json_raw is None:
        return {}
    parsed = json.loads(payload_json_raw)
    if not isinstance(parsed, dict):
        raise ValueError("payload_json must be a JSON object")
    return parsed


def main() -> None:
    parser = _build_parser()
    args = parser.parse_args()

    try:
        payload = _resolve_payload(args.payload_json)
        with Session(get_engine()) as session:
            ensure_default_datasets(session)
            result = execute_workflow(
                session=session,
                payload=payload,
                llm_client=get_llm_client(),
                embedding_client=get_embedding_client(),
            )
    except Exception as exc:
        print(f"[workflow-job-runner] failed: {exc}", file=sys.stderr, flush=True)
        raise SystemExit(1) from exc

    print(json.dumps(result), flush=True)


if __name__ == "__main__":
    main()
