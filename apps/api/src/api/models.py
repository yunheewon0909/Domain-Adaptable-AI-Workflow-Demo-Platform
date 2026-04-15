from datetime import datetime
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from api.db import Base


class JobRecord(Base):
    __tablename__ = "jobs"
    __table_args__ = (
        Index("ix_jobs_type_status_created_at", "type", "status", "created_at"),
        Index(
            "ix_jobs_workflow_dataset_status_created_at",
            "workflow_key",
            "dataset_key",
            "status",
            "created_at",
        ),
        Index(
            "ix_jobs_dataset_status_created_at", "dataset_key", "status", "created_at"
        ),
        Index(
            "ix_jobs_plc_suite_status_created_at",
            "plc_suite_id",
            "status",
            "created_at",
        ),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    type: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        server_default=text("'generic'"),
    )
    workflow_key: Mapped[str | None] = mapped_column(String(64), nullable=True)
    dataset_key: Mapped[str | None] = mapped_column(String(64), nullable=True)
    plc_suite_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    payload_json: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    attempts: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        server_default=text("0"),
    )
    max_attempts: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        server_default=text("3"),
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("CURRENT_TIMESTAMP"),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("CURRENT_TIMESTAMP"),
    )
    started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    finished_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    result_json: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)


class DatasetRecord(Base):
    __tablename__ = "datasets"
    __table_args__ = (
        Index("ix_datasets_is_active", "is_active"),
        Index("ix_datasets_profile_key", "profile_key"),
    )

    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    domain_type: Mapped[str] = mapped_column(String(64), nullable=False)
    profile_key: Mapped[str] = mapped_column(String(64), nullable=False)
    source_dir: Mapped[str] = mapped_column(String(512), nullable=False)
    index_dir: Mapped[str] = mapped_column(String(512), nullable=False)
    db_path: Mapped[str] = mapped_column(String(512), nullable=False)
    is_active: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        server_default=text("false"),
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("CURRENT_TIMESTAMP"),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("CURRENT_TIMESTAMP"),
    )


class PLCTestSuiteRecord(Base):
    __tablename__ = "plc_test_suites"
    __table_args__ = (
        Index("ix_plc_test_suites_created_at", "created_at"),
        Index("ix_plc_test_suites_source_format", "source_format"),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    source_filename: Mapped[str] = mapped_column(String(255), nullable=False)
    source_format: Mapped[str] = mapped_column(String(16), nullable=False)
    case_count: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        server_default=text("0"),
    )
    definition_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("CURRENT_TIMESTAMP"),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("CURRENT_TIMESTAMP"),
    )


class PLCTestExecutionProfileRecord(Base):
    __tablename__ = "plc_execution_profiles"
    __table_args__ = (
        Index("ix_plc_execution_profiles_memory_profile_key", "memory_profile_key"),
        Index("ix_plc_execution_profiles_instruction_name", "instruction_name"),
        Index("ix_plc_execution_profiles_is_active", "is_active"),
    )

    key: Mapped[str] = mapped_column(String(255), primary_key=True)
    memory_profile_key: Mapped[str | None] = mapped_column(String(255), nullable=True)
    instruction_name: Mapped[str] = mapped_column(String(255), nullable=False)
    input_type: Mapped[str] = mapped_column(String(64), nullable=False)
    output_type: Mapped[str] = mapped_column(String(64), nullable=False)
    profile_version: Mapped[str | None] = mapped_column(String(64), nullable=True)
    timeout_policy_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    setup_requirements_json: Mapped[dict[str, Any]] = mapped_column(
        JSON, nullable=False
    )
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    address_contract_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("true")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("CURRENT_TIMESTAMP"),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("CURRENT_TIMESTAMP"),
    )


class PLCTestCaseRecord(Base):
    __tablename__ = "plc_testcases"
    __table_args__ = (
        UniqueConstraint(
            "suite_id", "case_key", name="uq_plc_testcases_suite_case_key"
        ),
        Index("ix_plc_testcases_suite_id", "suite_id"),
        Index("ix_plc_testcases_instruction_name", "instruction_name"),
        Index("ix_plc_testcases_input_type", "input_type"),
        Index("ix_plc_testcases_is_active", "is_active"),
        Index("ix_plc_testcases_created_at", "created_at"),
    )

    id: Mapped[str] = mapped_column(String(128), primary_key=True)
    suite_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("plc_test_suites.id"), nullable=False
    )
    testcase_key: Mapped[str] = mapped_column(String(128), nullable=False)
    case_key: Mapped[str] = mapped_column(String(128), nullable=False)
    instruction_name: Mapped[str] = mapped_column(String(255), nullable=False)
    input_type: Mapped[str] = mapped_column(String(64), nullable=False)
    output_type: Mapped[str] = mapped_column(String(64), nullable=False)
    input_vector_json: Mapped[list[Any]] = mapped_column(JSON, nullable=False)
    expected_output_json: Mapped[Any] = mapped_column(JSON, nullable=False)
    expected_outputs_json: Mapped[list[Any]] = mapped_column(JSON, nullable=False)
    expected_outcome: Mapped[str] = mapped_column(
        String(16), nullable=False, server_default=text("'pass'")
    )
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    tags_json: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    memory_profile_key: Mapped[str | None] = mapped_column(String(255), nullable=True)
    execution_profile_key: Mapped[str | None] = mapped_column(
        String(255), ForeignKey("plc_execution_profiles.key"), nullable=True
    )
    timeout_ms: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("3000")
    )
    source_row_number: Mapped[int] = mapped_column(Integer, nullable=False)
    source_case_index: Mapped[int] = mapped_column(Integer, nullable=False)
    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("true")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("CURRENT_TIMESTAMP"),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("CURRENT_TIMESTAMP"),
    )


class PLCTestTargetRecord(Base):
    __tablename__ = "plc_targets"
    __table_args__ = (
        Index("ix_plc_targets_is_active", "is_active"),
        Index("ix_plc_targets_created_at", "created_at"),
    )

    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    display_name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    executor_mode: Mapped[str] = mapped_column(String(32), nullable=False)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("true")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("CURRENT_TIMESTAMP"),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("CURRENT_TIMESTAMP"),
    )


class PLCLLMSuggestionRecord(Base):
    __tablename__ = "plc_llm_suggestions"
    __table_args__ = (
        Index("ix_plc_llm_suggestions_status_created_at", "status", "created_at"),
        Index("ix_plc_llm_suggestions_suite_id", "suite_id"),
        Index("ix_plc_llm_suggestions_testcase_id", "testcase_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    suite_id: Mapped[str | None] = mapped_column(
        String(64), ForeignKey("plc_test_suites.id"), nullable=True
    )
    testcase_id: Mapped[str | None] = mapped_column(
        String(128), ForeignKey("plc_testcases.id"), nullable=True
    )
    suggestion_type: Mapped[str] = mapped_column(String(64), nullable=False)
    payload_schema_version: Mapped[str] = mapped_column(String(64), nullable=False)
    source_payload_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    suggestion_payload_json: Mapped[dict[str, Any]] = mapped_column(
        JSON, nullable=False
    )
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, server_default=text("'pending'")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("CURRENT_TIMESTAMP"),
    )
    reviewed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


class PLCTestRunRecord(Base):
    __tablename__ = "plc_test_runs"
    __table_args__ = (
        UniqueConstraint("backing_job_id", name="uq_plc_test_runs_backing_job_id"),
        Index("ix_plc_test_runs_suite_id_created_at", "suite_id", "created_at"),
        Index("ix_plc_test_runs_status_created_at", "status", "created_at"),
        Index("ix_plc_test_runs_target_key", "target_key"),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    suite_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("plc_test_suites.id"), nullable=False
    )
    target_key: Mapped[str] = mapped_column(String(64), nullable=False)
    backing_job_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("jobs.id"), nullable=False
    )
    request_schema_version: Mapped[str | None] = mapped_column(
        String(64), nullable=True
    )
    executor_mode: Mapped[str | None] = mapped_column(String(32), nullable=True)
    validator_version: Mapped[str | None] = mapped_column(String(64), nullable=True)
    target_snapshot_json: Mapped[dict[str, Any] | None] = mapped_column(
        JSON, nullable=True
    )
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    total_count: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("0")
    )
    queued_count: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("0")
    )
    running_count: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("0")
    )
    passed_count: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("0")
    )
    failed_count: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("0")
    )
    error_count: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("0")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("CURRENT_TIMESTAMP"),
    )
    started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    finished_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


class PLCTestRunItemRecord(Base):
    __tablename__ = "plc_test_run_items"
    __table_args__ = (
        UniqueConstraint(
            "run_id", "testcase_id", name="uq_plc_test_run_items_run_testcase"
        ),
        Index("ix_plc_test_run_items_run_id", "run_id"),
        Index("ix_plc_test_run_items_testcase_id", "testcase_id"),
        Index("ix_plc_test_run_items_status", "status"),
        Index("ix_plc_test_run_items_case_key", "case_key"),
    )

    id: Mapped[str] = mapped_column(String(160), primary_key=True)
    run_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("plc_test_runs.id"), nullable=False
    )
    testcase_id: Mapped[str] = mapped_column(
        String(128), ForeignKey("plc_testcases.id"), nullable=False
    )
    case_key: Mapped[str] = mapped_column(String(128), nullable=False)
    instruction_name: Mapped[str] = mapped_column(String(255), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    input_type: Mapped[str | None] = mapped_column(String(64), nullable=True)
    output_type: Mapped[str | None] = mapped_column(String(64), nullable=True)
    timeout_ms: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("3000")
    )
    expected_outcome: Mapped[str] = mapped_column(
        String(16), nullable=False, server_default=text("'pass'")
    )
    memory_profile_key: Mapped[str | None] = mapped_column(String(255), nullable=True)
    execution_profile_key: Mapped[str | None] = mapped_column(
        String(255), nullable=True
    )
    inputs_json: Mapped[list[Any] | None] = mapped_column(JSON, nullable=True)
    request_context_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    expected_output_json: Mapped[Any] = mapped_column(JSON, nullable=False)
    actual_output_json: Mapped[Any] = mapped_column(JSON, nullable=True)
    validator_result_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    failure_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    duration_ms: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("0")
    )
    executor_log: Mapped[str] = mapped_column(
        Text, nullable=False, server_default=text("''")
    )
    started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    finished_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


class PLCTestRunIOLogRecord(Base):
    __tablename__ = "plc_test_run_io_logs"
    __table_args__ = (
        Index("ix_plc_test_run_io_logs_run_item_id", "run_item_id"),
        Index(
            "ix_plc_test_run_io_logs_run_item_sequence",
            "run_item_id",
            "sequence_no",
        ),
        Index("ix_plc_test_run_io_logs_direction", "direction"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_item_id: Mapped[str] = mapped_column(
        String(160), ForeignKey("plc_test_run_items.id"), nullable=False
    )
    direction: Mapped[str] = mapped_column(String(16), nullable=False)
    memory_address: Mapped[str | None] = mapped_column(String(128), nullable=True)
    memory_symbol: Mapped[str | None] = mapped_column(String(128), nullable=True)
    value_json: Mapped[Any] = mapped_column(JSON, nullable=True)
    raw_type: Mapped[str | None] = mapped_column(String(64), nullable=True)
    sequence_no: Mapped[int] = mapped_column(Integer, nullable=False)
    recorded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("CURRENT_TIMESTAMP"),
    )


class WorkerHeartbeatRecord(Base):
    __tablename__ = "worker_heartbeats"

    worker_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    last_heartbeat: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("CURRENT_TIMESTAMP"),
    )
