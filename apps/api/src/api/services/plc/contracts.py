from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class PLCTestCaseModel(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    case_key: str
    instruction_name: str
    input_type: str
    output_type: str
    input_vector_json: list[Any]
    expected_output_json: Any
    expected_outputs_json: list[Any]
    memory_profile_key: str | None = None
    description: str | None = None
    tags: list[str] = Field(default_factory=list)
    timeout_ms: int = Field(default=3000, ge=1)
    source_row_number: int = Field(ge=1)
    source_case_index: int = Field(ge=0)
    expected_outcome: Literal["pass", "fail"] = "pass"


class PLCTestSuiteDefinitionModel(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["plc-suite.v1"] = "plc-suite.v1"
    cases: list[PLCTestCaseModel]
    warnings: list[str] = Field(default_factory=list)


class PLCTestSuiteSummaryModel(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    title: str
    source_filename: str
    source_format: str
    case_count: int
    created_at: str | None = None
    updated_at: str | None = None


class PLCTestSuiteDetailModel(PLCTestSuiteSummaryModel):
    definition_json: PLCTestSuiteDefinitionModel


class PLCExecutionRequestModel(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["plc-execution-request.v1"] = "plc-execution-request.v1"
    testcase_id: str
    instruction: str
    input_type: str
    output_type: str
    inputs: list[Any]
    expected: Any
    expected_outcome: Literal["pass", "fail"] = "pass"
    memory_profile_key: str | None = None
    timeout_ms: int = Field(default=3000, ge=1)
    target_key: str | None = None
    testcase_metadata: dict[str, Any] = Field(default_factory=dict)
    execution_context: dict[str, Any] = Field(default_factory=dict)


class PLCIOMemoryValueModel(BaseModel):
    model_config = ConfigDict(extra="forbid")

    address: str
    value: Any
    symbol: str | None = None
    raw_type: str | None = None


class PLCExecutionResultModel(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["plc-execution-result.v1"] = "plc-execution-result.v1"
    status: Literal["completed", "failed"]
    write_values: list[PLCIOMemoryValueModel] = Field(default_factory=list)
    read_values: list[PLCIOMemoryValueModel] = Field(default_factory=list)
    actual_output: Any = None
    expected_output: Any = None
    duration_ms: int = Field(default=0, ge=0)
    raw_log: str = ""
    executor_exit_code: int = 0
    diagnostics: list[str] = Field(default_factory=list)
    warning_codes: list[str] = Field(default_factory=list)
    executor_metadata: dict[str, Any] = Field(default_factory=dict)


class PLCValidationResultModel(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: Literal["passed", "failed"]
    validator: str
    reason: str | None = None
    expected_output_json: Any = None
    actual_output_json: Any = None
    type_mismatch: bool = False


class PLCTestRunItemModel(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    testcase_id: str
    case_key: str
    instruction_name: str
    status: Literal["passed", "failed", "error"]
    expected_output_json: Any = None
    actual_output_json: Any = None
    validator_result_json: dict[str, Any]
    failure_reason: str | None = None
    duration_ms: int = Field(default=0, ge=0)
    io_logs: list[dict[str, Any]] = Field(default_factory=list)
    executor_log: str = ""


class PLCTestRunResultModel(BaseModel):
    model_config = ConfigDict(extra="forbid")

    suite_id: str
    suite_title: str
    target_key: str
    executor_mode: str
    validator_version: str
    total_count: int
    passed_count: int
    failed_count: int
    error_count: int
    items: list[PLCTestRunItemModel]
    warnings: list[str] = Field(default_factory=list)
