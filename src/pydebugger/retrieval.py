"""Persistent vector retrieval with pgvector as the primary backend."""

from __future__ import annotations

import hashlib
import json
import math
import re
from collections.abc import Iterable, Sequence
from pathlib import Path
from threading import RLock
from typing import Any, Protocol

from sqlalchemy import bindparam, create_engine, text
from sqlalchemy.engine import Connection, Engine
from sqlalchemy.exc import SQLAlchemyError

from .models import DocumentChunk, RetrievedChunk
from .providers import EmbeddingProvider

INDEX_SCHEMA_VERSION = "chunks-v2"


class RetrievalError(RuntimeError):
    """Raised when indexing or retrieval cannot safely continue."""


class EmbeddingMismatchError(RetrievalError):
    """Raised when a persisted collection belongs to another embedding model."""


class VectorIndex(Protocol):
    def add(self, chunks: Iterable[DocumentChunk]) -> None: ...

    def remove_document(self, document_id: str) -> None: ...

    def replace_document(
        self, document_id: str, chunks: Iterable[DocumentChunk]
    ) -> None: ...

    def search(
        self,
        query: str,
        document_ids: set[str] | None = None,
        limit: int = 5,
    ) -> list[RetrievedChunk]: ...

    def list_source_metadata(self) -> tuple[dict[str, Any], ...]: ...


class _ProviderEmbeddings:
    """LangChain Embeddings-compatible adapter with dimension and value checks."""

    def __init__(
        self, provider: EmbeddingProvider, expected_dimension: int | None = None
    ) -> None:
        self.provider = provider
        self._dimension = expected_dimension
        self._lock = RLock()

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        vectors = self.provider.embed_documents(texts)
        if len(vectors) != len(texts):
            raise RetrievalError(
                "Embedding provider returned an unexpected vector count"
            )
        return [self._validate_vector(vector) for vector in vectors]

    def embed_query(self, text: str) -> list[float]:
        return self._validate_vector(self.provider.embed_query(text))

    def _validate_vector(self, vector: Sequence[float]) -> list[float]:
        normalized = [float(value) for value in vector]
        if not normalized:
            raise RetrievalError("Embedding provider returned an empty vector")
        if any(not math.isfinite(value) for value in normalized):
            raise RetrievalError("Embedding provider returned a non-finite vector")
        with self._lock:
            if self._dimension is None:
                self._dimension = len(normalized)
            elif len(normalized) != self._dimension:
                raise RetrievalError(
                    "Embedding provider returned inconsistent vector dimensions"
                )
        return normalized


class ChromaVectorIndex:
    """Supported persistent index; all selected documents are ranked in one query."""

    def __init__(
        self,
        embeddings: EmbeddingProvider,
        persist_directory: Path,
        collection_name: str,
    ) -> None:
        import chromadb
        from chromadb.config import Settings as ChromaSettings
        from langchain_chroma import Chroma

        persist_directory.mkdir(parents=True, exist_ok=True)
        self._embedding_identity = embeddings.embedding_identity
        self._embedding_adapter = _ProviderEmbeddings(embeddings)
        self._lock = RLock()
        self._client = chromadb.PersistentClient(
            path=str(persist_directory),
            settings=ChromaSettings(anonymized_telemetry=False),
        )

        existing_names = {item.name for item in self._client.list_collections()}
        if collection_name in existing_names:
            collection = self._client.get_collection(collection_name)
            collection_metadata = collection.metadata or {}
            stored_identity = collection_metadata.get("embedding_identity")
            if stored_identity != self._embedding_identity:
                raise EmbeddingMismatchError(
                    "The persisted vector collection was created with embedding identity "
                    f"{stored_identity!r}, but configuration requires "
                    f"{self._embedding_identity!r}. Use a new collection name or rebuild "
                    "the existing collection."
                )
            stored_schema = collection_metadata.get("index_schema_version")
            if stored_schema != INDEX_SCHEMA_VERSION:
                raise RetrievalError(
                    "The persisted vector collection uses index schema "
                    f"{stored_schema!r}, but this application requires "
                    f"{INDEX_SCHEMA_VERSION!r}. Use a new collection name or rebuild it."
                )
        else:
            collection = self._client.create_collection(
                collection_name,
                metadata={
                    "embedding_identity": self._embedding_identity,
                    "index_schema_version": INDEX_SCHEMA_VERSION,
                    "hnsw:space": "cosine",
                },
            )

        self._store = Chroma(
            client=self._client,
            collection_name=collection_name,
            embedding_function=self._embedding_adapter,
            relevance_score_fn=self._cosine_relevance,
            create_collection_if_not_exists=False,
        )

    def add(self, chunks: Iterable[DocumentChunk]) -> None:
        from langchain_core.documents import Document

        items = list(chunks)
        if not items:
            return
        documents = [
            Document(
                id=item.id,
                page_content=item.text,
                metadata=self._metadata_for_chroma(item),
            )
            for item in items
        ]
        try:
            with self._lock:
                self._store.add_documents(
                    documents=documents,
                    ids=[item.id for item in items],
                )
        except Exception as error:
            raise RetrievalError(
                "Could not index chunks. Verify the embedding deployment and vector "
                "collection use the same model and dimensions."
            ) from error

    def remove_document(self, document_id: str) -> None:
        with self._lock:
            result = self._store.get(
                where={"document_id": document_id},
                include=[],
            )
            ids = list(result.get("ids") or [])
            if ids:
                self._store.delete(ids=ids)

    def replace_document(
        self, document_id: str, chunks: Iterable[DocumentChunk]
    ) -> None:
        items = list(chunks)
        if not items or any(item.document_id != document_id for item in items):
            raise RetrievalError(
                "Replacement chunks must belong to the target document"
            )
        new_ids = {item.id for item in items}
        with self._lock:
            existing = self._store.get(where={"document_id": document_id}, include=[])
            old_ids = set(existing.get("ids") or [])
            try:
                self.add(items)
            except Exception:
                created_ids = new_ids - old_ids
                if created_ids:
                    self._store.delete(ids=sorted(created_ids))
                raise
            obsolete_ids = old_ids - new_ids
            if obsolete_ids:
                self._store.delete(ids=sorted(obsolete_ids))

    def search(
        self,
        query: str,
        document_ids: set[str] | None = None,
        limit: int = 5,
    ) -> list[RetrievedChunk]:
        cleaned_query = query.strip()
        if not cleaned_query:
            raise ValueError("Retrieval query cannot be empty")
        if limit < 1:
            raise ValueError("Retrieval limit must be at least one")
        if document_ids == set():
            return []

        where: dict[str, Any] | None = None
        if document_ids:
            sorted_ids = sorted(document_ids)
            where = (
                {"document_id": sorted_ids[0]}
                if len(sorted_ids) == 1
                else {"document_id": {"$in": sorted_ids}}
            )
        try:
            with self._lock:
                matches = self._store.similarity_search_with_relevance_scores(
                    cleaned_query,
                    k=limit,
                    filter=where,
                )
        except Exception as error:
            raise RetrievalError(
                "Vector search failed. Verify the configured embedding deployment still "
                "matches the persisted collection."
            ) from error

        results: list[RetrievedChunk] = []
        for document, score in matches:
            metadata = dict(document.metadata)
            chunk_id = str(metadata.get("chunk_id") or document.id or "")
            document_id = str(metadata.get("document_id") or "")
            if not chunk_id or not document_id:
                raise RetrievalError(
                    "Stored vector record is missing traceability metadata"
                )
            results.append(
                RetrievedChunk(
                    chunk=DocumentChunk(
                        id=chunk_id,
                        document_id=document_id,
                        text=document.page_content,
                        metadata=metadata,
                    ),
                    score=max(0.0, min(1.0, float(score))),
                )
            )
        return results

    def list_source_metadata(self) -> tuple[dict[str, Any], ...]:
        with self._lock:
            result = self._store.get(include=["metadatas"])
        sources: dict[str, dict[str, Any]] = {}
        for metadata in result.get("metadatas") or []:
            if not metadata:
                continue
            source_id = str(metadata.get("source_id") or "")
            if source_id and source_id not in sources:
                sources[source_id] = dict(metadata)
        return tuple(sources[key] for key in sorted(sources))

    @staticmethod
    def _metadata_for_chroma(
        chunk: DocumentChunk,
    ) -> dict[str, str | int | float | bool]:
        metadata: dict[str, str | int | float | bool] = {
            "chunk_id": chunk.id,
            "document_id": chunk.document_id,
        }
        for key, value in chunk.metadata.items():
            if value is None:
                continue
            if isinstance(value, bool | str | int | float):
                metadata[key] = value
            else:
                metadata[key] = json.dumps(value, sort_keys=True, ensure_ascii=False)
        return metadata

    @staticmethod
    def _cosine_relevance(distance: float) -> float:
        # Chroma cosine distance is 0 for identical and can reach 2 for opposite.
        return max(0.0, min(1.0, 1.0 - float(distance) / 2.0))


class PgVectorIndex:
    """PostgreSQL/pgvector index with traceable metadata and HNSW search."""

    def __init__(
        self,
        embeddings: EmbeddingProvider,
        database: str | Engine,
        collection_name: str,
        embedding_dimension: int,
    ) -> None:
        if not re.fullmatch(
            r"[A-Za-z0-9][A-Za-z0-9._-]{1,61}[A-Za-z0-9]", collection_name
        ):
            raise ValueError("Invalid pgvector collection name")
        if not 1 <= embedding_dimension <= 4_000:
            raise ValueError("Embedding dimension must be between 1 and 4000")
        self._engine = (
            create_engine(database, pool_pre_ping=True)
            if isinstance(database, str)
            else database
        )
        self._collection = collection_name
        self._dimension = embedding_dimension
        self._embedding_identity = embeddings.embedding_identity
        self._embeddings = _ProviderEmbeddings(embeddings, embedding_dimension)
        self._initialize_collection()

    def _initialize_collection(self) -> None:
        try:
            with self._engine.begin() as connection:
                connection.execute(
                    text(
                        "INSERT INTO vector_collections "
                        "(name, embedding_identity, index_schema_version, "
                        "embedding_dimension) "
                        "VALUES (:name, :identity, :schema, :dimension) "
                        "ON CONFLICT (name) DO NOTHING"
                    ),
                    {
                        "name": self._collection,
                        "identity": self._embedding_identity,
                        "schema": INDEX_SCHEMA_VERSION,
                        "dimension": self._dimension,
                    },
                )
                stored = (
                    connection.execute(
                        text(
                            "SELECT embedding_identity, index_schema_version, "
                            "embedding_dimension FROM vector_collections "
                            "WHERE name = :name"
                        ),
                        {"name": self._collection},
                    )
                    .mappings()
                    .one()
                )
                if stored["embedding_identity"] != self._embedding_identity:
                    raise EmbeddingMismatchError(
                        "The pgvector collection was created with embedding identity "
                        f"{stored['embedding_identity']!r}, but configuration requires "
                        f"{self._embedding_identity!r}. Use a new collection name or "
                        "rebuild the existing collection."
                    )
                if stored["index_schema_version"] != INDEX_SCHEMA_VERSION:
                    raise RetrievalError(
                        "The pgvector collection uses an incompatible index schema"
                    )
                if int(stored["embedding_dimension"]) != self._dimension:
                    raise EmbeddingMismatchError(
                        "The pgvector collection embedding dimension does not match "
                        "PYDEBUGGER_EMBEDDING_DIMENSION"
                    )
                connection.execute(text(self._hnsw_index_statement()))
        except SQLAlchemyError as error:
            raise RetrievalError(
                "Could not initialize pgvector. Run 'alembic upgrade head' and verify "
                "PostgreSQL connectivity."
            ) from error

    def _hnsw_index_statement(self) -> str:
        suffix = hashlib.sha256(self._collection.encode("utf-8")).hexdigest()[:12]
        return (
            f"CREATE INDEX IF NOT EXISTS ix_vector_chunks_hnsw_{suffix} "
            "ON vector_chunks USING hnsw "
            f"((embedding::halfvec({self._dimension})) halfvec_cosine_ops) "
            f"WHERE collection_name = '{self._collection}'"
        )

    def add(self, chunks: Iterable[DocumentChunk]) -> None:
        items = list(chunks)
        if not items:
            return
        vectors = self._embeddings.embed_documents([item.text for item in items])
        try:
            with self._engine.begin() as connection:
                self._upsert_documents(connection, items)
                self._upsert_chunks(connection, items, vectors)
        except SQLAlchemyError as error:
            raise RetrievalError("Could not add chunks to pgvector") from error

    def replace_document(
        self, document_id: str, chunks: Iterable[DocumentChunk]
    ) -> None:
        items = list(chunks)
        if not items or any(item.document_id != document_id for item in items):
            raise RetrievalError(
                "Replacement chunks must belong to the target document"
            )
        vectors = self._embeddings.embed_documents([item.text for item in items])
        try:
            with self._engine.begin() as connection:
                self._upsert_documents(connection, items)
                self._upsert_chunks(connection, items, vectors)
                statement = text(
                    "DELETE FROM vector_chunks WHERE collection_name = :collection "
                    "AND document_id = :document_id AND id NOT IN :chunk_ids"
                ).bindparams(bindparam("chunk_ids", expanding=True))
                connection.execute(
                    statement,
                    {
                        "collection": self._collection,
                        "document_id": document_id,
                        "chunk_ids": [item.id for item in items],
                    },
                )
        except SQLAlchemyError as error:
            raise RetrievalError(
                "Could not replace pgvector document chunks"
            ) from error

    def _upsert_documents(
        self, connection: Connection, items: list[DocumentChunk]
    ) -> None:
        sources: dict[str, dict[str, Any]] = {}
        for item in items:
            sources.setdefault(item.document_id, dict(item.metadata))
        parameters = [
            {
                "collection": self._collection,
                "document_id": document_id,
                "metadata": json.dumps(metadata, sort_keys=True, default=str),
            }
            for document_id, metadata in sources.items()
        ]
        connection.execute(
            text(
                "INSERT INTO vector_documents "
                "(collection_name, id, source_metadata) "
                "VALUES (:collection, :document_id, CAST(:metadata AS jsonb)) "
                "ON CONFLICT (collection_name, id) DO UPDATE SET "
                "source_metadata = EXCLUDED.source_metadata, updated_at = now()"
            ),
            parameters,
        )

    def _upsert_chunks(
        self,
        connection: Connection,
        items: list[DocumentChunk],
        vectors: list[list[float]],
    ) -> None:
        parameters = [
            {
                "collection": self._collection,
                "chunk_id": item.id,
                "document_id": item.document_id,
                "content": item.text,
                "metadata": json.dumps(item.metadata, sort_keys=True, default=str),
                "embedding": json.dumps(vector, separators=(",", ":")),
            }
            for item, vector in zip(items, vectors, strict=True)
        ]
        connection.execute(
            text(
                "INSERT INTO vector_chunks "
                "(collection_name, id, document_id, content, chunk_metadata, embedding) "
                "VALUES (:collection, :chunk_id, :document_id, :content, "
                "CAST(:metadata AS jsonb), CAST(:embedding AS vector)) "
                "ON CONFLICT (collection_name, id) DO UPDATE SET "
                "document_id = EXCLUDED.document_id, content = EXCLUDED.content, "
                "chunk_metadata = EXCLUDED.chunk_metadata, "
                "embedding = EXCLUDED.embedding, updated_at = now()"
            ),
            parameters,
        )

    def remove_document(self, document_id: str) -> None:
        try:
            with self._engine.begin() as connection:
                connection.execute(
                    text(
                        "DELETE FROM vector_documents WHERE collection_name = :collection "
                        "AND id = :document_id"
                    ),
                    {"collection": self._collection, "document_id": document_id},
                )
        except SQLAlchemyError as error:
            raise RetrievalError("Could not remove the pgvector document") from error

    def search(
        self,
        query: str,
        document_ids: set[str] | None = None,
        limit: int = 5,
    ) -> list[RetrievedChunk]:
        cleaned_query = query.strip()
        if not cleaned_query:
            raise ValueError("Retrieval query cannot be empty")
        if limit < 1:
            raise ValueError("Retrieval limit must be at least one")
        if document_ids == set():
            return []
        query_vector = self._embeddings.embed_query(cleaned_query)
        distance = (
            f"embedding::halfvec({self._dimension}) <=> "
            f"CAST(:query_vector AS halfvec({self._dimension}))"
        )
        filter_sql = ""
        parameters: dict[str, Any] = {
            "collection": self._collection,
            "query_vector": json.dumps(query_vector, separators=(",", ":")),
            "limit": limit,
        }
        if document_ids:
            filter_sql = " AND document_id IN :document_ids"
            parameters["document_ids"] = sorted(document_ids)
        statement = text(
            "SELECT id, document_id, content, chunk_metadata, "
            f"({distance}) AS distance FROM vector_chunks "
            f"WHERE collection_name = :collection{filter_sql} "
            "ORDER BY distance ASC LIMIT :limit"
        )
        if document_ids:
            statement = statement.bindparams(bindparam("document_ids", expanding=True))
        try:
            with self._engine.connect() as connection:
                rows = connection.execute(statement, parameters).mappings().all()
        except SQLAlchemyError as error:
            raise RetrievalError("Vector search failed in PostgreSQL") from error
        results: list[RetrievedChunk] = []
        for row in rows:
            metadata = self._as_metadata(row["chunk_metadata"])
            metadata.setdefault("chunk_id", str(row["id"]))
            metadata.setdefault("document_id", str(row["document_id"]))
            score = max(0.0, min(1.0, 1.0 - float(row["distance"]) / 2.0))
            results.append(
                RetrievedChunk(
                    chunk=DocumentChunk(
                        id=str(row["id"]),
                        document_id=str(row["document_id"]),
                        text=str(row["content"]),
                        metadata=metadata,
                    ),
                    score=score,
                )
            )
        return results

    def list_source_metadata(self) -> tuple[dict[str, Any], ...]:
        try:
            with self._engine.connect() as connection:
                rows = (
                    connection.execute(
                        text(
                            "SELECT source_metadata FROM vector_documents "
                            "WHERE collection_name = :collection ORDER BY id"
                        ),
                        {"collection": self._collection},
                    )
                    .mappings()
                    .all()
                )
        except SQLAlchemyError as error:
            raise RetrievalError("Could not list pgvector document metadata") from error
        return tuple(self._as_metadata(row["source_metadata"]) for row in rows)

    @staticmethod
    def _as_metadata(value: Any) -> dict[str, Any]:
        if isinstance(value, str):
            value = json.loads(value)
        if not isinstance(value, dict):
            raise RetrievalError("Stored vector record has invalid metadata")
        return dict(value)


class InMemoryVectorIndex:
    """Deterministic test double; the application does not select this backend."""

    def __init__(self, embeddings: EmbeddingProvider) -> None:
        self._embeddings = _ProviderEmbeddings(embeddings)
        self._entries: dict[str, tuple[DocumentChunk, list[float]]] = {}
        self._lock = RLock()

    def add(self, chunks: Iterable[DocumentChunk]) -> None:
        items = list(chunks)
        if not items:
            return
        vectors = self._embeddings.embed_documents([item.text for item in items])
        with self._lock:
            for item, vector in zip(items, vectors, strict=True):
                self._entries[item.id] = (item, vector)

    def remove_document(self, document_id: str) -> None:
        with self._lock:
            matching = [
                chunk_id
                for chunk_id, (chunk, _) in self._entries.items()
                if chunk.document_id == document_id
            ]
            for chunk_id in matching:
                del self._entries[chunk_id]

    def replace_document(
        self, document_id: str, chunks: Iterable[DocumentChunk]
    ) -> None:
        items = list(chunks)
        if not items or any(item.document_id != document_id for item in items):
            raise RetrievalError(
                "Replacement chunks must belong to the target document"
            )
        vectors = self._embeddings.embed_documents([item.text for item in items])
        replacement = dict(
            zip((item.id for item in items), zip(items, vectors), strict=True)
        )
        with self._lock:
            self._entries = {
                key: value
                for key, value in self._entries.items()
                if value[0].document_id != document_id
            }
            self._entries.update(replacement)

    def search(
        self,
        query: str,
        document_ids: set[str] | None = None,
        limit: int = 5,
    ) -> list[RetrievedChunk]:
        query_vector = self._embeddings.embed_query(query)
        with self._lock:
            candidates = list(self._entries.values())
        ranked = [
            RetrievedChunk(chunk=chunk, score=self._cosine(query_vector, vector))
            for chunk, vector in candidates
            if document_ids is None or chunk.document_id in document_ids
        ]
        ranked.sort(key=lambda item: item.score, reverse=True)
        return ranked[:limit]

    def list_source_metadata(self) -> tuple[dict[str, Any], ...]:
        with self._lock:
            entries = list(self._entries.values())
        sources: dict[str, dict[str, Any]] = {}
        for chunk, _ in entries:
            source_id = str(chunk.metadata.get("source_id") or chunk.document_id)
            sources.setdefault(source_id, dict(chunk.metadata))
        return tuple(sources[key] for key in sorted(sources))

    @staticmethod
    def _cosine(left: list[float], right: list[float]) -> float:
        if len(left) != len(right):
            raise RetrievalError("Embedding dimensions do not match")
        left_norm = math.sqrt(sum(value * value for value in left))
        right_norm = math.sqrt(sum(value * value for value in right))
        if not left_norm or not right_norm:
            return 0.0
        similarity = sum(a * b for a, b in zip(left, right, strict=True)) / (
            left_norm * right_norm
        )
        return max(0.0, min(1.0, (similarity + 1.0) / 2.0))
