from fastapi.testclient import TestClient


def test_demo_surface_shows_wizard_steps(client: TestClient) -> None:
    response = client.get("/demo")

    assert response.status_code == 200
    text = response.text
    # 3 wizard steps + settings advanced
    assert "Knowledge base" in text
    assert "Train a model from this collection" in text
    assert "Chat" in text
    assert "Advanced" in text
    # Plain language explainers exist for each step (smoke check)
    assert "Upload one or more documents" in text
    assert "MLX QLoRA" in text
    assert "Pick a model" in text
    # Form controls are present
    assert 'id="kb-select"' in text
    assert 'id="kb-upload-button"' in text
    assert 'id="train-start"' in text
    assert 'id="chat-form"' in text
    assert 'id="chat-model"' in text
    # External chat client hints
    assert "lobe-chat" in text
    assert "Open WebUI" in text


def test_demo_app_js_wires_wizard_endpoints(client: TestClient) -> None:
    response = client.get("/demo/assets/app.js")

    assert response.status_code == 200
    text = response.text
    # KB / train / chat / status flows hit the documented endpoints
    assert "/rag-collections" in text
    assert "/ft-datasets/from-rag-collection" in text
    assert "/ft-training-jobs" in text
    assert "/v1/chat/completions" in text
    assert "/v1/models" in text
    assert "/health" in text
    # Grounding option must wire rag_collection_id into chat completions
    assert "rag_collection_id" in text
    # Lifecycle polling is present
    assert "pollTrainingJob" in text


def test_demo_styles_includes_theme_tokens(client: TestClient) -> None:
    response = client.get("/demo/assets/styles.css")

    assert response.status_code == 200
    text = response.text
    assert "--bg" in text
    assert "--accent" in text
    assert "prefers-color-scheme: dark" in text
