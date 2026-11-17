# React parity and Streamlit retirement gate

`app.py` and the Streamlit dependencies must remain until every automated and
manual gate below passes. Technical implementation alone does not authorize
removal: the React application must be exercised against PostgreSQL, pgvector,
the configured model provider, and the Docker execution sandbox.

## Implemented in React

- Email/password registration, login, logout, session restoration, and protected routes.
- Multiple document upload with independent ingestion progress and cancellation.
- YouTube transcript ingestion with ordered language preferences.
- Owned document listing, selection, and deletion.
- Programming Tutor and Rubber Duck modes.
- Conversation context, evidence status, source excerpts, source links, chunk IDs,
  relevance scores, and conversation clearing.
- A standalone progressive-hint problem editor and hint progression.
- Monaco Python editing, multiple files, file removal, and project reset.
- A separately selectable project entry point.
- Optional structured test execution with stdin, expected output, pass/fail,
  duration, stderr, and diagnostic details.
- Execution progress, cancellation, stdout/stderr, exit code, traceback,
  timeout, cancellation, disabled-executor, and resource-limit feedback.
- API liveness, PostgreSQL/pgvector readiness, and operational metrics.
- Responsive navigation and layouts.

## Automated gate

- [x] Focused FastAPI route and service tests exist for authentication, documents,
  tutoring, execution, health, readiness, monitoring, and ownership boundaries.
- [x] Focused frontend API-client and unauthenticated-routing tests pass.
- [x] Focused React parity tests cover multi-file upload controls, transcript
  languages, standalone hints, Monaco, entry-point selection, test toggling, and reset.
- [x] TypeScript compilation and the Vite production build pass.
- [ ] Browser workflow tests cover registration through document-grounded tutoring.
- [ ] Browser workflow tests cover multi-file execution, tests, diagnostics, and cancellation.

## Manual parity gate

- [ ] Start PostgreSQL/pgvector and apply all Alembic migrations.
- [ ] Register two accounts and confirm document, job, tutoring, and execution isolation.
- [ ] Upload each supported format: PDF, TXT, CSV, PPTX, Markdown, and restricted RST.
- [ ] Upload several files together; confirm progress, failure handling, cancellation,
  replacement, deletion, and cache/index invalidation.
- [ ] Index an available YouTube transcript using multiple preferred languages.
- [ ] Ask grounded and unsupported questions in both tutoring modes; inspect citations.
- [ ] Request several hints for a standalone problem and confirm progression.
- [ ] Run a multi-file project with and without tests.
- [ ] Verify syntax errors, runtime errors, traceback line numbers, timeout, cancellation,
  output limits, and resource-limit messages.
- [ ] Confirm health, readiness, monitoring, responsive mobile layout, keyboard use,
  focus visibility, and basic screen-reader labels.
- [ ] Run an agreed classroom pilot and record approval from the project owner.

## Retirement procedure

Only after every gate is checked:

1. Mark Streamlit deprecated in the README and show an in-app migration notice.
2. Keep `app.py` for one release as a documented fallback.
3. Confirm there is no production traffic or deployment using Streamlit.
4. Remove `app.py`, `streamlit`, and `streamlit-monaco-editor` in one dedicated change.
5. Regenerate dependency locks and rerun API, frontend, security, and migration checks.

Until then, do not delete `app.py`, Streamlit dependencies, or Streamlit-specific
configuration.
