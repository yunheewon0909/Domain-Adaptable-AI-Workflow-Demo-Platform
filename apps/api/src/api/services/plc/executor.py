from __future__ import annotations

from typing import Protocol

from api.config import Settings
from api.services.plc.cli_adapter import CLIBasedPLCExecutor
from api.services.plc.contracts import PLCExecutionRequestModel, PLCExecutionResultModel
from api.services.plc.stub_executor import DeterministicStubPLCExecutor


class PLCExecutor(Protocol):
    def run_case(
        self, request: PLCExecutionRequestModel
    ) -> PLCExecutionResultModel: ...


def get_plc_executor(settings: Settings) -> PLCExecutor:
    if settings.plc_executor_mode == "cli":
        return CLIBasedPLCExecutor(
            cli_path=settings.plc_cli_path,
            timeout_seconds=settings.plc_cli_timeout_seconds,
        )
    return DeterministicStubPLCExecutor()
