from fastapi.testclient import TestClient


def test_demo_surface_includes_workflow_and_plc_modes(client: TestClient) -> None:
    response = client.get("/demo")

    assert response.status_code == 200
    text = response.text
    assert "Workflow reviewer" in text
    assert "Workflow source" in text
    assert "Workflow inference model" in text
    assert "Refresh sources &amp; models" in text
    assert "Choose a legacy dataset or RAG collection source for workflow review" in text
    assert "source and model metadata" in text
    assert "PLC testing MVP" in text
    assert "PLC stub execution does not call an LLM." in text
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
    assert "run preflight first for any new worker runtime" in text
    assert "Smoke test guide" in text
    assert "Fill smoke hyperparameter preset" in text
    assert "Prepare smoke dataset" in text
    assert "Enqueue smoke training" in text
    assert "Run preflight first" in text
    assert "Runtime preflight" in text
    assert "Docker demo defaults are CPU-friendly for tiny smoke tests" in text
    assert "Host worker recommended for Apple Silicon MPS" in text
    assert "Docker worker is not macOS MPS-capable" in text
    assert (
        "Do not treat CPU smoke defaults as guidance for large-model training" in text
    )
    assert "Smoke fallback trainer was used" in text
    assert "This validates dataset/export/artifact/registry flow, not model quality" in text
    assert "Use host MPS/local_peft path for real trainer validation" in text
    assert "./scripts/ft_smoke_preflight.sh --worker-runtime host" in text
    assert "./scripts/ft_smoke_preflight.sh --worker-runtime docker" in text
    assert "./scripts/ft_smoke_test.sh" in text
    assert "artifact_ready" in text
    assert "publish_ready" in text
    assert "not inference-selectable" in text
    assert (
        "Smoke training validates adapter artifact creation, not Ollama serving readiness"
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
    assert "Trainer/source mismatch" in text
    assert "Artifact validation" in text
    assert "Publish readiness" in text
    assert "Trainer source" in text
    assert "Runtime ready reason" in text
    assert "Review details" in text
    assert "Use for inference" in text
    assert "Workflow source status" in text
    assert "Workflow model status" in text
    assert "Workflow run metadata" in text
    assert "Evidence context" in text
    assert "Model used" in text
    assert "No runtime-ready/selectable workflow models are available yet." in text
    assert "Selected inference model" in text
    assert "Selected RAG collection" in text
    assert "Only runtime-ready/selectable models can run inference." in text
    assert "Artifact-only models stay reviewable here" in text
    assert "demo-ui-smoke-dataset" in text
    assert "Preparing smoke dataset" in text
    assert "preparing_data" in text
    assert "packaging" in text
    assert "registering" in text
    assert "Enqueueing smoke training for" in text
    assert "Review in Models" in text
    assert "review-only handoff" in text
    assert "Run preflight first before enqueueing a new runtime" in text
    assert "Docker demo defaults are CPU-friendly for tiny smoke tests" in text
    assert "classifyFtTrainingFailure" in text
    assert "User-facing summary" in text
    assert "What to do next" in text
    assert (
        "Training failed because required fine-tuning dependencies are missing in the worker runtime."
        in text
    )
    assert "Training failed while downloading the tiny trainer model." in text
    assert "Training failed during artifact validation." in text
    assert (
        "use ./scripts/ft_smoke_preflight.sh --worker-runtime docker for Docker checks"
        in text
    )
    assert "do not expect Ollama model publishing from the smoke job" in text
    assert "RAG index is not ready" in text
    assert "Evidence is unavailable until the legacy RAG index is initialized." in text
    assert "This did not call an LLM." in text
    assert "Delete document" in text
    assert "Retrieval preview was cleared after document deletion." in text
