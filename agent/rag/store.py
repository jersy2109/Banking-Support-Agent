"""Single shared Qdrant client."""

from qdrant_client import QdrantClient

from . import config

_client = None


def get_client():
    global _client
    if _client is None:
        _client = QdrantClient(host=config.QDRANT_HOST, port=config.QDRANT_PORT)
    return _client
