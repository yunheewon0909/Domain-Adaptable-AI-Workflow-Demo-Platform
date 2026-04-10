from __future__ import annotations

from typing import Any

from api.services.plc.contracts import (
    PLCExecutionRequestModel,
    PLCExecutionResultModel,
    PLCIOMemoryValueModel,
)


def _coerce_failure_value(expected: Any) -> Any:
    if isinstance(expected, bool):
        return not expected
    if isinstance(expected, int) and not isinstance(expected, bool):
        return expected + 1
    if isinstance(expected, float):
        return expected + 1.0
    if isinstance(expected, str):
        return f"{expected}__mismatch"
    if isinstance(expected, list):
        return list(reversed(expected)) if expected else ["mismatch"]
    if isinstance(expected, dict):
        mismatched = dict(expected)
        mismatched["mismatch"] = True
        return mismatched
    return {"mismatch": True, "expected": expected}


class DeterministicStubPLCExecutor:
    def run_case(self, request: PLCExecutionRequestModel) -> PLCExecutionResultModel:
        writes = [
            PLCIOMemoryValueModel(
                address=f"D{100 + index * 2}",
                value=value,
                symbol=f"INPUT_{index + 1}",
                raw_type=request.input_type,
            )
            for index, value in enumerate(request.inputs)
        ]
        actual_output = (
            request.expected
            if request.expected_outcome == "pass"
            else _coerce_failure_value(request.expected)
        )
        reads = [
            PLCIOMemoryValueModel(
                address="D200",
                value=actual_output,
                symbol=request.memory_profile_key or "OUTPUT_1",
                raw_type=request.output_type,
            )
        ]
        duration_ms = max(25, min(request.timeout_ms, 250) + len(request.inputs) * 7)
        return PLCExecutionResultModel(
            status="completed",
            write_values=writes,
            read_values=reads,
            actual_output=actual_output,
            expected_output=request.expected,
            duration_ms=duration_ms,
            raw_log=(
                f"stub executor handled {request.testcase_id} "
                f"instruction={request.instruction} memory_profile={request.memory_profile_key or 'default'}"
            ),
            executor_exit_code=0,
        )
