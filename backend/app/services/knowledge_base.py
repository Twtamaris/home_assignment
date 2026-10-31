import re
import math
from typing import List, Dict, Any, Optional
import httpx
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.core.config import settings
from app.models.models import KnowledgeChunk

def tokenize(text: str) -> List[str]:
    # Extract lowercased alpha-numeric tokens
    return [w for w in re.findall(r"[a-z0-9]+", text.lower()) if len(w) > 1]

def simple_embed(text: str, dim: int = 128) -> List[float]:
    vec = [0.0] * dim
    for token in tokenize(text):
        vec[hash(token) % dim] += 1.0
    return vec

async def get_embedding(text: str) -> List[float]:
    return simple_embed(text)

class KnowledgeBaseService:
    @staticmethod
    async def search_knowledge(
        db: AsyncSession,
        org_id: str,
        query: str,
        top_k: int = 4
    ) -> List[Dict[str, Any]]:
        """
        Multi-tenant Knowledge Retrieval:
        STRICT GUARANTEE: Never retrieves chunks belonging to another organisation!
        Enforces org_id filter at DB layer.
        Combines TF-IDF term relevance with section heading boosting.
        """
        # Step 1: Query ONLY chunks for the user's org_id
        stmt = select(KnowledgeChunk).where(KnowledgeChunk.org_id == org_id)
        result = await db.execute(stmt)
        chunks = result.scalars().all()
        if not chunks:
            return []

        q_tokens = tokenize(query)
        if not q_tokens:
            return []

        # Step 2: Compute Document Frequencies across org chunks
        N = len(chunks)
        df = {}
        chunk_token_list = []
        for ch in chunks:
            tokens = set(tokenize(ch.section_name) * 3 + tokenize(ch.content))
            chunk_token_list.append(tokens)
            for t in tokens:
                df[t] = df.get(t, 0) + 1

        scored_chunks = []
        for i, ch in enumerate(chunks):
            ch_tokens = tokenize(ch.content)
            sec_tokens = tokenize(ch.section_name)
            doc_tokens = tokenize(ch.doc_name)

            score = 0.0
            matched_terms = 0

            for qt in q_tokens:
                # IDF
                doc_freq = df.get(qt, 0)
                if doc_freq == 0:
                    continue
                idf = math.log((N - doc_freq + 0.5) / (doc_freq + 0.5) + 1.0)

                # Term frequency in content
                tf = ch_tokens.count(qt)
                # Term frequency in section title (3x boost)
                tf_sec = sec_tokens.count(qt) * 3.5
                # Term frequency in doc name
                tf_doc = doc_tokens.count(qt) * 2.0

                total_tf = tf + tf_sec + tf_doc
                if total_tf > 0:
                    matched_terms += 1
                    # BM25-like saturation
                    score += idf * (total_tf / (total_tf + 1.5))

            # Phrase match bonus
            clean_query = " ".join(q_tokens)
            if clean_query in ch.content.lower():
                score += 3.0
            if any(qt in ch.section_name.lower() for qt in q_tokens if len(qt) > 3):
                score += 1.5

            # Normalized score
            if matched_terms > 0:
                normalized_score = min(1.0, score / (len(q_tokens) * 2.5 + 1.0))
                scored_chunks.append((normalized_score, ch))
            else:
                scored_chunks.append((0.0, ch))

        scored_chunks.sort(key=lambda x: x[0], reverse=True)
        top_results = [item for item in scored_chunks if item[0] > 0.0][:top_k]

        return [
            {
                "doc_name": ch.doc_name,
                "section_name": ch.section_name,
                "content": ch.content,
                "score": round(score, 4),
                "citation": f"[Source: {ch.doc_name} > {ch.section_name}]"
            }
            for score, ch in top_results
        ]
