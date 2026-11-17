# PyDebugger Learning Platform

PyDebugger is a document-grounded Python tutor and debugging assistant. The
supported application has one backend composition root, a Streamlit entry
point, and a React + FastAPI classroom interface. Earlier scripts remain
in `langchain-openai/` and `webscrapping/` as historical experiments; new
backend development should use `src/pydebugger/` and `src/pydebugger_api/`.

## Supported architecture

The backend is split into modules with narrow responsibilities:

- `config.py` — validated environment configuration
- `providers.py` — AI chat and embedding provider adapters
- `ingestion.py` — safe document extraction and chunking
- `youtube.py` — validated video references and transcript-provider adapter
- `retrieval.py` — vector indexing and corpus-wide ranking
- `routing.py` — bounded LangGraph request routing with rule-based classification
- `hints.py` — LangGraph hint progression and duplicate prevention
- `tutoring.py` — tutor prompts, citations, history, and progressive hints
- `execution.py` — asynchronous, cancellable Docker execution jobs
- `jobs.py` — bounded background queues, retries, deadlines, and progress
- `monitoring.py` — durable latency, failure, usage, and cost metrics
- `quality.py` — measured end-to-end engine evaluation
- `engine.py` — the single composition root used by the application
- `pydebugger_api/` — FastAPI routes, API configuration, and PostgreSQL access

The primary vector backend is PostgreSQL with pgvector. It records the embedding
identity, vector dimension, and index schema; uses collection-specific HNSW
indexes; ranks matches across all selected documents in one query; and returns
stable chunk IDs and relevance scores for traceable citations. Chroma remains a
temporary migration fallback, and the in-memory index exists only as a test
double.

Uploads support validated PDF, UTF-8 text, CSV, PPTX, Markdown, and restricted
reStructuredText. Chunks retain file hashes, media types, page/slide/row or
heading locations, line and character ranges, and source origin. YouTube URLs or
video IDs can be indexed from available transcripts with timestamp and language
metadata. Transcript availability depends on YouTube and may be blocked from
some cloud-hosting IP ranges.

The validation rules, parser limits, metadata contract, and transcript behavior
are documented in `docs/INGESTION.md`.

Document uploads and YouTube transcripts run as background jobs with bounded
worker and queue capacity. Jobs expose progress, current phase, attempt count,
and stable terminal states. Invalid input fails immediately; transient storage
or indexing errors retry up to the configured limit. See
`docs/BACKGROUND_JOBS.md` for lifecycle and timeout semantics.

The Operations tab reads durable local metrics from SQLite. Chat-token counts
come from the model response; embedding-token counts are explicitly labeled
estimates because the embedding integration does not return usage. Cost is only
calculated after the deployment's contracted per-million-token rates are set in
configuration. See `docs/QUALITY_MONITORING.md`.

## FastAPI, PostgreSQL, and React application

The API layer is intentionally separate from the learning engine. FastAPI owns
HTTP concerns, SQLAlchemy owns database connections, and `src/pydebugger/`
continues to own ingestion, tutoring, retrieval, and execution behavior. This
keeps both the existing Streamlit UI and the React UI thin.

Start the local PostgreSQL 17 database with pgvector:

```powershell
docker compose up -d postgres
uv run --locked alembic upgrade head
```

Start the API:

```powershell
uv run --locked uvicorn pydebugger_api.main:app --reload --host 127.0.0.1 --port 8000
```

In a second PowerShell terminal, install and start the React development UI:

```powershell
Set-Location "N:\CODE\Codex\RubberDuck\frontend"
npm install
npm run dev
```

Open [http://localhost:5173](http://localhost:5173), create an account, and sign
in. Vite proxies `/api` requests to the FastAPI process on port 8000. The React
application includes the authenticated course library, grounded tutor,
multi-file Monaco Python workspace, structured test results and diagnostics,
and operational monitoring. The existing Streamlit application remains a
supported transition interface until the manual parity gate in
`docs/REACT_PARITY.md` is completed. It is not deprecated or scheduled for
removal yet.

To point a production frontend build at a different API origin, copy
`frontend/.env.example` to `frontend/.env` and set `VITE_API_BASE_URL`. Build
the static bundle with:

```powershell
npm run build
```

Useful development URLs:

- API documentation: [http://localhost:8000/docs](http://localhost:8000/docs)
- Liveness: [http://localhost:8000/api/v1/health](http://localhost:8000/api/v1/health)
- PostgreSQL/pgvector readiness: [http://localhost:8000/api/v1/ready](http://localhost:8000/api/v1/ready)

`/health` confirms that the API process is running. `/ready` additionally checks
that PostgreSQL is reachable and that the `vector` extension exists. Keeping
these checks separate allows deployment platforms to distinguish a live process
from one that is not ready to receive traffic.

The local database credentials in `compose.yaml` are development-only. Use a
strong secret and override `PYDEBUGGER_DATABASE_URL` outside local development.
The engine selects pgvector by default from environment configuration. Set
`PYDEBUGGER_EMBEDDING_DIMENSION` to the exact output dimension of the configured
embedding model. Existing collections reject model or dimension changes instead
of mixing incompatible vectors.

### Basic authentication API

Authentication uses normalized email addresses, Argon2 password hashes, and
signed one-hour JWT access tokens. Set a unique secret of at least 32 characters
in `.env`; never use the documented development default in a deployment:

```dotenv
PYDEBUGGER_ENVIRONMENT="production"
PYDEBUGGER_JWT_SECRET_KEY="replace-with-a-long-random-production-secret"
PYDEBUGGER_JWT_EXPIRY_MINUTES="60"
```

Available endpoints:

- `POST /api/v1/auth/register` with JSON `email` and `password`
- `POST /api/v1/auth/login` with JSON `email` and `password`
- `GET /api/v1/auth/me` with `Authorization: Bearer <token>`
- `POST /api/v1/auth/logout` with `Authorization: Bearer <token>`

Access tokens are stateless. Logout therefore removes the token from the React
client; refresh-token rotation and server-side revocation are intentionally
reserved for a later production-hardening phase.

### Authenticated document API

Document IDs are namespaced by authenticated user, so two students can upload
the same filename or index the same YouTube video without replacing each
other's content. PostgreSQL records document and ingestion-job ownership; every
read, cancellation, and deletion checks that ownership without revealing
whether another user owns the requested ID.

- `POST /api/v1/documents/upload` — multipart field `file`
- `POST /api/v1/documents/youtube` — JSON `reference` and `languages`
- `GET /api/v1/documents` — list the current user's indexed documents
- `DELETE /api/v1/documents/{document_id}` — remove owned storage and vectors
- `GET /api/v1/ingestion-jobs/{job_id}` — read owned job progress/results
- `POST /api/v1/ingestion-jobs/{job_id}/cancel` — cancel an owned job

Upload bodies are bounded before engine submission. Ingestion continues through
the existing validated background worker, and completed engine metadata is
synchronized into the owned PostgreSQL document catalog. Ingestion worker state
and results are persisted in PostgreSQL. If the process restarts during active
work, startup recovery marks that job failed with `worker_restarted` rather than
leaving it permanently queued.

### Authenticated tutoring API

`POST /api/v1/tutor/answer` accepts a question, learning mode, selected document
IDs, and recent conversation history. Before retrieval or an LLM call, the API
verifies that every selected document belongs to the authenticated user. Answers
return structured citations and a `grounded` flag.

```json
{
  "query": "Explain Python loops",
  "mode": "programming_tutor",
  "document_ids": ["upload-document-id"],
  "history": [{"role": "user", "content": "What repeats?"}]
}
```

`POST /api/v1/tutor/hint` accepts the current problem, conversation history, and
previous hints. It returns the next progressive hint without exposing another
user's documents. History is validated and bounded at the API boundary, while
the existing tutor service performs relevance selection and token budgeting.

Conversation history is currently supplied by the React client on each request.
Durable student conversation history will be introduced in its own milestone.

### Authenticated execution API

Execution routes submit work only to the existing isolated execution service;
the FastAPI process never evaluates student Python or launches a host Python
subprocess.

- `POST /api/v1/executions/single-file` — submit one Python source string
- `POST /api/v1/executions/project` — submit validated files, entrypoint, and tests
- `GET /api/v1/executions/{execution_id}` — poll owned job state and results
- `POST /api/v1/executions/{execution_id}/cancel` — cancel an owned execution

Responses contain stdout/stderr, duration, exit code, timeout/cancellation and
resource-limit flags, structured test results, and Python diagnostics with file
and line information. Job ownership is persisted in PostgreSQL, while detailed
state, attempts, errors, diagnostics, test results, and progress snapshots are
persisted by worker callbacks.

### Durable job state

Ingestion and execution workers publish queued, running, retrying, progress, and
terminal snapshots to PostgreSQL. Job result payloads survive API restarts, so
clients can still retrieve completed document metadata, diagnostics, output, and
test results after the in-memory worker object is gone.

The bounded thread pools and their queued payloads remain process-local. An API
restart cannot resume code or ingestion that was actively running; those records
become terminal failures with the stable `worker_restarted` error code. Moving
payload execution to an external broker/worker system remains a later scaling
step, but it will retain the same public job contracts.

### Health and monitoring APIs

- `GET /api/v1/health` is a public liveness probe. It does not contact external
  dependencies.
- `GET /api/v1/ready` is a public readiness probe. It reports separate
  PostgreSQL, pgvector, and Alembic migration checks and returns `503` until all
  are ready.
- `GET /api/v1/monitoring/summary?window_seconds=86400` requires authentication
  and returns per-operation calls, failures, failure rate, average/p95 latency,
  token usage, and configured cost totals.

Monitoring responses never include prompts, answers, document content, student
code, filenames, credentials, or API keys. Until instructor/admin roles are
introduced, any authenticated user can access aggregate operational metrics;
deployments that require stricter separation should disable the route at the
gateway.

Stop the local database without deleting its volume:

```powershell
docker compose stop postgres
```

## Run the Streamlit transition application

Python 3.12 is the supported runtime. `uv.lock` pins the complete dependency
graph, and `.python-version` pins the Python patch release.

### Windows step-by-step guide

1. Install the required tools:

   - Python 3.12
   - [uv](https://docs.astral.sh/uv/getting-started/installation/)
   - Docker Desktop only if you want to execute student code

2. Open PowerShell and enter the repository directory:

   ```powershell
   Set-Location "N:\CODE\Codex\RubberDuck"
   ```

3. Install the exact locked dependencies:

   ```powershell
   uv sync --locked --extra dev
   ```

4. Create the local environment file if it does not already exist:

   ```powershell
   Copy-Item .env.example .env
   ```

5. Open `.env` and configure Google Gemini:

   ```dotenv
   PYDEBUGGER_AI_PROVIDER="gemini"
   GOOGLE_API_KEY="your-google-ai-studio-key"
   GOOGLE_CHAT_MODEL="gemini-3.5-flash-lite"
   GOOGLE_EMBEDDING_MODEL="gemini-embedding-001"
   ```

   Create a key at [Google AI Studio](https://aistudio.google.com/apikey). Never
   commit the `.env` file or share its API key.

6. Optional: enable the isolated Python lab. Start Docker Desktop, wait for the
   Docker engine to become ready, and run:

   ```powershell
   docker pull python:3.13-slim-bookworm@sha256:a5a7017efc5969e00ae2b91c8eb0631049a569652aa4ffc4501769049ae45c72
   ```

   Then set this value in `.env`:

   ```dotenv
   PYDEBUGGER_EXECUTION_BACKEND="docker"
   ```

   Keep `PYDEBUGGER_EXECUTION_BACKEND="disabled"` when Docker is unavailable.
   Tutoring and document retrieval will still work, but code execution will be
   disabled.

7. Start the application:

   ```powershell
   uv run --locked streamlit run app.py
   ```

8. Open [http://localhost:8501](http://localhost:8501) in your browser. To use a
   different port:

   ```powershell
   uv run --locked streamlit run app.py --server.port 8502
   ```

9. Verify the main workflows:

   - Upload a PDF, TXT, Markdown, CSV, RST, or PPTX document.
   - Select the indexed document and ask a question in **Tutor**.
   - Open **Python lab**, edit `main.py`, add files or tests, and select
     **Run project**.
   - Open **System health** to review operations, failures, latency, and usage.

10. Run the automated tests:

    ```powershell
    uv run --locked pytest -q
    uv lock --check
    ```

    Docker integration tests are optional and require the Docker engine plus the
    pinned image:

    ```powershell
    $env:PYDEBUGGER_RUN_DOCKER_TESTS="1"
    uv run --locked pytest -q tests\test_execution_docker.py
    ```

11. Stop the application by returning to its PowerShell window and pressing
    `Ctrl+C`.

### Common startup problems

- **Configuration error:** confirm `.env` contains a valid Gemini or Azure key.
- **Port already in use:** start with `--server.port 8502` or another free port.
- **Docker backend is not ready:** start Docker Desktop and confirm `docker version`
  succeeds.
- **Pinned image is missing:** repeat the `docker pull` command from step 6.
- **Old embeddings fail after changing models:** use a new
  `PYDEBUGGER_VECTOR_COLLECTION` value in `.env`.

```powershell
uv sync --locked --extra dev
Copy-Item .env.example .env
uv run --locked streamlit run app.py
```

Gemini through Google AI Studio is the default low-cost provider. Populate
`.env` with `GOOGLE_API_KEY`, `GOOGLE_CHAT_MODEL`, and
`GOOGLE_EMBEDDING_MODEL`. To use Azure instead, set
`PYDEBUGGER_AI_PROVIDER="azure_openai"` and configure its endpoint, API key,
chat deployment, and embedding deployment.

The current Gemini defaults are `gemini-3.5-flash-lite` for tutoring and
`gemini-embedding-001` for retrieval. Changing the embedding model requires a
new `PYDEBUGGER_VECTOR_COLLECTION` name so incompatible vectors are never mixed.

Token controls default to three retrieved chunks, a 2,500-token retrieval
context budget, a 750-token conversation budget (at most six relevant messages),
and 600 output tokens. Override `PYDEBUGGER_RETRIEVAL_LIMIT`,
`PYDEBUGGER_RETRIEVAL_CONTEXT_TOKENS`,
`PYDEBUGGER_CONVERSATION_CONTEXT_TOKENS`, or
`PYDEBUGGER_LLM_MAX_OUTPUT_TOKENS` when a course needs different limits. Request
routing and hint-stage updates are deterministic; they do not consume an extra
model call.

Configuration is validated before providers or storage are initialized. Invalid
URLs, placeholders, numeric limits, mutable execution images, and unavailable
Docker runtimes produce a clear startup error without printing secrets.

Code execution is disabled by default. To enable the isolated runner, start the
Docker Linux engine and pull the exact pinned image from `.env.example`:

```powershell
docker pull python:3.13-slim-bookworm@sha256:a5a7017efc5969e00ae2b91c8eb0631049a569652aa4ffc4501769049ae45c72
# Set PYDEBUGGER_EXECUTION_BACKEND="docker" in .env
uv run --locked streamlit run app.py
```

Each submission runs outside the app server in a disposable container with no
network, a read-only root filesystem and source mount, an unprivileged user, no
Linux capabilities, no-new-privileges, and CPU, memory, process, temporary
storage, output, source-size, and time limits. Runs can be cancelled and are
forcibly cleaned up. See `docs/EXECUTION_SECURITY.md` for the threat model and
deployment requirements.

Syntax and runtime failures are returned as structured diagnostics with the
original submitted line and column numbers. Runtime traces contain only learner
frames from `submission.py`; sandbox bootstrap frames are hidden. The supported
interface intentionally provides **Run** and **Cancel** only. Experimental pause,
step, breakpoint, and watch controls are not presented until a real interactive
debugger protocol is implemented.

## Test the backend

```powershell
uv run --locked --extra dev pytest
uv lock --check
```

The tests use fake AI providers, so they do not consume API credits.

To run the versioned baseline against the configured AI provider and the
real supported engine (this consumes model quota):

```powershell
uv run --locked python scripts/evaluate_engine.py evaluation/classroom_baseline.json `
  --output evaluation-result.json
```

The evaluation uses an isolated temporary corpus and exits non-zero when its
minimum pass rate is missed. The old random/mock evaluator was removed.

## Supported document flow

1. `PyDebuggerEngine.add_document()` validates and stores the upload.
2. `DocumentIngestor` extracts text and preserves source locations.
3. `PgVectorIndex` persists chunks and ranks matches across all selected files.
4. `TutorService` selects relevant history, enforces an evidence threshold, and
   builds citations. Unsupported questions do not call the chat model.
5. The configured `ChatProvider` generates the response.

Uploading the same normalized filename replaces that logical document. Its ID
stays stable, while its SHA-256 content hash and chunk index version change.
New chunks are indexed before obsolete chunks and files are removed; failed
replacement leaves the previous revision available. Deletion clears both the
vector records and the document's bounded storage directory.

Supported uploads are PDF, TXT, Markdown, reStructuredText, CSV, and PPTX.
reStructuredText raw directives and external file insertion are disabled.

## Current milestone boundaries

- Document files persist in bounded local storage; catalog metadata and vectors
  persist in PostgreSQL for shared application instances.
- Gemini and Azure OpenAI are supported provider adapters; Gemini is the default
  when `GOOGLE_API_KEY` is configured.
- Code execution is off unless the Docker backend and pinned image pass startup checks.
- Basic authentication is implemented. Courses, enrollment, durable student
  history, assignments, and instructor dashboards remain planned.

## Legacy experiments

Install `requirements-legacy.txt` only when reproducing the older experimental
scripts. They use separate app flows and are not the supported production path.
Some legacy documentation in `USAGE.md` describes those earlier scripts.
