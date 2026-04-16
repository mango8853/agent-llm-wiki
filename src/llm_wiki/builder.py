from __future__ import annotations

from collections import defaultdict
from dataclasses import asdict
from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Dict, Iterable, List, Optional

from .parser import (
    Document,
    FormatError,
    Person,
    Statement,
    group_by_topic,
    parse_document,
    sort_statements,
    statement_label,
    topic_slug,
)


def build_wiki(source_path: Path, output_root: Path, increments_dir: Optional[Path] = None) -> Path:
    source_doc = parse_document(source_path)
    if source_doc.kind != "source" or source_doc.person is None:
        raise FormatError(f"{source_path}: build requires a base source file with # Person")

    increments = _load_increments(increments_dir, source_doc.person.slug)
    merged_statements = _merge_statements(source_doc.statements, increments)

    wiki_root = output_root / source_doc.person.slug
    topic_dir = wiki_root / "topics"
    meta_dir = wiki_root / "_meta"
    topic_dir.mkdir(parents=True, exist_ok=True)
    meta_dir.mkdir(parents=True, exist_ok=True)

    _write_file(wiki_root / "index.md", render_index(source_doc.person, merged_statements))
    _write_file(wiki_root / "timeline.md", render_timeline(source_doc.person, merged_statements))
    _write_file(wiki_root / "sources.md", render_sources(source_doc.person, merged_statements))
    _write_file(wiki_root / "log.md", render_log(source_doc.person, source_doc.path, increments))
    _write_file(wiki_root / "AGENTS.md", render_agents(source_doc.person))

    for topic, statements in group_by_topic(merged_statements).items():
        _write_file(topic_dir / f"{topic_slug(topic)}.md", render_topic_page(source_doc.person, topic, statements))

    manifest = {
        "person": asdict(source_doc.person),
        "source_file": str(source_doc.path),
        "increments": [
            {
                "path": str(doc.path),
                "update_note": doc.update_note,
                "statement_count": len(doc.statements),
            }
            for doc in increments
        ],
        "statement_count": len(merged_statements),
        "topic_count": len(group_by_topic(merged_statements)),
        "built_at": _build_timestamp(),
    }
    _write_file(meta_dir / "manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2) + "\n")
    _write_file(
        meta_dir / "statements.json",
        json.dumps([asdict(statement) for statement in merged_statements], ensure_ascii=False, indent=2) + "\n",
    )
    return wiki_root


def validate_inputs(source_path: Path, increments_dir: Optional[Path] = None) -> Dict[str, object]:
    source_doc = parse_document(source_path)
    if source_doc.kind != "source" or source_doc.person is None:
        raise FormatError(f"{source_path}: check requires a base source file with # Person")
    increments = _load_increments(increments_dir, source_doc.person.slug)
    merged = _merge_statements(source_doc.statements, increments)
    return {
        "person": source_doc.person.name,
        "slug": source_doc.person.slug,
        "base_statements": len(source_doc.statements),
        "increment_files": len(increments),
        "total_statements": len(merged),
        "topics": sorted(group_by_topic(merged).keys(), key=str.lower),
    }


def _load_increments(increments_dir: Optional[Path], person_slug: str) -> List[Document]:
    if increments_dir is None:
        return []
    increment_docs: List[Document] = []
    for path in sorted(increments_dir.glob("*.md")):
        doc = parse_document(path)
        if doc.kind != "increment":
            raise FormatError(f"{path}: files inside --increments must use # Increment")
        if doc.person_slug != person_slug:
            raise FormatError(f"{path}: increment person_slug '{doc.person_slug}' does not match '{person_slug}'")
        increment_docs.append(doc)
    return increment_docs


def _merge_statements(base_statements: Iterable[Statement], increments: Iterable[Document]) -> List[Statement]:
    merged: Dict[str, Statement] = {statement.id: statement for statement in base_statements}
    for doc in increments:
        for statement in doc.statements:
            merged[statement.id] = statement
    return sort_statements(list(merged.values()))


def render_index(person: Person, statements: List[Statement]) -> str:
    grouped = group_by_topic(statements)
    canonical = [statement for statement in statements if statement.canonical]
    recent = statements[:5]

    lines = [
        f"# {person.name}",
        "",
        person.description or "_No description yet._",
        "",
        "## Overview",
        "",
        f"- Slug: `{person.slug}`",
        f"- Aliases: {', '.join(person.aliases) if person.aliases else 'None'}",
        f"- Statements: {len(statements)}",
        f"- Topics: {len(grouped)}",
        f"- Canonical statements: {len(canonical)}",
        "",
        "## Topic Index",
        "",
    ]
    for topic, topic_statements in grouped.items():
        lines.append(f"- [{topic}](topics/{topic_slug(topic)}.md) ({len(topic_statements)} statements)")

    lines.extend(["", "## Recent Statements", ""])
    for statement in recent:
        lines.append(
            f"- `{statement.when}` {statement_label(statement)}"
            f" [{_topic_links(statement.topics)}] - {_summary_or_text(statement)}"
        )
    return "\n".join(lines).strip() + "\n"


def render_timeline(person: Person, statements: List[Statement]) -> str:
    buckets: Dict[str, List[Statement]] = defaultdict(list)
    for statement in sort_statements(statements):
        buckets[_timeline_bucket(statement)].append(statement)

    lines = [f"# {person.name} Timeline", ""]
    for bucket in sorted(buckets.keys(), reverse=True):
        lines.extend([f"## {bucket}", ""])
        for statement in buckets[bucket]:
            lines.append(f"### {statement.when} - {statement_label(statement)}")
            lines.append("")
            lines.append(f"- ID: `{statement.id}`")
            lines.append(f"- Source: {_source_summary(statement)}")
            lines.append(f"- Topics: {_topic_links(statement.topics)}")
            if statement.stance:
                lines.append(f"- Stance: {statement.stance}")
            if statement.summary:
                lines.append(f"- Summary: {statement.summary}")
            if statement.claims:
                lines.append("- Claims:")
                for claim in statement.claims:
                    lines.append(f"  - {claim}")
            lines.append("- Original Text:")
            for text_line in statement.text.splitlines():
                lines.append(f"  > {text_line}")
            if statement.notes:
                lines.append("- Notes:")
                for note in statement.notes:
                    lines.append(f"  - {note}")
            if statement.source_refs:
                lines.append("- Source Refs:")
                for ref in statement.source_refs:
                    lines.append(f"  - `{ref}`")
            lines.append("")
    return "\n".join(lines).strip() + "\n"


def render_topic_page(person: Person, topic: str, statements: List[Statement]) -> str:
    lines = [
        f"# {person.name} on {topic}",
        "",
        f"- Topic: `{topic}`",
        f"- Statements: {len(statements)}",
        "",
        "## Statements",
        "",
    ]
    for statement in statements:
        lines.append(f"### {statement.when} - {statement_label(statement)}")
        lines.append("")
        lines.append(f"- ID: `{statement.id}`")
        lines.append(f"- Source: {_source_summary(statement)}")
        if statement.summary:
            lines.append(f"- Summary: {statement.summary}")
        if statement.claims:
            lines.append("- Claims:")
            for claim in statement.claims:
                lines.append(f"  - {claim}")
        lines.append("- Original Text:")
        for text_line in statement.text.splitlines():
            lines.append(f"  > {text_line}")
        if statement.notes:
            lines.append("- Notes:")
            for note in statement.notes:
                lines.append(f"  - {note}")
        if statement.source_refs:
            lines.append("- Source Refs:")
            for ref in statement.source_refs:
                lines.append(f"  - `{ref}`")
        lines.append("")
    return "\n".join(lines).strip() + "\n"


def render_sources(person: Person, statements: List[Statement]) -> str:
    lines = [f"# {person.name} Sources", "", "| When | ID | Label | Source | Origin |", "| --- | --- | --- | --- | --- |"]
    for statement in sort_statements(statements):
        lines.append(
            "| {when} | `{sid}` | {label} | {source} | `{origin}` |".format(
                when=statement.when,
                sid=statement.id,
                label=_escape_pipe(statement_label(statement)),
                source=_escape_pipe(_source_summary(statement)),
                origin=statement.from_file,
            )
        )
    return "\n".join(lines).strip() + "\n"


def render_log(person: Person, source_path: Path, increments: List[Document]) -> str:
    lines = [
        f"# {person.name} Build Log",
        "",
        f"- Built at: {_build_timestamp()}",
        f"- Base source: `{source_path}`",
        "",
        "## Increments",
        "",
    ]
    if not increments:
        lines.append("- No increments loaded.")
    else:
        for doc in increments:
            note = f" - {doc.update_note}" if doc.update_note else ""
            lines.append(f"- `{doc.path}` ({len(doc.statements)} statements){note}")
    lines.append("")
    return "\n".join(lines)


def render_agents(person: Person) -> str:
    lines = [
        f"# AGENTS.md for {person.name}",
        "",
        "This wiki is the preferred context layer for answering questions about this person.",
        "",
        "## Reading Order",
        "",
        "1. Start with `index.md` for the topic map and recent statements.",
        "2. Open `topics/*.md` when the question is topic-specific.",
        "3. Use `timeline.md` when the question depends on chronology or opinion changes.",
        "4. Use `sources.md` when you need provenance or to trace a statement back to the source bundle.",
        "",
        "## Answering Rules",
        "",
        "- Prefer wording like 'as of <when>' when the person's position may have changed over time.",
        "- Distinguish direct quotes from summaries.",
        "- If multiple statements conflict, surface the tension instead of smoothing it away.",
        "- Prefer local source refs first; use external links only when they actually help.",
        "- If the wiki is silent, say so and request more source material instead of inventing facts.",
        "",
        "## Update Rules",
        "",
        "- New material should arrive as an increment markdown file.",
        "- Keep the original statement text inside each statement record.",
        "- Use `when: unknown` when the exact time cannot be determined.",
        "- Prefer updating the source markdown files and rebuilding the wiki.",
        "",
    ]
    return "\n".join(lines)


def _topic_links(topics: List[str]) -> str:
    if not topics:
        return "uncategorized"
    return ", ".join(f"[{topic}](topics/{topic_slug(topic)}.md)" for topic in topics)


def _summary_or_text(statement: Statement) -> str:
    return statement.summary or _compact_text(statement.text)


def _compact_text(text: str, limit: int = 100) -> str:
    compact = " ".join(text.split())
    if len(compact) <= limit:
        return compact
    return compact[: limit - 3].rstrip() + "..."


def _timeline_bucket(statement: Statement) -> str:
    sort_date = statement.sort_date or ""
    if len(sort_date) >= 4 and sort_date[:4].isdigit():
        return sort_date[:4]
    return "Unknown Time"


def _source_summary(statement: Statement) -> str:
    parts: List[str] = []
    if statement.source_type:
        parts.append(statement.source_type)
    parts.extend(statement.source_refs)
    if not parts:
        return "No source reference provided"
    return " | ".join(parts)


def _write_file(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _escape_pipe(value: str) -> str:
    return value.replace("|", "\\|")


def _build_timestamp() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()
