from __future__ import annotations

import argparse
import json
import sys
from typing import Any

from sqlalchemy.orm import Session

from api.config import get_settings
from api.db import get_engine
from api.services.plc.cli_adapter import PLCExecutorTransportError
from api.services.plc.contracts import (
    PLCExecutionRequestModel,
    PLCExecutionResultModel,
    PLCRunContextModel,
    PLCTestCaseModel,
    PLCTestcaseContextModel,
    PLCTestRunItemModel,
    PLCTestRunResultModel,
    PLCTargetContextModel,
    PLCValidationResultModel,
)
from api.services.plc.executor import get_plc_executor
from api.services.plc.persistence import build_plc_job_summary, persist_plc_run_result
from api.services.plc.validator import validate_execution_result


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="plc-job-runner",
        description="Run a deterministic PLC test suite job and emit structured JSON",
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


def _io_logs_from_result(result: PLCExecutionResultModel) -> list[dict[str, Any]]:
    logs: list[dict[str, Any]] = []
    sequence_no = 1
    for value in result.write_values:
        logs.append(
            {
                "direction": "write",
                "memory_address": value.address,
                "memory_symbol": value.symbol,
                "value_json": value.value,
                "raw_type": value.raw_type,
                "sequence_no": sequence_no,
            }
        )
        sequence_no += 1
    for value in result.read_values:
        logs.append(
            {
                "direction": "read",
                "memory_address": value.address,
                "memory_symbol": value.symbol,
                "value_json": value.value,
                "raw_type": value.raw_type,
                "sequence_no": sequence_no,
            }
        )
        sequence_no += 1
    return logs


def _executor_failure_reason(result: PLCExecutionResultModel) -> str:
    if result.diagnostics:
        return "; ".join(str(item) for item in result.diagnostics if str(item).strip())
    if result.raw_log.strip():
        return result.raw_log.strip()
    return "PLC executor reported failed status"


def execute_plc_job(
    payload: dict[str, Any], *, session: Session | None = None
) -> dict[str, Any]:
    suite_id = str(payload.get("suite_id", "")).strip()
    suite_title = str(payload.get("suite_title", suite_id)).strip() or suite_id
    target_key = str(payload.get("target_key", "stub-local")).strip() or "stub-local"
    run_id = str(payload.get("run_id") or payload.get("backing_job_id") or "").strip()
    raw_cases = payload.get("testcases")
    if not isinstance(raw_cases, list) or not raw_cases:
        raise RuntimeError("PLC job payload must contain testcases")

    settings = get_settings()
    executor = get_plc_executor(settings)
    target_snapshot = payload.get("target_snapshot")
    target_snapshot_json = (
        target_snapshot if isinstance(target_snapshot, dict) else {"key": target_key}
    )
    items: list[PLCTestRunItemModel] = []
    warnings: list[str] = []
    for raw_case in raw_cases:
        case = PLCTestCaseModel.model_validate(raw_case)
        target_metadata = target_snapshot_json.get("metadata_json")
        target_metadata_json = (
            target_metadata if isinstance(target_metadata, dict) else {}
        )
        request = PLCExecutionRequestModel(
            testcase_id=case.id,
            instruction=case.instruction_name,
            input_type=case.input_type,
            output_type=case.output_type,
            inputs=case.input_vector_json,
            expected=case.expected_output_json,
            expected_outcome=case.expected_outcome,
            memory_profile_key=case.memory_profile_key,
            execution_profile_key=case.execution_profile_key,
            execution_profile=case.execution_profile,
            timeout_ms=case.timeout_ms,
            target_key=target_key,
            testcase_context=PLCTestcaseContextModel(
                case_key=case.case_key,
                description=case.description,
                tags=case.tags,
                source_row_number=case.source_row_number,
                source_case_index=case.source_case_index,
            ),
            run_context=PLCRunContextModel(
                run_id=run_id or None,
                suite_id=suite_id,
                suite_title=suite_title,
            ),
            target_context=PLCTargetContextModel(
                key=str(target_snapshot_json.get("key") or target_key),
                display_name=(
                    str(target_snapshot_json.get("display_name"))
                    if target_snapshot_json.get("display_name") is not None
                    else None
                ),
                executor_mode=(
                    str(target_snapshot_json.get("executor_mode"))
                    if target_snapshot_json.get("executor_mode") is not None
                    else None
                ),
                environment_label=(
                    str(target_metadata_json.get("environment_label"))
                    if target_metadata_json.get("environment_label") is not None
                    else None
                ),
                tags=[str(tag) for tag in (target_metadata_json.get("tags") or [])],
                metadata_json=target_metadata_json,
            ),
        )
        try:
            execution = executor.run_case(request)
        except PLCExecutorTransportError:
            raise

        if execution.status == "failed":
            validation = PLCValidationResultModel(
                status="failed",
                validator="executor-status.v1",
                reason=_executor_failure_reason(execution),
                expected_output_json=case.expected_output_json,
                actual_output_json=execution.actual_output,
                type_mismatch=False,
            )
            item_status = "error"
            failure_reason = validation.reason
            warnings.append(f"case {case.case_key}: executor reported failed status")
        else:
            validation = validate_execution_result(request=request, result=execution)
            item_status = "passed" if validation.status == "passed" else "failed"
            failure_reason = validation.reason

        items.append(
            PLCTestRunItemModel(
                id=f"{run_id or suite_id}::{case.case_key}::result",
                testcase_id=case.id,
                case_key=case.case_key,
                instruction_name=case.instruction_name,
                status=item_status,
                input_type=case.input_type,
                output_type=case.output_type,
                timeout_ms=case.timeout_ms,
                expected_outcome=case.expected_outcome,
                memory_profile_key=case.memory_profile_key,
                execution_profile_key=case.execution_profile_key,
                inputs_json=case.input_vector_json,
                request_context_json={
                    "run_context": request.run_context.model_dump(mode="json")
                    if request.run_context is not None
                    else None,
                    "testcase_context": request.testcase_context.model_dump(mode="json")
                    if request.testcase_context is not None
                    else None,
                    "target_context": request.target_context.model_dump(mode="json")
                    if request.target_context is not None
                    else None,
                    "execution_profile": request.execution_profile.model_dump(
                        mode="json"
                    )
                    if request.execution_profile is not None
                    else None,
                },
                expected_output_json=case.expected_output_json,
                actual_output_json=execution.actual_output,
                validator_result_json=validation.model_dump(mode="json"),
                failure_reason=failure_reason,
                duration_ms=execution.duration_ms,
                io_logs=_io_logs_from_result(execution),
                executor_log=execution.raw_log,
            )
        )

    result = PLCTestRunResultModel(
        suite_id=suite_id,
        suite_title=suite_title,
        target_key=target_key,
        executor_mode=settings.plc_executor_mode,
        validator_version="exact-match.v1",
        total_count=len(items),
        passed_count=sum(1 for item in items if item.status == "passed"),
        failed_count=sum(1 for item in items if item.status == "failed"),
        error_count=sum(1 for item in items if item.status == "error"),
        items=items,
        warnings=warnings,
    )
    if session is not None and run_id:
        persist_plc_run_result(session, run_id=run_id, result=result)
        session.commit()
        return build_plc_job_summary(result)
    return result.model_dump(mode="json")


def main() -> None:
    parser = _build_parser()
    args = parser.parse_args()
    try:
        payload = _resolve_payload(args.payload_json)
        with Session(get_engine()) as session:
            result = execute_plc_job(payload, session=session)
    except Exception as exc:
        print(f"[plc-job-runner] failed: {exc}", file=sys.stderr, flush=True)
        raise SystemExit(1) from exc
    print(json.dumps(result), flush=True)


if __name__ == "__main__":
    main()
