import json
import subprocess
from typing import Literal

import pytest

from api.services.plc.cli_adapter import CLIBasedPLCExecutor, PLCExecutorTransportError
from api.services.plc.contracts import PLCExecutionRequestModel, PLCExecutionResultModel
from api.services.plc.job_runner import execute_plc_job
from api.services.plc.stub_executor import DeterministicStubPLCExecutor


def _build_request(
    *, expected_outcome: Literal["pass", "fail"] = "pass"
) -> PLCExecutionRequestModel:
    return PLCExecutionRequestModel(
        testcase_id="plc-suite-1::ADD_001",
        instruction="add",
        input_type="LWORD",
        output_type="LWORD",
        inputs=[1, 1],
        expected=2,
        expected_outcome=expected_outcome,
        memory_profile_key="ls_add_lword_v1",
        timeout_ms=3000,
    )


def test_stub_executor_returns_deterministic_completed_payload() -> None:
    executor = DeterministicStubPLCExecutor()
    result = executor.run_case(_build_request())

    assert result.status == "completed"
    assert result.actual_output == 2
    assert result.expected_output == 2
    assert len(result.write_values) == 2
    assert len(result.read_values) == 1


def test_stub_executor_can_force_failure_signal() -> None:
    executor = DeterministicStubPLCExecutor()
    result = executor.run_case(_build_request(expected_outcome="fail"))

    assert result.actual_output != result.expected_output


def test_cli_executor_raises_when_path_missing() -> None:
    executor = CLIBasedPLCExecutor(cli_path=None, timeout_seconds=1)
    with pytest.raises(PLCExecutorTransportError):
        executor.run_case(_build_request())


def test_cli_executor_validates_json(monkeypatch) -> None:
    class _Completed:
        returncode = 0
        stdout = json.dumps(
            {
                "status": "completed",
                "write_values": [{"address": "D100", "value": 1}],
                "read_values": [{"address": "D200", "value": 2}],
                "actual_output": 2,
                "expected_output": 2,
                "duration_ms": 30,
                "raw_log": "ok",
                "executor_exit_code": 0,
            }
        )
        stderr = ""

    monkeypatch.setattr("subprocess.run", lambda *args, **kwargs: _Completed())
    executor = CLIBasedPLCExecutor(cli_path="/tmp/plc-cli", timeout_seconds=1)
    result = executor.run_case(_build_request())

    assert result.actual_output == 2
    assert result.schema_version == "plc-execution-result.v1"


def test_cli_executor_raises_for_invalid_json(monkeypatch) -> None:
    class _Completed:
        returncode = 0
        stdout = "not-json"
        stderr = ""

    monkeypatch.setattr("subprocess.run", lambda *args, **kwargs: _Completed())
    executor = CLIBasedPLCExecutor(cli_path="/tmp/plc-cli", timeout_seconds=1)

    with pytest.raises(PLCExecutorTransportError, match="invalid JSON"):
        executor.run_case(_build_request())


def test_cli_executor_raises_for_empty_stdout(monkeypatch) -> None:
    class _Completed:
        returncode = 0
        stdout = "  \n"
        stderr = ""

    monkeypatch.setattr("subprocess.run", lambda *args, **kwargs: _Completed())
    executor = CLIBasedPLCExecutor(cli_path="/tmp/plc-cli", timeout_seconds=1)

    with pytest.raises(PLCExecutorTransportError, match="empty stdout"):
        executor.run_case(_build_request())


def test_cli_executor_raises_for_non_zero_exit(monkeypatch) -> None:
    class _Completed:
        returncode = 7
        stdout = ""
        stderr = "boom"

    monkeypatch.setattr("subprocess.run", lambda *args, **kwargs: _Completed())
    executor = CLIBasedPLCExecutor(cli_path="/tmp/plc-cli", timeout_seconds=1)

    with pytest.raises(PLCExecutorTransportError, match="exit=7"):
        executor.run_case(_build_request())


def test_cli_executor_raises_for_timeout(monkeypatch) -> None:
    def _raise_timeout(*args, **kwargs):
        raise subprocess.TimeoutExpired(cmd=["/tmp/plc-cli"], timeout=1)

    monkeypatch.setattr("subprocess.run", _raise_timeout)
    executor = CLIBasedPLCExecutor(cli_path="/tmp/plc-cli", timeout_seconds=1)

    with pytest.raises(PLCExecutorTransportError, match="timed out"):
        executor.run_case(_build_request())


def test_cli_executor_raises_for_schema_validation_failure(monkeypatch) -> None:
    class _Completed:
        returncode = 0
        stdout = json.dumps({"status": "unexpected-status"})
        stderr = "warning: missing fields"

    monkeypatch.setattr("subprocess.run", lambda *args, **kwargs: _Completed())
    executor = CLIBasedPLCExecutor(cli_path="/tmp/plc-cli", timeout_seconds=1)

    with pytest.raises(PLCExecutorTransportError, match="schema validation failed"):
        executor.run_case(_build_request())


def test_execute_plc_job_raises_on_executor_transport_error(monkeypatch) -> None:
    class _Executor:
        def run_case(self, request):
            raise PLCExecutorTransportError("transport failed")

    monkeypatch.setattr(
        "api.services.plc.job_runner.get_plc_executor", lambda settings: _Executor()
    )

    payload = {
        "suite_id": "plc-suite-1",
        "suite_title": "Suite",
        "target_key": "stub-local",
        "testcases": [
            {
                "id": "plc-suite-1::ADD_001",
                "case_key": "ADD_001",
                "instruction_name": "add",
                "input_type": "LWORD",
                "output_type": "LWORD",
                "input_vector_json": [1, 1],
                "expected_output_json": 2,
                "expected_outputs_json": [2],
                "memory_profile_key": "ls_add_lword_v1",
                "description": None,
                "tags": [],
                "timeout_ms": 3000,
                "source_row_number": 2,
                "source_case_index": 0,
                "expected_outcome": "pass",
            }
        ],
    }

    with pytest.raises(PLCExecutorTransportError, match="transport failed"):
        execute_plc_job(payload)


def test_execute_plc_job_marks_executor_failed_status_as_item_error(
    monkeypatch,
) -> None:
    class _Executor:
        def run_case(self, request):
            return PLCExecutionResultModel(
                status="failed",
                actual_output=None,
                expected_output=2,
                duration_ms=5,
                raw_log="executor reported case-level issue",
                executor_exit_code=0,
                diagnostics=["case-level issue"],
            )

    monkeypatch.setattr(
        "api.services.plc.job_runner.get_plc_executor", lambda settings: _Executor()
    )

    payload = {
        "suite_id": "plc-suite-1",
        "suite_title": "Suite",
        "target_key": "stub-local",
        "testcases": [
            {
                "id": "plc-suite-1::ADD_001",
                "case_key": "ADD_001",
                "instruction_name": "add",
                "input_type": "LWORD",
                "output_type": "LWORD",
                "input_vector_json": [1, 1],
                "expected_output_json": 2,
                "expected_outputs_json": [2],
                "memory_profile_key": "ls_add_lword_v1",
                "description": None,
                "tags": [],
                "timeout_ms": 3000,
                "source_row_number": 2,
                "source_case_index": 0,
                "expected_outcome": "pass",
            }
        ],
    }

    result = execute_plc_job(payload)

    assert result["error_count"] == 1
    assert result["failed_count"] == 0
    assert result["items"][0]["status"] == "error"
    assert (
        result["items"][0]["validator_result_json"]["validator"] == "executor-status.v1"
    )
