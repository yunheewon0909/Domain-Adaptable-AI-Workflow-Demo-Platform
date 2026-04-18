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
    assert "Trainer model mapping for smoke tests" in text
    assert "Model registry" in text
    assert "Model selection status" in text
    assert "Reviewing model" in text
    assert "Inference model" in text
    assert "validated adapter artifacts" in text
    assert "Inference run" in text
    assert "Inference model selector" in text
    assert "Create RAG collection" in text
    assert "Retrieval preview" in text


def test_demo_app_js_includes_lineage_and_readiness_labels(client: TestClient) -> None:
    response = client.get("/demo/assets/app.js")

    assert response.status_code == 200
    text = response.text
    assert "Trainer/source mismatch" in text
    assert "Artifact validation" in text
    assert "Publish readiness" in text
    assert "Trainer source" in text
    assert "Runtime ready reason" in text
    assert "Use for inference" in text
    assert "Artifact-only models stay reviewable here" in text
