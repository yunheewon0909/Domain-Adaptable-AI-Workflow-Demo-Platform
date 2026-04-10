from __future__ import annotations

import argparse
import json
import sys
from typing import Any

from sqlalchemy.orm import Session

from api.config import get_settings
from api.db import get_engine
from api.services.plc.contracts import (
    PLCExecutionRequestModel,
    PLCExecutionResultModel,
    PLCTestCaseModel,
    PLCTestRunItemModel,
    PLCTestRunResultModel,
    PLCValidationResultModel,
)
from api.services.plc.executor import get_plc_executor


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


def _validate_result(
    *,
    request: PLCExecutionRequestModel,
    result: PLCExecutionResultModel,
) -> PLCValidationResultModel:
    type_mismatch = False
    actual = result.actual_output
    expected = request.expected
    if (
        actual is not None
        and expected is not None
        and type(actual) is not type(expected)
    ):
        type_mismatch = True
    passed = actual == expected and not type_mismatch
    return PLCValidationResultModel(
        status="passed" if passed else "failed",
        validator="exact-match.v1",
        reason=None
        if passed
        else (
            "type mismatch"
            if type_mismatch
            else "actual output did not match expected output"
        ),
        expected_output_json=expected,
        actual_output_json=actual,
        type_mismatch=type_mismatch,
    )


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


def execute_plc_job(payload: dict[str, Any]) -> dict[str, Any]:
    suite_id = str(payload.get("suite_id", "")).strip()
    suite_title = str(payload.get("suite_title", suite_id)).strip() or suite_id
    target_key = str(payload.get("target_key", "stub-local")).strip() or "stub-local"
    raw_cases = payload.get("testcases")
    if not isinstance(raw_cases, list) or not raw_cases:
        raise RuntimeError("PLC job payload must contain testcases")

    settings = get_settings()
    executor = get_plc_executor(settings)
    items: list[PLCTestRunItemModel] = []
    warnings: list[str] = []
    for raw_case in raw_cases:
        case = PLCTestCaseModel.model_validate(raw_case)
        request = PLCExecutionRequestModel(
            testcase_id=case.id,
            instruction=case.instruction_name,
            input_type=case.input_type,
            output_type=case.output_type,
            inputs=case.input_vector_json,
            expected=case.expected_output_json,
            expected_outcome=case.expected_outcome,
            memory_profile_key=case.memory_profile_key,
            timeout_ms=case.timeout_ms,
        )
        try:
            execution = executor.run_case(request)
            validation = _validate_result(request=request, result=execution)
            item_status = "passed" if validation.status == "passed" else "failed"
            failure_reason = validation.reason
        except Exception as exc:
            execution = PLCExecutionResultModel(
                status="failed",
                actual_output=None,
                expected_output=case.expected_output_json,
                duration_ms=0,
                raw_log=str(exc),
                executor_exit_code=1,
            )
            validation = PLCValidationResultModel(
                status="failed",
                validator="exact-match.v1",
                reason=str(exc),
                expected_output_json=case.expected_output_json,
                actual_output_json=None,
                type_mismatch=False,
            )
            item_status = "error"
            failure_reason = str(exc)
            warnings.append(f"case {case.case_key}: executor error")

        items.append(
            PLCTestRunItemModel(
                id=f"{suite_id}::{case.case_key}::result",
                testcase_id=case.id,
                case_key=case.case_key,
                instruction_name=case.instruction_name,
                status=item_status,
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
    return result.model_dump(mode="json")


def main() -> None:
    parser = _build_parser()
    args = parser.parse_args()
    try:
        payload = _resolve_payload(args.payload_json)
        with Session(get_engine()):
            result = execute_plc_job(payload)
    except Exception as exc:
        print(f"[plc-job-runner] failed: {exc}", file=sys.stderr, flush=True)
        raise SystemExit(1) from exc
    print(json.dumps(result), flush=True)


if __name__ == "__main__":
    main()
