"""Organisation knowledge search.

Gemini Embedding 2 vectors live in a persistent Chroma collection and every
query is filtered by org_id. When embeddings are unavailable the same chunks
are ranked with BM25. That lexical path is a fallback, not a hybrid score.

Both paths return only passages that clear a relevance floor, so a question the
knowledge base cannot answer yields no results instead of the least-bad chunk.
"""
import asyncio
import logging
import re
from typing import Any, Dict, List, Sequence

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.models import KnowledgeChunk

log = logging.getLogger("uvicorn.error")

_COLLECTION = "knowledge"
_EMBED_BATCH = 50


def _stem(word: str) -> str:
    for suffix in ("ing", "ed", "es", "s"):
        if len(word) > len(suffix) + 3 and word.endswith(suffix):
            return word[: -len(suffix)]
    return word


_STOPWORDS = frozenset("""
a an the and or but if then than so as of in on at to for from by with about into over under again also
is are was were be been being am do does did done have has had having can could should would will shall may might must
i me my we our you your he she it its they them their this that these those there here who whom whose which what when where why how
not no nor yes any some all each every both few more most other such only own same too very just
tell please want need like get got give show let know say said won win
policy policies information info details regarding question answer explain faq
""".split())


def tokenize(text: str) -> List[str]:
    """Lower-case word stems. Stopwords are dropped so 'the' and 'in' cannot make a passage look relevant."""
    words = [word for word in re.findall(r"[a-z0-9]+", text.lower()) if len(word) > 1 and word not in _STOPWORDS]
    return [_stem(word) for word in words]


def _has_body(chunk: KnowledgeChunk) -> bool:
    """A heading with no sentences is not a citable passage."""
    lines = [line.strip() for line in (chunk.content or "").splitlines() if line.strip()]
    return any(not line.startswith("#") for line in lines)


def document_text(title: str | None, content: str) -> str:
    return f"title: {title or 'none'} | text: {content}"


def query_text(content: str) -> str:
    return f"task: search result | query: {content}"


def embeddings_enabled() -> bool:
    return settings.EMBEDDING_PROVIDER == "gemini" and bool(settings.GEMINI_API_KEY)


def _collection():
    import chromadb

    client = chromadb.PersistentClient(path=settings.CHROMA_PATH)
    # Cosine distance, so 1 - distance is a similarity that does not depend on vector length.
    return client.get_or_create_collection(name=_COLLECTION, metadata={"hnsw:space": "cosine"})


def reset_collection() -> None:
    """Drop every stored vector. A rebuild starts from nothing so no stale chunk survives."""
    import chromadb

    client = chromadb.PersistentClient(path=settings.CHROMA_PATH)
    try:
        client.delete_collection(_COLLECTION)
    except Exception:
        pass  # the collection did not exist yet


async def embed_texts(texts: Sequence[str]) -> List[List[float]]:
    """
    Embed already-formatted strings, one vector per string. Returns [] when embeddings are off.

    gemini-embedding-2 merges a plain list of strings into a SINGLE embedding. Each string is therefore sent as
    its own Content object, which returns one vector per input. The count is checked so a misaligned index
    can never be written.
    """
    if not embeddings_enabled() or not texts:
        return []
    from google import genai
    from google.genai import types

    client = genai.Client(api_key=settings.GEMINI_API_KEY)
    vectors: List[List[float]] = []
    for start in range(0, len(texts), _EMBED_BATCH):
        batch = list(texts[start:start + _EMBED_BATCH])
        contents = [types.Content(parts=[types.Part(text=text)]) for text in batch]
        for attempt in range(4):
            try:
                response = await client.aio.models.embed_content(
                    model=settings.GEMINI_EMBEDDING_MODEL, contents=contents,
                )
                break
            except Exception as exc:
                # Free-tier limits: wait and retry, then give up so the caller can fall back to BM25.
                if attempt == 3 or not any(t in str(exc) for t in ("429", "503", "RESOURCE_EXHAUSTED", "UNAVAILABLE")):
                    raise
                await asyncio.sleep(2 ** attempt * 5)
        got = [list(item.values) for item in response.embeddings]
        if len(got) != len(batch):
            raise RuntimeError(f"Embedding API returned {len(got)} vectors for {len(batch)} inputs")
        vectors.extend(got)
    return vectors


async def embed_documents(items: Sequence[Dict[str, str]]) -> List[List[float]]:
    """items: dicts with section_name and content. One vector per item, or [] if embeddings are off."""
    return await embed_texts([document_text(i["section_name"], i["content"]) for i in items])


def index_chunks(org_id: str, chunk_ids: Sequence[str], items: Sequence[Dict[str, str]], vectors: Sequence[List[float]]) -> None:
    if not vectors:
        return
    if not (len(chunk_ids) == len(items) == len(vectors)):
        raise ValueError("chunks and vectors are not aligned")
    _collection().upsert(
        ids=list(chunk_ids),
        embeddings=list(vectors),
        documents=[i["content"] for i in items],
        metadatas=[
            {"org_id": org_id, "doc_name": i["doc_name"], "section_name": i["section_name"]}
            for i in items
        ],
    )


async def _search_chroma(org_id: str, query: str, top_k: int) -> List[Dict[str, Any]]:
    if not embeddings_enabled():
        return []
    try:
        collection = _collection()
        if collection.count() == 0:
            return []
        vectors = await embed_texts([query_text(query)])
        if not vectors:
            return []
        found = await asyncio.to_thread(
            collection.query,
            query_embeddings=[vectors[0]],
            n_results=top_k,
            where={"org_id": org_id},
            include=["documents", "metadatas", "distances"],
        )
    except Exception as exc:
        log.warning("chroma search failed, using bm25: %s", exc)
        return []
    if not (found.get("ids") or [[]])[0]:
        return []
    hits = []
    for document, metadata, distance in zip(found["documents"][0], found["metadatas"][0], found["distances"][0]):
        metadata = metadata or {}
        if metadata.get("org_id") != org_id:
            continue  # belt and braces: the where-filter already scopes the query
        similarity = round(1.0 - float(distance), 4)
        if similarity < settings.KB_MIN_SIMILARITY:
            continue
        doc_name = metadata.get("doc_name") or "Knowledge"
        section = metadata.get("section_name") or ""
        hits.append({
            "doc_name": doc_name,
            "section_name": section,
            "content": document,
            "score": similarity,
            "citation": f"[Source: {doc_name} > {section}]",
            "retrieval": "chroma",
        })
    return hits


def _search_bm25(chunks: List[KnowledgeChunk], query: str, top_k: int) -> List[Dict[str, Any]]:
    from rank_bm25 import BM25Okapi

    tokenized = [tokenize(f"{chunk.doc_name} {chunk.section_name} {chunk.content}") for chunk in chunks]
    if not any(tokenized):
        return []
    scores = BM25Okapi(tokenized).get_scores(tokenize(query))
    ranked = sorted(zip(scores, chunks), key=lambda item: item[0], reverse=True)
    positive = [(score, chunk) for score, chunk in ranked if score > 0][:top_k]
    if not positive:
        return []
    query_terms = set(tokenize(query))
    if not query_terms:
        return []
    hits = []
    for score, chunk in positive:
        document_terms = set(tokenize(f"{chunk.doc_name} {chunk.section_name} {chunk.content}"))
        matched = query_terms & document_terms
        coverage = len(matched) / len(query_terms)
        # A raw BM25 winner is not automatically a relevant one. The passage has to contain most of the
        # question's meaningful words, and at least two of them when the question has two or more. That is
        # what keeps "who won the football world cup" from returning the one FAQ that mentions a cup.
        if len(matched) < min(2, len(query_terms)) or coverage < settings.KB_BM25_MIN_COVERAGE:
            continue
        hits.append({
            "doc_name": chunk.doc_name,
            "section_name": chunk.section_name,
            "content": chunk.content,
            "score": round((float(score) / (float(score) + 6.0)) * coverage, 4),
            "citation": f"[Source: {chunk.doc_name} > {chunk.section_name}]",
            "retrieval": "bm25",
        })
    return hits


class KnowledgeBaseService:
    @staticmethod
    async def search_knowledge(
        db: AsyncSession,
        org_id: str,
        query: str,
        top_k: int = 4,
    ) -> List[Dict[str, Any]]:
        result = await db.execute(select(KnowledgeChunk).where(KnowledgeChunk.org_id == org_id))
        chunks = [chunk for chunk in result.scalars().all() if _has_body(chunk)]
        if not chunks:
            return []
        vector_hits = await _search_chroma(org_id, query, top_k)
        if vector_hits:
            return vector_hits
        return _search_bm25(chunks, query, top_k)
