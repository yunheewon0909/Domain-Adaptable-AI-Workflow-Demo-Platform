from __future__ import annotations

from api.services.plc.contracts import (
    PLCExecutionRequestModel,
    PLCExecutionResultModel,
    PLCValidationResultModel,
)


def validate_execution_result(
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
