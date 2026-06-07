from fastapi.testclient import TestClient


def test_demo_surface_is_admin_dashboard_not_chat(client: TestClient) -> None:
    response = client.get("/demo")

    assert response.status_code == 200
    text = response.text
    # Admin/debug framing, explicitly not a competing chat UI.
    assert "admin / evaluation / debug dashboard" in text
    assert "Open WebUI" in text
    # Inspection sections present.
    assert "Service status" in text
    assert "Runtime models" in text
    assert "RAG collections" in text
    assert 'id="model-list"' in text
    assert 'id="collection-list"' in text
    # No fine-tuning wizard remnants.
    assert "MLX QLoRA" not in text
    assert "Fine-tune" not in text


def test_demo_app_js_wires_read_only_endpoints(client: TestClient) -> None:
    response = client.get("/demo/assets/app.js")

    assert response.status_code == 200
    text = response.text
    assert "/health" in text
    assert "/v1/models" in text
    assert "/rag-collections" in text
    # No fine-tuning endpoints.
    assert "ft-training-jobs" not in text
    assert "ft-datasets" not in text


def test_demo_styles_includes_theme_tokens(client: TestClient) -> None:
    response = client.get("/demo/assets/styles.css")

    assert response.status_code == 200
    text = response.text
    assert "--bg" in text
    assert "--accent" in text
    assert "prefers-color-scheme: dark" in text
