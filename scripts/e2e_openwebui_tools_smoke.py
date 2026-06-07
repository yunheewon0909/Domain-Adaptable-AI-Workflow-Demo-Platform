#!/usr/bin/env python3
"""E2E: the Open WebUI tool manifest + artifact are served and complete.

Host-side: requires the api service running.
Run: ``python scripts/e2e_openwebui_tools_smoke.py``.
"""

from __future__ import annotations

from e2e_helpers import (
    ensure,
    json_dict,
    print_ok,
    print_step,
    request,
    request_json,
    run_main,
    wait_for_api_health,
)

_EXPECTED_METHODS = {
    "list_collections",
    "create_collection",
    "upload_text_document",
    "search_collection",
    "get_entity",
    "get_subgraph",
    "generate_evaluation_set",
    "run_rag_evaluation",
    "get_evaluation_report",
}


def main() -> None:
    wait_for_api_health()

    print_step("GET /openwebui/manifest.json")
    manifest = json_dict(
        request_json("GET", "/openwebui/manifest.json", expected_status=200), "manifest"
    )
    tools = manifest.get("tools") or []
    ensure(bool(tools), "manifest advertises no tools")
    methods = set(tools[0].get("methods") or [])
    missing = _EXPECTED_METHODS - methods
    ensure(not missing, f"manifest missing methods: {sorted(missing)}")
    print_ok(f"manifest advertises {len(methods)} methods")

    print_step("GET /openwebui/platform_tools.py")
    resp = request("GET", "/openwebui/platform_tools.py", expected_status=200)
    body = resp.text
    ensure("class Tools" in body, "artifact missing Tools class")
    for method in _EXPECTED_METHODS:
        ensure(f"def {method}" in body, f"artifact missing def {method}")
    print_ok("tool artifact serves all expected methods")


if __name__ == "__main__":
    run_main(main)
