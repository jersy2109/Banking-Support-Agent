"""
Chunk the policy docs, embed them, and load them into Qdrant.

Run from the project root:
    python -m agent.rag.ingest

The collection is dropped and rebuilt on every run, so the result always matches
the files on disk (no stale chunks if a doc or section is removed or renamed).
"""

import sys
from collections import Counter

from qdrant_client.models import Distance, PayloadSchemaType, PointStruct, VectorParams

from . import config, embeddings
from .chunker import load_chunks
from .store import get_client


def main():
    chunks = load_chunks()
    if not chunks:
        sys.exit(f"No chunks found under {config.POLICY_DOCS_DIR}")
    print(f"Chunked {len(set(c.payload['source_file'] for c in chunks))} documents into {len(chunks)} chunks")

    print(f"Embedding with {config.EMBED_MODEL} via {config.OLLAMA_BASE_URL} ...")
    vectors = embeddings.embed_documents([c.text for c in chunks])
    dim = len(vectors[0])  # read from the model instead of hardcoding, so swapping models just works

    client = get_client()
    if client.collection_exists(config.COLLECTION_NAME):
        client.delete_collection(config.COLLECTION_NAME)
    client.create_collection(
        collection_name=config.COLLECTION_NAME,
        vectors_config=VectorParams(size=dim, distance=Distance.COSINE),
    )
    # Indexes on the fields we filter by (jurisdiction and access control).
    for field in ("country", "doc_type", "allowed_roles"):
        client.create_payload_index(config.COLLECTION_NAME, field_name=field, field_schema=PayloadSchemaType.KEYWORD)

    client.upsert(
        collection_name=config.COLLECTION_NAME,
        points=[PointStruct(id=c.chunk_id, vector=v, payload=c.payload) for c, v in zip(chunks, vectors)],
    )

    print(f"Loaded {len(chunks)} chunks (dim={dim}, cosine) into '{config.COLLECTION_NAME}':")
    for doc_id, count in sorted(Counter(c.payload["doc_id"] for c in chunks).items()):
        print(f"  {doc_id}: {count}")


if __name__ == "__main__":
    main()
