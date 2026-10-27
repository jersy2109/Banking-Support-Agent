"""Embedding helpers (Ollama). Prefixes depend on the model, so they live in one place."""

import ollama

from . import config

# nomic-embed-text is trained with task prefixes; other models (e.g. bge-m3) use none.
_PREFIXES = {
    "nomic-embed-text": ("search_document: ", "search_query: "),
}

_client = None


def _get_client():
    global _client
    if _client is None:
        _client = ollama.Client(host=config.OLLAMA_BASE_URL)
    return _client


def _prefixes():
    return _PREFIXES.get(config.EMBED_MODEL.split(":")[0], ("", ""))


def embed_documents(texts, batch_size=16):
    """Embed document chunks. Returns one vector (list of floats) per text, in order."""
    doc_prefix, _ = _prefixes()
    vectors = []
    for i in range(0, len(texts), batch_size):
        batch = [doc_prefix + t for t in texts[i : i + batch_size]]
        response = _get_client().embed(model=config.EMBED_MODEL, input=batch)
        vectors.extend(list(v) for v in response["embeddings"])
    return vectors


def embed_query(text):
    """Embed a user question."""
    _, query_prefix = _prefixes()
    response = _get_client().embed(model=config.EMBED_MODEL, input=[query_prefix + text])
    return list(response["embeddings"][0])
