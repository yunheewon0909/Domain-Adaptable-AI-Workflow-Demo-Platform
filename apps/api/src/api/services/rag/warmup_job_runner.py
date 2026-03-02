from __future__ import annotations

import argparse
import json
import sys
from time import perf_counter
from typing import TypedDict

import httpx

from api.config import get_settings


class WarmupResult(TypedDict):
    embed_ok: bool
    chat_ok: bool
    embed_latency_ms: int
    chat_latency_ms: int
    embed_model: str
    chat_model: str


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="rag-warmup-runner",
        description="Probe Ollama embedding/chat endpoints and models",
    )
    parser.add_argument(
        "--payload-json",
        default=None,
        help="Optional JSON payload for compatibility with queue runners (currently unused)",
    )
    return parser


def _resolve_payload(payload_json_raw: str | None) -> dict[str, object]:
    if payload_json_raw is None:
        return {}

    parsed = json.loads(payload_json_raw)
    if not isinstance(parsed, dict):
        raise ValueError("payload_json must be a JSON object")
    return parsed


def _model_pull_hint(model: str) -> str:
    return (
        "Warmup MVP does not auto-pull models. "
        f"Run: docker compose exec -T ollama ollama pull {model}"
    )


def _format_http_status_error(exc: httpx.HTTPStatusError) -> str:
    response = exc.response
    if response is None:
        return str(exc)

    status = response.status_code
    body = ""
    try:
        body = response.text.strip()
    except Exception:
        body = ""

    if body:
        return f"HTTP {status}: {body}"
    return f"HTTP {status}"


def _probe(
    *,
    url: str,
    payload: dict[str, object],
    timeout_seconds: float,
    model: str,
    label: str,
) -> int:
    start = perf_counter()

    try:
        response = httpx.post(url, json=payload, timeout=timeout_seconds)
        response.raise_for_status()
    except httpx.HTTPStatusError as exc:
        raise RuntimeError(
            f"{label} probe failed for model '{model}': {_format_http_status_error(exc)}. "
            f"{_model_pull_hint(model)}"
        ) from exc
    except httpx.HTTPError as exc:
        raise RuntimeError(
            f"{label} probe failed for model '{model}': {exc}. "
            f"{_model_pull_hint(model)}"
        ) from exc

    return int((perf_counter() - start) * 1000)


def run_warmup_job() -> WarmupResult:
    settings = get_settings()

    embed_model = settings.ollama_embed_model
    chat_model = settings.ollama_model

    embed_latency_ms = _probe(
        url=f"{settings.ollama_embed_base_url.rstrip('/')}/embeddings",
        payload={"model": embed_model, "input": "hello"},
        timeout_seconds=settings.ollama_timeout_seconds,
        model=embed_model,
        label="embedding",
    )

    chat_latency_ms = _probe(
        url=f"{settings.ollama_base_url.rstrip('/')}/chat/completions",
        payload={
            "model": chat_model,
            "messages": [
                {
                    "role": "user",
                    "content": "warmup ping",
                }
            ],
            "temperature": 0,
            "max_tokens": 1,
        },
        timeout_seconds=settings.ollama_timeout_seconds,
        model=chat_model,
        label="chat",
    )

    return {
        "embed_ok": True,
        "chat_ok": True,
        "embed_latency_ms": embed_latency_ms,
        "chat_latency_ms": chat_latency_ms,
        "embed_model": embed_model,
        "chat_model": chat_model,
    }


def main() -> None:
    parser = _build_parser()
    args = parser.parse_args()

    try:
        _resolve_payload(args.payload_json)
        result = run_warmup_job()
    except Exception as exc:
        print(f"[rag-warmup-runner] failed: {exc}", file=sys.stderr, flush=True)
        raise SystemExit(1) from exc

    print(json.dumps(result), flush=True)


if __name__ == "__main__":
    main()
