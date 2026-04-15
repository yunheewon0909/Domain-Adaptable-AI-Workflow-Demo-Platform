from io import BytesIO

from openpyxl import Workbook
import pytest
from sqlalchemy.orm import Session

from api.db import get_engine
from api.models import (
    JobRecord,
    PLCTestCaseRecord,
    PLCTestRunItemRecord,
    PLCTestRunRecord,
    PLCTestTargetRecord,
)


def _csv_upload_bytes() -> bytes:
    return (
        "instruction_name,input_values,expected_outputs,input_type,output_type,description,tags,memory_profile_key\n"
        'add,"[[1,1],[2,2]]","[2,4]",LWORD,LWORD,adder,"smoke,math",ls_add_lword_v1\n'
    ).encode("utf-8")


def _xlsx_upload_bytes() -> bytes:
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
    sheet.append(["add", "[[1,1]]", "[2]", "LWORD", "LWORD"])
    buffer = BytesIO()
    workbook.save(buffer)
    return buffer.getvalue()


def test_plc_import_and_query_happy_path(client) -> None:
    response = client.post(
        "/plc-testcases/import",
        files={"file": ("suite.csv", _csv_upload_bytes(), "text/csv")},
        data={"title": "LS Demo"},
    )

    assert response.status_code == 201
    payload = response.json()
    assert payload["imported_count"] == 2
    suite_id = payload["suite_id"]

    suites_response = client.get("/plc-test-suites")
    assert suites_response.status_code == 200
    assert suites_response.json()[0]["id"] == suite_id

    testcase_response = client.get("/plc-testcases", params={"suite_id": suite_id})
    assert testcase_response.status_code == 200
    testcases = testcase_response.json()
    assert len(testcases) == 2
    assert testcases[0]["testcase_key"] == testcases[0]["id"]
    assert testcases[0]["instruction_name"] == "add"
    assert testcases[0]["is_active"] is True
    assert testcases[0]["execution_profile_key"] == "ls-add-lword-v1"
    assert testcases[0]["execution_profile"]["memory_profile_key"] == "ls_add_lword_v1"


def test_plc_import_supports_xlsx(client) -> None:
    response = client.post(
        "/plc-testcases/import",
        files={
            "file": (
                "suite.xlsx",
                _xlsx_upload_bytes(),
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            )
        },
    )
    assert response.status_code == 201
    assert response.json()["imported_count"] == 1


def test_plc_import_rejects_malformed_file(client) -> None:
    response = client.post(
        "/plc-testcases/import",
        files={"file": ("broken.csv", b"instruction_name\nadd\n", "text/csv")},
    )
    assert response.status_code == 400


def test_plc_run_and_detail_endpoints(client) -> None:
    import_response = client.post(
        "/plc-testcases/import",
        files={"file": ("suite.csv", _csv_upload_bytes(), "text/csv")},
        data={"title": "LS Demo"},
    )
    suite_id = import_response.json()["suite_id"]

    cases = client.get("/plc-testcases", params={"suite_id": suite_id}).json()
    run_response = client.post(
        "/plc-test-runs",
        json={"suite_id": suite_id, "target_key": "stub-local"},
    )
    assert run_response.status_code == 202
    run_id = run_response.json()["job_id"]

    detail_response = client.get(f"/plc-test-runs/{run_id}")
    assert detail_response.status_code == 200
    assert detail_response.json()["status"] == "queued"

    with Session(get_engine()) as session:
        run = session.get(PLCTestRunRecord, run_id)
        run_items = (
            session.query(PLCTestRunItemRecord)
            .filter(PLCTestRunItemRecord.run_id == run_id)
            .all()
        )

    assert run is not None
    assert run.target_key == "stub-local"
    assert run.queued_count == 2
    assert len(run_items) == 2
    assert {item.status for item in run_items} == {"queued"}

    jobs_response = client.get("/plc-test-runs")
    assert jobs_response.status_code == 200
    assert jobs_response.json()[0]["plc_suite_id"] == suite_id

    run_items_response = client.get(f"/plc-test-runs/{run_id}/items")
    assert run_items_response.status_code == 200
    assert len(run_items_response.json()) == 2
    assert run_items_response.json()[0]["status"] == "queued"
    assert run_items_response.json()[0]["execution_profile_key"] == "ls-add-lword-v1"
    assert (
        run_items_response.json()[0]["request_context_json"]["run_context"]["suite_id"]
        == suite_id
    )

    run_item_detail_response = client.get(
        f"/plc-test-runs/{run_id}/items/{run_items_response.json()[0]['id']}"
    )
    assert run_item_detail_response.status_code == 200
    assert run_item_detail_response.json()["id"] == run_items_response.json()[0]["id"]

    run_logs_response = client.get(f"/plc-test-runs/{run_id}/io-logs")
    assert run_logs_response.status_code == 200
    assert run_logs_response.json() == []

    targets_response = client.get("/plc-targets")
    assert targets_response.status_code == 200
    assert targets_response.json()[0]["key"] == "stub-local"

    suggestion_response = client.post(
        "/plc-llm/suggest-testcase-normalization",
        json={
            "raw_row": {
                "instruction_name": "add",
                "input_values": "[[1,1]]",
                "expected_outputs": "[2]",
                "input_type": "LWORD",
                "output_type": "LWORD",
            }
        },
    )
    assert suggestion_response.status_code == 200
    assert suggestion_response.json()["review_required"] is True

    single_case_response = client.get(f"/plc-testcases/{cases[0]['id']}")
    assert single_case_response.status_code == 200
    assert single_case_response.json()["execution_profile"]["key"] == "ls-add-lword-v1"


def test_plc_dashboard_summary_endpoint(client) -> None:
    import_response = client.post(
        "/plc-testcases/import",
        files={"file": ("suite.csv", _csv_upload_bytes(), "text/csv")},
    )
    suite_id = import_response.json()["suite_id"]
    client.post(
        "/plc-test-runs", json={"suite_id": suite_id, "target_key": "stub-local"}
    )

    response = client.get("/plc-dashboard/summary")
    assert response.status_code == 200
    payload = response.json()
    assert payload["suite_count"] == 1
    assert payload["run_count"] == 1


def test_plc_run_enqueue_recreates_missing_relational_testcases(client) -> None:
    import_response = client.post(
        "/plc-testcases/import",
        files={"file": ("suite.csv", _csv_upload_bytes(), "text/csv")},
    )
    suite_id = import_response.json()["suite_id"]

    with Session(get_engine()) as session:
        session.query(PLCTestCaseRecord).filter(
            PLCTestCaseRecord.suite_id == suite_id
        ).delete()
        session.commit()

    run_response = client.post(
        "/plc-test-runs",
        json={"suite_id": suite_id, "target_key": "stub-local"},
    )

    assert run_response.status_code == 202
    with Session(get_engine()) as session:
        recreated_cases = (
            session.query(PLCTestCaseRecord)
            .filter(PLCTestCaseRecord.suite_id == suite_id)
            .all()
        )
    assert len(recreated_cases) == 2


def test_plc_run_enqueue_rejects_partial_relational_drift(client) -> None:
    import_response = client.post(
        "/plc-testcases/import",
        files={"file": ("suite.csv", _csv_upload_bytes(), "text/csv")},
    )
    suite_id = import_response.json()["suite_id"]

    with Session(get_engine()) as session:
        session.query(PLCTestCaseRecord).filter(
            PLCTestCaseRecord.id == f"{suite_id}::ADD_002"
        ).delete()
        session.commit()

    response = client.post(
        "/plc-test-runs",
        json={"suite_id": suite_id, "target_key": "stub-local"},
    )

    assert response.status_code == 400
    assert "testcase masters are incomplete" in response.json()["detail"]


def test_plc_run_enqueue_rolls_back_if_run_materialization_fails(
    client, monkeypatch: pytest.MonkeyPatch
) -> None:
    import_response = client.post(
        "/plc-testcases/import",
        files={"file": ("suite.csv", _csv_upload_bytes(), "text/csv")},
    )
    suite_id = import_response.json()["suite_id"]

    def _boom(*args, **kwargs):
        raise RuntimeError("boom")

    monkeypatch.setattr("api.routers.plc.create_plc_run", _boom)

    with pytest.raises(RuntimeError, match="boom"):
        client.post(
            "/plc-test-runs",
            json={"suite_id": suite_id, "target_key": "stub-local"},
        )

    with Session(get_engine()) as session:
        jobs = session.query(JobRecord).filter(JobRecord.type == "plc_test_run").all()
    assert jobs == []


def test_plc_run_enqueue_rejects_unknown_target(client) -> None:
    import_response = client.post(
        "/plc-testcases/import",
        files={"file": ("suite.csv", _csv_upload_bytes(), "text/csv")},
    )
    suite_id = import_response.json()["suite_id"]

    response = client.post(
        "/plc-test-runs",
        json={"suite_id": suite_id, "target_key": "missing-target"},
    )

    assert response.status_code == 400
    assert "was not found" in response.json()["detail"]
    with Session(get_engine()) as session:
        jobs = session.query(JobRecord).filter(JobRecord.type == "plc_test_run").all()
        runs = session.query(PLCTestRunRecord).all()
    assert jobs == []
    assert runs == []


def test_plc_run_enqueue_rejects_inactive_target(client) -> None:
    import_response = client.post(
        "/plc-testcases/import",
        files={"file": ("suite.csv", _csv_upload_bytes(), "text/csv")},
    )
    suite_id = import_response.json()["suite_id"]

    with Session(get_engine()) as session:
        session.add(
            PLCTestTargetRecord(
                key="stub-local",
                display_name="Stub Local",
                description="disabled",
                executor_mode="stub",
                metadata_json={},
                is_active=False,
            )
        )
        session.commit()

    response = client.post(
        "/plc-test-runs",
        json={"suite_id": suite_id, "target_key": "stub-local"},
    )

    assert response.status_code == 400
    assert "is inactive" in response.json()["detail"]


def test_plc_run_enqueue_rejects_executor_mode_mismatch(
    client, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("PLC_EXECUTOR_MODE", "stub")
    import_response = client.post(
        "/plc-testcases/import",
        files={"file": ("suite.csv", _csv_upload_bytes(), "text/csv")},
    )
    suite_id = import_response.json()["suite_id"]

    with Session(get_engine()) as session:
        session.add(
            PLCTestTargetRecord(
                key="cli-target",
                display_name="CLI Target",
                description="cli only",
                executor_mode="cli",
                metadata_json={},
                is_active=True,
            )
        )
        session.commit()

    response = client.post(
        "/plc-test-runs",
        json={"suite_id": suite_id, "target_key": "cli-target"},
    )

    assert response.status_code == 400
    assert "requires executor mode 'cli'" in response.json()["detail"]


def test_plc_targets_includes_stub_local_even_when_other_targets_exist(client) -> None:
    with Session(get_engine()) as session:
        session.add(
            PLCTestTargetRecord(
                key="bench-a",
                display_name="Bench A",
                description="custom target",
                executor_mode="stub",
                metadata_json={"line": "A"},
                is_active=True,
            )
        )
        session.commit()

    response = client.get("/plc-targets")

    assert response.status_code == 200
    keys = [item["key"] for item in response.json()]
    assert keys[0] == "stub-local"
    assert "bench-a" in keys


def test_plc_llm_suggestion_persistence_and_review_flow(client) -> None:
    import_response = client.post(
        "/plc-testcases/import",
        files={"file": ("suite.csv", _csv_upload_bytes(), "text/csv")},
    )
    suite_id = import_response.json()["suite_id"]
    testcase_id = client.get("/plc-testcases", params={"suite_id": suite_id}).json()[0][
        "id"
    ]

    create_response = client.post(
        "/plc-llm/suggest-testcase-normalization",
        json={
            "suite_id": suite_id,
            "testcase_id": testcase_id,
            "persist": True,
            "raw_row": {
                "instruction_name": "add",
                "input_values": "[[1,1]]",
                "expected_outputs": "[2]",
                "input_type": "LWORD",
                "output_type": "LWORD",
            },
        },
    )

    assert create_response.status_code == 200
    persisted = create_response.json()["persisted_suggestion"]
    assert persisted["status"] == "pending"
    assert persisted["suite_id"] == suite_id
    assert persisted["testcase_id"] == testcase_id

    list_response = client.get(
        "/plc-llm/suggestions",
        params={"suite_id": suite_id, "testcase_id": testcase_id, "status": "pending"},
    )
    assert list_response.status_code == 200
    assert len(list_response.json()) == 1

    detail_response = client.get(f"/plc-llm/suggestions/{persisted['id']}")
    assert detail_response.status_code == 200
    assert (
        detail_response.json()["source_payload_json"]["raw_row"]["instruction_name"]
        == "add"
    )

    review_response = client.post(
        f"/plc-llm/suggestions/{persisted['id']}/review",
        json={"status": "accepted"},
    )
    assert review_response.status_code == 200
    assert review_response.json()["status"] == "accepted"
    assert review_response.json()["reviewed_at"] is not None

    testcase_response = client.get(f"/plc-testcases/{testcase_id}")
    assert testcase_response.status_code == 200
    assert testcase_response.json()["expected_output_json"] == 2
