"""Shared seed helpers: markdown chunking and knowledge-base ingestion for any organisation."""
import logging
from pathlib import Path
from typing import Dict, List, Tuple

from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.models import KnowledgeChunk
from app.services import knowledge_base as kb

log = logging.getLogger("uvicorn.error")

SEED_DIR = Path(__file__).resolve().parent.parent / "seed_data"
KNOWLEDGE_SUFFIX = "_knowledge"


def parse_markdown_chunks(file_path: Path, doc_name: str) -> List[Dict[str, str]]:
    """
    Splits markdown on heading boundaries (#, ##, ###). Each chunk keeps its document name and
    section title, and holds one complete unit such as a single FAQ answer, policy or guide.
    """
    chunks: List[Dict[str, str]] = []
    section = "Overview"
    current: List[str] = []

    def flush() -> None:
        body = "\n".join(current).strip()
        if body:
            chunks.append({"doc_name": doc_name, "section_name": section, "content": body})

    for line in file_path.read_text(encoding="utf-8").splitlines():
        if line.startswith(("# ", "## ", "### ")):
            flush()
            section = line.lstrip("#").strip()
            current = [line]
        else:
            current.append(line)
    flush()
    return chunks


def knowledge_dirs() -> Dict[str, Path]:
    """org_id -> directory, discovered from seed_data/<org_id>_knowledge. Adding an org adds a folder."""
    return {
        path.name[: -len(KNOWLEDGE_SUFFIX)]: path
        for path in sorted(SEED_DIR.glob(f"*{KNOWLEDGE_SUFFIX}"))
        if path.is_dir()
    }


async def ingest_knowledge(session: AsyncSession, org_id: str, directory: Path) -> Tuple[int, bool]:
    """
    Replace one organisation's knowledge base from its markdown files: rows in the relational
    table plus vectors in Chroma when embeddings are configured.
    Returns (chunk count, whether vectors were stored). False means search will use BM25.
    """
    await session.execute(delete(KnowledgeChunk).where(KnowledgeChunk.org_id == org_id))

    items: List[Dict[str, str]] = []
    for md_file in sorted(directory.glob("*.md")):
        items.extend(parse_markdown_chunks(md_file, md_file.name))

    rows = []
    for item in items:
        row = KnowledgeChunk(
            org_id=org_id,
            doc_name=item["doc_name"],
            section_name=item["section_name"],
            content=item["content"],
        )
        session.add(row)
        rows.append(row)
    await session.flush()

    indexed = False
    if kb.embeddings_enabled():
        try:
            vectors = await kb.embed_documents(items)
            kb.index_chunks(org_id, [f"{org_id}_{row.id}" for row in rows], items, vectors)
            indexed = bool(vectors)
        except Exception as exc:
            # The relational chunks are already stored, so BM25 search still works.
            print(f"   ! embeddings failed for {org_id} ({exc}); BM25 fallback will be used")
    return len(rows), indexed
