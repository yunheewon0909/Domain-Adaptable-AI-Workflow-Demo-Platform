from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from api.models import (
    PLCLLMSuggestionRecord,
    PLCTestCaseRecord,
    PLCTestRunIOLogRecord,
    PLCTestRunItemRecord,
    PLCTestRunRecord,
    PLCTestTargetRecord,
)
from api.services.jobs import to_iso
from api.services.plc.contracts import PLCTestCaseModel, PLCTestRunResultModel


STUB_LOCAL_TARGET = {
    "key": "stub-local",
    "display_name": "Stub Local",
    "description": "Deterministic in-repo stub executor target for PLC test reviews.",
    "executor_mode": "stub",
    "metadata_json": {},
    "is_active": True,
    "created_at": None,
    "updated_at": None,
}


def _serialize_target_record(target: PLCTestTargetRecord) -> dict[str, Any]:
    return {
        "key": target.key,
        "display_name": target.display_name,
        "description": target.description,
        "executor_mode": target.executor_mode,
        "metadata_json": target.metadata_json,
        "is_active": target.is_active,
        "created_at": to_iso(target.created_at),
        "updated_at": to_iso(target.updated_at),
    }


def create_plc_run(
    session: Session,
    *,
    run_id: str,
    suite_id: str,
    target_key: str,
    backing_job_id: str,
    cases: list[PLCTestCaseModel],
) -> PLCTestRunRecord:
    run = PLCTestRunRecord(
        id=run_id,
        suite_id=suite_id,
        target_key=target_key,
        backing_job_id=backing_job_id,
        status="queued",
        total_count=len(cases),
        queued_count=len(cases),
        running_count=0,
        passed_count=0,
        failed_count=0,
        error_count=0,
    )
    session.add(run)
    session.add_all(
        [
            PLCTestRunItemRecord(
                id=f"{run_id}::{case.case_key}::result",
                run_id=run_id,
                testcase_id=case.id,
                case_key=case.case_key,
                instruction_name=case.instruction_name,
                status="queued",
                expected_output_json=case.expected_output_json,
                actual_output_json=None,
                validator_result_json={},
                failure_reason=None,
                duration_ms=0,
                executor_log="",
                started_at=None,
                finished_at=None,
            )
            for case in cases
        ]
    )
    session.flush()
    return run


def mark_plc_run_running(session: Session, *, run_id: str) -> None:
    run = session.get(PLCTestRunRecord, run_id)
    if run is None:
        return
    started_at = datetime.now(timezone.utc)
    run.status = "running"
    run.started_at = run.started_at or started_at
    run.running_count = run.total_count
    run.queued_count = 0

    items = session.scalars(
        select(PLCTestRunItemRecord).where(PLCTestRunItemRecord.run_id == run_id)
    ).all()
    for item in items:
        item.status = "running"
        item.started_at = item.started_at or started_at
    session.flush()


def mark_plc_run_failed(
    session: Session, *, run_id: str, failure_reason: str | None = None
) -> None:
    run = session.get(PLCTestRunRecord, run_id)
    if run is None:
        return
    finished_at = datetime.now(timezone.utc)
    run.status = "failed"
    run.finished_at = finished_at
    run.running_count = 0
    remaining_items = session.scalars(
        select(PLCTestRunItemRecord).where(PLCTestRunItemRecord.run_id == run_id)
    ).all()
    queued_or_running = [
        item for item in remaining_items if item.status in {"queued", "running"}
    ]
    if queued_or_running:
        run.error_count += len(queued_or_running)
    run.queued_count = 0
    for item in queued_or_running:
        item.status = "error"
        item.failure_reason = failure_reason or item.failure_reason or "PLC run failed"
        item.finished_at = finished_at
    session.flush()


def persist_plc_run_result(
    session: Session,
    *,
    run_id: str,
    result: PLCTestRunResultModel,
) -> None:
    run = session.get(PLCTestRunRecord, run_id)
    if run is None:
        return

    finished_at = datetime.now(timezone.utc)
    run.started_at = run.started_at or finished_at
    run.finished_at = finished_at
    run.total_count = result.total_count
    run.queued_count = 0
    run.running_count = 0
    run.passed_count = result.passed_count
    run.failed_count = result.failed_count
    run.error_count = result.error_count

    items = {
        item.id: item
        for item in session.scalars(
            select(PLCTestRunItemRecord).where(PLCTestRunItemRecord.run_id == run_id)
        ).all()
    }

    for result_item in result.items:
        item = items.get(result_item.id)
        if item is None:
            item = PLCTestRunItemRecord(
                id=result_item.id,
                run_id=run_id,
                testcase_id=result_item.testcase_id,
                case_key=result_item.case_key,
                instruction_name=result_item.instruction_name,
                status=result_item.status,
                expected_output_json=result_item.expected_output_json,
                actual_output_json=result_item.actual_output_json,
                validator_result_json=result_item.validator_result_json,
                failure_reason=result_item.failure_reason,
                duration_ms=result_item.duration_ms,
                executor_log=result_item.executor_log,
                started_at=run.started_at,
                finished_at=finished_at,
            )
            session.add(item)
        else:
            item.status = result_item.status
            item.expected_output_json = result_item.expected_output_json
            item.actual_output_json = result_item.actual_output_json
            item.validator_result_json = result_item.validator_result_json
            item.failure_reason = result_item.failure_reason
            item.duration_ms = result_item.duration_ms
            item.executor_log = result_item.executor_log
            item.started_at = item.started_at or run.started_at
            item.finished_at = finished_at

        session.execute(
            delete(PLCTestRunIOLogRecord).where(
                PLCTestRunIOLogRecord.run_item_id == item.id
            )
        )
        session.add_all(
            [
                PLCTestRunIOLogRecord(
                    run_item_id=item.id,
                    direction=str(log.get("direction", "unknown")),
                    memory_address=(
                        str(log["memory_address"])
                        if log.get("memory_address") is not None
                        else None
                    ),
                    memory_symbol=(
                        str(log["memory_symbol"])
                        if log.get("memory_symbol") is not None
                        else None
                    ),
                    value_json=log.get("value_json"),
                    raw_type=(
                        str(log["raw_type"])
                        if log.get("raw_type") is not None
                        else None
                    ),
                    sequence_no=int(log.get("sequence_no", 0)),
                )
                for log in result_item.io_logs
            ]
        )
    session.flush()


def list_plc_run_items(session: Session, *, run_id: str) -> list[dict[str, Any]]:
    items = session.scalars(
        select(PLCTestRunItemRecord)
        .where(PLCTestRunItemRecord.run_id == run_id)
        .order_by(PLCTestRunItemRecord.id.asc())
    ).all()
    if not items:
        return []
    io_logs = session.scalars(
        select(PLCTestRunIOLogRecord)
        .where(PLCTestRunIOLogRecord.run_item_id.in_([item.id for item in items]))
        .order_by(
            PLCTestRunIOLogRecord.run_item_id.asc(),
            PLCTestRunIOLogRecord.sequence_no.asc(),
        )
    ).all()
    io_logs_by_item: dict[str, list[dict[str, Any]]] = {}
    for log in io_logs:
        io_logs_by_item.setdefault(log.run_item_id, []).append(
            {
                "direction": log.direction,
                "memory_address": log.memory_address,
                "memory_symbol": log.memory_symbol,
                "value_json": log.value_json,
                "raw_type": log.raw_type,
                "sequence_no": log.sequence_no,
                "recorded_at": to_iso(log.recorded_at),
            }
        )
    return [
        {
            "id": item.id,
            "testcase_id": item.testcase_id,
            "case_key": item.case_key,
            "instruction_name": item.instruction_name,
            "status": item.status,
            "expected_output_json": item.expected_output_json,
            "actual_output_json": item.actual_output_json,
            "validator_result_json": item.validator_result_json,
            "failure_reason": item.failure_reason,
            "duration_ms": item.duration_ms,
            "io_logs": io_logs_by_item.get(item.id, []),
            "executor_log": item.executor_log,
            "started_at": to_iso(item.started_at),
            "finished_at": to_iso(item.finished_at),
        }
        for item in items
    ]


def list_plc_run_io_logs(session: Session, *, run_id: str) -> list[dict[str, Any]]:
    item_ids = session.scalars(
        select(PLCTestRunItemRecord.id).where(PLCTestRunItemRecord.run_id == run_id)
    ).all()
    if not item_ids:
        return []
    logs = session.scalars(
        select(PLCTestRunIOLogRecord)
        .where(PLCTestRunIOLogRecord.run_item_id.in_(item_ids))
        .order_by(
            PLCTestRunIOLogRecord.run_item_id.asc(),
            PLCTestRunIOLogRecord.sequence_no.asc(),
        )
    ).all()
    return [
        {
            "id": log.id,
            "run_item_id": log.run_item_id,
            "direction": log.direction,
            "memory_address": log.memory_address,
            "memory_symbol": log.memory_symbol,
            "value_json": log.value_json,
            "raw_type": log.raw_type,
            "sequence_no": log.sequence_no,
            "recorded_at": to_iso(log.recorded_at),
        }
        for log in logs
    ]


def list_plc_targets(session: Session) -> list[dict[str, Any]]:
    targets = session.scalars(
        select(PLCTestTargetRecord).order_by(PLCTestTargetRecord.key.asc())
    ).all()
    items = [_serialize_target_record(target) for target in targets]
    if not any(target["key"] == STUB_LOCAL_TARGET["key"] for target in items):
        items.insert(0, dict(STUB_LOCAL_TARGET))
    return items


def resolve_plc_target(session: Session, *, target_key: str) -> dict[str, Any] | None:
    normalized_key = target_key.strip()
    if not normalized_key:
        return None
    if normalized_key == STUB_LOCAL_TARGET["key"]:
        target = session.get(PLCTestTargetRecord, normalized_key)
        return (
            _serialize_target_record(target)
            if target is not None
            else dict(STUB_LOCAL_TARGET)
        )

    target = session.get(PLCTestTargetRecord, normalized_key)
    if target is None:
        return None
    return _serialize_target_record(target)


def create_plc_llm_suggestion(
    session: Session,
    *,
    suite_id: str | None,
    testcase_id: str | None,
    suggestion_type: str,
    source_payload_json: dict[str, Any],
    suggestion_payload_json: dict[str, Any],
) -> dict[str, Any]:
    record = PLCLLMSuggestionRecord(
        suite_id=suite_id,
        testcase_id=testcase_id,
        suggestion_type=suggestion_type,
        source_payload_json=source_payload_json,
        suggestion_payload_json=suggestion_payload_json,
        status="pending",
    )
    session.add(record)
    session.commit()
    session.refresh(record)
    return serialize_plc_llm_suggestion(record)


def serialize_plc_llm_suggestion(record: PLCLLMSuggestionRecord) -> dict[str, Any]:
    return {
        "id": record.id,
        "suite_id": record.suite_id,
        "testcase_id": record.testcase_id,
        "suggestion_type": record.suggestion_type,
        "source_payload_json": record.source_payload_json,
        "suggestion_payload_json": record.suggestion_payload_json,
        "status": record.status,
        "created_at": to_iso(record.created_at),
        "reviewed_at": to_iso(record.reviewed_at),
    }


def list_plc_llm_suggestions(
    session: Session,
    *,
    suite_id: str | None = None,
    testcase_id: str | None = None,
    status: str | None = None,
) -> list[dict[str, Any]]:
    stmt = select(PLCLLMSuggestionRecord)
    if suite_id is not None:
        stmt = stmt.where(PLCLLMSuggestionRecord.suite_id == suite_id)
    if testcase_id is not None:
        stmt = stmt.where(PLCLLMSuggestionRecord.testcase_id == testcase_id)
    if status is not None:
        stmt = stmt.where(PLCLLMSuggestionRecord.status == status)
    records = session.scalars(
        stmt.order_by(
            PLCLLMSuggestionRecord.created_at.desc(),
            PLCLLMSuggestionRecord.id.desc(),
        )
    ).all()
    return [serialize_plc_llm_suggestion(record) for record in records]


def get_plc_llm_suggestion(
    session: Session, *, suggestion_id: int
) -> dict[str, Any] | None:
    record = session.get(PLCLLMSuggestionRecord, suggestion_id)
    if record is None:
        return None
    return serialize_plc_llm_suggestion(record)


def review_plc_llm_suggestion(
    session: Session, *, suggestion_id: int, status: str
) -> dict[str, Any] | None:
    record = session.get(PLCLLMSuggestionRecord, suggestion_id)
    if record is None:
        return None
    record.status = status
    record.reviewed_at = datetime.now(timezone.utc)
    session.commit()
    session.refresh(record)
    return serialize_plc_llm_suggestion(record)


def build_plc_job_summary(result: PLCTestRunResultModel) -> dict[str, Any]:
    return {
        "suite_id": result.suite_id,
        "suite_title": result.suite_title,
        "target_key": result.target_key,
        "executor_mode": result.executor_mode,
        "validator_version": result.validator_version,
        "total_count": result.total_count,
        "passed_count": result.passed_count,
        "failed_count": result.failed_count,
        "error_count": result.error_count,
        "warnings": result.warnings,
    }


def get_testcase_models_for_suite(
    session: Session, *, suite_id: str
) -> list[PLCTestCaseModel]:
    records = session.scalars(
        select(PLCTestCaseRecord)
        .where(PLCTestCaseRecord.suite_id == suite_id)
        .where(PLCTestCaseRecord.is_active.is_(True))
        .order_by(
            PLCTestCaseRecord.source_row_number.asc(),
            PLCTestCaseRecord.source_case_index.asc(),
            PLCTestCaseRecord.id.asc(),
        )
    ).all()
    return [
        PLCTestCaseModel(
            id=record.id,
            case_key=record.case_key,
            instruction_name=record.instruction_name,
            input_type=record.input_type,
            output_type=record.output_type,
            input_vector_json=record.input_vector_json,
            expected_output_json=record.expected_output_json,
            expected_outputs_json=record.expected_outputs_json,
            memory_profile_key=record.memory_profile_key,
            description=record.description,
            tags=record.tags_json,
            timeout_ms=record.timeout_ms,
            source_row_number=record.source_row_number,
            source_case_index=record.source_case_index,
            expected_outcome=("fail" if record.expected_outcome == "fail" else "pass"),
        )
        for record in records
    ]


def get_testcase_record(
    session: Session, *, testcase_id: str
) -> PLCTestCaseRecord | None:
    return session.get(PLCTestCaseRecord, testcase_id)
