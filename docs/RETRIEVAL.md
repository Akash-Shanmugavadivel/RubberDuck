# Retrieval and document lifecycle

PyDebugger's primary retrieval path is `PgVectorIndex`, backed by PostgreSQL and
pgvector. Environment-based startup selects it by default. `ChromaVectorIndex`
is retained temporarily for migration compatibility, while
`InMemoryVectorIndex` remains a deterministic test double.

## Identity and compatibility

- A logical upload ID is derived from its normalized filename; a YouTube ID is
  derived from its canonical video ID. Replacing content therefore preserves the
  document ID.
- Every revision has a SHA-256 content hash and a content-derived index version.
- Chunk IDs contain the logical document ID and index version.
- Collection metadata records the embedding deployment identity, dimension, and
  chunk schema version. Startup refuses an incompatible collection instead of
  mixing embeddings or metadata formats.
- Each collection receives a partial HNSW cosine index. Embeddings are stored as
  full vectors and indexed through `halfvec`, supporting Gemini's 3,072
  dimensions within pgvector's HNSW limits.

## Replacement and deletion

Replacement writes and extracts the new file, embeds its versioned chunks, and
only then removes obsolete chunks and the previous file. If validation,
extraction, or embedding fails, the new file is cleaned up and the current
revision remains active. Uploading identical content is idempotent.

Deletion first removes the document's vector records. After that succeeds, the
catalog entry and files in that document's exact storage directory are removed.
This ordering avoids displaying a document whose evidence has disappeared.

## Search and citations

All selected document IDs are filtered in one PostgreSQL query, producing a single
cross-document ranking. Each result retains the document ID, stable chunk ID,
source location, origin URI, and normalized relevance score. `TutorService`
filters results using `PYDEBUGGER_RETRIEVAL_MIN_SCORE`; when nothing passes, it
returns a deterministic no-evidence response without invoking the chat model.

PostgreSQL provides a shared retrieval backend for multiple API instances.
Document replacement, chunk upserts, and obsolete-chunk deletion occur in one
database transaction. Collection identity checks prevent an API instance using
the wrong embedding model or dimension.
