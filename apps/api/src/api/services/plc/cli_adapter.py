from __future__ import annotations

import json
import subprocess

from api.services.plc.contracts import PLCExecutionRequestModel, PLCExecutionResultModel


class CLIBasedPLCExecutor:
    def __init__(self, *, cli_path: str | None, timeout_seconds: int) -> None:
        self._cli_path = cli_path
        self._timeout_seconds = timeout_seconds

    def run_case(self, request: PLCExecutionRequestModel) -> PLCExecutionResultModel:
        if not self._cli_path:
            raise RuntimeError("PLC_CLI_PATH is not configured for cli executor mode")

        completed = subprocess.run(
            [self._cli_path],
            input=request.model_dump_json(),
            capture_output=True,
            text=True,
            check=False,
            timeout=self._timeout_seconds,
        )
        if completed.returncode != 0:
            stderr = completed.stderr.strip() or completed.stdout.strip() or "<empty>"
            raise RuntimeError(
                f"PLC CLI failed (exit={completed.returncode}): {stderr}"
            )

        try:
            payload = json.loads(completed.stdout)
        except json.JSONDecodeError as exc:
            raise RuntimeError("PLC CLI returned invalid JSON") from exc
        if not isinstance(payload, dict):
            raise RuntimeError("PLC CLI result must be a JSON object")
        return PLCExecutionResultModel.model_validate(payload)
