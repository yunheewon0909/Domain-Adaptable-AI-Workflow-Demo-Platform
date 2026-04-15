from pathlib import Path

from openpyxl import Workbook
import pytest
from sqlalchemy.orm import Session

from api.db import get_engine
from api.models import (
    PLCTestCaseRecord,
    PLCTestExecutionProfileRecord,
    PLCTestRunIOLogRecord,
    PLCTestRunItemRecord,
    PLCTestRunRecord,
)
from api.services.plc.contracts import PLCTestRunResultModel
from api.services.plc.job_runner import execute_plc_job
from api.services.plc.persistence import create_plc_run
from api.services.plc.service import (
    PLCImportError,
    build_normalization_suggestion,
    create_plc_job_payload,
    flatten_cases,
    import_plc_suite,
)


def test_import_plc_suite_expands_multiple_cases_from_single_csv_row(client) -> None:
    csv_bytes = (
        "instruction_name,input_values,expected_outputs,input_type,output_type,description,tags,memory_profile_key\n"
        'add,"[[1,1],[2,2],[4,4]]","[2,4,8]",LWORD,LWORD,adder,"smoke,math",ls_add_lword_v1\n'
    ).encode("utf-8")

    with Session(get_engine()) as session:
        suite, imported_count, rejected_count = import_plc_suite(
            session,
            filename="ls-add.csv",
            file_bytes=csv_bytes,
            title="LS Add",
        )

    assert suite.title == "LS Add"
    assert imported_count == 3
    assert rejected_count == 0
    assert [case.case_key for case in suite.definition_json.cases] == [
        "ADD_001",
        "ADD_002",
        "ADD_003",
    ]
    assert suite.definition_json.cases[0].memory_profile_key == "ls_add_lword_v1"
    assert suite.definition_json.cases[0].execution_profile_key == "ls-add-lword-v1"
    assert suite.definition_json.cases[0].execution_profile is not None
    assert suite.definition_json.cases[0].tags == ["smoke", "math"]

    with Session(get_engine()) as session:
        persisted_cases = session.query(PLCTestCaseRecord).all()
        persisted_profiles = session.query(PLCTestExecutionProfileRecord).all()

    assert [case.id for case in persisted_cases] == [
        "plc-suite-1::ADD_001",
        "plc-suite-1::ADD_002",
        "plc-suite-1::ADD_003",
    ]
    assert persisted_cases[0].suite_id == suite.id
    assert persisted_cases[0].tags_json == ["smoke", "math"]
    assert persisted_cases[0].execution_profile_key == "ls-add-lword-v1"
    assert len(persisted_profiles) == 1
    assert persisted_profiles[0].key == "ls-add-lword-v1"
    assert persisted_profiles[0].timeout_policy_json["default_timeout_ms"] == 3000


def test_import_plc_suite_reads_xlsx(tmp_path: Path, client) -> None:
    workbook = Workbook()
    sheet = workbook.active
    assert sheet is not None
    sheet.append(
        [
            "instruction_name",
            "input_values",
            "expected_outputs",
            "input_type",
            "output_type",
        ]
    )
    sheet.append(["add", "[[1, 1]]", "[2]", "LWORD", "LWORD"])
    file_path = tmp_path / "suite.xlsx"
    workbook.save(file_path)

    with Session(get_engine()) as session:
        suite, imported_count, rejected_count = import_plc_suite(
            session,
            filename="suite.xlsx",
            file_bytes=file_path.read_bytes(),
            title=None,
        )

    assert suite.source_format == "xlsx"
    assert suite.case_count == 1
    assert imported_count == 1
    assert rejected_count == 0

    with Session(get_engine()) as session:
        persisted_case = session.get(PLCTestCaseRecord, "plc-suite-1::ADD_001")

    assert persisted_case is not None
    assert persisted_case.expected_output_json == 2


def test_import_plc_suite_rejects_missing_required_columns(client) -> None:
    csv_bytes = b"instruction_name,input_type,output_type\nadd,LWORD,LWORD\n"

    with Session(get_engine()) as session:
        with pytest.raises(PLCImportError):
            import_plc_suite(
                session,
                filename="bad.csv",
                file_bytes=csv_bytes,
                title="Bad",
            )


def test_build_normalization_suggestion_returns_reviewable_preview() -> None:
    suggestion = build_normalization_suggestion(
        {
            "instruction_name": "add",
            "input_values": "[[1,1],[2,2]]",
            "expected_outputs": "[2,4]",
            "input_type": "LWORD",
            "output_type": "LWORD",
        }
    )

    assert suggestion["source_of_truth"] is False
    assert suggestion["review_required"] is True
    assert len(suggestion["normalized_cases"]) == 2


def test_execute_plc_job_aggregates_results() -> None:
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
            },
            {
                "id": "plc-suite-1::ADD_002",
                "case_key": "ADD_002",
                "instruction_name": "add",
                "input_type": "LWORD",
                "output_type": "LWORD",
                "input_vector_json": [2, 2],
                "expected_output_json": 4,
                "expected_outputs_json": [4],
                "memory_profile_key": "ls_add_lword_v1",
                "description": None,
                "tags": [],
                "timeout_ms": 3000,
                "source_row_number": 2,
                "source_case_index": 1,
                "expected_outcome": "fail",
            },
        ],
    }

    result = PLCTestRunResultModel.model_validate(execute_plc_job(payload))

    assert result.total_count == 2
    assert result.passed_count == 1
    assert result.failed_count == 1
    assert result.error_count == 0


def test_execute_plc_job_persists_relational_run_results(client) -> None:
    csv_bytes = (
        "instruction_name,input_values,expected_outputs,input_type,output_type,description,tags,memory_profile_key\n"
        'add,"[[1,1],[2,2]]","[2,5]",LWORD,LWORD,adder,"smoke,math",ls_add_lword_v1\n'
    ).encode("utf-8")

    with Session(get_engine()) as session:
        suite, _, _ = import_plc_suite(
            session,
            filename="ls-add.csv",
            file_bytes=csv_bytes,
            title="LS Add",
        )
        create_plc_run(
            session,
            run_id="7",
            suite_id=suite.id,
            suite_title=suite.title,
            target_key="stub-local",
            target_snapshot={
                "key": "stub-local",
                "display_name": "Stub Local",
                "executor_mode": "stub",
                "metadata_json": {"environment_label": "stub-lab", "tags": ["stub"]},
            },
            backing_job_id="7",
            cases=suite.definition_json.cases,
        )
        session.commit()
        run_cases = [
            case.model_dump(mode="json") for case in suite.definition_json.cases
        ]
        run_cases[1]["expected_outcome"] = "fail"

        result_summary = execute_plc_job(
            {
                "suite_id": suite.id,
                "suite_title": suite.title,
                "target_key": "stub-local",
                "run_id": "7",
                "backing_job_id": "7",
                "testcases": run_cases,
            },
            session=session,
        )
        session.expire_all()

        run = session.get(PLCTestRunRecord, "7")
        run_items = (
            session.query(PLCTestRunItemRecord)
            .filter(PLCTestRunItemRecord.run_id == "7")
            .all()
        )
        io_logs = session.query(PLCTestRunIOLogRecord).all()

    assert "items" not in result_summary
    assert result_summary["passed_count"] == 1
    assert result_summary["failed_count"] == 1
    assert run is not None
    assert run.total_count == 2
    assert run.passed_count == 1
    assert run.failed_count == 1
    assert run.request_schema_version == "plc-execution-request.v2"
    assert run.executor_mode == "stub"
    assert run.target_snapshot_json is not None
    assert run.target_snapshot_json["key"] == "stub-local"
    assert len(run_items) == 2
    assert {item.status for item in run_items} == {"passed", "failed"}
    assert run_items[0].execution_profile_key == "ls-add-lword-v1"
    assert run_items[0].input_type == "LWORD"
    assert run_items[0].request_context_json["run_context"]["suite_id"] == suite.id
    assert io_logs


def test_flatten_cases_prefers_relational_rows_over_definition_json(client) -> None:
    csv_bytes = (
        "instruction_name,input_values,expected_outputs,input_type,output_type\n"
        'add,"[[1,1]]","[2]",LWORD,LWORD\n'
    ).encode("utf-8")

    with Session(get_engine()) as session:
        suite, _, _ = import_plc_suite(
            session,
            filename="ls-add.csv",
            file_bytes=csv_bytes,
            title="LS Add",
        )
        case = session.get(PLCTestCaseRecord, "plc-suite-1::ADD_001")
        assert case is not None
        case.expected_output_json = 99
        session.commit()

        flattened = flatten_cases(session, suite_id=suite.id)
        _, payload, selected_cases = create_plc_job_payload(
            session,
            suite_id=suite.id,
            testcase_ids=None,
            target_key="stub-local",
        )

    assert flattened[0]["expected_output_json"] == 99
    assert flattened[0]["case_source"] == "relational"
    assert flattened[0]["execution_profile_key"] == "add--lword--lword"
    assert flattened[0]["execution_profile"]["instruction_name"] == "add"
    assert selected_cases[0].expected_output_json == 99
    assert payload["testcase_source"] == "relational"
    assert payload["testcases"][0]["expected_output_json"] == 99


def test_flatten_cases_uses_definition_json_only_when_suite_lacks_relational_rows(
    client,
) -> None:
    csv_bytes = (
        "instruction_name,input_values,expected_outputs,input_type,output_type\n"
        'add,"[[1,1],[2,2]]","[2,4]",LWORD,LWORD\n'
    ).encode("utf-8")

    with Session(get_engine()) as session:
        suite, _, _ = import_plc_suite(
            session,
            filename="ls-add.csv",
            file_bytes=csv_bytes,
            title="LS Add",
        )
        session.query(PLCTestCaseRecord).filter(
            PLCTestCaseRecord.suite_id == suite.id
        ).delete()
        session.commit()

        flattened = flatten_cases(session, suite_id=suite.id)
        _, payload, selected_cases = create_plc_job_payload(
            session,
            suite_id=suite.id,
            testcase_ids=None,
            target_key="stub-local",
        )

    assert len(flattened) == 2
    assert flattened[0]["expected_output_json"] == 2
    assert flattened[0]["case_source"] == "definition_json_fallback"
    assert len(selected_cases) == 2
    assert payload["testcase_source"] == "definition_json_fallback"
    assert payload["testcases"][1]["expected_output_json"] == 4
