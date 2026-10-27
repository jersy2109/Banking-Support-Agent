"""
Turn the markdown policy docs into chunks, one chunk per `##` section.

Each doc starts with a YAML front matter block (title, country, doc_type,
allowed_roles, effective_date, version). The front matter is parsed into
metadata and removed from the text, so it never gets embedded. Every chunk
keeps the doc title and section header in its text so it makes sense on its own.
"""

import re
import uuid
from dataclasses import dataclass
from pathlib import Path

import yaml

from . import config

REQUIRED_METADATA = ["title", "country", "doc_type", "allowed_roles", "effective_date", "version"]
_FRONT_MATTER = re.compile(r"\A---\s*\n(.*?)\n---\s*\n", re.DOTALL)
_SECTION_SPLIT = re.compile(r"^## ", re.MULTILINE)


@dataclass
class Chunk:
    chunk_id: str  # deterministic UUID, so re-ingesting the same doc yields the same IDs
    text: str  # what gets embedded and shown as the source passage
    payload: dict  # everything stored in Qdrant alongside the vector


def parse_front_matter(raw, source):
    """Split a doc into (metadata dict, body text). Fails loudly if metadata is missing."""
    match = _FRONT_MATTER.match(raw)
    if not match:
        raise ValueError(f"{source}: missing YAML front matter block at the top of the file")
    meta = yaml.safe_load(match.group(1)) or {}

    missing = [key for key in REQUIRED_METADATA if key not in meta]
    if missing:
        raise ValueError(f"{source}: front matter is missing {missing}")
    if not isinstance(meta["allowed_roles"], list) or not meta["allowed_roles"]:
        raise ValueError(f"{source}: allowed_roles must be a non-empty list")

    meta["country"] = str(meta["country"]).upper()
    meta["effective_date"] = str(meta["effective_date"])  # YAML parses dates into date objects
    meta["version"] = str(meta["version"])
    meta["allowed_roles"] = [str(role) for role in meta["allowed_roles"]]
    return meta, raw[match.end():]


def chunk_document(path, docs_dir):
    raw = path.read_text(encoding="utf-8")  # explicit: Windows defaults to cp1252
    rel = path.relative_to(docs_dir).as_posix()
    meta, body = parse_front_matter(raw, rel)

    # The first piece is the H1 title and the disclaimer line, not a section, so skip it.
    sections = _SECTION_SPLIT.split(body)[1:]

    chunks, seen_headers = [], {}
    for index, section in enumerate(sections):
        header, _, content = section.partition("\n")
        header, content = header.strip(), content.strip()
        if not content:
            continue

        seen_headers[header] = seen_headers.get(header, 0) + 1
        suffix = f"#{seen_headers[header]}" if seen_headers[header] > 1 else ""
        chunk_id = str(uuid.uuid5(uuid.NAMESPACE_URL, f"{rel}::{header}{suffix}"))

        payload = {
            "doc_id": path.stem,
            "source_file": rel,
            "title": meta["title"],
            "section": header,
            "chunk_index": index,
            "country": meta["country"],
            "doc_type": meta["doc_type"],
            "allowed_roles": meta["allowed_roles"],
            "effective_date": meta["effective_date"],
            "version": meta["version"],
        }
        text = f"{meta['title']} - {header}\n\n{content}"
        payload["text"] = text
        chunks.append(Chunk(chunk_id=chunk_id, text=text, payload=payload))
    return chunks


def load_chunks(docs_dir=None):
    docs_dir = Path(docs_dir or config.POLICY_DOCS_DIR)
    chunks = []
    for path in sorted(docs_dir.rglob("*.md")):
        chunks.extend(chunk_document(path, docs_dir))
    return chunks
