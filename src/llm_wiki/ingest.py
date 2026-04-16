from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
import json
from pathlib import Path
from typing import Any, Dict, List, Optional

from .builder import build_wiki
from .parser import FormatError, slugify


@dataclass
class StatementPayload:
    person_slug: str
    text: str
    id: Optional[str] = None
    when: str = "unknown"
    sort_date: Optional[str] = None
    title: Optional[str] = None
    summary: Optional[str] = None
    source_type: Optional[str] = None
    source_link: Optional[str] = None
    source_refs: List[str] = field(default_factory=list)
    topics: List[str] = field(default_factory=list)
    tags: List[str] = field(default_factory=list)
    stance: Optional[str] = None
    claims: List[str] = field(default_factory=list)
    notes: List[str] = field(default_factory=list)
    canonical: Optional[bool] = None
    update_note: Optional[str] = None


def load_payload_from_json(raw: str, person_slug_override: Optional[str] = None) -> StatementPayload:
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise FormatError(f"invalid JSON payload: {exc.msg}") from exc
    if not isinstance(data, dict):
        raise FormatError("JSON payload must be an object")
    return payload_from_dict(data, person_slug_override=person_slug_override)


def payload_from_dict(data: Dict[str, Any], person_slug_override: Optional[str] = None) -> StatementPayload:
    person_slug = person_slug_override or _optional_str(data.get("person_slug"))
    if not person_slug:
        raise FormatError("statement payload requires 'person_slug'")
    text = _optional_str(data.get("text")) or _optional_str(data.get("excerpt"))
    if not text:
        raise FormatError("statement payload requires 'text'")
    source_link = _optional_str(data.get("source_link"))
    source_refs = _coerce_list(data.get("source_refs"))
    if source_link and source_link not in source_refs:
        source_refs.append(source_link)
    return StatementPayload(
        person_slug=person_slug,
        text=text,
        id=_optional_str(data.get("id")),
        when=_optional_str(data.get("when")) or "unknown",
        sort_date=_optional_str(data.get("sort_date")),
        title=_optional_str(data.get("title")),
        summary=_optional_str(data.get("summary")),
        source_type=_optional_str(data.get("source_type")),
        source_link=source_link,
        source_refs=source_refs,
        topics=_coerce_list(data.get("topics")),
        tags=_coerce_list(data.get("tags")),
        stance=_optional_str(data.get("stance")),
        claims=_coerce_list(data.get("claims")),
        notes=_coerce_list(data.get("notes")),
        canonical=_coerce_bool(data.get("canonical")),
        update_note=_optional_str(data.get("update_note")),
    )


def ingest_statement(
    payload: StatementPayload,
    increments_dir: Path,
    source_path: Optional[Path] = None,
    build_output: Optional[Path] = None,
) -> Dict[str, str]:
    statement_id = payload.id or _auto_statement_id(payload)
    output_path = _resolve_increment_path(increments_dir, payload, statement_id)
    increment_text = render_single_increment(payload, statement_id)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(increment_text, encoding="utf-8")

    result = {
        "increment_path": str(output_path),
        "statement_id": statement_id,
    }
    if source_path and build_output:
        wiki_root = build_wiki(source_path, build_output, increments_dir)
        result["wiki_root"] = str(wiki_root)
    elif source_path or build_output:
        raise FormatError("source_path and build_output must be provided together to auto-build")
    return result


def render_single_increment(payload: StatementPayload, statement_id: str) -> str:
    lines = [
        "# Increment",
        f"person_slug: {payload.person_slug}",
    ]
    if payload.update_note:
        lines.append(f"update_note: {payload.update_note}")
    lines.extend(["", "# Statements", "", f"## {statement_id}", f"when: {payload.when}"])
    if payload.sort_date:
        lines.append(f"sort_date: {payload.sort_date}")
    if payload.title:
        lines.append(f"title: {payload.title}")
    if payload.source_type:
        lines.append(f"source_type: {payload.source_type}")
    if payload.source_link:
        lines.append(f"source_link: {payload.source_link}")
    if payload.source_refs:
        lines.append("source_refs:")
        for ref in payload.source_refs:
            lines.append(f"- {ref}")
    if payload.topics:
        lines.append(f"topics: {' | '.join(payload.topics)}")
    if payload.tags:
        lines.append(f"tags: {' | '.join(payload.tags)}")
    if payload.summary:
        lines.append(f"summary: {payload.summary}")
    if payload.stance:
        lines.append(f"stance: {payload.stance}")
    if payload.canonical is not None:
        lines.append(f"canonical: {'true' if payload.canonical else 'false'}")
    if payload.claims:
        lines.append("claims:")
        for claim in payload.claims:
            lines.append(f"- {claim}")
    if payload.notes:
        lines.append("notes:")
        for note in payload.notes:
            lines.append(f"- {note}")
    lines.append("text:")
    for text_line in payload.text.splitlines():
        if text_line:
            lines.append(f"> {text_line}")
        else:
            lines.append(">")
    lines.append("")
    return "\n".join(lines)


def _auto_statement_id(payload: StatementPayload) -> str:
    title_basis = payload.title or payload.summary or _shorten(payload.text)
    return f"{_time_fragment(payload.when)}-{slugify(title_basis)}".strip("-")


def _resolve_increment_path(increments_dir: Path, payload: StatementPayload, statement_id: str) -> Path:
    increments_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    filename = f"{stamp}-{payload.person_slug}-{statement_id}.md"
    return increments_dir / filename


def _time_fragment(when: str) -> str:
    normalized = when.strip().lower() if when else "unknown"
    if not normalized or normalized == "unknown":
        return "unknown"
    chars = []
    for char in normalized:
        if char.isalnum():
            chars.append(char)
        else:
            chars.append("-")
    compact = "".join(chars)
    while "--" in compact:
        compact = compact.replace("--", "-")
    return compact.strip("-") or "unknown"


def _shorten(text: str, limit: int = 48) -> str:
    compact = " ".join(text.split())
    if len(compact) <= limit:
        return compact
    return compact[: limit - 3].rstrip() + "..."


def _optional_str(value: Any) -> Optional[str]:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _coerce_list(value: Any) -> List[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    if isinstance(value, str):
        return [item.strip() for item in value.split("|") if item.strip()]
    return [str(value).strip()]


def _coerce_bool(value: Any) -> Optional[bool]:
    if value is None or value == "":
        return None
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes"}
