# Tutoring API

## Answer flow

1. FastAPI verifies the JWT and loads the active user.
2. `TutoringService` confirms every selected document belongs to that user.
3. The existing engine retrieves evidence only from those document IDs.
4. `TutorService` selects relevant conversation turns within its token budget.
5. The configured model produces one answer with traceable citations.

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

## Hint flow

The client returns its previous hints with the current problem. The engine
maintains progression, prevents duplicate hints, and returns the full updated
hint sequence. Persisting this sequence as durable student history is outside
the current milestone.
