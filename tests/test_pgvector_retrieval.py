from __future__ import annotations

from contextlib import AbstractContextManager
from types import SimpleNamespace
from typing import Any

import pytest

from pydebugger.config import VectorBackend
from pydebugger.engine import VectorStoreManager
from pydebugger.models import DocumentChunk
from pydebugger.retrieval import (
    EmbeddingMismatchError,
    PgVectorIndex,
    RetrievalError,
)


class FakeResult:
    def __init__(self, rows: list[dict[str, Any]] | None = None) -> None:
        self.rows = rows or []

    def mappings(self) -> FakeResult:
        return self

    def one(self) -> dict[str, Any]:
        return self.rows[0]

    def all(self) -> list[dict[str, Any]]:
        return self.rows


class FakeConnection:
    def __init__(self, engine: FakeEngine) -> None:
        self.engine = engine

    def execute(self, statement, parameters=None) -> FakeResult:
        sql = str(statement)
        self.engine.calls.append((sql, parameters))
        if "SELECT embedding_identity" in sql:
            return FakeResult([self.engine.collection])
        if "SELECT id, document_id, content" in sql:
            return FakeResult(self.engine.search_rows)
        if "SELECT source_metadata" in sql:
            return FakeResult(self.engine.source_rows)
        return FakeResult()


class FakeContext(AbstractContextManager[FakeConnection]):
    def __init__(self, engine: FakeEngine) -> None:
        self.connection = FakeConnection(engine)

    def __enter__(self) -> FakeConnection:
        return self.connection

    def __exit__(self, *args) -> None:
        return None


class FakeEngine:
    def __init__(self, identity: str = "embedding-v1", dimension: int = 3) -> None:
        self.collection = {
            "embedding_identity": identity,
            "index_schema_version": "chunks-v2",
            "embedding_dimension": dimension,
        }
        self.search_rows: list[dict[str, Any]] = []
        self.source_rows: list[dict[str, Any]] = []
        self.calls: list[tuple[str, Any]] = []

    def begin(self) -> FakeContext:
        return FakeContext(self)

    def connect(self) -> FakeContext:
        return FakeContext(self)


class FakeEmbeddings:
    embedding_identity = "embedding-v1"

    def __init__(self) -> None:
        self.document_calls = 0
        self.query_calls = 0

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        self.document_calls += 1
        return [[float(text.count("loop")), 0.0, 1.0] for text in texts]

    def embed_query(self, text: str) -> list[float]:
        self.query_calls += 1
        return [float(text.count("loop")), 0.0, 1.0]


def chunk(chunk_id: str, document_id: str, text: str) -> DocumentChunk:
    return DocumentChunk(
        id=chunk_id,
        document_id=document_id,
        text=text,
        metadata={
            "source_id": document_id,
            "source_name": f"{document_id}.txt",
            "nested": {"unit": 1},
        },
    )


def store(
    engine: FakeEngine | None = None, embeddings: FakeEmbeddings | None = None
) -> tuple[PgVectorIndex, FakeEngine, FakeEmbeddings]:
    resolved_engine = engine or FakeEngine()
    resolved_embeddings = embeddings or FakeEmbeddings()
    index = PgVectorIndex(
        resolved_embeddings,
        resolved_engine,
        "classroom-content",
        3,
    )
    return index, resolved_engine, resolved_embeddings


def test_pgvector_initializes_collection_and_hnsw_index() -> None:
    _, engine, _ = store()

    sql = "\n".join(call[0] for call in engine.calls)
    assert "INSERT INTO vector_collections" in sql
    assert "USING hnsw" in sql
    assert "halfvec(3)" in sql
    assert "halfvec_cosine_ops" in sql


def test_pgvector_rejects_embedding_contract_mismatch() -> None:
    with pytest.raises(EmbeddingMismatchError, match="embedding-v2"):
        store(FakeEngine(identity="embedding-v2"))


def test_pgvector_replacement_is_atomic_and_removes_obsolete_chunks() -> None:
    index, engine, embeddings = store()
    engine.calls.clear()

    index.replace_document(
        "doc-loops",
        [
            chunk("loops-1", "doc-loops", "loop basics"),
            chunk("loops-2", "doc-loops", "loop control"),
        ],
    )

    assert embeddings.document_calls == 1
    sql = "\n".join(call[0] for call in engine.calls)
    assert "INSERT INTO vector_documents" in sql
    assert "INSERT INTO vector_chunks" in sql
    assert "id NOT IN" in sql


def test_pgvector_search_filters_documents_and_returns_traceable_results() -> None:
    index, engine, embeddings = store()
    engine.search_rows = [
        {
            "id": "loops-1",
            "document_id": "doc-loops",
            "content": "loop basics",
            "chunk_metadata": {"source_name": "loops.txt"},
            "distance": 0.2,
        }
    ]
    engine.calls.clear()

    results = index.search("loop", {"doc-loops"}, limit=2)

    assert embeddings.query_calls == 1
    assert results[0].chunk.id == "loops-1"
    assert results[0].chunk.metadata["document_id"] == "doc-loops"
    assert results[0].score == pytest.approx(0.9)
    search_call = next(call for call in engine.calls if "SELECT id" in call[0])
    assert search_call[1]["document_ids"] == ["doc-loops"]


def test_empty_selection_does_not_embed_or_query() -> None:
    index, engine, embeddings = store()
    engine.calls.clear()

    assert index.search("loop", set()) == []
    assert embeddings.query_calls == 0
    assert engine.calls == []


def test_pgvector_validates_embedding_dimension() -> None:
    class WrongDimensionEmbeddings(FakeEmbeddings):
        def embed_query(self, text: str) -> list[float]:
            return [1.0, 2.0]

    index, _, _ = store(embeddings=WrongDimensionEmbeddings())

    with pytest.raises(RetrievalError, match="inconsistent vector dimensions"):
        index.search("loop")


def test_pgvector_restores_source_metadata() -> None:
    index, engine, _ = store()
    engine.source_rows = [
        {
            "source_metadata": {
                "source_id": "doc-loops",
                "source_name": "loops.txt",
                "nested": {"unit": 1},
            }
        }
    ]

    metadata = index.list_source_metadata()

    assert metadata[0]["source_id"] == "doc-loops"
    assert metadata[0]["nested"] == {"unit": 1}


def test_vector_store_manager_selects_pgvector(monkeypatch) -> None:
    selected: dict[str, Any] = {}
    sentinel = object()

    def fake_pgvector(embeddings, database, collection, dimension):
        selected.update(
            embeddings=embeddings,
            database=database,
            collection=collection,
            dimension=dimension,
        )
        return sentinel

    monkeypatch.setattr("pydebugger.engine.PgVectorIndex", fake_pgvector)
    embeddings = FakeEmbeddings()
    settings = SimpleNamespace(
        vector_backend=VectorBackend.PGVECTOR,
        database_url="postgresql+psycopg://localhost/pydebugger",
        vector_collection="classroom-content",
        embedding_dimension=3,
    )

    manager = VectorStoreManager(settings, embeddings)

    assert manager.db is sentinel
    assert selected == {
        "embeddings": embeddings,
        "database": "postgresql+psycopg://localhost/pydebugger",
        "collection": "classroom-content",
        "dimension": 3,
    }
