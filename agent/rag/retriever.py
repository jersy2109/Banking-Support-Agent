"""
Retrieve the policy chunks most relevant to a question.

Access control and jurisdiction are applied as Qdrant filters inside the search
itself, so chunks the caller isn't allowed to see are never ranked or returned.
`role` is required on purpose: there is no way to search without saying who is asking.
"""

from qdrant_client.models import FieldCondition, Filter, MatchValue

from . import config, embeddings
from .store import get_client


def retrieve(query, role, country=None, top_k=4, score_threshold=None):
    """
    Returns a list of dicts ordered by similarity (best first); an empty list
    means nothing matched, and callers must say so instead of guessing.

    role:            required; only chunks whose allowed_roles include it are searched
    country:         optional jurisdiction filter (e.g. "US", "MX", "ES")
    score_threshold: optional minimum cosine similarity; weaker matches are dropped
    """
    if not role:
        raise ValueError("role is required")

    must = [FieldCondition(key="allowed_roles", match=MatchValue(value=role))]
    if country:
        must.append(FieldCondition(key="country", match=MatchValue(value=country.upper())))

    response = get_client().query_points(
        collection_name=config.COLLECTION_NAME,
        query=embeddings.embed_query(query),
        query_filter=Filter(must=must),
        limit=top_k,
        score_threshold=score_threshold,
        with_payload=True,
    )

    results = []
    for point in response.points:
        p = point.payload
        results.append(
            {
                "score": point.score,
                "text": p["text"],
                "doc_id": p["doc_id"],
                "source_file": p["source_file"],
                "title": p["title"],
                "section": p["section"],
                "country": p["country"],
                "doc_type": p["doc_type"],
                "version": p["version"],
                "effective_date": p["effective_date"],
            }
        )
    return results
