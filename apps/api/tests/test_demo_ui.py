from fastapi.testclient import TestClient


def test_demo_surface_includes_workflow_and_plc_modes(client: TestClient) -> None:
    response = client.get("/demo")

    assert response.status_code == 200
    text = response.text
    assert "Workflow reviewer" in text
    assert "PLC testing MVP" in text
