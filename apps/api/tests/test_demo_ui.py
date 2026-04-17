from fastapi.testclient import TestClient


def test_demo_surface_includes_workflow_and_plc_modes(client: TestClient) -> None:
    response = client.get("/demo")

    assert response.status_code == 200
    text = response.text
    assert "Workflow reviewer" in text
    assert "PLC testing MVP" in text
    assert "Fine-tuning" in text
    assert "Models" in text
    assert "RAG" in text
    assert "Suggestion review" in text
    assert "Dashboard scope" in text
    assert "Instruction failure profile" in text
    assert "Suggestion status" in text
    assert "Target status" in text
    assert "Filter run items" in text
    assert "failed lifecycle state" in text
    assert "Create fine-tuning dataset" in text
    assert "Training jobs" in text
    assert "Model registry" in text
    assert "Inference run" in text
    assert "Create RAG collection" in text
    assert "Retrieval preview" in text
