#!/usr/bin/env python3
"""E2E: the API is up and the runtime serves models.

Host-side: requires the compose stack (api + ollama) running with a chat model
pulled into Ollama. Run: ``python scripts/e2e_runtime_smoke.py``.
"""

from __future__ import annotations

from e2e_helpers import (
    json_dict,
    list_models,
    print_ok,
    print_step,
    request_json,
    run_main,
    wait_for_api_health,
)


def main() -> None:
    wait_for_api_health()

    print_step("GET /v1/models reflects the runtime")
    payload = json_dict(request_json("GET", "/v1/models", expected_status=200), "/v1/models")
    assert payload.get("object") == "list", payload
    print_ok(f"/v1/models returned {len(payload.get('data') or [])} model(s)")

    print_step("GET /models (runtime-backed registry)")
    models = list_models()
    print_ok(f"/models returned {len(models)} model(s)")


if __name__ == "__main__":
    run_main(main)
