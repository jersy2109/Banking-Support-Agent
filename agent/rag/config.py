"""Settings for the RAG pipeline. Defaults target the Docker services from a host-side Python run."""

import os
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
POLICY_DOCS_DIR = PROJECT_ROOT / "data" / "policy_docs"

# Ollama container is published on host port 11435 (11434 may be taken by a native Ollama install).
# Named OLLAMA_BASE_URL on purpose: OLLAMA_HOST is read by the native Ollama tooling and would clash.
OLLAMA_BASE_URL = os.environ.get("OLLAMA_BASE_URL", "http://127.0.0.1:11435")
EMBED_MODEL = os.environ.get("OLLAMA_EMBED_MODEL", "nomic-embed-text")

QDRANT_HOST = os.environ.get("QDRANT_HOST", "127.0.0.1")
QDRANT_PORT = int(os.environ.get("QDRANT_PORT", "6333"))
COLLECTION_NAME = os.environ.get("QDRANT_COLLECTION", "policy_docs")
