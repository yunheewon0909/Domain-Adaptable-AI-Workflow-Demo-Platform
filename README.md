# Domain-Adaptable AI Workflow Demo Platform

## 0. Portfolio Snapshot
이 레포는 기존 API/Worker/RAG/Ollama/Compose 기반을 재사용해, **dataset selector + workflow catalog + evidence-backed result**를 한 화면에서 보여주는 co-hosted demo platform입니다.

Phase-1에서 바로 시연 가능한 핵심은 다음입니다.

- `/demo` 정적 UI에서 dataset 전환
- 정확히 3개의 workflow 실행: `briefing`, `recommendation`, `report_generator`
- `workflow_run` job queue + worker 처리
- mandatory `evidence[]` 포함 typed output
- minimal dataset registry skeleton (`datasets` table + active dataset selection)
- 기존 `/rag/search`, `/ask`, `/rag/warmup`, `/rag/verify`, `/rag/reindex` 유지

기존 산업 도메인 중심 표시 이름은 **default dataset narrative**로만 남기고, 제품 표시는 **domain-adaptable AI workflow demo platform** 방향으로 정리했다.

## 1. Implemented Features
- [x] **Co-hosted demo UI**: `/demo`에서 dataset dropdown, workflow selector, prompt input, job status, result, evidence panel 제공.
- [x] **Workflow catalog (Phase-1 fixed)**: `briefing`, `recommendation`, `report_generator` 3종만 노출.
- [x] **Workflow queue path**: `type=workflow_run`, `jobs.workflow_key`, `jobs.dataset_key`, worker subprocess runner 추가.
- [x] **Minimal dataset registry**: `datasets` control-plane table, `GET /datasets`, `POST /datasets/active`, active dataset resolver.
- [x] **Retrieval-first typed outputs**: 모든 workflow 결과는 typed contract + mandatory `evidence[]`를 저장.
- [x] **RAG primitives retained**: `/rag/search`, `/ask`, local SQLite/JSON fallback retrieval, Ollama-backed answer path 유지.
- [x] **Operational jobs retained**: `/rag/warmup`, `/rag/verify`, `/rag/reindex` enqueue + worker 처리 유지.
- [x] **OMX sandbox retained**: `omx --madmax`, `codex`를 컨테이너 내부로 격리하고 SSH agent forwarding, `~/.codex` read-only mount + one-time copy 유지.

## 2. Quick Demo (3~5분)

### A) Compose 트랙 (권장)
1) **서비스 기동**
```bash
docker compose up -d --build
```
기대 결과: `api`, `worker`, `postgres`, `ollama` 컨테이너가 실행 상태.

2) **(초회 1회) Ollama 모델 pull**
```bash
docker compose exec -T ollama ollama pull qwen2.5:3b-instruct-q4_K_M
docker compose exec -T ollama ollama pull qwen2.5:7b-instruct-q4_K_M
docker compose exec -T ollama ollama pull nomic-embed-text
```
기대 결과: `/ask`, `workflow_run`, `/rag/warmup` 경로가 안정적으로 동작.

3) **헬스체크 + catalog 확인**
```bash
curl -s http://127.0.0.1:8000/health
curl -s http://127.0.0.1:8000/datasets
curl -s http://127.0.0.1:8000/workflows
```
기대 결과: health OK, dataset 2종(`industrial_demo`, `enterprise_docs`), workflow 3종 확인.

4) **Demo UI 열기**
```text
http://127.0.0.1:8000/demo
```
기대 결과: dataset selector + workflow cards + prompt input + result/evidence panel이 한 화면에 표시.

5) **CLI로 workflow enqueue 확인**
```bash
curl -sS -X POST http://127.0.0.1:8000/workflows/briefing/jobs \
  -H "Content-Type: application/json" \
  -d '{"dataset_key":"industrial_demo","prompt":"Prepare a reviewer briefing for this dataset.","k":4}'
```
기대 결과: HTTP `202` + `job_id/status/workflow_key/dataset_key` 반환, worker가 이후 `result_json.evidence[]`를 저장.

6) **Job filtering 확인**
```bash
curl -sS "http://127.0.0.1:8000/jobs?workflow_key=briefing&dataset_key=industrial_demo&status=queued"
curl -sS http://127.0.0.1:8000/jobs/<job_id>
```
기대 결과: workflow/dataset/status 기준으로 job 조회 가능.

7) **RAG primitive 확인(선택)**
```bash
curl -sG "http://127.0.0.1:8000/rag/search" \
  --data-urlencode "q=maintenance automation" \
  --data-urlencode "k=3" \
  --data-urlencode "dataset_key=industrial_demo"
curl -s -X POST "http://127.0.0.1:8000/ask" \
  -H "Content-Type: application/json" \
  -d '{"question":"What maintenance actions are recommended?","k":3,"dataset_key":"industrial_demo"}'
```
기대 결과: `/rag/search`는 evidence-style hit 배열을, `/ask`는 `answer + sources[] + meta`를 반환.

### B) Host-only 트랙 (가능 시)
1) **마이그레이션 + API 실행**
```bash
uv run --project apps/api alembic -c apps/api/alembic.ini upgrade head
uv run --project apps/api uvicorn api.main:app --host 0.0.0.0 --port 8000
```

2) **데모 API 확인**
```bash
curl -s http://127.0.0.1:8000/datasets
curl -s http://127.0.0.1:8000/workflows
curl -s http://127.0.0.1:8000/demo | head
```

3) **workflow enqueue 확인**
```bash
curl -sS -X POST http://127.0.0.1:8000/workflows/report_generator/jobs \
  -H "Content-Type: application/json" \
  -d '{"dataset_key":"enterprise_docs","prompt":"Generate a one-page report for the pilot review.","k":4}'
```

### Job Status 확인 (Queue/Worker 진행상태)
상태 전이는 `queued -> running -> succeeded/failed` 순서로 진행된다.

```bash
# 전체 job 목록
curl -sS http://127.0.0.1:8000/jobs

# 기존 operational job filter
curl -sS "http://127.0.0.1:8000/jobs?type=rag_verify_index&status=queued"

# workflow demo filter
curl -sS "http://127.0.0.1:8000/jobs?workflow_key=recommendation&dataset_key=enterprise_docs&status=queued"

# 상세 조회
curl -sS http://127.0.0.1:8000/jobs/<job_id>
```

worker 진행 상황은 `docker compose logs -f --tail=200 worker`로 확인한다.

## 3. Repo Navigation
- `apps/api/src/api/main.py`: router/static mount 중심 FastAPI 조립 파일.
- `apps/api/src/api/routers/`: `datasets`, `workflows`, `jobs`, `demo`, `rag`, `health` 라우터.
- `apps/api/src/api/services/datasets/`: default dataset seed, active dataset selection, dataset path resolver.
- `apps/api/src/api/services/workflows/`: workflow contracts, catalog, profile prompts, runner/service.
- `apps/api/src/api/services/retrieval/service.py`: dataset-aware evidence retrieval + grounding context 조립.
- `apps/api/src/api/static/demo/`: co-hosted static HTML/CSS/JS demo UI.
- `apps/worker/src/worker/main.py`: job claim/retry/heartbeat + `workflow_run` subprocess dispatch.
- `data/sample_docs`, `data/rag_index`: legacy default industrial dataset artifact paths.
- `data/datasets/enterprise_docs/`: Phase-1 secondary demo dataset source/index skeleton.
- `compose.yml`, `compose.omx.yml`, `Dockerfile`, `entrypoint.sh`: 실행/격리/부트스트랩 진입점.

## 3.1 현재 목적
- domain-adaptable AI workflow demo를 한 레포에서 바로 검토/시연 가능하게 유지한다.
- 기존 API/FastAPI + Worker + RAG + Ollama + Compose 기반을 재사용한다.
- schema/API/worker/UI 계약을 작게 고정하고, Phase-1 범위 밖 플랫폼 재설계는 피한다.

## 3.2 Phase-1 범위 요약
- 포함: demo UI, workflow catalog 3종, minimal dataset registry, `workflow_run`, README 동기화
- 제외: `apps/web`, multi-user/auth, full dataset versioning, generalized upload pipeline, `job_runs`, retry/history redesign, retrieval engine 교체, broad Kubernetes packaging

## 4. 호스트 사전 준비(필수)

아래는 **호스트(macOS)** 에서만 실행:

```bash
brew install uv || brew upgrade uv
uv --version

echo $SSH_AUTH_SOCK
ssh-add -l

ls -la ~/.codex
docker --version
docker compose version
```

## 5. 안전 실행 원칙

- `omx --madmax`, `codex` 실행은 **반드시 컨테이너 내부에서만** 수행한다.
- 호스트에서는 빌드/런/셸 진입/상태 확인까지만 수행한다.
- SSH 키 파일은 공유하지 않고 `SSH_AUTH_SOCK` 에이전트 포워딩만 사용한다.
- 호스트 `~/.codex`는 컨테이너에 read-only 마운트하고, 컨테이너 내부 `CODEX_HOME`에 1회 복사해 사용한다.

## 6. 마일스톤 커밋 게이트 규칙(필수)

각 마일스톤마다 아래 순서를 강제한다.

1. 변경사항 검증
2. README 업데이트 (이번 마일스톤 반영)
3. Conventional Commit으로 커밋
4. 다음 마일스톤 진행

권장 커밋 메시지:

- `chore: init repo skeleton and policies`
- `chore(omx): add docker sandbox for madmax execution`
- `chore(uv): scaffold api/worker python projects with uv`
- `chore(compose): add minimal compose for api/worker`

## 7. 실행/검증(호스트 기준)

### 7.1 OMX 샌드박스

`compose.omx.yml`의 서비스명은 `omx-sandbox`다.

```bash
docker compose -f compose.omx.yml build
docker compose -f compose.omx.yml run --rm omx-sandbox
```

샌드박스 이미지는 빌드 시 `en_US.UTF-8`, `ko_KR.UTF-8`를 모두 생성하고 기본 로케일을 `ko_KR.UTF-8`로 고정한다. 또한 진단용 `python3`와 `python`(=`python3` symlink)을 포함한다.

UTF-8 locale + python 진단(컨테이너 내부):

```bash
locale | grep -E '^(LANG|LC_ALL|LC_CTYPE)='
python --version
python3 --version
python -c "print('한글 출력 테스트')"
```

호스트에서 한 번에 확인하려면:

```bash
docker compose -f compose.omx.yml build --no-cache
docker compose -f compose.omx.yml run --rm omx-sandbox bash -lc 'locale | egrep "^(LANG|LC_ALL|LC_CTYPE)="; python -c "print(\"한글 테스트: 가나다라마바사\")"'
```

캐시 무시 재빌드가 필요한 경우에만 `--no-cache`를 사용한다.

```bash
docker compose -f compose.omx.yml build --no-cache
```

orphan 컨테이너 정리는 `down/up` 계열에서만 `--remove-orphans`를 사용한다 (`run`에는 사용하지 않음).

```bash
docker compose -f compose.omx.yml down --remove-orphans
```

SSH agent 포워딩 문제(`ssh-add -l`가 `permission denied`)가 나오면 `compose.omx.yml`의 `omx-sandbox`에 아래 설정이 있어야 한다.

```yaml
group_add:
  - "0"
```

검증(호스트):

```bash
docker compose -f compose.omx.yml run --rm omx-sandbox bash -lc 'ls -l $SSH_AUTH_SOCK; ssh-add -l'
```

`codex`와 `oh-my-codex`를 최신으로 강제 갱신하며 빌드하려면:

```bash
NPM_REFRESH=$(date +%s) docker compose -f compose.omx.yml build --pull
docker compose -f compose.omx.yml run --rm omx-sandbox
```

특정 npm 태그를 지정하고 싶다면:

```bash
CODEX_NPM_TAG=latest OMX_NPM_TAG=latest NPM_REFRESH=$(date +%s) docker compose -f compose.omx.yml build --pull
```

컨테이너 셸에 진입한 뒤 OMX 실행:

```bash
omx setup --scope project-local
omx --xhigh --madmax
```

프롬프트 카탈로그가 보이지 않으면 fallback으로 아래를 1회 실행한다.

```bash
omx setup --scope user
```

참고:

- 엔트리포인트가 `~/.codex/config.toml`의 호스트 절대경로(예: `/Users/.../.omx/agents/...`)를 컨테이너 경로 `/workspace/.omx/agents/...`로 자동 보정한다.
- 따라서 호스트와 컨테이너를 오갈 때마다 `omx setup`을 매번 다시 할 필요는 없다.
- 단, 프로젝트의 `.omx`를 지웠거나 컨테이너의 Codex 상태 볼륨(`omx-codex-home`)을 초기화한 경우에는 컨테이너에서 `omx setup --scope project-local`을 1회 다시 실행한다.

기대 로그(요약):

- git user/email 설정 확인
- SSH agent 소켓 감지 성공
- `/host-codex` -> `$CODEX_HOME` 1회 복사 메시지

#### 7.1.1 다른 프로젝트에서 샌드박스 재사용

가능하다. 아래 3개 파일을 다른 프로젝트 루트로 복사하면 경로 매핑은 자동으로 맞춰진다.

- `Dockerfile`
- `entrypoint.sh`
- `compose.omx.yml`

복사 예시(호스트):

```bash
# 대상 프로젝트 루트로 이동
cd <target-project-root>

# 이 레포를 소스 템플릿으로 사용해 복사
cp <omx-sandbox-source>/Dockerfile .
cp <omx-sandbox-source>/entrypoint.sh .
cp <omx-sandbox-source>/compose.omx.yml .
chmod +x entrypoint.sh
```

자동 매핑되는 항목:

- 대상 프로젝트 루트(`./`) -> 컨테이너 `/workspace`
- 호스트 `~/.codex`(ro) -> 컨테이너 `/host-codex`
- SSH agent 소켓 -> 컨테이너 `/ssh-agent`
- `~/.codex/config.toml`의 호스트 절대경로(`/Users/.../.omx/...`) -> `/workspace/.omx/...`로 엔트리포인트가 자동 보정

재사용 시 실행 순서(호스트):

```bash
NPM_REFRESH=$(date +%s) docker compose -f compose.omx.yml build --pull
docker compose -f compose.omx.yml run --rm omx-sandbox
```

주의:

- 대상 프로젝트에 `.omx/agents`가 없으면 경로 보정은 스킵된다. 이 경우 컨테이너에서 `omx setup --scope project-local`을 1회 실행해 `.omx`를 먼저 생성한다.
- `.omx`를 삭제했거나 `omx-codex-home` 볼륨을 초기화했다면, 역시 컨테이너에서 `omx setup --scope project-local`을 1회 다시 실행한다.

### 7.2 API 단독 검증(호스트)

```bash
export API_DATABASE_URL=postgresql+psycopg://postgres:postgres@127.0.0.1:5432/industrial_ai

# jobs / worker_heartbeats / datasets schema migration 적용
uv run --project apps/api alembic -c apps/api/alembic.ini upgrade head

uv run --project apps/api uvicorn api.main:app --host 0.0.0.0 --port 8000
curl -s http://127.0.0.1:8000/health
curl -s http://127.0.0.1:8000/datasets
curl -s http://127.0.0.1:8000/workflows

# migration head 확인
uv run --project apps/api alembic -c apps/api/alembic.ini heads
```

기대 응답:

- `/health` -> `{"status":"ok"}`
- `/datasets` -> dataset registry 목록 + active dataset 상태
- `/workflows` -> `briefing`, `recommendation`, `report_generator` 3종

### 7.2.0 Workflow Demo API / UI

Phase-1 demo reviewer path는 `/demo`와 아래 API 조합이다.

```bash
# dataset 목록
curl -s http://127.0.0.1:8000/datasets

# active dataset 전환
curl -sS -X POST http://127.0.0.1:8000/datasets/active \
  -H "Content-Type: application/json" \
  -d '{"dataset_key":"enterprise_docs"}'

# workflow catalog
curl -s http://127.0.0.1:8000/workflows

# workflow enqueue
curl -sS -X POST http://127.0.0.1:8000/workflows/recommendation/jobs \
  -H "Content-Type: application/json" \
  -d '{"dataset_key":"enterprise_docs","prompt":"Recommend next actions for the pilot review.","k":4}'

# workflow-aware job filter
curl -sS "http://127.0.0.1:8000/jobs?workflow_key=recommendation&dataset_key=enterprise_docs&status=queued"
```

브라우저에서 `http://127.0.0.1:8000/demo`를 열면 같은 흐름을 한 화면에서 수행할 수 있다.

### 7.2.1 Reindex Job Queue API

`POST /rag/reindex`는 mode에 따라 full/incremental job을 큐에 넣고 worker가 백그라운드 실행합니다.

- `mode=full` (default) -> `type=rag_reindex`
- `mode=incremental` -> `type=rag_reindex_incremental`

incremental semantics (M2):

- `RAG_SOURCE_DIR`를 스캔해 `source_path + content_hash` 기준으로 변경분만 반영
- changed/new 문서만 re-chunk/re-embed
- source에서 사라진 문서는 `documents + chunks`에서 삭제
- 전체 재생성이 필요하면 `mode=full` 사용

권장 운영 순서:

1. `POST /rag/warmup`
2. `POST /rag/verify`
3. `POST /rag/reindex?mode=incremental`

주의(M2 한정): SQLite write contention 방지를 위해 full/incremental reindex를 동시에 실행하지 않는다.

```bash
# enqueue full (default)
curl -sS -X POST http://127.0.0.1:8000/rag/reindex

# enqueue explicit full
curl -sS -X POST 'http://127.0.0.1:8000/rag/reindex?mode=full'

# enqueue incremental
curl -sS -X POST 'http://127.0.0.1:8000/rag/reindex?mode=incremental'

# enqueue with optional payload_json
curl -sS -X POST 'http://127.0.0.1:8000/rag/reindex?mode=incremental' \
  -H "Content-Type: application/json" \
  -d '{"payload_json":{"requested_by":"manual","notes":"changed docs only"}}'

# duplicate queued/running job exists -> 409
curl -sS -X POST 'http://127.0.0.1:8000/rag/reindex?mode=incremental'
# {"detail":"rag_reindex_incremental already queued/running","existing_job_id":"..."}

# mode validation error -> 422
curl -sS -X POST 'http://127.0.0.1:8000/rag/reindex?mode=invalid'
# {"detail":[...query mode validation error...]}

# list/filter
curl -sS "http://127.0.0.1:8000/jobs?type=rag_reindex&status=queued"
curl -sS "http://127.0.0.1:8000/jobs?type=rag_reindex_incremental&status=queued"

# detail
curl -sS http://127.0.0.1:8000/jobs/<job_id>
```

incremental enqueue 검증(권장):

```bash
# 1) incremental enqueue
response=$(curl -sS -X POST 'http://127.0.0.1:8000/rag/reindex?mode=incremental')
echo "$response"

# 2) returned job_id 확인 (jq 없는 환경은 수동 복사)
job_id=$(echo "$response" | jq -r '.job_id')

# 3) job detail에서 type 확인
curl -sS "http://127.0.0.1:8000/jobs/${job_id}"
# 기대: "type":"rag_reindex_incremental"

# 4) result_json 확인
# 기대 필드: unchanged / new / updated / removed / documents_total_after / chunks_total_after
```

참고:

- `GET /jobs?type=rag_reindex_incremental`가 계속 빈 배열이면 mode 매핑이 깨졌을 가능성이 있다.
- 현재 버전에서는 `mode=incremental` -> `type=rag_reindex_incremental`로 enqueue되도록 수정되어 있다.

Worker 로그에서 poll/claim/execution 상태를 확인합니다.

```bash
docker compose logs --tail=200 worker
```

### 7.2.2 Operational jobs: warmup / verify

R5-M1에서 운영 점검용 job 2종을 추가했다.

- `POST /rag/warmup` -> `type=ollama_warmup`
- `POST /rag/verify` -> `type=rag_verify_index`

두 엔드포인트 모두 기존 reindex enqueue 패턴과 동일하게 동작한다.

- 성공: `202` + `{"job_id":"...","status":"queued"}`
- 중복(queued/running 존재): `409` + `{"detail":"<job_type> already queued/running","existing_job_id":"..."}`

```bash
# warmup enqueue
curl -sS -X POST http://127.0.0.1:8000/rag/warmup

# verify enqueue
curl -sS -X POST http://127.0.0.1:8000/rag/verify

# list/filter
curl -sS "http://127.0.0.1:8000/jobs?type=ollama_warmup"
curl -sS "http://127.0.0.1:8000/jobs?type=rag_verify_index"
```

`ollama_warmup` runner는 아래를 probe한다.

- Embedding endpoint: `POST /v1/embeddings` (`OLLAMA_EMBED_MODEL`)
- Chat endpoint: `POST /v1/chat/completions` (`OLLAMA_MODEL`)

성공 시 `result_json` 예시:

```json
{
  "embed_ok": true,
  "chat_ok": true,
  "embed_latency_ms": 18,
  "chat_latency_ms": 42,
  "embed_model": "nomic-embed-text",
  "chat_model": "qwen2.5:7b-instruct-q4_K_M"
}
```

중요: **Warmup MVP는 모델 자동 pull을 수행하지 않는다.**
모델 미존재/404/연결 오류 시 job은 실패하며, 에러 메시지에 아래 actionable 가이드를 포함한다.

```bash
docker compose exec -T ollama ollama pull <model>
```

`rag_verify_index` runner는 `RAG_DB_PATH`의 SQLite를 검사한다.

- required tables: `documents`, `chunks`
- counts: `documents`, `chunks` (`chunks > 0` 필수)
- embedding dim: `embedding_dim > 0` 필수
- strict dim check: `RAG_EXPECTED_EMBED_DIM > 0`이면 정확히 일치해야 성공
- sample query sanity check: `RAG_VERIFY_SAMPLE_QUERY` (기본값 `maintenance automation`)로 top-1 검색 결과가 1개 이상이어야 성공

관련 env:

- `RAG_EXPECTED_EMBED_DIM` (default `768`, `0`이면 strict dim check 비활성화)
- `RAG_VERIFY_SAMPLE_QUERY` (default `maintenance automation`)

#### Job 조회 치트시트

```bash
# 최근 N개(기본)
curl -sS "http://127.0.0.1:8000/jobs" | head

# operational type 필터
curl -sS "http://127.0.0.1:8000/jobs?type=rag_reindex_incremental"

# workflow demo 필터
curl -sS "http://127.0.0.1:8000/jobs?workflow_key=briefing&dataset_key=industrial_demo"

# status 필터
curl -sS "http://127.0.0.1:8000/jobs?status=queued"

# type + status
curl -sS "http://127.0.0.1:8000/jobs?type=rag_reindex_incremental&status=queued"

# workflow + dataset + status
curl -sS "http://127.0.0.1:8000/jobs?workflow_key=report_generator&dataset_key=enterprise_docs&status=queued"

# detail
curl -sS "http://127.0.0.1:8000/jobs/<job_id>"
```

- 상태 전이: `queued -> running -> succeeded/failed`
- 완료 후 `GET /jobs/<job_id>`의 `result_json`에서 operational metrics 또는 workflow `evidence[]`/typed output을 확인한다.

### 7.3 Worker 단독 검증(호스트)

```bash
export WORKER_DATABASE_URL=postgresql+psycopg://postgres:postgres@127.0.0.1:5432/industrial_ai
export WORKER_ID=worker-local
export WORKER_HEARTBEAT_SECONDS=30
export WORKER_POLL_SECONDS=5
export JOB_MAX_ATTEMPTS=3
export WORKER_API_PROJECT_DIR=/workspace/apps/api

uv run --project apps/worker python -m worker.main
```

기대 로그(요약):

- `worker_heartbeats` 테이블에 upsert heartbeat 수행
- `workflow_run`, `rag_reindex*`, `ollama_warmup`, `rag_verify_index`를 poll/claim 가능
- DB 오류 시 exponential backoff + jitter로 재시도

### 7.4 Compose(postgres/api/worker/ollama) 검증(선택)

Compose 경로에서는 `api` 컨테이너가 시작 시 아래 순서로 자동 실행한다.

1. `uv run alembic upgrade head`
2. `uv run uvicorn api.main:app --host 0.0.0.0 --port 8000`

따라서 7.2(호스트 단독 검증)과 달리 Compose에서는 수동 migration 명령을 별도로 실행할 필요가 없다.

Troubleshooting / Dev note:

- 코드/README를 수정한 뒤 컨테이너를 재시작하지 않으면 이전 버전 API가 계속 실행될 수 있다.

```bash
# 빠른 재시작
docker compose restart api worker

# 이미지 반영 강제
docker compose up -d --build --force-recreate
```

- openapi에서 `mode` 파라미터가 안 보이면(또는 `mode=invalid`가 422가 아니면) old 컨테이너를 먼저 의심한다.

compose에서 명시적으로 사용하는 주요 환경변수:

- API DB: `API_DATABASE_URL`
- Worker DB: `WORKER_DATABASE_URL`
- Worker poll interval: `WORKER_POLL_SECONDS` (default `5`)
- Worker retry cap fallback: `JOB_MAX_ATTEMPTS` (default `3`)
- Worker API project path for subprocess runner: `WORKER_API_PROJECT_DIR`
- Default dataset source dir (compose override): `RAG_SOURCE_DIR=/workspace/data/sample_docs`
- Default dataset index dir (compose override): `RAG_INDEX_DIR=/workspace/data/rag_index`
- Default dataset sqlite path (compose override): `RAG_DB_PATH=/workspace/data/rag_index/rag.db`
- Secondary demo dataset path: `/workspace/data/datasets/enterprise_docs/{source,index}`
- Worker Ollama env for subprocess runner: `OLLAMA_BASE_URL`, `OLLAMA_EMBED_BASE_URL`, `OLLAMA_EMBED_MODEL`
- Verify runner settings: `RAG_EXPECTED_EMBED_DIM` (default `768`, disable with `0`), `RAG_VERIFY_SAMPLE_QUERY`
- Ollama base URL: `OLLAMA_BASE_URL=http://ollama:11434/v1`
- Ollama model: `OLLAMA_MODEL=qwen2.5:7b-instruct-q4_K_M`
- Ollama fallback model: `OLLAMA_FALLBACK_MODEL=qwen2.5:3b-instruct-q4_K_M`
- Ollama embed base URL: `OLLAMA_EMBED_BASE_URL=http://ollama:11434/v1`
- Ollama embed model: `OLLAMA_EMBED_MODEL=nomic-embed-text`
- Ollama timeout: `OLLAMA_TIMEOUT_SECONDS=60`

`RAG_DB_PATH` 우선순위 규칙: `RAG_DB_PATH`가 설정되면 그 값을 사용하고, 비어있으면 `RAG_INDEX_DIR/rag.db`를 기본값으로 사용한다.

컨테이너 vs 호스트 경로(중요):

- Host 기본 dataset artifact: `data/sample_docs`, `data/rag_index/rag.db`
- Compose(컨테이너) 기본 override: `/workspace/data/sample_docs`, `/workspace/data/rag_index/rag.db`
- Secondary demo dataset artifact: `data/datasets/enterprise_docs/source`, `data/datasets/enterprise_docs/index/index.json`
- 호스트에서 만든 파일이 compose에서 보이려면 repo working tree를 공유 마운트(= `/workspace`)해야 한다.

Ollama 모델 영속성:

- compose는 `/root/.ollama`를 외부 볼륨 `ollama-models`에 마운트한다.
- 모델/볼륨을 삭제할 수 있는 위험 명령 예시(주의):
  - `docker compose down -v` (프로젝트 볼륨 삭제 가능)
  - `docker system prune --volumes` (볼륨까지 정리되어 모델 손실 가능)
  - `docker volume rm ollama-models` (외부 볼륨 직접 삭제)
- 안전한 대안:
  - `docker compose down --remove-orphans`
- `ollama-models` 볼륨은 external로 유지되며, 위 위험 명령을 피하면 모델 재다운로드를 방지할 수 있다.
- 최초 1회 볼륨 생성:
  - `docker volume create ollama-models || true`

```bash
# run on host
docker compose up -d --build

# 서비스명 확인
docker compose config --services

# 모델 warm-up (초회 1회 권장; pull이 끝나야 /ask 응답이 빠르게 안정화됨)
docker compose exec -T ollama ollama pull qwen2.5:3b-instruct-q4_K_M
# (선택) 기본 모델을 미리 받을 경우
docker compose exec -T ollama ollama pull qwen2.5:7b-instruct-q4_K_M
# embeddings 모델
docker compose exec -T ollama ollama pull nomic-embed-text

# HTTP 라우트 확인
curl -s http://127.0.0.1:8000/health
curl -s http://127.0.0.1:8000/datasets
curl -s http://127.0.0.1:8000/workflows
curl -s http://127.0.0.1:8000/demo | head
curl -s http://127.0.0.1:8000/jobs
curl -sG "http://127.0.0.1:8000/rag/search" \
  --data-urlencode "q=maintenance automation" \
  --data-urlencode "k=3" \
  --data-urlencode "dataset_key=industrial_demo"
curl -s -X POST "http://127.0.0.1:8000/ask" \
  -H "Content-Type: application/json" \
  -d '{"question":"What maintenance actions are recommended?","k":3,"dataset_key":"industrial_demo"}'

# 로그 확인
docker compose logs -f --tail=120 worker

# DB 스키마 확인
docker compose exec -T postgres psql -U postgres -d industrial_ai -c "\d worker_heartbeats"
docker compose exec -T postgres psql -U postgres -d industrial_ai -c "select worker_id, updated_at from worker_heartbeats order by updated_at desc limit 3;"
```

기대 로그(요약):

- `postgres` healthy 상태 진입
- `api` 로그에 `[api] running alembic upgrade head` 출력 후 migration 적용
- `api` 서비스 기동 및 8000 포트 노출
- `worker` heartbeat upsert 반복 출력
- `ollama` 서비스 기동 (11434 포트)
- `/ask` 응답 JSON에 `answer`, `sources`, `meta` 필드 포함

### 7.5 How to run tests

테스트는 Docker/Postgres 없이 로컬에서 실행 가능하다.

```bash
uv run --project apps/api pytest -q apps/api/tests
uv run --project apps/worker pytest -q apps/worker/tests
```

현재 스위트에는 Phase-1 migration, dataset/workflow API, workflow service typed output, worker `workflow_run` 저장 검증이 포함된다.

위처럼 각 테스트 루트를 명시하면 api/worker 간 테스트 교차 탐색을 막을 수 있다.
특히 워크스페이스 루트에서 실행할 때도 의도한 스위트만 실행된다.
검증 로그와 실패 지점을 서비스 단위로 분리해 추적하기 쉽다.

### 7.6 Type-check (Pyright)

Pyright의 canonical 검증 명령은 아래 2줄이다.

```bash
uv sync --dev
uv run pyright -p pyrightconfig.json
```

`uvx --with pyright pyright ...`는 격리된 환경에서 실행되어 프로젝트 의존성을 보지 못할 수 있다.
이 경우 missing-import 오탐이 발생할 수 있으므로 공식 검증 증거로 사용하지 않는다.

### 7.7 Week-2 R1/R4 RAG ingestion (호스트, hermetic)

기본 입력 경로는 `data/sample_docs`이며 `.txt`, `.md` 문서를 읽어 로컬 SQLite 인덱스(`rag.db`)를 생성한다.
R4에서 retrieval 저장소를 JSON 파일에서 SQLite 단일 파일로 전환했다.

- SQLite 선택 이유: 단일 파일 배포/백업이 쉽고, 문서/청크/벡터를 트랜잭션으로 일관되게 관리할 수 있다.
- retrieval 계산은 현재 Python brute-force cosine(MVP/demo-scale)이며, ANN/kNN 최적화는 R5로 deferred.

```bash
uv run --project apps/api rag-ingest
find data/rag_index -maxdepth 3 -type f | sort
```

기대 결과(요약):

- `[rag-ingest] completed documents=<N> chunks=<M> index=data/rag_index/rag.db` (또는 절대경로 출력)
- `data/rag_index/rag.db` 파일 생성
- Docker/Compose 없이 호스트에서 단독 실행 가능
- Compose 실행 시에는 `RAG_SOURCE_DIR`, `RAG_INDEX_DIR`, `RAG_DB_PATH` 환경변수로 `/workspace/...` 경로를 명시 override한다.

Ollama embedding 모델 준비(최초 1회):

```bash
ollama pull nomic-embed-text
```

SQLite index 확인:

```bash
sqlite3 data/rag_index/rag.db "select count(*) as chunks from chunks;"

# sqlite3 CLI가 없으면 python stdlib 대안
python -c "import sqlite3; c=sqlite3.connect('data/rag_index/rag.db'); print(c.execute('select count(*) from chunks').fetchone()[0]); c.close()"
```

### 7.8 Week-2 R2/R4 RAG search API (호스트, hermetic)

R2/R4는 로컬 SQLite 인덱스(`rag.db`)를 읽어 `GET /rag/search` 조회를 수행한다(포트 `8000`).
호환성 윈도우(1 release) 동안 `rag.db`가 없고 기존 `index.json`만 있으면 fallback으로 JSON 인덱스를 읽는다.

```bash
# 1) 인덱스 생성
uv run --project apps/api rag-ingest

# 2) API 실행
uv run --project apps/api uvicorn api.main:app --host 0.0.0.0 --port 8000

# 3) 검색 요청
curl -sG "http://127.0.0.1:8000/rag/search" \
  --data-urlencode "q=maintenance automation" \
  --data-urlencode "k=3"
```

기대 결과(요약):

- `/rag/search`가 `chunk_id`, `source_path`, `title`, `score`, `text` 필드를 포함한 JSON 배열 반환
- `rag.db`가 없고 `index.json`이 있으면 JSON fallback으로 검색
- 둘 다 없으면 503 + `rag-ingest` 실행 안내 메시지 반환
- Compose 실행 중에도 동일하게 `http://127.0.0.1:8000/rag/search`로 조회 가능

### 7.9 Week-2 R3 `/ask` (RAG + Ollama, fully local)

`POST /ask`는 로컬 RAG SQLite 인덱스 검색 결과를 컨텍스트로 묶고, Ollama의 OpenAI-compatible chat completions API(`/v1/chat/completions`)를 호출해 답변을 생성한다.
검색 query embedding 생성에는 Ollama OpenAI-compatible embeddings API(`/v1/embeddings`)를 사용한다.

요청/응답 요약:

- Request: `{"question":"...", "k":3, "dataset_key":"industrial_demo"}` (`dataset_key`는 optional)
- Response: `{"answer": "...", "sources": [...], "meta": {...}}`
- `sources`에는 `chunk_id`, `source_path`, `title`, `score`, `text`가 포함된다.
- `meta`에는 `dataset_key`, `dataset_title`이 함께 포함된다.

#### 7.9.1 macOS 런타임 선택: Ollama vs LM Studio

> **macOS Docker has no GPU passthrough; Ollama-in-Docker is CPU-only and slow; Metal acceleration requires host runtime; recommend LM Studio host when Metal/GUI needed.**

- Compose 기본값은 `OLLAMA_BASE_URL=http://ollama:11434/v1` (컨테이너 내부 서비스 경로).
- Embedding 기본값은 `OLLAMA_EMBED_BASE_URL=http://ollama:11434/v1`, `OLLAMA_EMBED_MODEL=nomic-embed-text`.
- 호스트에서 Ollama/LM Studio를 띄우고 API 컨테이너가 이를 바라보게 하려면 fallback으로 아래를 사용:
  - `OLLAMA_BASE_URL=http://host.docker.internal:11434/v1`
  - `OLLAMA_EMBED_BASE_URL=http://host.docker.internal:11434/v1`

#### 7.9.2 MacBook Air M2 16GB 권장 모델

- Chat (기본): `qwen2.5:7b-instruct-q4_K_M`
- Chat fallback(메모리/속도 우선): `qwen2.5:3b-instruct-q4_K_M`
- Embedding: `nomic-embed-text`

## 8. 디렉토리 구조

```text
.
├── AGENTS.md
├── Dockerfile
├── README.md
├── compose.omx.yml
├── compose.yml
├── entrypoint.sh
├── .python-version
├── pyproject.toml
├── uv.lock
├── apps
│   ├── api
│   │   ├── pyproject.toml
│   │   ├── alembic.ini
│   │   ├── alembic/
│   │   │   ├── env.py
│   │   │   ├── script.py.mako
│   │   │   └── versions/
│   │   │       ├── 20260227_0001_create_jobs_table.py
│   │   │       ├── 20260227_0002_create_worker_heartbeats_table.py
│   │   │       ├── 20260302_0003_extend_jobs_for_rag_reindex.py
│   │   │       └── 20260308_0004_add_datasets_and_workflow_fields.py
│   │   └── src/api/
│   │       ├── config.py
│   │       ├── db.py
│   │       ├── dependencies.py
│   │       ├── ingest.py
│   │       ├── main.py
│   │       ├── models.py
│   │       ├── routers/
│   │       ├── services/datasets/
│   │       ├── services/retrieval/
│   │       ├── services/workflows/
│   │       └── static/demo/
│   └── worker
│       ├── pyproject.toml
│       └── src/worker/main.py
├── data
│   ├── sample_docs/
│   ├── rag_index/
│   └── datasets/
│       ├── industrial_demo/
│       └── enterprise_docs/
└── shared
    └── db/interface.py
```
