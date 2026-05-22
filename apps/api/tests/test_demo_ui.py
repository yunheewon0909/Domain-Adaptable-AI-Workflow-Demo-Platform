from fastapi.testclient import TestClient


def test_demo_surface_includes_core_reviewer_modes(client: TestClient) -> None:
    response = client.get("/demo")

    assert response.status_code == 200
    text = response.text
    assert "Fine-tuning" in text
    assert "Models" in text
    assert "RAG" in text
    assert "Create fine-tuning dataset" in text
    assert "Training jobs" in text
    assert "./scripts/ft_smoke_preflight.sh" in text
    assert "Smoke test guide" in text
    assert "Fill smoke hyperparameter preset" in text
    assert "Prepare smoke dataset" in text
    assert "Enqueue smoke training" in text
    assert "Runtime preflight" in text
    assert "Preflight validates brew" in text
    assert (
        "Do not treat them as guidance for large-model training" in text
    )
    assert "Smoke fallback trainer was used" in text
    assert "This validates dataset/export/artifact/registry flow, not model quality" in text
    assert "Use the Mac-native MLX QLoRA path for real trainer validation" in text
    assert "./scripts/ft_smoke_test.sh" in text
    assert "artifact_ready" in text
    assert "publish_ready" in text
    assert "not inference-selectable" in text
    assert (
        "Smoke training validates adapter artifact creation, not LM Studio serving readiness"
        in text
    )
    assert "Artifact-ready rows remain review-only" in text
    assert "Model registry" in text
    assert "Model selection status" in text
    assert "Reviewing model" in text
    assert "Inference model" in text
    assert "validated adapter artifacts" in text
    assert "Inference run" in text
    assert "Inference model selector" in text
    assert "Only runtime-ready/selectable models can run inference." in text
    assert "Create RAG collection" in text
    assert "Retrieval preview" in text
    assert "This retrieval preview does not call an LLM." in text
    assert "delete collection-managed files" in text
    assert "delete the selected collection-managed document" in text


def test_demo_app_js_includes_lineage_and_readiness_labels(client: TestClient) -> None:
    response = client.get("/demo/assets/app.js")

    assert response.status_code == 200
    text = response.text
    # FT / Models / RAG reviewer mode labels survive
    assert "Trainer/source mismatch" in text
    assert "Artifact validation" in text
    assert "Publish readiness" in text
    assert "Trainer source" in text
    assert "Runtime ready reason" in text
    assert "Review details" in text
    assert "Use for inference" in text
    assert "Selected inference model" in text
    assert "Selected RAG collection" in text
    assert "Only runtime-ready/selectable models can run inference." in text
    assert "Artifact-only models stay reviewable here" in text
    # Smoke guide + FT lifecycle
    assert "demo-ui-smoke-dataset" in text
    assert "Preparing smoke dataset" in text
    assert "preparing_data" in text
    assert "packaging" in text
    assert "registering" in text
    assert "Enqueueing smoke training for" in text
    assert "Review in Models" in text
    assert "review-only handoff" in text
    assert "Run ./scripts/ft_smoke_preflight.sh on the macOS host" in text
    # Failure classifier surface
    assert "classifyFtTrainingFailure" in text
    assert "User-facing summary" in text
    assert "What to do next" in text
    assert "Training failed while downloading the tiny trainer model." in text
    assert "Training failed during artifact validation." in text
    # RAG mode
    assert "This did not call an LLM." in text
    assert "Delete document" in text
    assert "Retrieval preview was cleared after document deletion." in text
