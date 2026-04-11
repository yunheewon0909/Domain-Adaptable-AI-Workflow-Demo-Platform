from io import BytesIO

from openpyxl import Workbook


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
    assert testcases[0]["instruction_name"] == "add"


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

    jobs_response = client.get("/plc-test-runs")
    assert jobs_response.status_code == 200
    assert jobs_response.json()[0]["plc_suite_id"] == suite_id

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
