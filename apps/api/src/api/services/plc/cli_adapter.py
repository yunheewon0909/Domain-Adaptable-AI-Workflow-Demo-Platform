from __future__ import annotations

import json
import subprocess

from api.services.plc.contracts import PLCExecutionRequestModel, PLCExecutionResultModel


class PLCExecutorTransportError(RuntimeError):
    pass


class CLIBasedPLCExecutor:
    def __init__(self, *, cli_path: str | None, timeout_seconds: int) -> None:
        self._cli_path = cli_path
        self._timeout_seconds = timeout_seconds

    def run_case(self, request: PLCExecutionRequestModel) -> PLCExecutionResultModel:
        if not self._cli_path:
            raise PLCExecutorTransportError(
                "PLC_CLI_PATH is not configured for cli executor mode"
            )

        try:
            completed = subprocess.run(
                [self._cli_path],
                input=request.model_dump_json(),
                capture_output=True,
                text=True,
                check=False,
                timeout=self._timeout_seconds,
            )
        except subprocess.TimeoutExpired as exc:
            raise PLCExecutorTransportError(
                f"PLC CLI timed out after {self._timeout_seconds}s"
            ) from exc
        if completed.returncode != 0:
            stderr = completed.stderr.strip() or completed.stdout.strip() or "<empty>"
            raise PLCExecutorTransportError(
                f"PLC CLI failed (exit={completed.returncode}): {stderr}"
            )

        stdout = completed.stdout.strip()
        if not stdout:
            raise PLCExecutorTransportError("PLC CLI returned empty stdout")

        try:
            payload = json.loads(stdout)
        except json.JSONDecodeError as exc:
            raise PLCExecutorTransportError("PLC CLI returned invalid JSON") from exc
        if not isinstance(payload, dict):
            raise PLCExecutorTransportError("PLC CLI result must be a JSON object")

        if payload.get("executor_exit_code") is None:
            payload["executor_exit_code"] = completed.returncode
        if completed.stderr.strip():
            diagnostics = payload.get("diagnostics")
            if not isinstance(diagnostics, list):
                diagnostics = []
            payload["diagnostics"] = [
                *[str(item) for item in diagnostics],
                completed.stderr.strip(),
            ]

        try:
            return PLCExecutionResultModel.model_validate(payload)
        except Exception as exc:
            raise PLCExecutorTransportError(
                f"PLC CLI result schema validation failed: {exc}"
            ) from exc
