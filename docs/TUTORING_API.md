# Tutoring API

## Answer flow

1. FastAPI verifies the JWT and loads the active user.
2. `TutoringService` confirms every selected document belongs to that user.
3. The existing engine retrieves evidence only from those document IDs.
4. Existing server-side messages are loaded for a supplied conversation ID.
5. `TutorService` selects relevant conversation turns within its token budget.
6. The configured model produces one answer with traceable citations.
7. The question, answer, grounding status, and citations are stored atomically.

Ownership validation occurs before retrieval or model execution. A missing or
foreign document produces the same `404` response and does not consume model
quota. Questions with no evidence retain the engine's deterministic ungrounded
response behavior.

## Request limits

- Questions and message contents: 8,000 characters each
- Selected documents: 1–20
- Conversation messages: at most 50 at the API boundary
- Previous hints: at most 10
- Roles: `user` or `assistant`

The engine applies stricter relevance and token-budget selection after these
transport-level validation limits.

## Durable conversation history

- `GET /api/v1/tutor/conversations` lists up to 100 conversations, newest first.
- `GET /api/v1/tutor/conversations/{id}` returns ordered messages and citations.
- `DELETE /api/v1/tutor/conversations/{id}` permanently removes that conversation.

All three operations are scoped to the authenticated student. Passing another
student's conversation ID returns `404`. The React tutor screen can start, reopen,
continue, and delete conversations. Run `uv run alembic upgrade head` after
pulling this database migration.

## Learning-aware behavior and policy

Answer requests may set `behavior` to `socratic`, `explain`, `exam_prep`, or
`debug_coach`, and `difficulty` to `beginner`, `intermediate`, or `advanced`.
Both values are stored with the conversation and restored by the React client.

`GET /api/v1/tutor/policy` returns the active assistance limits. Only an account
listed in `PYDEBUGGER_INSTRUCTOR_EMAILS` may call `PUT /api/v1/tutor/policy` to
control direct answers, complete code solutions, or hints-only behavior. These
limits are applied on the server and override student selections.

## Hint flow

The client returns its previous hints with the current problem. The engine
maintains progression, prevents duplicate hints, and returns the full updated
hint sequence. Persisting this sequence as durable student history is outside
the current milestone.
