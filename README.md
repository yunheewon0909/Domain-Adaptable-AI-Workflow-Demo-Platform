# Industrial AI Harness Platform

Week-1 MVP를 위한 초기 스켈레톤 저장소입니다.  
원칙은 `호스트(macOS) = Homebrew + uv 중심`, `위험 실행(OMX madmax/codex) = Docker sandbox 내부 전용`입니다.

## 1. 목적

- 산업용 AI 하네스 플랫폼의 최소 실행 뼈대를 만든다.
- API/FastAPI와 Worker를 분리해 이후 DB/큐를 단계적으로 붙일 수 있게 한다.
- 운영 규칙(커밋 게이트, 문서 우선 업데이트)을 코드와 문서에 함께 강제한다.

## 2. Week-1 범위

- `apps/api`: FastAPI `/health`, `/jobs`(DB 조회) + Alembic jobs 마이그레이션
- `apps/worker`: DB heartbeat upsert + retry/backoff
- `shared/db/interface.py`: 다음 마일스톤용 DB 인터페이스 자리만 제공
- `Dockerfile`, `entrypoint.sh`, `compose.omx.yml`: OMX 격리 샌드박스
- `compose.yml`: api/worker/postgres 최소 실행 골격
- Week-2 R1-R4: 로컬 RAG ingestion + search + ask API (`data/sample_docs` -> chunk/embed -> `data/rag_index/rag.db`, `/rag/search`, `/ask`)

## 2.1 마일스톤 진행 상태

- [x] M0: 레포 초기화 + 기본 문서/규칙 + 디렉토리 트리
- [x] M1: OMX 도커 샌드박스 파일 + 호스트 검증
- [x] M2: uv 기반 Python api/worker 스켈레톤
- [x] M3: Postgres 서비스 + API DB 설정 플럼빙 + Alembic 스캐폴드
- [x] M4: Alembic jobs 마이그레이션 + `/jobs` DB 조회
- [x] M5: worker heartbeat DB upsert + retry/backoff

## 2.2 Week-2 RAG v1 진행 상태

- [x] R1: `data/sample_docs` -> chunk -> embed -> `data/rag_index` ingestion
- [x] R2 (accepted): 로컬 인덱스 기반 `/rag/search` 조회 API
- [x] R3: `POST /ask` + Ollama(OpenAI-compatible) 생성 경로 + compose `ollama` 서비스
- [x] R4: Ollama embeddings + SQLite(`rag.db`) 기반 retrieval 전환 (JSON fallback 1-release 호환)

## 3. 아키텍처(초기)

```text
macOS host
  ├─ uv / git / docker (host tools)
  ├─ repo working tree
  └─ Docker OMX sandbox
       ├─ Node 20+, @openai/codex, oh-my-codex
       ├─ forwarded SSH agent socket
       └─ host ~/.codex(ro) -> container $CODEX_HOME(rw, one-time copy)

Week-1 services
  ├─ api (FastAPI)
  └─ worker (heartbeat loop)
```

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

# jobs / worker_heartbeats 테이블 migration 적용
uv run --project apps/api alembic -c apps/api/alembic.ini upgrade head

uv run --project apps/api uvicorn api.main:app --host 0.0.0.0 --port 8000
curl -s http://127.0.0.1:8000/health
curl -s http://127.0.0.1:8000/jobs

# migration head 확인
uv run --project apps/api alembic -c apps/api/alembic.ini heads
```

기대 응답:

- `/health` -> `{"status":"ok"}`
- `/jobs` -> `jobs` 테이블 조회 결과(JSON 배열)

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

# type 필터
curl -sS "http://127.0.0.1:8000/jobs?type=rag_reindex_incremental"

# status 필터
curl -sS "http://127.0.0.1:8000/jobs?status=queued"

# type + status
curl -sS "http://127.0.0.1:8000/jobs?type=rag_reindex_incremental&status=queued"

# detail
curl -sS "http://127.0.0.1:8000/jobs/<job_id>"
```

- 상태 전이: `queued -> running -> succeeded/failed`
- 완료 후 `GET /jobs/<job_id>`의 `result_json`에서 `unchanged/new/updated/removed` 및 오류 메시지를 확인한다.

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
- RAG source dir (compose override): `RAG_SOURCE_DIR=/workspace/data/sample_docs`
- RAG index dir (compose override): `RAG_INDEX_DIR=/workspace/data/rag_index`
- RAG sqlite path (compose override): `RAG_DB_PATH=/workspace/data/rag_index/rag.db`
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

- Host 기본: `data/sample_docs`, `data/rag_index/rag.db`
- Compose(컨테이너) 기본 override: `/workspace/data/sample_docs`, `/workspace/data/rag_index/rag.db`
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
curl -s http://127.0.0.1:8000/jobs
curl -sG "http://127.0.0.1:8000/rag/search" \
  --data-urlencode "q=maintenance automation" \
  --data-urlencode "k=3"
curl -s -X POST "http://127.0.0.1:8000/ask" \
  -H "Content-Type: application/json" \
  -d '{"question":"What maintenance actions are recommended?","k":3}'

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

- `/rag/search`가 `chunk_id`, `source_path`, `score`, `text` 필드를 포함한 JSON 배열 반환
- `rag.db`가 없고 `index.json`이 있으면 JSON fallback으로 검색
- 둘 다 없으면 503 + `rag-ingest` 실행 안내 메시지 반환
- Compose 실행 중에도 동일하게 `http://127.0.0.1:8000/rag/search`로 조회 가능

### 7.9 Week-2 R3 `/ask` (RAG + Ollama, fully local)

`POST /ask`는 로컬 RAG SQLite 인덱스 검색 결과를 컨텍스트로 묶고, Ollama의 OpenAI-compatible chat completions API(`/v1/chat/completions`)를 호출해 답변을 생성한다.
검색 query embedding 생성에는 Ollama OpenAI-compatible embeddings API(`/v1/embeddings`)를 사용한다.

요청/응답 요약:

- Request: `{"question":"...", "k":3}` (`question` 필드명 고정)
- Response: `{"answer": "...", "sources": [...], "meta": {...}}`
- `sources`에는 `chunk_id`, `source_path`, `score`, `text`가 포함된다.

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
│   │   │       └── 20260227_0001_create_jobs_table.py
│   │   │       └── 20260227_0002_create_worker_heartbeats_table.py
│   │   └── src/api/
│   │       ├── config.py
│   │       ├── db.py
│   │       ├── ingest.py
│   │       ├── models.py
│   │       ├── main.py
│   │       └── services/rag/
│   │           ├── ingest.py
│   │           ├── query.py
│   │           └── ...
│   └── worker
│       ├── pyproject.toml
│       └── src/worker/main.py
├── data
│   ├── sample_docs/
│   └── rag_index/ (runtime output, git ignored)
└── shared
    └── db/interface.py
```
