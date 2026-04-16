from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
from typing import Dict, List, Optional

from .parser import slugify


class WikiBackendError(ValueError):
    """Raised when a requested wiki asset cannot be found or parsed."""


@dataclass
class WikiPerson:
    slug: str
    name: str
    description: str
    statement_count: int
    topic_count: int
    path: Path


class WikiBackend:
    def __init__(self, wiki_root: Path) -> None:
        self.wiki_root = wiki_root.expanduser().resolve()
        if not self.wiki_root.exists():
            raise WikiBackendError(f"wiki root does not exist: {self.wiki_root}")

    def list_people(self) -> List[Dict[str, object]]:
        people: List[Dict[str, object]] = []
        for person_dir in sorted(self.wiki_root.iterdir(), key=lambda item: item.name):
            if not person_dir.is_dir():
                continue
            if not (person_dir / "index.md").exists():
                continue
            manifest = self._load_manifest(person_dir.name)
            person = manifest.get("person", {})
            people.append(
                {
                    "slug": person.get("slug", person_dir.name),
                    "name": person.get("name", person_dir.name),
                    "description": person.get("description", ""),
                    "statement_count": manifest.get("statement_count", 0),
                    "topic_count": manifest.get("topic_count", 0),
                }
            )
        return people

    def get_index(self, person_slug: str) -> str:
        return self._read_text(person_slug, "index.md")

    def get_timeline(self, person_slug: str) -> str:
        return self._read_text(person_slug, "timeline.md")

    def get_sources(self, person_slug: str) -> str:
        return self._read_text(person_slug, "sources.md")

    def get_agents_guide(self, person_slug: str) -> str:
        return self._read_text(person_slug, "AGENTS.md")

    def list_topics(self, person_slug: str) -> List[Dict[str, object]]:
        counts: Dict[str, int] = {}
        for statement in self._load_statements(person_slug):
            for topic in statement.get("topics") or ["uncategorized"]:
                counts[topic] = counts.get(topic, 0) + 1
        return [
            {"topic": topic, "slug": slugify(topic), "statement_count": count}
            for topic, count in sorted(counts.items(), key=lambda item: (-item[1], item[0]))
        ]

    def get_topic_page(self, person_slug: str, topic: str) -> str:
        topic_path = self._topic_path(person_slug, topic)
        return topic_path.read_text(encoding="utf-8")

    def get_topic_statements(
        self,
        person_slug: str,
        topic: str,
        *,
        limit: int = 20,
        offset: int = 0,
    ) -> Dict[str, object]:
        normalized = self._topic_name(person_slug, topic)
        statements = [item for item in self._load_statements(person_slug) if normalized in (item.get("topics") or ["uncategorized"])]
        sliced = statements[offset : offset + max(limit, 1)]
        return {
            "topic": normalized,
            "offset": offset,
            "limit": limit,
            "total": len(statements),
            "items": [self._statement_preview(item) for item in sliced],
        }

    def search_statements(
        self,
        person_slug: str,
        *,
        query: str = "",
        topic: Optional[str] = None,
        limit: int = 20,
        offset: int = 0,
    ) -> Dict[str, object]:
        topic_name = self._topic_name(person_slug, topic) if topic else None
        matches: List[Dict[str, object]] = []
        query_text = query.strip().lower()
        for statement in self._load_statements(person_slug):
            topics = statement.get("topics") or ["uncategorized"]
            if topic_name and topic_name not in topics:
                continue
            haystack = "\n".join(
                [
                    statement.get("title", "") or "",
                    statement.get("summary", "") or "",
                    statement.get("text", "") or "",
                    "\n".join(statement.get("notes") or []),
                ]
            ).lower()
            if query_text and query_text not in haystack:
                continue
            matches.append(self._statement_preview(statement))
        sliced = matches[offset : offset + max(limit, 1)]
        return {
            "query": query,
            "topic": topic_name,
            "offset": offset,
            "limit": limit,
            "total": len(matches),
            "items": sliced,
        }

    def get_statement(self, person_slug: str, statement_id: str) -> Dict[str, object]:
        for statement in self._load_statements(person_slug):
            if statement.get("id") == statement_id:
                return statement
        raise WikiBackendError(f"statement not found: {person_slug}/{statement_id}")

    def get_recent_statements(
        self,
        person_slug: str,
        *,
        limit: int = 20,
        topic: Optional[str] = None,
    ) -> Dict[str, object]:
        topic_name = self._topic_name(person_slug, topic) if topic else None
        statements = self._load_statements(person_slug)
        if topic_name:
            statements = [item for item in statements if topic_name in (item.get("topics") or ["uncategorized"])]
        return {
            "topic": topic_name,
            "limit": limit,
            "items": [self._statement_preview(item) for item in statements[: max(limit, 1)]],
        }

    def _person_dir(self, person_slug: str) -> Path:
        person_dir = self.wiki_root / person_slug
        if not person_dir.exists():
            raise WikiBackendError(f"person wiki not found: {person_slug}")
        return person_dir

    def _read_text(self, person_slug: str, relative_path: str) -> str:
        path = self._person_dir(person_slug) / relative_path
        if not path.exists():
            raise WikiBackendError(f"wiki file not found: {path}")
        return path.read_text(encoding="utf-8")

    def _load_manifest(self, person_slug: str) -> Dict[str, object]:
        path = self._person_dir(person_slug) / "_meta" / "manifest.json"
        if not path.exists():
            raise WikiBackendError(f"manifest not found: {path}")
        return json.loads(path.read_text(encoding="utf-8"))

    def _load_statements(self, person_slug: str) -> List[Dict[str, object]]:
        path = self._person_dir(person_slug) / "_meta" / "statements.json"
        if not path.exists():
            raise WikiBackendError(f"statements metadata not found: {path}")
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, list):
            raise WikiBackendError(f"invalid statements metadata: {path}")
        return data

    def _topic_path(self, person_slug: str, topic: str) -> Path:
        topic_name = self._topic_name(person_slug, topic)
        path = self._person_dir(person_slug) / "topics" / f"{slugify(topic_name)}.md"
        if not path.exists():
            raise WikiBackendError(f"topic page not found: {person_slug}/{topic_name}")
        return path

    def _topic_name(self, person_slug: str, topic: Optional[str]) -> str:
        if topic is None:
            raise WikiBackendError("topic is required")
        if topic == "uncategorized":
            return topic
        slug = slugify(topic)
        for item in self.list_topics(person_slug):
            if item["topic"] == topic or item["slug"] == slug:
                return str(item["topic"])
        raise WikiBackendError(f"unknown topic '{topic}' for person '{person_slug}'")

    def _statement_preview(self, statement: Dict[str, object]) -> Dict[str, object]:
        text = " ".join(str(statement.get("text", "")).split())
        preview = text if len(text) <= 180 else text[:177].rstrip() + "..."
        return {
            "id": statement.get("id"),
            "when": statement.get("when"),
            "title": statement.get("title"),
            "summary": statement.get("summary"),
            "topics": statement.get("topics") or ["uncategorized"],
            "source_refs": statement.get("source_refs") or [],
            "preview": preview,
        }
