import json

import pytest

from api.services.plc.cli_adapter import CLIBasedPLCExecutor
from api.services.plc.contracts import PLCExecutionRequestModel
from api.services.plc.stub_executor import DeterministicStubPLCExecutor


def _build_request(*, expected_outcome: str = "pass") -> PLCExecutionRequestModel:
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
    with pytest.raises(RuntimeError):
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
